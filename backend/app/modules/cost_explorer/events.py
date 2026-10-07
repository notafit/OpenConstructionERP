# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Cost Explorer reverse-index freshness.

Keeps ``oe_cost_item_resource`` in step with the costs table by subscribing to
the ``costs.item.*`` / ``costs.items.*`` events the costs module already
publishes. A single item change refreshes just that item's edges; a bulk import
triggers one debounced full rebuild. Without this the reverse index would go
silently stale after every rate edit or price-base import, and the four search
modes would answer from stale edges with no warning.

Auto-imported by the module loader when ``oe_cost_explorer`` is loaded (see
``module_loader._load_module`` -> ``events.py``). Every handler runs detached
from the request transaction in its own short-lived session and swallows errors,
so a sync hiccup never propagates into a user request or the publishing module.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

# A bulk import fires one event per region file. A single debounced drainer
# collapses a burst into one rebuild per region and loops until the pending set
# is empty, so no region file is ever left unindexed even if it lands mid-rebuild.
_BULK_DEBOUNCE_SECONDS = 2.0
# Above this many cost items a region-less (whole-catalog) automatic rebuild
# stands down (mirrors the startup auto-build cap) so a huge base is left to a
# deliberate admin reindex. A region-scoped rebuild is bounded by that region
# and always runs, so importing a second big base is never silently unindexed.
_BULK_AUTOREBUILD_MAX_ITEMS = 40000

# Regions awaiting a post-import reindex, plus a flag for a region-less full
# pass, drained by one worker so a burst collapses to one rebuild per region and
# nothing enqueued during a rebuild is lost. One-element lists keep the flags
# mutable from the nested handler without a module-level ``global`` statement.
_PENDING_REGIONS: set[str] = set()
_PENDING_GLOBAL = [False]
_DRAINING = [False]
_PENDING_LOCK = asyncio.Lock()


def _extract_item_id(event: Event) -> uuid.UUID | None:
    """Pull ``item_id`` out of an event payload as a UUID, or None if absent/bad."""
    raw = (event.data or {}).get("item_id")
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _refresh_one(item_id: uuid.UUID) -> None:
    """Rebuild the reverse-index edges for a single changed cost item."""
    from app.database import async_session_factory
    from app.modules.cost_explorer.repository import CostExplorerRepository
    from app.modules.cost_explorer.service import CostExplorerService

    try:
        async with async_session_factory() as session:
            repo = CostExplorerRepository(session)
            # Only maintain an index that already exists. Before the first build
            # a single item event must not seed a one-row index and thereby
            # suppress the full startup build.
            if await repo.count_edges() == 0:
                return
            await CostExplorerService(repo).refresh_item(item_id)
            await session.commit()
    except Exception:  # pragma: no cover - best-effort background sync
        logger.debug("Cost Explorer: edge refresh failed for %s", item_id, exc_info=True)


async def _remove_one(item_id: uuid.UUID) -> None:
    """Drop a deleted cost item's edges from the reverse index."""
    from app.database import async_session_factory
    from app.modules.cost_explorer.repository import CostExplorerRepository

    try:
        async with async_session_factory() as session:
            repo = CostExplorerRepository(session)
            await repo.delete_edges_for_item(item_id)
            await session.commit()
    except Exception:  # pragma: no cover - best-effort background sync
        logger.debug("Cost Explorer: edge delete failed for %s", item_id, exc_info=True)


async def _on_cost_item_created(event: Event) -> None:
    item_id = _extract_item_id(event)
    if item_id is not None:
        await _refresh_one(item_id)


async def _on_cost_item_updated(event: Event) -> None:
    item_id = _extract_item_id(event)
    if item_id is not None:
        await _refresh_one(item_id)


async def _on_cost_item_deleted(event: Event) -> None:
    item_id = _extract_item_id(event)
    if item_id is not None:
        await _remove_one(item_id)


