# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File-search event handlers - index eviction.

Subscribes to ``documents.document.deleted`` and removes the matching
``oe_file_search_index`` row so a deleted document stops surfacing in
full-text search results.

This module is auto-imported by the module loader when the
``oe_file_search`` module is loaded (see ``module_loader._load_module``
-> ``events.py``).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import delete

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.file_search import service
from app.modules.file_search.models import FileSearchIndex

logger = logging.getLogger(__name__)

# Documents are indexed under this file kind (see ``_KIND_LOADERS`` in
# ``file_search.service``); ``file_id`` is the Document UUID.
_DOCUMENT_FILE_KIND = "document"


async def _on_document_deleted(event: Event) -> None:
    """Evict the search-index row(s) for a deleted document.

    Idempotent: removal is a bulk DELETE keyed on ``(file_kind, file_id)``
    (optionally project-scoped), so re-delivery removes zero further
    rows. Failures are logged and swallowed - index eviction is
    best-effort and must never break the document delete path.
    """
    data = event.data or {}
    file_id = str(data.get("document_id") or "").strip()
    if not file_id:
        return

    project_id: uuid.UUID | None = None
    project_raw = str(data.get("project_id") or "").strip()
    if project_raw:
        try:
            project_id = uuid.UUID(project_raw)
        except (ValueError, AttributeError):
            project_id = None

    try:
        async with async_session_factory() as session:
            if project_id is not None:
                removed = await service.delete_index_for_file(
                    session,
                    project_id,
                    file_id,
                    kind=_DOCUMENT_FILE_KIND,
                )
            else:
                # No project scope on the event - fall back to a direct
                # delete keyed on (file_kind, file_id). The Document UUID
                # is globally unique, so this stays precise.
                result = await session.execute(
                    delete(FileSearchIndex).where(
                        FileSearchIndex.file_kind == _DOCUMENT_FILE_KIND,
                        FileSearchIndex.file_id == file_id,
                    )
                )
                await session.flush()
                removed = int(result.rowcount or 0)
            await session.commit()
        if removed:
            logger.info(
                "Evicted %d search-index row(s) for deleted document %s",
                removed,
                file_id,
            )
    except Exception:
        logger.debug(
            "file_search index eviction failed for document %s",
            file_id,
            exc_info=True,
        )


event_bus.subscribe_once("documents.document.deleted", _on_document_deleted)
