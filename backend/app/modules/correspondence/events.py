# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Correspondence event handlers - vector indexing subscribers.

Subscribes to ``correspondence.created`` / ``correspondence.updated`` /
``correspondence.deleted`` lifecycle events and keeps the
``oe_correspondence_correspondence`` vector collection in sync with the
underlying Correspondence rows so semantic search and the floating-chat
assistant always reflect the latest data.

This module is auto-imported by the module loader when the
``oe_correspondence`` module is loaded (see ``module_loader._load_module``
→ ``events.py``), so the ``event_bus.subscribe`` calls below run at
startup.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.correspondence.models import Correspondence
from app.modules.correspondence.vector_adapter import correspondence_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_correspondence_correspondence`` collection in sync with the
# live Correspondence rows.  Each handler opens its own short-lived
# session, loads the row and forwards it to the adapter.  Failures are
# logged and swallowed - vector indexing is best-effort and must never
# break a normal CRUD path.


async def _index_correspondence(event: Event) -> None:
    """Re-embed a single Correspondence row after create / update."""
    cid_raw = (event.data or {}).get("correspondence_id")
    if not cid_raw:
        return
    try:
        correspondence_id = uuid.UUID(str(cid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(Correspondence).where(Correspondence.id == correspondence_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(correspondence_vector_adapter, str(correspondence_id))
                return
            project_id = str(row.project_id) if row.project_id is not None else None
            await vector_index_one(
                correspondence_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Correspondence vector index failed for %s", cid_raw, exc_info=True)


async def _delete_correspondence_vector(event: Event) -> None:
    """Remove a deleted Correspondence row from the vector store."""
    cid_raw = (event.data or {}).get("correspondence_id")
    if not cid_raw:
        return
    try:
        await vector_delete_one(correspondence_vector_adapter, str(cid_raw))
    except Exception:
        logger.debug("Correspondence vector delete failed for %s", cid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_correspondence_created(event: Event) -> None:
    await _index_correspondence(event)


async def _on_correspondence_updated(event: Event) -> None:
    await _index_correspondence(event)


async def _on_correspondence_deleted(event: Event) -> None:
    await _delete_correspondence_vector(event)


event_bus.subscribe_once("correspondence.created", _on_correspondence_created)
event_bus.subscribe_once("correspondence.updated", _on_correspondence_updated)
event_bus.subscribe_once("correspondence.deleted", _on_correspondence_deleted)
