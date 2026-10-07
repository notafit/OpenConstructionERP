# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""contracts - the schema for monthly payment applications in depth.

One revision for all of the contracts DDL the billing-depth work needs, so the
four pieces of logic that follow it (period order, retention step-down, stored
materials, change orders per line) code against tables that already exist.

Columns added to existing tables
    ``oe_contracts_progress_claim``
        ``period_from``, ``period_to`` (indexed) and ``application_date`` as
        dates. The String columns ``period_start``, ``period_end`` and
        ``claim_date`` stay: they are the API contract, and a String column
        cannot be retyped on an install whose schema moves through the boot
        heal. ``completed_stored_to_date`` and ``retention_held_to_date`` are
        the certificate snapshot the next claim's "less previous certificates"
        is read from.
    ``oe_contracts_progress_claim_line``
        ``prior_completed_value`` (column D), ``materials_stored_value``
        (column F), and the per-line retention snapshot ``retention_to_date``,
        ``retention_stored_to_date`` and ``retention_rate``.
    ``oe_contracts_contract_line``
        ``origin``, ``source_key`` (indexed) and ``original_value``.

Tables created
    ``oe_contracts_sov_adjustment``, ``oe_contracts_retention_release``,
    ``oe_contracts_stored_material`` and ``oe_contracts_stored_material_movement``.

