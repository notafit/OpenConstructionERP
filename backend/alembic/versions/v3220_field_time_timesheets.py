# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""field_time - cost-coded, signed labour + plant field timesheets.

Adds the two tables of the field_time module:

    oe_field_time_timesheet - a foreman's end-of-day, signed field timesheet
                              for one project-day (draft -> submitted ->
                              approved, with a reversing timesheet as the only
                              correction to an approved one)
    oe_field_time_line      - one labour OR plant hours booking on a timesheet,
                              coded to a BOQ position

Each line is labour XOR plant: a CHECK constraint enforces that exactly one of
resource_id / equipment_id is set. project_id / resource_id / equipment_id /
variation_id are real foreign keys; reverses_id is a self-referential foreign
key (a reversal points at the timesheet it corrects).

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the tables / indexes. Every create_index call is guarded.

Revision ID: v3220_field_time_timesheets
Revises: v3219_carbon_whole_life
Create Date: 2026-07-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3220_field_time_timesheets"
down_revision: Union[str, Sequence[str], None] = "v3219_carbon_whole_life"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TIMESHEET = "oe_field_time_timesheet"
_LINE = "oe_field_time_line"

# Labour XOR plant - exactly one of resource_id / equipment_id must be set.
_LABOUR_XOR_PLANT = (
    "(resource_id IS NOT NULL AND equipment_id IS NULL) OR (resource_id IS NULL AND equipment_id IS NOT NULL)"
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
    unique: bool = False,
) -> None:
    if not _has_table(inspector, table):
        return
    if _has_index(inspector, table, name):
        return
    try:
        op.create_index(name, table, cols, unique=unique)
    except sa.exc.OperationalError:
        # Tolerate a race with another upgrade or a pre-existing index that did
        # not show up in the cached inspector data.
        pass


_TABLE_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    ("ix_oe_field_time_timesheet_project_id", _TIMESHEET, ("project_id",), False),
    ("ix_oe_field_time_timesheet_date", _TIMESHEET, ("date",), False),
    ("ix_oe_field_time_timesheet_status", _TIMESHEET, ("status",), False),
    ("ix_oe_field_time_timesheet_reverses_id", _TIMESHEET, ("reverses_id",), False),
    ("ix_oe_field_time_timesheet_project_date", _TIMESHEET, ("project_id", "date"), False),
    ("ix_oe_field_time_line_timesheet_id", _LINE, ("timesheet_id",), False),
    ("ix_oe_field_time_line_resource", _LINE, ("resource_id",), False),
    ("ix_oe_field_time_line_equipment", _LINE, ("equipment_id",), False),
)

# Drop children before parents on downgrade.
_NEW_TABLES: tuple[str, ...] = (_LINE, _TIMESHEET)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # ``String(36)`` on PostgreSQL too. ``GUID`` in ``app.database`` is a
    # ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
    # ``create_all`` builds every identity column as ``character varying(36)``
    # and a native uuid here cannot carry a foreign key to one: PostgreSQL
    # answers ``DatatypeMismatch`` as soon as the chain is walked, not stamped.
    guid_type = sa.String(36)

    def _common_cols() -> list[sa.Column]:
        return [
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
        ]

    # -- oe_field_time_timesheet -------------------------------------------
    if not _has_table(inspector, _TIMESHEET):
        op.create_table(
            _TIMESHEET,
            *_common_cols(),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("reference", sa.String(50), nullable=False, server_default=""),
            sa.Column("date", sa.Date(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("submitted_by", guid_type, nullable=True),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("approved_by", guid_type, nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "reverses_id",
                guid_type,
                sa.ForeignKey("oe_field_time_timesheet.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("project_id", "reference", name="uq_oe_field_time_timesheet_project_ref"),
        )

    # -- oe_field_time_line -------------------------------------------------
    if not _has_table(inspector, _LINE):
        op.create_table(
            _LINE,
            *_common_cols(),
            sa.Column(
                "timesheet_id",
                guid_type,
                sa.ForeignKey("oe_field_time_timesheet.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "equipment_id",
                guid_type,
                sa.ForeignKey("oe_equipment_equipment.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("hours", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("cost_code", sa.String(100), nullable=False, server_default=""),
            sa.Column("wbs", sa.String(100), nullable=True),
            sa.Column("is_daywork", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column(
                "variation_id",
                guid_type,
                sa.ForeignKey("oe_variations_order.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("daywork_sheet_id", guid_type, nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.CheckConstraint(_LABOUR_XOR_PLANT, name="ck_oe_field_time_line_labour_xor_plant"),
        )

    # Refresh the inspector - table creation above invalidates the cached
    # metadata - then create the supporting indexes.
    inspector = sa.inspect(bind)
    for name, table, cols, unique in _TABLE_INDEXES:
        _safe_create_index(inspector, name, table, list(cols), unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table, _cols, _unique in _TABLE_INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    for tbl in _NEW_TABLES:
        if _has_table(inspector, tbl):
            try:
                op.drop_table(tbl)
            except sa.exc.OperationalError:
                pass
