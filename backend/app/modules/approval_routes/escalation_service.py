# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Approval-SLA escalation-depth service - the thin database layer (#17).

Where :mod:`sla_engine` answers "is this step breached?" and the SLA monitor
nudges the holder, this layer answers the follow-on question the pure
:mod:`escalation` engine decides: a breached step has sat past its grace window,
so *should we escalate now, and to whom next?* It gathers the live standing of
one pending instance and feeds it to :func:`escalation.decide_escalation`.

It owns no new table. The escalation policy is derived from data already on the
route and step:

* ``chain`` - the named approvers of the route's *later* steps, in order. A
  stuck step is escalated upward to the next authority on the route; role-only
  steps (no concrete ``approver_user_id``) contribute no addressable target and
  are skipped, and so is anyone already entitled to decide the current step,
  who would otherwise be "escalated" to a step they can act on today.
* ``sla_hours`` - the current step's own SLA budget.
* ``escalate_after_hours`` - a grace window derived as
  :data:`ESCALATE_GRACE_FACTOR` times the SLA, so the chain is only walked once
  the step is overdue by a further full window, not the instant it breaches.

The set of approvers already escalated to is reconstructed migration-free from
the notification store (the same technique the monitor uses to de-duplicate
breach reminders): each escalation lands an ``approval_escalated`` notification
carrying the target and step ordinal, so a target is escalated to at most once
per step and the escalation ``level`` advances deterministically.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.approval_routes import sla_engine
from app.modules.approval_routes.delegation_engine import DelegationView
from app.modules.approval_routes.escalation import (
    EscalationPolicy,
    EscalationState,
    classify_severity,
    decide_escalation,
    hours_overdue,
)
from app.modules.approval_routes.models import Instance, Route, Step, StepState
from app.modules.approval_routes.service import (
    ApprovalRouteService,
    delegation_views_from_rows,
    step_holder,
)
from app.modules.notifications.models import Notification

#: Grace multiple on the SLA before the chain is walked. At the default of 2 a
#: step is escalated once it has been held for twice its SLA budget (overdue by
#: one further full window), giving the holder slack past the breach first.
ESCALATE_GRACE_FACTOR = 2

#: Notification type for an escalation. Carries the word "escalat" on purpose:
#: the inbox severity classifier promotes overdue / breach / escalation
#: notifications to "critical". Also the de-dup key for already-escalated targets.
ESCALATED_TYPE = "approval_escalated"

#: Entity type the escalation (and breach) notifications are filed under.
ENTITY_TYPE = "approval_instance"


@dataclass(frozen=True)
class EscalationView:
    """Read model for one instance's escalation standing.

    ``has_sla`` is ``False`` when the instance is not pending or its current
    step has no SLA clock - in that case the severity is ``on_time`` and no
    escalation is due. All money-free; the only numbers are an hour count and a
    1-based level.
    """

    instance_id: str
    target_kind: str
    current_step_ordinal: int
    has_sla: bool
    severity: str
    hours_overdue: float
    should_escalate: bool
    next_target: str | None
    level: int
    reason: str
    chain_length: int
    current_holder: str | None


def _idle_view(instance: Instance) -> EscalationView:
    """The standing for an instance with no live escalation clock."""
    return EscalationView(
        instance_id=str(instance.id),
        target_kind=instance.target_kind,
        current_step_ordinal=instance.current_step_ordinal,
        has_sla=False,
        severity="on_time",
        hours_overdue=0.0,
        should_escalate=False,
        next_target=None,
        level=0,
        reason="within_window",
        chain_length=0,
        current_holder=None,
    )


async def _prior_step_decisions(session: AsyncSession, instance: Instance) -> list[datetime | None]:
    """Decision timestamps on the step immediately before the current one.

    Empty for the first step. The latest of these is when the current step
    became active (see :func:`sla_engine.current_step_baseline`).
    """
    if instance.current_step_ordinal <= 1:
        return []
    rows = await session.execute(
        select(StepState.decided_at)
        .join(Step, Step.id == StepState.step_id)
        .where(
            StepState.instance_id == instance.id,
            Step.ordinal == instance.current_step_ordinal - 1,
        )
    )
    return list(rows.scalars().all())


async def _prior_escalation_targets(
    session: AsyncSession,
    instance_id: uuid.UUID,
    step_ordinal: int,
) -> tuple[str, ...]:
    """Approver ids already escalated to for this instance + step.

    Reconstructed from ``approval_escalated`` notifications (migration-free, the
    same store the monitor uses to de-duplicate breach reminders). Keyed on the
    step ordinal so advancing to a new step starts a fresh escalation ladder.
    Order is preserved by ``created_at`` so the ladder reads oldest-first.
    """
    rows = await session.execute(
        select(Notification)
        .where(
            Notification.entity_type == ENTITY_TYPE,
            Notification.entity_id == str(instance_id),
            Notification.notification_type == ESCALATED_TYPE,
        )
        .order_by(Notification.created_at)
    )
    targets: list[str] = []
    for note in rows.scalars().all():
        meta = note.metadata_ or {}
        if meta.get("step_ordinal") == step_ordinal and meta.get("escalated_to"):
            targets.append(str(meta["escalated_to"]))
    return tuple(targets)


