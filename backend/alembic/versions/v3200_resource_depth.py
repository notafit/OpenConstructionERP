# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""resources T3.1: resource depth (effective-dated rates + assignment curves).

Adds the resource-depth tables and two demand columns:

* ``oe_resources_rate`` - effective-dated, multi-type rate rows per resource.
* ``oe_resources_assignment_curve`` - an optional spreading curve per assignment
  (unique on ``assignment_id``).
* ``oe_resources_assignment.units`` / ``.unit_kind`` - the native-units demand
  lane (crew=3, excavator=1), additive on the existing assignment table.

FKs into the existing resources tables reuse ``String(36)``, which is what
those tables were created with on every dialect: ``GUID`` in ``app.database``
is a ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
``create_all`` renders each identity column as ``character varying(36)`` on
PostgreSQL as well. This paragraph used to say the type was dialect-aware and
native uuid on PostgreSQL, and the constraints did not type-match at all - a
uuid child pointing at a varchar parent is refused with ``DatatypeMismatch``
the moment the chain is walked rather than stamped. Every step is guarded so re-applying on a DB
where ``Base.metadata.create_all`` already built the schema is a no-op; the
downgrade fully reverses the upgrade.

Revision ID: v3200_resource_depth
Revises: v3199_portfolio_tree
Create Date: 2026-06-23
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3200_resource_depth"
down_revision: Union[str, Sequence[str], None] = "v3199_portfolio_tree"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_RATE = "oe_resources_rate"
_CURVE = "oe_resources_assignment_curve"
_ASSIGNMENT = "oe_resources_assignment"

# (index_name, table, [columns], unique)
_INDEXES: tuple[tuple[str, str, list[str], bool], ...] = (
    ("ix_oe_resources_rate_resource_id", _RATE, ["resource_id"], False),
    ("ix_oe_resources_rate_lookup", _RATE, ["resource_id", "rate_type", "effective_from"], False),
)


def _has_table(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _has_index(bind: sa.engine.Connection, table: str, index: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index for ix in insp.get_indexes(table))


def _has_column(bind: sa.engine.Connection, table: str, column: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
    )


def upgrade() -> None:
    bind = op.get_bind()
    # ``String(36)`` on PostgreSQL too. ``GUID`` in ``app.database`` is a
    # ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
    # ``create_all`` builds every identity column as ``character varying(36)``
    # and a native uuid here cannot carry a foreign key to one: PostgreSQL
    # answers ``DatatypeMismatch`` as soon as the chain is walked, not stamped.
    guid_type = sa.String(36)

    if not _has_table(bind, _RATE):
        op.create_table(
            _RATE,
            sa.Column("id", guid_type, primary_key=True),
            *_timestamps(),
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("rate", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("rate_type", sa.String(16), nullable=False, server_default="cost"),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    if not _has_table(bind, _CURVE):
        op.create_table(
            _CURVE,
            sa.Column("id", guid_type, primary_key=True),
            *_timestamps(),
            sa.Column(
                "assignment_id",
                guid_type,
                sa.ForeignKey("oe_resources_assignment.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("curve_type", sa.String(16), nullable=False, server_default="flat"),
            sa.Column("manual_weights", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("assignment_id", name="uq_resources_assignment_curve_assignment"),
        )

    for index_name, table, columns, unique in _INDEXES:
        if _has_table(bind, table) and not _has_index(bind, table, index_name):
            op.create_index(index_name, table, columns, unique=unique)

    # Additive demand columns on the existing assignment table.
    if _has_table(bind, _ASSIGNMENT) and not _has_column(bind, _ASSIGNMENT, "units"):
        op.add_column(_ASSIGNMENT, sa.Column("units", sa.Numeric(18, 4), nullable=True))
    if _has_table(bind, _ASSIGNMENT) and not _has_column(bind, _ASSIGNMENT, "unit_kind"):
        op.add_column(_ASSIGNMENT, sa.Column("unit_kind", sa.String(16), nullable=False, server_default="labor"))

    logger.info("v3200 resource depth: 2 tables + 2 assignment columns ensured")


def downgrade() -> None:
    bind = op.get_bind()

    for column in ("unit_kind", "units"):
        if _has_column(bind, _ASSIGNMENT, column):
            try:
                op.drop_column(_ASSIGNMENT, column)
            except (sa.exc.OperationalError, NotImplementedError):  # pragma: no cover - sqlite pre-batch
                pass

    # Child/leaf tables before any parent (none here reference each other).
    for table in (_CURVE, _RATE):
        if _has_table(bind, table):
            for index_name, idx_table, _columns, _unique in _INDEXES:
                if idx_table == table and _has_index(bind, table, index_name):
                    op.drop_index(index_name, table_name=table)
            op.drop_table(table)

    logger.info("v3200 resource depth: reverted")
