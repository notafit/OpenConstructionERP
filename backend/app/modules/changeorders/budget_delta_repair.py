# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Put change order budget rows written by 17.7.0 and 17.7.1 back into delta shape.

What went wrong
---------------
An approved change order writes one ``ProjectBudget`` row, and every reader of
the budget (the finance dashboard, the EVM snapshot, the change order impact
preview) sums all of a project's rows. So the row has to carry the change and
nothing else: ``original_budget`` 0, ``revised_budget`` the order's effect.
That is what it carried from v2.9.17 until 17.7.0.

17.7.0 changed the create path to write ``original_budget`` as the project
budget before the change and ``revised_budget`` as that plus the effect. Summed,
each such row added the whole project budget once more: a 100 000 budget with
two change orders of 10 000 and 5 000 read 310 000 original and 325 000 revised
instead of 100 000 and 115 000. The create path is fixed; this module repairs
the rows already on file.

Which rows, exactly
-------------------
A row is rewritten only when all four hold:

* ``metadata.change_order_id`` names a change order that exists,
* that change order went through approval (``approved`` or ``executed``),
* ``original_budget`` is not zero,
* ``revised_budget - original_budget`` equals the change order's ``cost_impact``
  exactly.

That is the 17.7.x signature and nothing wider. A delta row already in shape
has ``original_budget`` 0 and is skipped. A baseline row has no change order
link. A linked row whose difference is not the order's amount is somebody's
edit, not something this release wrote, and deciding what it should say is not
a call this repair gets to make. Each of those is counted and logged as left
alone rather than guessed at.

The rewrite keeps the row's effect and drops the carried budget:
``original_budget`` becomes 0 and ``revised_budget`` becomes the difference.
After that the row no longer matches (its ``original_budget`` is 0), which is
what makes a second pass a no-op without any marker saying the repair ran.

The UPDATE carries the values it read in its WHERE clause, so a row somebody
changed between the read and the write is not overwritten.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.changeorders.models import ChangeOrder
from app.modules.finance.models import ProjectBudget

logger = logging.getLogger(__name__)

#: The statuses a change order holds once its approval has written the budget row.
_APPROVED_STATUSES = frozenset({"approved", "executed"})


def _dec(value: object) -> Decimal:
    return Decimal(str(value if value is not None else 0))


async def repair_carried_forward_budget_deltas(session: AsyncSession) -> int:
    """Rewrite change order budget rows that carry the project budget forward.

    Args:
        session: An open session. The caller commits; the repair registry does.

    Returns:
        Number of rows rewritten. Zero on every pass after the first, and zero
        on an install that never ran 17.7.0 or 17.7.1.
    """
    linked = ProjectBudget.metadata_["change_order_id"].as_string()
    candidates = (
        await session.execute(
            select(
                ProjectBudget.id,
                ProjectBudget.original_budget,
                ProjectBudget.revised_budget,
                linked,
            ).where(linked.is_not(None))
        )
    ).all()

    carried: list[tuple[uuid.UUID, Decimal, Decimal, uuid.UUID]] = []
    for row_id, original, revised, order_ref in candidates:
        original_d = _dec(original)
        if original_d == 0:
            continue
        try:
            order_id = uuid.UUID(str(order_ref))
        except ValueError:
            continue
        carried.append((row_id, original_d, _dec(revised), order_id))
    if not carried:
        return 0

    orders = {
        order_id: (status, _dec(cost_impact))
        for order_id, status, cost_impact in (
            await session.execute(
                select(ChangeOrder.id, ChangeOrder.status, ChangeOrder.cost_impact).where(
                    ChangeOrder.id.in_({order_id for *_, order_id in carried})
                )
            )
        ).all()
    }

    repaired = 0
    left_alone = 0
    for row_id, original, revised, order_id in carried:
        order = orders.get(order_id)
        if order is None or order[0] not in _APPROVED_STATUSES or revised - original != order[1]:
            left_alone += 1
            continue
        result = await session.execute(
            update(ProjectBudget)
            .where(
                ProjectBudget.id == row_id,
                ProjectBudget.original_budget == original,
                ProjectBudget.revised_budget == revised,
            )
            .values(original_budget=Decimal("0"), revised_budget=revised - original)
        )
        repaired += result.rowcount or 0

    if repaired:
        logger.info(
            "Repaired %d change order budget row(s) that carried the project budget forward as their "
            "original budget (written by 17.7.0/17.7.1); each now carries only its change.",
            repaired,
        )
    if left_alone:
        logger.info(
            "Left %d change order budget row(s) with a non-zero original budget untouched: they do not "
            "match the 17.7.0/17.7.1 shape exactly, so they are not this repair's to rewrite.",
            left_alone,
        )
    return repaired
