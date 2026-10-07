# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""contracts - deepen the data model (parties / security / EOT / docs / milestones).

Adds five tables and one column to the contracts module:

    oe_contracts_party        - structured parties / roles (employer, contractor,
                                consultant, guarantor, ...) with a plain-UUID link
                                to a contact / subcontractor / user
    oe_contracts_security     - bonds / guarantees / insurance held on a contract
    oe_contracts_eot_claim    - extension-of-time claims with a decision FSM
    oe_contracts_document     - contract documents register
    oe_contracts_milestone    - milestones / payment schedule

    oe_contracts_progress_claim.milestone_id  - optional link to a milestone

party_id, document_id, linked_delay_event_id and milestone_id are deliberately
plain GUID columns (no SQLAlchemy ForeignKey), since they may reference rows
owned by other modules (contacts, subcontractors, users, documents, planning /
schedule) and are resolved at the service layer. contract_id columns are real
foreign keys into oe_contracts_contract with ON DELETE CASCADE.

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the tables / column. Every create_index call is guarded.

Revision ID: v3217_contracts_depth
Revises: v3216_project_status_drop_waiting
Create Date: 2026-06-30
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3217_contracts_depth"
down_revision: Union[str, Sequence[str], None] = "v3216_project_status_drop_waiting"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
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
        # Tolerate a race with another upgrade or a pre-existing index that
        # did not show up in the cached inspector data.
        pass


_TABLE_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    # (index_name, table, cols, unique)
    ("ix_oe_contracts_party_contract_id", "oe_contracts_party", ("contract_id",), False),
    ("ix_oe_contracts_party_party_role", "oe_contracts_party", ("party_role",), False),
    ("ix_oe_contracts_party_party_id", "oe_contracts_party", ("party_id",), False),
    ("ix_oe_contracts_security_contract_id", "oe_contracts_security", ("contract_id",), False),
    ("ix_oe_contracts_security_security_type", "oe_contracts_security", ("security_type",), False),
    ("ix_oe_contracts_security_status", "oe_contracts_security", ("status",), False),
    ("ix_oe_contracts_eot_claim_contract_id", "oe_contracts_eot_claim", ("contract_id",), False),
    ("ix_oe_contracts_eot_claim_status", "oe_contracts_eot_claim", ("status",), False),
    ("ix_oe_contracts_document_contract_id", "oe_contracts_document", ("contract_id",), False),
    ("ix_oe_contracts_document_document_id", "oe_contracts_document", ("document_id",), False),
    ("ix_oe_contracts_document_doc_role", "oe_contracts_document", ("doc_role",), False),
    ("ix_oe_contracts_milestone_contract_id", "oe_contracts_milestone", ("contract_id",), False),
    ("ix_oe_contracts_milestone_status", "oe_contracts_milestone", ("status",), False),
)

_NEW_TABLES: tuple[str, ...] = (
    "oe_contracts_milestone",
    "oe_contracts_document",
    "oe_contracts_eot_claim",
    "oe_contracts_security",
    "oe_contracts_party",
)


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

    # -- oe_contracts_party --------------------------------------------------
    if not _has_table(inspector, "oe_contracts_party"):
        op.create_table(
            "oe_contracts_party",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("party_role", sa.String(40), nullable=False, server_default="other"),
            sa.Column("party_type", sa.String(40), nullable=False, server_default="external"),
            sa.Column("party_id", guid_type, nullable=True),
            sa.Column("display_name", sa.String(500), nullable=False, server_default=""),
            sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("contact_details", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_contracts_security -----------------------------------------------
    if not _has_table(inspector, "oe_contracts_security"):
        op.create_table(
            "oe_contracts_security",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("security_type", sa.String(40), nullable=False, server_default="other"),
            sa.Column("reference", sa.String(120), nullable=True),
            sa.Column("provider_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("percent_of_contract", sa.Numeric(7, 4), nullable=True),
            sa.Column("valid_from", sa.String(40), nullable=True),
            sa.Column("valid_to", sa.String(40), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="required"),
            sa.Column("document_id", guid_type, nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_contracts_eot_claim ----------------------------------------------
    if not _has_table(inspector, "oe_contracts_eot_claim"):
        op.create_table(
            "oe_contracts_eot_claim",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("eot_number", sa.String(40), nullable=False, server_default=""),
            sa.Column("cause_category", sa.String(80), nullable=False, server_default="other"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("days_claimed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("days_granted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("claim_date", sa.String(40), nullable=True),
            sa.Column("decision_date", sa.String(40), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("revised_completion_date", sa.String(40), nullable=True),
            sa.Column("linked_delay_event_id", guid_type, nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_contracts_document -----------------------------------------------
    if not _has_table(inspector, "oe_contracts_document"):
        op.create_table(
            "oe_contracts_document",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("document_id", guid_type, nullable=True),
            sa.Column("doc_role", sa.String(40), nullable=False, server_default="other"),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("version", sa.String(40), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_contracts_milestone ----------------------------------------------
    if not _has_table(inspector, "oe_contracts_milestone"):
        op.create_table(
            "oe_contracts_milestone",
            *_common_cols(),
            sa.Column(
                "contract_id",
                guid_type,
                sa.ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(80), nullable=False, server_default=""),
            sa.Column("name", sa.String(500), nullable=False, server_default=""),
            sa.Column("planned_date", sa.String(40), nullable=True),
            sa.Column("value", sa.Numeric(18, 4), nullable=True),
            sa.Column("percent_of_contract", sa.Numeric(7, 4), nullable=True),
            sa.Column("trigger", sa.String(40), nullable=False, server_default="date"),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # -- oe_contracts_progress_claim.milestone_id (additive nullable column) --
    if _has_table(inspector, "oe_contracts_progress_claim") and not _has_column(
        inspector,
        "oe_contracts_progress_claim",
        "milestone_id",
    ):
        op.add_column(
            "oe_contracts_progress_claim",
            sa.Column("milestone_id", guid_type, nullable=True),
        )

    # Refresh the inspector - table / column creation above invalidates the
    # cached metadata - then create the supporting indexes.
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

    # Drop the additive progress-claim column first (best-effort; dropping a
    # column on SQLite needs batch mode, so tolerate failure on that backend).
    if _has_column(inspector, "oe_contracts_progress_claim", "milestone_id"):
        try:
            op.drop_column("oe_contracts_progress_claim", "milestone_id")
        except (sa.exc.OperationalError, NotImplementedError):
            pass

    # Drop the new tables (children first; all reference oe_contracts_contract).
    for tbl in _NEW_TABLES:
        if _has_table(inspector, tbl):
            try:
                op.drop_table(tbl)
            except sa.exc.OperationalError:
                pass
