# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""cost_explorer - resource -> work reverse index.

Adds the one new table of the Cost Explorer module:

    oe_cost_item_resource - one (work item, resource) edge, mirrored from each
                            cost item's ``components`` list, so "which priced
                            works consume resource X" is an indexed lookup
                            instead of a full JSON scan.

The rows are managed wholesale per region by the reindex service (delete then
insert), so ``cost_item_id`` is an indexed column without a hard foreign key,
matching the bare-GUID cross-table convention used elsewhere in the costs module.

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the table / indexes. Every create is guarded.

Revision ID: v3221_cost_explorer_reverse_index
Revises: v3220_field_time_timesheets
Create Date: 2026-07-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3221_cost_explorer_reverse_index"
down_revision: Union[str, Sequence[str], None] = "v3220_field_time_timesheets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_cost_item_resource"

_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_oe_cost_item_resource_cost_item_id", ("cost_item_id",)),
    ("ix_oe_cir_region_resource", ("region", "resource_code")),
    ("ix_oe_cir_region_rate", ("region", "rate_code")),
    ("ix_oe_cir_resource_code", ("resource_code",)),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _safe_create_index(
    inspector: sa.engine.reflection.Inspector,
    name: str,
    table: str,
    cols: list[str],
) -> None:
    if not _has_table(inspector, table) or _has_index(inspector, table, name):
        return
    try:
        op.create_index(name, table, cols)
    except sa.exc.OperationalError:
        pass


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
        op.create_table(
            _TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("cost_item_id", guid_type, nullable=False),
            sa.Column("rate_code", sa.String(100), nullable=False),
            sa.Column("region", sa.String(50), nullable=True),
            sa.Column("resource_code", sa.String(100), nullable=False),
            sa.Column("resource_name", sa.String(500), nullable=False, server_default=""),
            sa.Column("resource_type", sa.String(20), nullable=False, server_default=""),
            sa.Column("quantity", sa.String(50), nullable=False, server_default=""),
            sa.Column("unit_rate", sa.String(50), nullable=False, server_default=""),
            sa.Column("cost", sa.String(50), nullable=False, server_default=""),
        )

    inspector = sa.inspect(bind)
    for name, cols in _INDEXES:
        _safe_create_index(inspector, name, _TABLE, list(cols))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, _cols in _INDEXES:
        if _has_index(inspector, _TABLE, name):
            try:
                op.drop_index(name, table_name=_TABLE)
            except sa.exc.OperationalError:
                pass

    if _has_table(inspector, _TABLE):
        try:
            op.drop_table(_TABLE)
        except sa.exc.OperationalError:
            pass
