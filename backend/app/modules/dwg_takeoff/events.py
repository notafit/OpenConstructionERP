# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""DWG Takeoff event handlers.

Auto-imported by the module loader when the ``oe_dwg_takeoff`` module is
loaded (see ``module_loader._load_module`` -> ``events.py``).

Currently handles one concern: keeping ``DwgAnnotation.linked_boq_position_id``
backlinks from dangling. When the BOQ module deletes a position it publishes
``boq.position.deleted`` with ``{"position_id": ..., "boq_id": ...}``. A
takeoff annotation that had been linked to that position still carries the
now-dead id in ``linked_boq_position_id``; left alone it points at a row that
no longer exists, which breaks the "jump to the linked position" backlink and
any quantity rollup that joins on it. This handler clears the stale reference
so the annotation falls back to "measured but not linked".

Unlike ``MatchGroup.boq_position_id`` (a real UUID column), this column is a
free-form ``String(255)``, so we match on the string form of the deleted id
and also on its canonical UUID spelling to cover either way it was stored.
"""

import logging
import uuid

from sqlalchemy import update

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.dwg_takeoff.models import DwgAnnotation

logger = logging.getLogger(__name__)


def _id_candidates(raw: object) -> list[str]:
    """Return the distinct string forms a linked id could have been stored as.

    The published ``position_id`` is already a string, but a linker may have
    stored it raw or as the canonical hyphenated UUID. We match on both so the
    cleanup catches the row regardless of how it was written.
    """
    if raw is None:
        return []
    raw_str = str(raw).strip()
    if not raw_str:
        return []
    forms = {raw_str}
    try:
        forms.add(str(uuid.UUID(raw_str)))
    except (ValueError, AttributeError, TypeError):
        pass
    return list(forms)


async def _on_boq_position_deleted(event: Event) -> None:
    """Clear ``linked_boq_position_id`` from annotations of a deleted position.

    Idempotent and non-throwing: a malformed payload, a missing id, or a DB
    hiccup is logged and swallowed so a takeoff-side cleanup can never block or
    roll back the BOQ delete that triggered it. Running it twice is harmless -
    the second pass matches zero rows.

    The BOQ delete cascade publishes one event per deleted id, so this handler
    fires once per deleted position and clears every annotation linked to it.
    """
    data = event.data or {}
    candidates = _id_candidates(data.get("position_id"))
    if not candidates:
        return

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                update(DwgAnnotation)
                .where(DwgAnnotation.linked_boq_position_id.in_(candidates))
                .values(linked_boq_position_id=None),
            )
            await session.commit()
            cleared = result.rowcount or 0
            if cleared:
                logger.info(
                    "Cleared dangling linked_boq_position_id=%s from %d annotation(s)",
                    candidates[0],
                    cleared,
                )
    except Exception:  # noqa: BLE001 - cleanup must never break the delete
        logger.exception(
            "Failed to clear linked_boq_position_id=%s from dwg annotations",
            candidates[0],
        )


def _register_handlers() -> None:
    """Register the dwg-takeoff event-bus handlers.

    Idempotent: tests can call ``event_bus.clear()`` then re-invoke this.
    """
    event_bus.subscribe_once("boq.position.deleted", _on_boq_position_deleted)


_register_handlers()
