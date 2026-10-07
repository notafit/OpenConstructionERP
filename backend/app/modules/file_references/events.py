# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File-references event handlers - orphan cleanup.

Subscribes to ``documents.document.deleted`` and purges the
``oe_file_reference`` rows that point at the now-deleted document, so
cross-entity links (RFI -> drawing, task -> photo, ...) never dangle to a
file that no longer exists.

This module is auto-imported by the module loader when the
``oe_file_references`` module is loaded (see ``module_loader._load_module``
-> ``events.py``).
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.file_references import service

logger = logging.getLogger(__name__)

# Document rows are recorded in file references under this file kind
# (see ``file_references.schemas.ALLOWED_FILE_KINDS``).
_DOCUMENT_FILE_KIND = "document"


async def _on_document_deleted(event: Event) -> None:
    """Purge every FileReference row for a deleted document.

    Idempotent: ``purge_references_for_file`` issues a bulk DELETE keyed
    on ``(file_kind, file_id)``, so re-delivery of the same event simply
    removes zero further rows. Failures are logged and swallowed - a
    best-effort cleanup must never break the document delete path.
    """
    data = event.data or {}
    file_id = str(data.get("document_id") or "").strip()
    if not file_id:
        return
    # Scope the purge to the project that owned the document so a delete
    # in one project never wipes a same-id file's references elsewhere
    # (file_id is a polymorphic string key, not globally unique by
    # contract). Omitted when the event predates the project_id payload.
    project_id = str(data.get("project_id") or "").strip() or None

    try:
        async with async_session_factory() as session:
            removed = await service.purge_references_for_file(
                session,
                file_kind=_DOCUMENT_FILE_KIND,
                file_id=file_id,
                project_id=project_id,
            )
            await session.commit()
        if removed:
            logger.info(
                "Purged %d file reference(s) for deleted document %s",
                removed,
                file_id,
            )
    except Exception:
        logger.debug(
            "file_references purge failed for document %s",
            file_id,
            exc_info=True,
        )


event_bus.subscribe_once("documents.document.deleted", _on_document_deleted)