async def _on_bulk_import(event: Event) -> None:
    """Refresh the reverse index after a bulk import.

    A price-base import loads one region at a time and the event carries that
    region, so rebuild JUST that region's edges: the work is bounded by the
    region and runs even when the whole catalog is past the global auto-rebuild
    cap (the common multi-region case, where a later import would otherwise be
    left silently unindexed with no signal). A region-less bulk event keeps the
    debounced, size-capped whole-catalog rebuild.

    Enqueue-and-drain: the first event becomes the drainer, waits out the
    debounce so a burst of files accumulates, then rebuilds every pending region
    in a loop until the pending set is empty, so a file that lands mid-rebuild is
    never dropped. Concurrent events just enqueue and return. The pending set and
    the drain hand-off are guarded by one lock, so an event that arrives exactly
    as the drainer exits either is seen by that drainer or makes the new arrival
    the next drainer - it is never stranded.
    """
    region = (event.data or {}).get("region")
    async with _PENDING_LOCK:
        if region is not None:
            _PENDING_REGIONS.add(str(region))
        else:
            _PENDING_GLOBAL[0] = True
        if _DRAINING[0]:
            return  # a drainer is already running; it will pick this up
        _DRAINING[0] = True

    try:
        await asyncio.sleep(_BULK_DEBOUNCE_SECONDS)  # let a burst of files settle
        while True:
            async with _PENDING_LOCK:
                if _PENDING_GLOBAL[0]:
                    _PENDING_GLOBAL[0] = False
                    _PENDING_REGIONS.clear()
                    job = ("global", None)
                elif _PENDING_REGIONS:
                    job = ("region", _PENDING_REGIONS.pop())
                else:
                    _DRAINING[0] = False  # nothing left; hand off while holding the lock
                    return
            try:
                if job[0] == "global":
                    await _rebuild_global()
                elif job[1] is not None:
                    await _rebuild_region(job[1])
            except Exception:  # pragma: no cover - best-effort; skip this job, keep draining
                logger.debug("Cost Explorer: post-import reindex failed for %r", job, exc_info=True)
    except Exception:  # pragma: no cover - unexpected escape; release the drain flag
        async with _PENDING_LOCK:
            _DRAINING[0] = False
        logger.debug("Cost Explorer: post-import reindex drain aborted", exc_info=True)


async def _rebuild_region(region: str) -> None:
    """Reindex one imported region's edges (bounded by the region, uncapped)."""
    from app.database import async_session_factory
    from app.modules.cost_explorer.repository import CostExplorerRepository
    from app.modules.cost_explorer.service import CostExplorerService

    async with async_session_factory() as session:
        report = await CostExplorerService(CostExplorerRepository(session)).reindex_guarded(region=region)
        if report is None:
            return  # another rebuild holds the lock; it will cover these rows
        await session.commit()
        logger.info(
            "Cost Explorer: reverse index rebuilt for region %s after import (%d items -> %d edges).",
            region,
            report.items_scanned,
            report.edges_written,
        )


async def _rebuild_global() -> None:
    """Rebuild the whole index after a region-less bulk import (size-capped)."""
    from app.database import async_session_factory
    from app.modules.cost_explorer.repository import CostExplorerRepository
    from app.modules.cost_explorer.service import CostExplorerService

    async with async_session_factory() as session:
        repo = CostExplorerRepository(session)
        if await repo.count_edges() == 0:
            return  # never built yet; the startup auto-build owns first population
        if await repo.count_cost_items() > _BULK_AUTOREBUILD_MAX_ITEMS:
            logger.info(
                "Cost Explorer: base too large for an automatic post-import rebuild; "
                "run POST /api/v1/cost-explorer/reindex to refresh the index."
            )
            return
        report = await CostExplorerService(repo).reindex_guarded()
        if report is None:
            return
        await session.commit()
        logger.info(
            "Cost Explorer: reverse index rebuilt after bulk import (%d items -> %d edges).",
            report.items_scanned,
            report.edges_written,
        )


def _register_handlers() -> None:
    """Wire the handlers into the event bus (idempotent by callable identity)."""
    event_bus.subscribe_once("costs.item.created", _on_cost_item_created)
    event_bus.subscribe_once("costs.item.updated", _on_cost_item_updated)
    event_bus.subscribe_once("costs.item.deleted", _on_cost_item_deleted)
    event_bus.subscribe_once("costs.items.bulk_imported", _on_bulk_import)


_register_handlers()


__all__ = [
    "_extract_item_id",
    "_on_bulk_import",
    "_on_cost_item_created",
    "_on_cost_item_deleted",
    "_on_cost_item_updated",
    "_rebuild_global",
    "_rebuild_region",
    "_register_handlers",
]
