# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Costs event handlers - vector indexing.

Subscribes to the existing ``costs.item.*`` and ``costs.items.*`` event
families published by :class:`~app.modules.costs.service.CostItemService`
and keeps the ``oe_cost_items`` vector collection in sync with the
underlying CostItem rows so the BOQ-element → catalog match feature
always sees fresh data.

Why not SQLAlchemy listeners?
-----------------------------

Per project policy the canonical wiring is the event bus. SQLAlchemy
``after_insert`` / ``after_update`` / ``after_delete`` listeners fire
inside the transaction's flush and, on async SQLite, can deadlock the
embedding-thread session against the open writer. Using the existing
``event_bus.publish_detached`` pattern lets the request transaction
commit before the embedding kicks off.

This module is auto-imported by the module loader when ``oe_costs`` is
loaded (see ``module_loader._load_module`` → ``events.py``).
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import bindparam, select, text
from sqlalchemy.exc import SQLAlchemyError

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.costs import vector_adapter as cost_vector
from app.modules.costs.models import CostItem

logger = logging.getLogger(__name__)

# Upper bound on how many referencing BOQ positions we enumerate per
# cost-item update. The handler is advisory (detect + notify), so a huge
# fan-out is capped to keep the detached task cheap; the warning still
# tells the operator the reference count is at least this many.
_MAX_REFERENCING_POSITIONS = 500


# ── Bulk debounce ────────────────────────────────────────────────────────
#
# CWICR loads emit one ``costs.items.bulk_imported`` event per file (~6k
# rows). Embedding 6k items inline would freeze the import endpoint for
# tens of seconds, so we debounce: the bulk event schedules a single
# detached reindex task that scoops up everything in the table that
# isn't yet indexed. Multiple bulk events arriving during the debounce
# window collapse into one task, avoiding duplicate work.
#
# A short asyncio.Lock makes sure we don't run two concurrent backfills
# (which would race on the LanceDB delete-then-insert upsert path).

_BULK_LOCK = asyncio.Lock()
_BULK_DEBOUNCE_SECONDS = 1.5


