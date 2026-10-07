# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Match Elements event handlers.

Auto-imported by the module loader when the ``oe_match_elements`` module
is loaded (see ``module_loader._load_module`` -> ``events.py``).

Currently handles one concern: keeping ``MatchGroup.boq_position_id``
backlinks from dangling. When the BOQ module deletes a position it
publishes ``boq.position.deleted`` with ``{"position_id": ..., "boq_id":
...}``. A match group that had been applied to that position still
carries the now-dead id in ``boq_position_id``; left alone it points at a
row that no longer exists, which breaks the "open the applied position"
backlink and any rollup that joins on it. This handler clears the stale
reference so the group falls back to "confirmed but not applied".
"""

import logging
import uuid

from sqlalchemy import update

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.match_elements.models import MatchGroup

logger = logging.getLogger(__name__)


def _coerce_uuid(raw: object) -> uuid.UUID | None:
    """Best-effort parse of an event-payload id into a UUID, else None."""
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        return None


async def _on_boq_position_deleted(event: Event) -> None:
    """Clear ``boq_position_id`` from groups that referenced a deleted position.

    Idempotent and non-throwing: a malformed payload, a missing id, or a
    DB hiccup is logged and swallowed so a match-side cleanup can never
    block or roll back the BOQ delete that triggered it. Running it twice
    is harmless - the second pass matches zero rows.

    The BOQ delete cascade can remove several descendant positions in one
    event burst (one event per deleted id), but it also publishes a single
    event per id, so we handle the single ``position_id`` carried by this
    event; a cascade simply fires this handler once per deleted id.
    """
    data = event.data or {}
    position_id = _coerce_uuid(data.get("position_id"))
    if position_id is None:
        return

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                update(MatchGroup).where(MatchGroup.boq_position_id == position_id).values(boq_position_id=None),
            )
            await session.commit()
            cleared = result.rowcount or 0
            if cleared:
                logger.info(
                    "Cleared dangling boq_position_id=%s from %d match group(s)",
                    position_id,
                    cleared,
                )
    except Exception:  # noqa: BLE001 - cleanup must never break the delete
        logger.exception(
            "Failed to clear boq_position_id=%s from match groups",
            position_id,
        )


def _register_handlers() -> None:
    """Register the match-elements event-bus handlers.

    Idempotent: tests can call ``event_bus.clear()`` then re-invoke this.
    """
    event_bus.subscribe_once("boq.position.deleted", _on_boq_position_deleted)


_register_handlers()