Nullability is a statement about the rows already there. A column whose zero
would be a false statement about a legacy row is nullable: a claim line written
before this revision has no stored prior value (the G703 builder derives it
from cumulative minus period, which is correct for those rows), no retention
snapshot (it was billed at the contract's flat rate) and no certificate
snapshot. A column whose zero is the truth for every legacy row, such as the
stored materials balance nothing could record before, is NOT NULL with a
scalar server default, which is the form the boot heal can carry.

DDL only, and every step asks the database first, so an install whose tables
``create_all`` already built reaches this revision and changes nothing. No row
is written here. The date columns are filled on the boot path by the repair
declared above ``upgrade()``, which parses the strings in Python so it reads a
stored period the same way the service does.

Constraint and index names are the ones ``create_all`` derives from the naming
convention in ``app.database``, read off the compiled models rather than
composed by hand: several foreign key names are longer than PostgreSQL's 63
character limit and SQLAlchemy shortens those with a hash suffix, which a hand
written name would not get. ``tests/unit/test_contracts_billing_migration_names.py``
compares the two.

Revision ID: v42_contracts_billing_depth
Revises: v41_funding_obligation_detail
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v42_contracts_billing_depth"
down_revision: Union[str, Sequence[str], None] = "v41_funding_obligation_detail"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONTRACT = "oe_contracts_contract"
_LINE = "oe_contracts_contract_line"
_CLAIM = "oe_contracts_progress_claim"
_CLAIM_LINE = "oe_contracts_progress_claim_line"
_ADJUSTMENT = "oe_contracts_sov_adjustment"
_RELEASE = "oe_contracts_retention_release"
_MATERIAL = "oe_contracts_stored_material"
_MOVEMENT = "oe_contracts_stored_material_movement"

_MONEY = sa.Numeric(18, 4)
_RATE = sa.Numeric(7, 4)

# Read off the compiled CREATE TABLE of the models, see the module docstring.
_FK_ADJUSTMENT_CONTRACT = "fk_oe_contracts_sov_adjustment_contract_id_oe_contracts_2dd4"
_FK_ADJUSTMENT_LINE = "fk_oe_contracts_sov_adjustment_contract_line_id_oe_cont_9c7c"
_UQ_ADJUSTMENT_LINE_SOURCE = "uq_oe_contracts_sov_adjustment_line_source"
_FK_RELEASE_CONTRACT = "fk_oe_contracts_retention_release_contract_id_oe_contra_9ba1"
_FK_MATERIAL_CONTRACT = "fk_oe_contracts_stored_material_contract_id_oe_contract_640c"
_FK_MATERIAL_LINE = "fk_oe_contracts_stored_material_contract_line_id_oe_con_18a4"
_FK_MOVEMENT_MATERIAL = "fk_oe_contracts_stored_material_movement_stored_materia_d3b7"


def _columns_added() -> dict[str, list[sa.Column]]:
    """The new columns on existing tables, keyed by table.

    Built by a function so each call hands ``add_column`` fresh Column objects;
    a Column can belong to one table only.
    """
    return {
        _CLAIM: [
            sa.Column("period_from", sa.Date(), nullable=True),
            sa.Column("period_to", sa.Date(), nullable=True),
            sa.Column("application_date", sa.Date(), nullable=True),
            sa.Column("completed_stored_to_date", _MONEY, nullable=True),
            sa.Column("retention_held_to_date", _MONEY, nullable=True),
        ],
        _CLAIM_LINE: [
            sa.Column("prior_completed_value", _MONEY, nullable=True),
            sa.Column("materials_stored_value", _MONEY, nullable=False, server_default="0"),
            sa.Column("retention_to_date", _MONEY, nullable=True),
            sa.Column("retention_stored_to_date", _MONEY, nullable=True),
            sa.Column("retention_rate", _RATE, nullable=True),
        ],
        _LINE: [
            sa.Column("origin", sa.String(length=20), nullable=False, server_default="original"),
            sa.Column("source_key", sa.String(length=120), nullable=True),
            sa.Column("original_value", _MONEY, nullable=True),
        ],
    }


#: (table, index name, columns). The names are the ``ix_<table>_<column>`` form
#: ``index=True`` produces, so a healed install and a migrated one hold one
#: index each rather than two over the same column.
_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    (_CLAIM, "ix_oe_contracts_progress_claim_period_to", ["period_to"]),
    (_LINE, "ix_oe_contracts_contract_line_source_key", ["source_key"]),
    (_ADJUSTMENT, "ix_oe_contracts_sov_adjustment_contract_id", ["contract_id"]),
    (_ADJUSTMENT, "ix_oe_contracts_sov_adjustment_contract_line_id", ["contract_line_id"]),
    (_RELEASE, "ix_oe_contracts_retention_release_contract_id", ["contract_id"]),
    (_RELEASE, "ix_oe_contracts_retention_release_progress_claim_id", ["progress_claim_id"]),
    (_RELEASE, "ix_oe_contracts_retention_release_status", ["status"]),
    (_MATERIAL, "ix_oe_contracts_stored_material_contract_id", ["contract_id"]),
    (_MATERIAL, "ix_oe_contracts_stored_material_contract_line_id", ["contract_line_id"]),
    (_MATERIAL, "ix_oe_contracts_stored_material_status", ["status"]),
    (_MOVEMENT, "ix_oe_contracts_stored_material_movement_progress_claim_id", ["progress_claim_id"]),
    (_MOVEMENT, "ix_oe_contracts_stored_material_movement_stored_material_id", ["stored_material_id"]),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _column_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _index_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def _base_columns() -> list[sa.Column]:
    """The three columns every model inherits from ``Base``."""
    return [
        sa.Column("id", GUID(), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def _create_adjustment() -> None:
    op.create_table(
        _ADJUSTMENT,
        *_base_columns(),
        sa.Column("contract_id", GUID(), nullable=False),
        sa.Column("contract_line_id", GUID(), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("source_kind", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("source_id", GUID(), nullable=True),
        sa.Column("source_code", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("delta_value", _MONEY, nullable=False, server_default="0"),
        sa.Column("delta_quantity", _MONEY, nullable=False, server_default="0"),
        sa.Column("created_line", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("approved_on", sa.Date(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["contract_id"], [f"{_CONTRACT}.id"], ondelete="CASCADE", name=_FK_ADJUSTMENT_CONTRACT),
        sa.ForeignKeyConstraint(["contract_line_id"], [f"{_LINE}.id"], ondelete="CASCADE", name=_FK_ADJUSTMENT_LINE),
        sa.UniqueConstraint("contract_line_id", "source_key", name=_UQ_ADJUSTMENT_LINE_SOURCE),
    )


def _create_release() -> None:
    op.create_table(
        _RELEASE,
        *_base_columns(),
        sa.Column("contract_id", GUID(), nullable=False),
        sa.Column("event", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="proposed"),
        sa.Column("amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("withheld_for_open_items", _MONEY, nullable=False, server_default="0"),
        sa.Column("released_on", sa.Date(), nullable=True),
        sa.Column("progress_claim_id", GUID(), nullable=True),
        sa.Column("document_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["contract_id"], [f"{_CONTRACT}.id"], ondelete="CASCADE", name=_FK_RELEASE_CONTRACT),
    )


def _create_material() -> None:
    op.create_table(
        _MATERIAL,
        *_base_columns(),
        sa.Column("contract_id", GUID(), nullable=False),
        sa.Column("contract_line_id", GUID(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("unit", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("quantity", _MONEY, nullable=False, server_default="0"),
        sa.Column("unit_cost", _MONEY, nullable=False, server_default="0"),
        sa.Column("value", _MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
        sa.Column("location_kind", sa.String(length=20), nullable=False, server_default="on_site"),
        sa.Column("location_text", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("vendor", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("delivery_ticket_document_id", GUID(), nullable=True),
        sa.Column("invoice_document_id", GUID(), nullable=True),
        sa.Column("bill_of_sale_document_id", GUID(), nullable=True),
        sa.Column("insurance_document_id", GUID(), nullable=True),
        sa.Column("photo_document_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("title_transferred", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("security_id", GUID(), nullable=True),
        sa.Column("owner_approved_offsite", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="recorded"),
        sa.Column("created_by", sa.String(length=36), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(["contract_id"], [f"{_CONTRACT}.id"], ondelete="CASCADE", name=_FK_MATERIAL_CONTRACT),
        sa.ForeignKeyConstraint(["contract_line_id"], [f"{_LINE}.id"], ondelete="CASCADE", name=_FK_MATERIAL_LINE),
    )


def _create_movement() -> None:
    op.create_table(
        _MOVEMENT,
        *_base_columns(),
        sa.Column("stored_material_id", GUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("quantity", _MONEY, nullable=False, server_default="0"),
        sa.Column("value", _MONEY, nullable=False, server_default="0"),
        sa.Column("moved_on", sa.Date(), nullable=False),
        sa.Column("progress_claim_id", GUID(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["stored_material_id"], [f"{_MATERIAL}.id"], ondelete="CASCADE", name=_FK_MOVEMENT_MATERIAL
        ),
    )


# This body writes no rows, so the gate does not require the line below. It is
# here so the revision and the repair that fills its date columns read as a pair.
# boot-repair: registry=contracts_claim_period_dates
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, columns in _columns_added().items():
        if not _has_table(inspector, table):
            # The contracts tables come from much earlier revisions, so a
            # missing one means the chain never got that far. Adding a column
            # to a table that is not there would stop the whole upgrade.
            continue
        existing = _column_names(inspector, table)
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)

    # Parents before children: the movement references the material.
    for table, create in (
        (_ADJUSTMENT, _create_adjustment),
        (_RELEASE, _create_release),
        (_MATERIAL, _create_material),
        (_MOVEMENT, _create_movement),
    ):
        inspector = sa.inspect(bind)
        if not _has_table(inspector, table):
            create()

    inspector = sa.inspect(bind)
    existing_indexes: dict[str, set[str]] = {}
    for table, name, columns in _INDEXES:
        if table not in existing_indexes:
            existing_indexes[table] = _index_names(inspector, table)
        if not _has_table(inspector, table) or name in existing_indexes[table]:
            continue
        op.create_index(name, table, columns)
        existing_indexes[table].add(name)


def downgrade() -> None:
    bind = op.get_bind()
    for table in (_MOVEMENT, _MATERIAL, _RELEASE, _ADJUSTMENT):
        inspector = sa.inspect(bind)
        if _has_table(inspector, table):
            op.drop_table(table)

    inspector = sa.inspect(bind)
    for table, name, _columns in _INDEXES:
        if table in (_CLAIM, _LINE) and name in _index_names(inspector, table):
            op.drop_index(name, table_name=table)
    for table, columns in _columns_added().items():
        if not _has_table(inspector, table):
            continue
        existing = _column_names(inspector, table)
        for column in columns:
            if column.name in existing:
                op.drop_column(table, column.name)
