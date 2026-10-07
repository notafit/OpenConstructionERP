# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI event handlers - vector indexing subscribers.

Subscribes to ``rfi.created`` / ``rfi.updated`` / ``rfi.deleted``
lifecycle events and keeps the ``oe_rfi_rfis`` vector collection in sync
with the underlying RFI rows so semantic search and the floating-chat
assistant always reflect the latest data.

This module is auto-imported by the module loader when the ``oe_rfi``
module is loaded (see ``module_loader._load_module`` → ``events.py``), so
the ``event_bus.subscribe`` calls below run at startup.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.rfi.models import RFI
from app.modules.rfi.vector_adapter import rfi_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_rfi_rfis`` collection in sync with the live RFI rows.  Each
# handler opens its own short-lived session, loads the row and forwards it
# to the adapter.  Failures are logged and swallowed - vector indexing is
# best-effort and must never break a normal CRUD path.


async def _index_rfi(event: Event) -> None:
    """Re-embed a single RFI row after create / update."""
    rid_raw = (event.data or {}).get("rfi_id")
    if not rid_raw:
        return
    try:
        rfi_id = uuid.UUID(str(rid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(RFI).where(RFI.id == rfi_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(rfi_vector_adapter, str(rfi_id))
                return
            project_id = str(row.project_id) if row.project_id is not None else None
            await vector_index_one(
                rfi_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("RFI vector index failed for %s", rid_raw, exc_info=True)


async def _delete_rfi_vector(event: Event) -> None:
    """Remove a deleted RFI row from the vector store."""
    rid_raw = (event.data or {}).get("rfi_id")
    if not rid_raw:
        return
    try:
        await vector_delete_one(rfi_vector_adapter, str(rid_raw))
    except Exception:
        logger.debug("RFI vector delete failed for %s", rid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_rfi_created(event: Event) -> None:
    await _index_rfi(event)


async def _on_rfi_updated(event: Event) -> None:
    await _index_rfi(event)


async def _on_rfi_deleted(event: Event) -> None:
    await _delete_rfi_vector(event)


event_bus.subscribe_once("rfi.created", _on_rfi_created)
event_bus.subscribe_once("rfi.updated", _on_rfi_updated)
event_bus.subscribe_once("rfi.deleted", _on_rfi_deleted)
# RFI lifecycle transitions (respond / close) also change the embedded
# text (official_response, status), so reindex on those too.
event_bus.subscribe_once("rfi.responded", _on_rfi_updated)
event_bus.subscribe_once("rfi.closed", _on_rfi_updated)
