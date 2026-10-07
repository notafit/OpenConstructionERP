# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the change orders module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def _run_budget_delta_original(session: AsyncSession) -> int:
    """Put change order budget rows written by 17.7.0 and 17.7.1 back into delta shape.

    Imported inside the function so that importing this module costs only the
    registration, not the repair's own dependency tree.
    """
    from app.modules.changeorders.budget_delta_repair import repair_carried_forward_budget_deltas

    return await repair_carried_forward_budget_deltas(session)


#: Nature ``always_wrong``: a change order's budget row carrying the project
#: budget forward as its ``original`` was never a correct value. Every reader
#: sums all of a project's budget rows, so from the first such row the original
#: and revised totals were overstated by the carried budget, and by more with
#: each further change order. No document was priced against the overstated
#: total being right, so rewriting the row in place is the whole repair.
#:
#: The row's effect on the revised budget is kept exactly; only the carried
#: budget is dropped. A project with no baseline rows still shows its original
#: budget afterwards, because ``BudgetRepository.aggregate_for_dashboard`` reads
#: it off the project. No alembic revision sits behind this: the defect was in
#: service code, not in a migration.
CHANGEORDER_BUDGET_DELTA_ORIGINAL = register_data_repair(
    DataRepair(
        repair_id="changeorder_budget_delta_carried_original",
        revision="",
        summary="Reset change order budget rows that carried the project budget forward as their original budget",
        run=_run_budget_delta_original,
        nature="always_wrong",
    )
)
