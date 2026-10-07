# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Boot-path data repairs owned by the funding module.

Imported by :func:`app.core.data_repairs.discover_data_repairs`, which is what
makes the registration below take effect. Nothing else imports this file, and
nothing needs to.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.data_repairs import DataRepair, register_data_repair

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_OBLIGATION = "oe_funding_obligation"

#: The one column ``v41_funding_obligation_detail`` tightens, with the SQL
#: literal that revision gives it. Copied from the revision deliberately rather
#: than derived, for the same reason the requirements repair copies its five:
#: the defect being repaired is two build paths disagreeing, so the repair has
#: to restore what the revision declared and the two literals have to be
#: readable side by side.
#:
#: ``detail_key`` is not here, and its absence is the finding. It was added by
#: the same edit, to the same table, declared the same way - and it arrived
#: correctly, because ``default=""`` is a scalar the heal can render into DDL
#: while ``default=dict`` is a callable it cannot. Two columns from one edit,
#: two different shapes in the database.
_OBLIGATION_COLUMNS = {
    "detail_params": "'{}'",
}


async def _run(session: AsyncSession) -> int:
    """Backfill and tighten the parameter column the heal could not carry NOT NULL.

    Imported inside the function so that importing this module costs only the
    registration, not the repair's own dependency tree.
    """
    from app.core.not_null_repair import tighten_not_null

    return await tighten_not_null(session, _OBLIGATION, _OBLIGATION_COLUMNS)


#: Nature ``always_wrong``: the model has declared this column NOT NULL since
#: the revision that added it and ``FundingObligationResponse`` types it
#: ``dict[str, Any]``. A NULL is not a value that used to be right, it is one
#: the model has never permitted.
#:
#: What this repair is for is worth stating exactly, because it is not what the
#: requirements repair is for. There, a NULL reached ``model_validate`` and the
#: read raised. Here it does not: ``FundingObligationResponse`` carries a
#: ``mode="before"`` validator that coerces ``None`` to ``{}``, written when
#: this same split turned the deadline list into a 500. So no read is broken
#: today and no row is unreadable, and a repair that claimed otherwise would be
#: overstating itself.
#:
#: Two things are still wrong and neither is reachable from the read path. The
#: column is declared nullable, so ``not_null_divergences`` reports it on every
#: boot and the install answers ``schema_matches_models=false`` for good - a
#: permanent false alarm, which is the kind that teaches an operator to read
#: ``degraded`` as normal and then hides a real one. And the column has no
#: DEFAULT, so an INSERT that omits it writes NULL on a healed database and
#: ``{}`` on a migrated one: the two populations behave differently for any
#: writer that does not go through the ORM.
#:
#: The revision tightens the column too, and on its own that reaches nobody.
#: The product moves its schema at boot and then stamps head, so ``upgrade()``
#: runs only where an operator runs alembic by hand. This registration is how
#: the ordinary install gets the same treatment.
FUNDING_OBLIGATION_DETAIL_PARAMS_NOT_NULL = register_data_repair(
    DataRepair(
        repair_id="funding_obligation_detail_params_not_null",
        revision="v41_funding_obligation_detail",
        summary="Backfill and re-tighten the funding obligation detail parameters the boot heal left nullable",
        run=_run,
        nature="always_wrong",
    )
)
