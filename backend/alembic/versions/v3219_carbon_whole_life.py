# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""carbon 6D Phase 2 - operational carbon (B6) + whole-life cost (ISO 15686-5).

Adds two tables to the carbon module:

    oe_carbon_operational_entry - B6 use-phase operational-carbon lines
                                  (energy demand x grid factor, over a study
                                  period), one per energy-consuming BIM asset or
                                  a single modelled whole-building line
    oe_carbon_lcc_entry         - ISO 15686-5 whole-life cost lines (capex +
                                  present-value opex + present-value B4/B5
                                  replacement cycle + present-value end-of-life)

element_id is a plain GUID cross-module ref to oe_bim_element.id (no
ForeignKey), matching EmbodiedCarbonEntry.element_id. inventory_id is a real
foreign key into oe_carbon_inventory with ON DELETE CASCADE.

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the tables / indexes. Every create_index call is guarded.

Revision ID: v3219_carbon_whole_life
Revises: v3218_carbon_element_link
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3219_carbon_whole_life"
down_revision: Union[str, Sequence[str], None] = "v3218_carbon_element_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OPERATIONAL = "oe_carbon_operational_entry"
_LCC = "oe_carbon_lcc_entry"


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
    ("ix_oe_carbon_operational_entry_inventory_id", _OPERATIONAL, ("inventory_id",), False),
    ("ix_oe_carbon_operational_entry_element_id", _OPERATIONAL, ("element_id",), False),
    ("ix_oe_carbon_operational_entry_element_ref", _OPERATIONAL, ("element_ref",), False),
    ("ix_oe_carbon_operational_entry_system", _OPERATIONAL, ("system",), False),
    ("ix_oe_carbon_operational_entry_status", _OPERATIONAL, ("status",), False),
    ("ix_oe_carbon_lcc_entry_inventory_id", _LCC, ("inventory_id",), False),
    ("ix_oe_carbon_lcc_entry_element_id", _LCC, ("element_id",), False),
    ("ix_oe_carbon_lcc_entry_element_ref", _LCC, ("element_ref",), False),
    ("ix_oe_carbon_lcc_entry_status", _LCC, ("status",), False),
)

_NEW_TABLES: tuple[str, ...] = (_LCC, _OPERATIONAL)


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

    # -- oe_carbon_operational_entry ----------------------------------------
    if not _has_table(inspector, _OPERATIONAL):
        op.create_table(
            _OPERATIONAL,
            *_common_cols(),
            sa.Column(
                "inventory_id",
                guid_type,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("element_id", guid_type, nullable=True),
            sa.Column("element_ref", sa.String(255), nullable=True),
            sa.Column("system", sa.String(80), nullable=False, server_default="whole_building"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("end_use", sa.String(20), nullable=False, server_default="regulated"),
            sa.Column("energy_source", sa.String(24), nullable=False, server_default="modelled_intensity"),
            sa.Column("annual_energy_kwh", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("grid_country", sa.String(8), nullable=False, server_default=""),
            sa.Column("grid_year", sa.Integer(), nullable=True),
            sa.Column("grid_factor_kg_co2e_per_kwh", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("study_period_years", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("annual_carbon_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("carbon_kg", sa.Numeric(18, 6), nullable=False, server_default="0"),
            sa.Column("stage", sa.String(8), nullable=False, server_default="b6"),
            sa.Column("source", sa.String(20), nullable=False, server_default="modelled"),
            sa.Column("match_confidence", sa.String(16), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("assumptions", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_carbon_lcc_entry ------------------------------------------------
    if not _has_table(inspector, _LCC):
        op.create_table(
            _LCC,
            *_common_cols(),
            sa.Column(
                "inventory_id",
                guid_type,
                sa.ForeignKey("oe_carbon_inventory.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("element_id", guid_type, nullable=True),
            sa.Column("element_ref", sa.String(255), nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("category", sa.String(80), nullable=False, server_default=""),
            sa.Column("currency", sa.String(8), nullable=False, server_default="EUR"),
            sa.Column("capex", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("annual_opex", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("replacement_cost", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("service_life_years", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("eol_cost", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("discount_rate", sa.Numeric(9, 6), nullable=False, server_default="0"),
            sa.Column("study_period_years", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("capex_pv", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("opex_pv", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("replacement_pv", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("replacement_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("eol_pv", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("whole_life_cost", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("source", sa.String(20), nullable=False, server_default="modelled"),
            sa.Column("confidence", sa.String(16), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("assumptions", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
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
