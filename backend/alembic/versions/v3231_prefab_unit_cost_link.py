# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""prefab - link an off-site unit to a BOQ position and/or an assembly.

Adds two additive columns to ``oe_prefab_unit`` so an off-site production unit
can reflect real cost and earned value instead of being a standalone board:

    boq_position_id - optional link to oe_boq_position.id (plain GUID, NO
                      ForeignKey, per the cross-module-ref convention) whose
                      unit_rate becomes the unit's cost basis
    assembly_id     - optional link to oe_assemblies_assembly.id (same
                      convention) whose total_rate is the fallback cost basis

plus an index on each. The linked rate is read at serialisation time; nothing
is stored on the unit.

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the columns / indexes. The downgrade drops the indexes then the
columns.

Revision ID: v3231_prefab_unit_cost_link
Revises: v3230_merge_estimate_costexplorer_heads
Create Date: 2026-07-08
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3231_prefab_unit_cost_link"
down_revision: Union[str, Sequence[str], None] = "v3230_merge_estimate_costexplorer_heads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "oe_prefab_unit"
_IX_BOQ = "ix_oe_prefab_unit_boq_position_id"
_IX_ASSEMBLY = "ix_oe_prefab_unit_assembly_id"


def _has_table(inspector: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # ``String(36)`` on PostgreSQL too. ``GUID`` in ``app.database`` is a
    # ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
    # ``create_all`` builds every identity column as ``character varying(36)``
    # and a native uuid here cannot carry a foreign key to one: PostgreSQL
    # answers ``DatatypeMismatch`` as soon as the chain is walked, not stamped.
    guid_type = sa.String(36)

    if not _has_table(inspector, _TABLE):
        # Fresh install where create_all has not yet built the table - the
        # model definition already carries the new columns, so nothing to do.
        logger.info("v3231 prefab unit cost link: table %s absent, skipping", _TABLE)
        return

    if not _has_column(inspector, _TABLE, "boq_position_id"):
        op.add_column(_TABLE, sa.Column("boq_position_id", guid_type, nullable=True))
    if not _has_column(inspector, _TABLE, "assembly_id"):
        op.add_column(_TABLE, sa.Column("assembly_id", guid_type, nullable=True))

    # Refresh the inspector - add_column above invalidates the cached metadata.
    inspector = sa.inspect(bind)
    for column, index in (("boq_position_id", _IX_BOQ), ("assembly_id", _IX_ASSEMBLY)):
        if _has_column(inspector, _TABLE, column) and not _has_index(inspector, _TABLE, index):
            try:
                op.create_index(index, _TABLE, [column])
            except sa.exc.OperationalError:
                # Tolerate a race with another upgrade or a pre-existing index
                # that did not show up in the cached inspector data.
                pass

    logger.info("v3231 prefab unit cost link: schema ensured")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for index in (_IX_BOQ, _IX_ASSEMBLY):
        if _has_index(inspector, _TABLE, index):
            try:
                op.drop_index(index, table_name=_TABLE)
            except sa.exc.OperationalError:
                pass

    for column in ("assembly_id", "boq_position_id"):
        if _has_column(inspector, _TABLE, column):
            try:
                op.drop_column(_TABLE, column)
            except (sa.exc.OperationalError, NotImplementedError):
                # Dropping a column on SQLite needs batch mode; tolerate failure
                # on that backend (dev only - production is PostgreSQL).
                pass

    logger.info("v3231 prefab unit cost link: reverted")
