# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Schedule Advanced event handlers - takt / line-of-balance.

Subscribes to the ``schedule_advanced.takt.*`` event family published by
:class:`~app.modules.schedule_advanced.service.TaktScheduleService` and
keeps lightweight, side-effect-free bookkeeping in place (structured log
lines for observability). These handlers are intentionally non-blocking
and never open a second DB session - they run inside the detached event
task scheduled by ``event_bus.publish_detached``.

This module is auto-imported by the module loader when ``oe_schedule_advanced``
is loaded (see ``module_loader._load_module`` → ``events.py``).
"""

from __future__ import annotations

import logging

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)


async def _on_takt_schedule_created(event: Event) -> None:
    """Log takt schedule creation for observability / downstream hooks."""
    data = event.data or {}
    logger.info(
        "takt schedule created: id=%s master=%s locations=%s",
        data.get("takt_schedule_id"),
        data.get("master_schedule_id"),
        data.get("location_count"),
    )


async def _on_takt_activities_imported(event: Event) -> None:
    """Log a bulk activity import into a takt schedule."""
    data = event.data or {}
    logger.info(
        "takt activities imported: takt=%s count=%s",
        data.get("takt_schedule_id"),
        data.get("count"),
    )


async def _on_takt_cycle_updated(event: Event) -> None:
    """Record a line-of-balance recomputation.

    The takt timeline shifting is a signal other modules (e.g. KPI
    rollups) may want to react to; for now we emit a structured log line
    so the makespan / violation movement is observable in production.
    """
    data = event.data or {}
    logger.info(
        "takt cycle updated: takt=%s makespan=%s violations=%s",
        data.get("takt_schedule_id"),
        data.get("makespan_days"),
        data.get("violation_count"),
    )


def _register_handlers() -> None:
    """Wire takt handlers into the event bus.

    Idempotent in practice - the bus dedups by callable identity, and the
    module loader imports this module exactly once per process.
    """
    event_bus.subscribe_once("schedule_advanced.takt.schedule.created", _on_takt_schedule_created)
    event_bus.subscribe_once("schedule_advanced.takt.activities_imported", _on_takt_activities_imported)
    event_bus.subscribe_once("schedule_advanced.takt.cycle_updated", _on_takt_cycle_updated)


_register_handlers()


__all__: list[str] = [
    "_on_takt_activities_imported",
    "_on_takt_cycle_updated",
    "_on_takt_schedule_created",
    "_register_handlers",
]
