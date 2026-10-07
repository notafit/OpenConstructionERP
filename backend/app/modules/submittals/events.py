# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Submittals event handlers - vector indexing subscribers.

Subscribes to ``submittal.created`` / ``submittal.updated`` /
``submittal.deleted`` lifecycle events and keeps the
``oe_submittals_submittals`` vector collection in sync with the
underlying Submittal rows so semantic search and the floating-chat
assistant always reflect the latest data.

This module is auto-imported by the module loader when the
``oe_submittals`` module is loaded (see ``module_loader._load_module`` →
``events.py``), so the ``event_bus.subscribe`` calls below run at startup.
"""

import logging
import uuid

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.submittals.models import Submittal
from app.modules.submittals.vector_adapter import submittal_vector_adapter

logger = logging.getLogger(__name__)


# ── Vector indexing subscribers ──────────────────────────────────────────
#
# Keep the ``oe_submittals_submittals`` collection in sync with the live
# Submittal rows.  Each handler opens its own short-lived session, loads
# the row and forwards it to the adapter.  Failures are logged and
# swallowed - vector indexing is best-effort and must never break a normal
# CRUD path.


async def _index_submittal(event: Event) -> None:
    """Re-embed a single Submittal row after create / update."""
    sid_raw = (event.data or {}).get("submittal_id")
    if not sid_raw:
        return
    try:
        submittal_id = uuid.UUID(str(sid_raw))
    except (ValueError, AttributeError):
        return

    try:
        async with async_session_factory() as session:
            stmt = select(Submittal).where(Submittal.id == submittal_id)
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                # Race: row was deleted between publish and handler.
                await vector_delete_one(submittal_vector_adapter, str(submittal_id))
                return
            project_id = str(row.project_id) if row.project_id is not None else None
            await vector_index_one(
                submittal_vector_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Submittal vector index failed for %s", sid_raw, exc_info=True)


async def _delete_submittal_vector(event: Event) -> None:
    """Remove a deleted Submittal row from the vector store."""
    sid_raw = (event.data or {}).get("submittal_id")
    if not sid_raw:
        return
    try:
        await vector_delete_one(submittal_vector_adapter, str(sid_raw))
    except Exception:
        logger.debug("Submittal vector delete failed for %s", sid_raw, exc_info=True)


# Wrappers that match the EventBus handler signature (Event → awaitable).
async def _on_submittal_created(event: Event) -> None:
    await _index_submittal(event)


async def _on_submittal_updated(event: Event) -> None:
    await _index_submittal(event)


async def _on_submittal_deleted(event: Event) -> None:
    await _delete_submittal_vector(event)


event_bus.subscribe_once("submittal.created", _on_submittal_created)
event_bus.subscribe_once("submittal.updated", _on_submittal_updated)
event_bus.subscribe_once("submittal.deleted", _on_submittal_deleted)
# Workflow transitions (submit / review / approve) change the embedded
# status, so reindex on those too.
event_bus.subscribe_once("submittal.submitted", _on_submittal_updated)
event_bus.subscribe_once("submittal.reviewed", _on_submittal_updated)
event_bus.subscribe_once("submittal.approved", _on_submittal_updated)