async def _index_one_by_id(item_id: uuid.UUID) -> None:
    """Resolve one CostItem by id and push it to the vector store.

    Opens its own short-lived session - the calling event-bus handler
    is decoupled from the request transaction and must not reuse the
    request session (which is closed by the time detached events fire).
    """
    try:
        async with async_session_factory() as session:
            stmt = select(CostItem).where(CostItem.id == item_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await cost_vector.delete([str(item_id)])
                return
            await cost_vector.upsert([row])
    except Exception:
        logger.debug("cost-vector index failed for %s", item_id, exc_info=True)


# ── Event-bus subscribers ───────────────────────────────────────────────
#
# Event names are the ones already published by CostItemService:
#   * costs.item.created     {item_id, code}
#   * costs.item.updated     {item_id, code, fields}
#   * costs.item.deleted     {item_id, code}
#   * costs.items.bulk_imported {created_count, skipped_count, skipped_codes}
#
# The first three carry an item_id we use to fetch the row. The bulk
# event doesn't enumerate ids (the payload stays small), so we trigger
# a delta backfill instead.


def _extract_item_id(event: Event) -> uuid.UUID | None:
    """Pull ``item_id`` out of the event payload as a UUID.

    Returns ``None`` for non-UUID values so the handler can no-op
    rather than crash on a malformed publish.
    """
    raw = (event.data or {}).get("item_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError):
        return None


async def _on_cost_item_created(event: Event) -> None:
    item_id = _extract_item_id(event)
    if item_id is not None:
        await _index_one_by_id(item_id)


async def _find_referencing_boq_positions(item_id: uuid.UUID) -> list[uuid.UUID]:
    """Find BOQ positions whose ``metadata.cost_item_id`` references *item_id*.

    BOQ positions store the linked cost item under ``metadata.cost_item_id``
    (a UUID string), see ``app.modules.boq``. We deliberately do NOT import
    the BOQ ORM model here - this module must stay decoupled and must not
    break when the ``oe_boq`` module is not loaded. Instead we run a portable
    text-match query against the ``oe_boq_position`` table's JSON ``metadata``
    column and confirm matches in Python (LIKE is a cheap prefilter; the JSON
    holds the canonical UUID string).

    Returns an empty list when the table is absent or the query fails for any
    reason - detection is best-effort and never raises into the caller.
    """
    # Match on the canonical UUID string via a LIKE prefilter, then verify in
    # Python. The ``metadata`` column is generic JSON (JSONB on PostgreSQL,
    # TEXT on SQLite); JSONB has no LIKE operator, so we CAST it to text first.
    # ``CAST(... AS TEXT)`` is portable across both dialects.
    needle = str(item_id)
    like_pattern = f"%{needle}%"
    stmt = text(
        "SELECT id, metadata FROM oe_boq_position WHERE CAST(metadata AS TEXT) LIKE :pat LIMIT :lim"
    ).bindparams(
        bindparam("pat", value=like_pattern),
        bindparam("lim", value=_MAX_REFERENCING_POSITIONS),
    )
    matched: list[uuid.UUID] = []
    try:
        async with async_session_factory() as session:
            rows = (await session.execute(stmt)).all()
    except SQLAlchemyError:
        # Table missing (BOQ module not loaded) or dialect quirk - stay quiet.
        logger.debug("BOQ reference scan skipped for cost item %s", item_id, exc_info=True)
        return matched
    except Exception:
        logger.debug("BOQ reference scan failed for cost item %s", item_id, exc_info=True)
        return matched

    for row in rows:
        meta = getattr(row, "metadata", None)
        # metadata may come back as a dict (JSON column) or a raw string
        # depending on the driver; normalise to a comparable cost_item_id.
        ref: object = None
        if isinstance(meta, dict):
            ref = meta.get("cost_item_id")
        if ref is None:
            # Fall back to confirming the LIKE hit really contained the UUID.
            ref = needle if needle in str(meta) else None
        if ref is None:
            continue
        try:
            if uuid.UUID(str(ref)) == item_id:
                matched.append(uuid.UUID(str(row.id)))
        except (ValueError, AttributeError, TypeError):
            continue
    return matched


async def _on_cost_item_updated(event: Event) -> None:
    item_id = _extract_item_id(event)
    if item_id is None:
        return

    # 1) Keep the vector store in sync (existing behaviour).
    await _index_one_by_id(item_id)

    # 2) Detect BOQ positions that reference this cost item so a rate /
    #    component change does not silently leave linked estimates stale.
    #    NON-DESTRUCTIVE: we only notify (log + publish a follow-up event).
    #    Recomputing or rewriting position rates is intentionally left to a
    #    human-confirmed flow, per the "AI-augmented, human-confirmed" and
    #    "no destructive cascade" project rules.
    try:
        position_ids = await _find_referencing_boq_positions(item_id)
    except Exception:
        logger.debug("BOQ reference detection errored for %s", item_id, exc_info=True)
        return

    if not position_ids:
        return

    capped = len(position_ids) >= _MAX_REFERENCING_POSITIONS
    logger.warning(
        "Cost item %s changed and is referenced by %s%d BOQ position(s) "
        "(metadata.cost_item_id); their stored unit rates may now be stale and "
        "should be reviewed. No automatic re-pricing was applied.",
        item_id,
        "at least " if capped else "",
        len(position_ids),
    )

    # Emit a follow-up event so any interested consumer (BOQ module, audit
    # log, notification service) can act on the stale linkage. We are already
    # running in a detached handler (no request transaction is open here), so
    # awaiting publish directly is safe and delivers to subscribers in order.
    try:
        await event_bus.publish(
            "costs.item.references_stale",
            {
                "item_id": str(item_id),
                "position_ids": [str(pid) for pid in position_ids],
                "position_count": len(position_ids),
                "capped": capped,
            },
        )
    except Exception:
        logger.debug("Failed to publish costs.item.references_stale for %s", item_id, exc_info=True)


async def _on_cost_item_deleted(event: Event) -> None:
    """Remove the deleted cost item from the vector store.

    The service uses soft-delete (``is_active=False``); we still drop
    the vector so the matcher doesn't return inactive items. If the
    operator re-activates the row, the next ``costs.item.updated``
    event will re-embed it.
    """
    raw = (event.data or {}).get("item_id")
    if raw is None:
        return
    try:
        await cost_vector.delete([str(raw)])
    except Exception:
        logger.debug("cost-vector delete failed for %s", raw, exc_info=True)


async def _on_bulk_import(event: Event) -> None:
    """Trigger a delta reindex after a CWICR bulk import.

    The bulk event payload doesn't carry per-row ids. We use the lock
    to coalesce overlapping calls - a typical CWICR load fires several
    events in quick succession (one per region file) and we'd rather
    do one full pass than four overlapping ones.
    """
    _ = event  # event payload is summary-only

    if _BULK_LOCK.locked():
        # Another bulk reindex is already running; that pass will pick
        # up the rows this event refers to too.
        return

    async with _BULK_LOCK:
        # Light debounce - give the import transaction a moment to
        # settle so the rows we're about to read are committed and
        # visible across the connection pool.
        await asyncio.sleep(_BULK_DEBOUNCE_SECONDS)
        try:
            indexed = await _delta_reindex_all_active()
            logger.info("cost-vector bulk reindex: indexed=%d", indexed)
        except Exception:
            logger.debug("cost-vector bulk reindex failed", exc_info=True)


async def _delta_reindex_all_active(*, batch_size: int = 500) -> int:
    """Embed all currently active CostItems.

    Uses streaming-style batching to keep memory bounded on tenants
    with hundreds of thousands of CWICR rows. The vector store's
    upsert is naturally idempotent, so re-embedding rows that are
    already indexed is wasteful but never incorrect.
    """
    indexed = 0
    async with async_session_factory() as session:
        offset = 0
        while True:
            stmt = (
                select(CostItem)
                .where(CostItem.is_active.is_(True))
                .order_by(CostItem.id)
                .offset(offset)
                .limit(batch_size)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            if not rows:
                break
            indexed += await cost_vector.upsert(rows)
            if len(rows) < batch_size:
                break
            offset += batch_size
    return indexed


# ── Registration ─────────────────────────────────────────────────────────


def _register_handlers() -> None:
    """Wire the handlers into the event bus.

    Idempotent: safe to call multiple times when the test suite resets
    the bus and reloads the module. The bus deduplicates by callable
    identity - re-registering the same function twice would create two
    invocations per event, so we keep registration in one place.
    """
    event_bus.subscribe_once("costs.item.created", _on_cost_item_created)
    event_bus.subscribe_once("costs.item.updated", _on_cost_item_updated)
    event_bus.subscribe_once("costs.item.deleted", _on_cost_item_deleted)
    event_bus.subscribe_once("costs.items.bulk_imported", _on_bulk_import)


_register_handlers()


# Re-exports for tests that want to drive the handlers directly without
# going through the event bus.
__all__: list[str] = [
    "_delta_reindex_all_active",
    "_extract_item_id",
    "_on_bulk_import",
    "_on_cost_item_created",
    "_on_cost_item_deleted",
    "_on_cost_item_updated",
    "_register_handlers",
]
