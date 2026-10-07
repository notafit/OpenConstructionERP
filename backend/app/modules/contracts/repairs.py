# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the contracts module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def _run_claim_period_dates(session: AsyncSession) -> int:
    """Fill each claim's date columns from its period strings.

    Parsed in Python rather than with a SQL cast, so every dialect reads a
    stored value the way the service's write path does
    (:func:`~app.modules.contracts.periods.parse_iso_day` in both places), and
    an unreadable string leaves its date NULL instead of failing the statement
    for every other row. Imported inside the function so that importing this
    module costs only the registration.
    """
    from sqlalchemy import and_, func, or_, select, update

    from app.modules.contracts.models import ProgressClaim
    from app.modules.contracts.periods import CLAIM_PERIOD_COLUMNS, claim_dates_to_backfill

    def _missing(text_column: str, date_column: str) -> Any:
        return and_(
            getattr(ProgressClaim, date_column).is_(None),
            func.coalesce(func.trim(getattr(ProgressClaim, text_column)), "") != "",
        )

    rows = (
        (
            await session.execute(
                select(
                    ProgressClaim.id,
                    ProgressClaim.period_start,
                    ProgressClaim.period_end,
                    ProgressClaim.claim_date,
                    ProgressClaim.period_from,
                    ProgressClaim.period_to,
                    ProgressClaim.application_date,
                ).where(or_(*(_missing(text, day) for text, day, _bound in CLAIM_PERIOD_COLUMNS)))
            )
        )
        .mappings()
        .all()
    )

    changed = 0
    unreadable = 0
    for row in rows:
        values = claim_dates_to_backfill(dict(row))
        if not values:
            # Every missing date sits beside a string the parser refused. Left
            # NULL on purpose: pay_application.period_unparsed reports it on the
            # claim, where a person can correct the string.
            unreadable += 1
            continue
        # The NULL guards let a concurrent write by the service win: whatever
        # it stored is never overwritten by this pass.
        guards = [getattr(ProgressClaim, column).is_(None) for column in values]
        result = await session.execute(
            update(ProgressClaim)
            .where(ProgressClaim.id == row["id"], *guards)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        changed += result.rowcount or 0

    if changed:
        logger.info("Stamped period dates on %d progress claim(s) from their period strings.", changed)
    if unreadable:
        logger.info(
            "Left %d progress claim(s) whose period string no date could be read from; "
            "pay_application.period_unparsed reports each one on its claim.",
            unreadable,
        )
    return changed


#: Nature ``always_wrong``: since ``v42_contracts_billing_depth`` the model
#: declares ``period_from``, ``period_to`` and ``application_date`` as the
#: parsed form of ``period_start``, ``period_end`` and ``claim_date``. A NULL
#: date beside a string that parses was never a valid state. It is only the
#: state every claim written before the columns existed arrives in, because the
#: boot heal adds a column and cannot fill it. Nothing was billed or certified
#: against the date being NULL, so filling it in place is the whole repair.
#: Idempotent: it writes only NULL targets, so a second pass finds nothing to
#: do, and a string that cannot be read stays NULL on every pass.
CONTRACTS_CLAIM_PERIOD_DATES = register_data_repair(
    DataRepair(
        repair_id="contracts_claim_period_dates",
        revision="v42_contracts_billing_depth",
        summary="Fill progress claim period dates from the period strings written before the date columns existed",
        run=_run_claim_period_dates,
        nature="always_wrong",
    )
)
