# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Auto-push wiring for finance connectors.

When an invoice is approved or paid, any active connector configured with
``auto_push`` for that event is pushed - but NOT inline in the detached
event task. The subscriber opens its own short-lived session, finds the
matching configs and hands the actual work to the job runner via
``submit_job``. That keeps the event task fast, survives the single-writer
constraint, and the per-event idempotency key prevents a re-delivered
event from pushing the same data twice.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.job_runner import register_handler, submit_job
from app.database import async_session_factory
from app.modules.finance.connector_models import AccountingConnectorConfig

if TYPE_CHECKING:
    from app.core.job_run import JobRun

logger = logging.getLogger(__name__)

_JOB_KIND = "finance.connector_sync"

# Events that can trigger an auto-push. ``invoice.paid`` is already emitted
# by FinanceService.pay_invoice; ``invoice.approved`` is emitted by
# approve_invoice (added alongside this feature).
_AUTO_PUSH_EVENTS = ("invoice.paid", "invoice.approved")


def _coerce_uuid(value: object) -> uuid.UUID | None:
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def _dispatch_auto_push(event: Event) -> None:
    """Find active auto-push configs for the event's project and enqueue them."""
    data = event.data or {}
    project_id = _coerce_uuid(data.get("project_id"))
    if project_id is None:
        return
    try:
        async with async_session_factory() as session:
            stmt = (
                select(AccountingConnectorConfig)
                .where(AccountingConnectorConfig.is_active.is_(True))
                .where(AccountingConnectorConfig.auto_push.is_(True))
                .where(
                    (AccountingConnectorConfig.project_id == project_id)
                    | (AccountingConnectorConfig.project_id.is_(None))
                )
            )
            configs = list((await session.execute(stmt)).scalars().all())
    except Exception:
        logger.debug("connector: auto-push lookup failed", exc_info=True)
        return

    for config in configs:
        events = config.auto_push_events or []
        if event.name not in events:
            continue
        if (config.direction or "both").lower() not in ("push", "both"):
            continue
        try:
            await submit_job(
                _JOB_KIND,
                {
                    "config_id": str(config.id),
                    "direction": "push",
                    "dry_run": False,
                    "trigger": "event",
                    "triggered_by_event": event.name,
                },
                idempotency_key=f"connsync:{config.id}:{event.id}",
            )
            logger.info(
                "connector: queued auto-push config=%s on event=%s (project=%s)",
                config.id,
                event.name,
                project_id,
            )
        except Exception:
            logger.debug("connector: submit_job failed for config %s", config.id, exc_info=True)


async def _run_connector_sync_job(job_run: JobRun, payload: dict[str, Any]) -> dict[str, Any]:
    """Job handler: run a connector sync in the background."""
    config_id = _coerce_uuid(payload.get("config_id"))
    if config_id is None:
        return {"error": "missing config_id"}
    direction = str(payload.get("direction") or "push")
    dry_run = bool(payload.get("dry_run", False))
    trigger = str(payload.get("trigger") or "event")
    triggered_by_event = payload.get("triggered_by_event")

    from app.core.job_runner import update_progress
    from app.modules.finance.connector_service import ConnectorService

    await update_progress(job_run.id, percent=10, message="Starting connector sync")
    async with async_session_factory() as session:
        service = ConnectorService(session)
        log = await service.run_sync(
            config_id,
            direction=direction,
            dry_run=dry_run,
            trigger=trigger,
            triggered_by_event=triggered_by_event,
            job_run_id=job_run.id,
        )
        result = {
            "sync_log_id": str(log.id),
            "status": log.status,
            "records_in": log.records_in,
            "records_out": log.records_out,
        }
    await update_progress(job_run.id, percent=100, message=f"Sync {result['status']}")
    return result


def register_connector_subscribers() -> None:
    """Subscribe the auto-push dispatcher to the invoice lifecycle events."""
    for name in _AUTO_PUSH_EVENTS:
        event_bus.subscribe_once(name, _dispatch_auto_push)
    logger.info("Finance connectors: subscribed to %d auto-push event(s)", len(_AUTO_PUSH_EVENTS))


def register_connector_job_handler() -> None:
    """Register the background sync handler with the job runner."""
    register_handler(_JOB_KIND, _run_connector_sync_job)