def _escalation_chain(steps: list[Step], current_ordinal: int, *, excluded: frozenset[str]) -> tuple[str, ...]:
    """Named approvers of the route's later steps, in order.

    Only steps after the current one with a concrete ``approver_user_id``
    contribute - a role-only step has no addressable user to escalate to. This
    is the authority ladder the stuck step is walked up.

    ``excluded`` drops everyone already entitled to decide the current step, so
    an out-of-office delegate who also sits higher up the route is not
    "escalated" to a step they can act on today. The pure engine skips a single
    holder by equality, while entitlement can name several people (a named
    approver and their delegate), which is why the set is applied here.

    Args:
        steps: The route's steps, any order.
        current_ordinal: The ordinal the instance is sitting on.
        excluded: Stringified ids that may not be escalation targets.

    Returns:
        The addressable authority ladder above the current step.
    """
    return tuple(
        str(step.approver_user_id)
        for step in steps
        if step.ordinal > current_ordinal
        and step.approver_user_id is not None
        and str(step.approver_user_id) not in excluded
    )


def _current_holder(
    instance: Instance,
    current_step: Step,
    delegations: list[DelegationView],
    *,
    now: datetime,
    project_id: uuid.UUID | None,
) -> str:
    """Whoever is expected to act on the current step now.

    Defers to :func:`service.step_holder`, the rule the SLA monitor nudges by,
    so the holder this view reports and the person a breach reminder reaches
    cannot disagree. Empty string when nothing names one.
    """
    holder = step_holder(instance, current_step, delegations, now=now, project_id=project_id)
    return str(holder) if holder is not None else ""


async def evaluate_escalation(
    session: AsyncSession,
    instance: Instance,
    route: Route,
    *,
    now: datetime | None = None,
) -> EscalationView:
    """Decide the escalation standing of one pending instance.

    Builds the policy (chain from the route's later approvers, the current
    step's SLA, the derived grace window) and the live state (how long the step
    has been held, who holds it, who has already been escalated to) and runs the
    pure engine. Anyone entitled to decide the current step is kept out of the
    chain: escalating to someone who can already act on the step is not an
    escalation. A non-pending instance, a missing current step or a step with
    no SLA returns an idle view (``has_sla`` False). Read-only.
    """
    now = now or datetime.now(UTC)

    steps = list(
        (await session.execute(select(Step).where(Step.route_id == route.id).order_by(Step.ordinal))).scalars().all()
    )
    current = next((s for s in steps if s.ordinal == instance.current_step_ordinal), None)

    if instance.status != "pending" or current is None or current.sla_hours is None:
        return _idle_view(instance)

    prior = await _prior_step_decisions(session, instance)
    baseline = sla_engine.current_step_baseline(instance.started_at, prior)
    hours_since = max(0.0, (now - baseline).total_seconds() / 3600.0)

    # Both questions are answered by the approval service, so this reader
    # cannot drift from the 403 gate or from the breach reminder: who may
    # decide the step (entitlement, which may name nobody on a role step) and
    # who is expected to act on it (the holder, which always names someone it
    # can).
    svc = ApprovalRouteService(session)
    entitled = await svc.entitled_deciders(instance, current, now=now)
    delegations = delegation_views_from_rows(await svc.repo.list_active_delegations())

    chain = _escalation_chain(
        steps,
        instance.current_step_ordinal,
        excluded=frozenset(str(uid) for uid in entitled or ()),
    )
    holder = _current_holder(instance, current, delegations, now=now, project_id=route.project_id)
    already = await _prior_escalation_targets(session, instance.id, instance.current_step_ordinal)

    policy = EscalationPolicy(
        target_kind=instance.target_kind,
        sla_hours=current.sla_hours,
        escalate_after_hours=current.sla_hours * ESCALATE_GRACE_FACTOR,
        chain=chain,
    )
    state = EscalationState(
        hours_since_assigned=hours_since,
        current_holder=holder,
        already_escalated_to=already,
    )

    decision = decide_escalation(policy, state)
    return EscalationView(
        instance_id=str(instance.id),
        target_kind=instance.target_kind,
        current_step_ordinal=instance.current_step_ordinal,
        has_sla=True,
        severity=classify_severity(policy, state),
        hours_overdue=round(hours_overdue(policy, state), 2),
        should_escalate=decision.should_escalate,
        next_target=decision.next_target,
        level=decision.level,
        reason=decision.reason,
        chain_length=len(chain),
        current_holder=holder or None,
    )
