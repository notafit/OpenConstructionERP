# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""funding - public funding applications and what an award obliges.

Six new tables, nothing existing touched. The shape is one programme offering
terms, one application per project asking for them, and four tables hanging
off the application for the things an award produces afterwards: the money
drawn, the account of where it went, the dated obligations, and the decision
about which of the project's costs the programme will count.

``oe_funding_programme`` is reference data and is the only table not scoped to
a project. It is unique on code and country rather than on code alone, because
the same programme code is reused by different authorities in different
countries and a catalogue keyed on the code would merge them.

``oe_funding_application`` carries the award on the application rather than in
a table of its own. An application has exactly one decision, and a separate
table would let a project hold an approved amount with no application behind
it. Its foreign key to the programme is RESTRICT, not CASCADE: deleting a
programme that projects have already applied to would destroy the record of
awards that were actually made, and refusing the delete is the right answer.

Dates are stored as ISO-8601 strings in VARCHAR(40) rather than as dates. A
funding deadline is a calendar day fixed by an authority in its own timezone,
not an instant, and a timestamp invites a conversion that moves a deadline
across midnight. Money is NUMERIC(18, 2), which is what MoneyType resolves to
on PostgreSQL; several of these columns are the difference between two others
and a float would be wrong in the last cent exactly where an auditor reads.

Every step is inspector-guarded and therefore idempotent, so a fresh install
whose tables ``env.py`` already built through ``Base.metadata.create_all``
reaches this revision and does nothing. An existing install, which is where
this file earns its keep, gets the six tables it has never had.

Revision ID: v41_funding_module
Revises: v41_boq_snapshot_summary_cols
Create Date: 2026-09-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v41_funding_module"
down_revision: Union[str, Sequence[str], None] = "v41_boq_snapshot_summary_cols"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PROGRAMME = "oe_funding_programme"
_APPLICATION = "oe_funding_application"
_DISBURSEMENT = "oe_funding_disbursement"
_PROOF = "oe_funding_proof_of_use"
_OBLIGATION = "oe_funding_obligation"
_ALLOCATION = "oe_funding_cost_allocation"
_PROJECT_TABLE = "oe_projects_project"

# MoneyType resolves to NUMERIC(18, 2) on PostgreSQL. Percentages are a
# different scale on purpose: a funding rate of 42.375 percent is a real thing
# a programme writes, and rounding it to two places changes the award.
_MONEY = sa.Numeric(18, 2)
_PERCENT = sa.Numeric(6, 3)

# Foreign key names, spelled out rather than composed.
#
# The naming convention in ``app.database`` builds these as
# ``fk_<table>_<column>_<referred table>``, and for four of the six that comes
# out longer than PostgreSQL's 63-character identifier limit. SQLAlchemy
# shortens a name it generated itself, by cutting it and appending four hex
# characters derived from the whole name, so ``create_all`` produces the odd
# looking values below and PostgreSQL accepts them. A name written out by hand
# gets no such treatment: it is passed through and the server rejects it, which
# is how the round-trip test found this file's first draft.
#
# So these are not guesses at the shortening. They were read off the compiled
# ``CREATE TABLE`` for the models, and
# ``tests/modules/funding/test_migration_names_match_the_models.py`` compares
# them against that same source, because an install built by ``create_all`` and
# one built by this file have to end up with the same constraint names or a
# later migration that drops one by name silently does nothing.
_FK_APPLICATION_PROJECT = "fk_oe_funding_application_project_id_oe_projects_project"
_FK_APPLICATION_PROGRAMME = "fk_oe_funding_application_programme_id_oe_funding_programme"
_FK_DISBURSEMENT_APPLICATION = "fk_oe_funding_disbursement_application_id_oe_funding_ap_9dcf"
_FK_PROOF_APPLICATION = "fk_oe_funding_proof_of_use_application_id_oe_funding_ap_852d"
_FK_OBLIGATION_APPLICATION = "fk_oe_funding_obligation_application_id_oe_funding_application"
_FK_ALLOCATION_APPLICATION = "fk_oe_funding_cost_allocation_application_id_oe_funding_3aef"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


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


def _create_programme(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _PROGRAMME):
        return
    op.create_table(
        _PROGRAMME,
        *_base_columns(),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("authority_name", sa.String(length=255), nullable=False, server_default=""),
        # supranational, national, regional or municipal. The level decides
        # whether two awards may be added together at all.
        sa.Column("authority_level", sa.String(length=40), nullable=False, server_default="national"),
        sa.Column("country", sa.String(length=2), nullable=False, server_default=""),
        sa.Column("region_code", sa.String(length=20), nullable=False, server_default=""),
        sa.Column("instrument", sa.String(length=40), nullable=False, server_default="grant"),
        sa.Column("funding_rate_percent", _PERCENT, nullable=False, server_default="0"),
        sa.Column("min_amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("max_amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("own_share_percent", _PERCENT, nullable=False, server_default="0"),
        sa.Column("aid_intensity_cap_percent", _PERCENT, nullable=False, server_default="0"),
        sa.Column("de_minimis", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("cumulative", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # Work begun before the application was filed is unfundable under most
        # programmes, and no later approval repairs it. The default is the
        # strict reading, so a programme typed in without this field examined
        # warns rather than stays silent.
        sa.Column(
            "requires_application_before_start",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("application_window_start", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("application_window_end", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("rolling", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("proof_of_use_due_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("disbursement_spend_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retention_years", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("eligible_applicant_types", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("eligible_cost_categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("excluded_cost_categories", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("source_url", sa.String(length=1000), nullable=False, server_default=""),
        # Funding terms change every budget year, and a catalogue with no date
        # on it reads as current forever.
        sa.Column("last_verified_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("pack_id", sa.String(length=80), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        # The same programme code is reused by different authorities in
        # different countries, so the country belongs in the key.
        sa.UniqueConstraint("code", "country", name="uq_oe_funding_programme_code_country"),
    )


def _create_application(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _APPLICATION):
        return
    op.create_table(
        _APPLICATION,
        *_base_columns(),
        sa.Column("project_id", GUID(), nullable=False),
        sa.Column("programme_id", GUID(), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("applicant_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("applicant_type", sa.String(length=60), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("eligible_cost_base", _MONEY, nullable=False, server_default="0"),
        sa.Column("requested_amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("own_share_amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
        sa.Column("submitted_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("decision_expected_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("decided_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("award_reference", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("approved_amount", _MONEY, nullable=False, server_default="0"),
        # Every date check the module makes about a cost is made against this
        # pair, so they are on the application and not derived from anything.
        sa.Column("award_period_start", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("award_period_end", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("conditions", sa.Text(), nullable=False, server_default=""),
        sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("measure_start_on", sa.String(length=40), nullable=False, server_default=""),
        # Set only where the authority granted permission to begin early, in
        # writing. It exists so the rule can be told the truth rather than be
        # switched off.
        sa.Column("early_start_approved", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("early_start_reference", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("responsible_user_id", sa.String(length=36), nullable=True),
        # Soft links, plain UUIDs with no database foreign key, so the module
        # stays installable without the modules it can point at.
        sa.Column("linked_estimate_id", GUID(), nullable=True),
        sa.Column("linked_schedule_id", GUID(), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            [f"{_PROJECT_TABLE}.id"],
            name=_FK_APPLICATION_PROJECT,
            ondelete="CASCADE",
        ),
        # RESTRICT rather than CASCADE: deleting a programme that projects
        # have applied to would destroy the record of awards actually made.
        sa.ForeignKeyConstraint(
            ["programme_id"],
            [f"{_PROGRAMME}.id"],
            name=_FK_APPLICATION_PROGRAMME,
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("project_id", "code", name="uq_oe_funding_application_project_code"),
    )


def _create_disbursement(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _DISBURSEMENT):
        return
    op.create_table(
        _DISBURSEMENT,
        *_base_columns(),
        sa.Column("application_id", GUID(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("code", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("period_from", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("period_to", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("requested_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("approved_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("received_on", sa.String(length=40), nullable=False, server_default=""),
        # Stamped from the programme's spend window when the money arrives and
        # then left alone, because the programme's terms can be edited later
        # and this particular deadline must not move when they are.
        sa.Column("spend_deadline_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("amount_requested", _MONEY, nullable=False, server_default="0"),
        sa.Column("amount_approved", _MONEY, nullable=False, server_default="0"),
        sa.Column("amount_received", _MONEY, nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="draft"),
        sa.Column("invoice_ids", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["application_id"],
            [f"{_APPLICATION}.id"],
            name=_FK_DISBURSEMENT_APPLICATION,
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("application_id", "sequence", name="uq_oe_funding_disbursement_app_sequence"),
    )


def _create_proof(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _PROOF):
        return
    op.create_table(
        _PROOF,
        *_base_columns(),
        sa.Column("application_id", GUID(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, server_default="final"),
        sa.Column("due_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("submitted_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("accepted_on", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        # Every jurisdiction asks for the same two halves under different
        # names, a narrative and a numeric statement, so they are two columns
        # and a Country Pack changes the form rather than the model.
        sa.Column("narrative_report", sa.Text(), nullable=False, server_default=""),
        sa.Column("total_eligible_spent", _MONEY, nullable=False, server_default="0"),
        sa.Column("total_funding_used", _MONEY, nullable=False, server_default="0"),
        sa.Column("total_own_share", _MONEY, nullable=False, server_default="0"),
        sa.Column("voucher_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("findings", sa.Text(), nullable=False, server_default=""),
        sa.Column("retention_until", sa.String(length=40), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["application_id"],
            [f"{_APPLICATION}.id"],
            name=_FK_PROOF_APPLICATION,
            ondelete="CASCADE",
        ),
    )


def _create_obligation(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _OBLIGATION):
        return
    op.create_table(
        _OBLIGATION,
        *_base_columns(),
        sa.Column("application_id", GUID(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False, server_default="condition"),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("detail", sa.Text(), nullable=False, server_default=""),
        sa.Column("due_on", sa.String(length=40), nullable=False, server_default=""),
        # A programme rule is the same for everyone, a condition in the notice
        # was written for this applicant, a manual entry is someone's own
        # note. A reader has to be able to tell them apart, because they can
        # be argued with to different degrees.
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("source_reference", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("responsible_user_id", sa.String(length=36), nullable=True),
        # Overdue is not a column: it is open with the due date passed, and
        # storing it would need a job to keep it true.
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("completed_on", sa.String(length=40), nullable=False, server_default=""),
        sa.ForeignKeyConstraint(
            ["application_id"],
            [f"{_APPLICATION}.id"],
            name=_FK_OBLIGATION_APPLICATION,
            ondelete="CASCADE",
        ),
    )


def _create_allocation(inspector: sa.engine.reflection.Inspector) -> None:
    if _has_table(inspector, _ALLOCATION):
        return
    op.create_table(
        _ALLOCATION,
        *_base_columns(),
        sa.Column("application_id", GUID(), nullable=False),
        # The cost code in whatever classification the project uses, stored as
        # written rather than mapped, because a funding body reads the
        # applicant's own classification back to them.
        sa.Column("cost_group", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("amount", _MONEY, nullable=False, server_default="0"),
        # Not derived from a percentage: partial eligibility is usually a
        # named carve-out rather than a ratio.
        sa.Column("eligible_amount", _MONEY, nullable=False, server_default="0"),
        sa.Column("eligibility", sa.String(length=30), nullable=False, server_default="undecided"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("source_ref_id", GUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["application_id"],
            [f"{_APPLICATION}.id"],
            name=_FK_ALLOCATION_APPLICATION,
            ondelete="CASCADE",
        ),
    )


# Index names follow the metadata naming convention in ``app.database``, which
# is ``ix_%(column_0_label)s`` for a single column. A composite index is named
# in the model itself, and the name is repeated here verbatim: a fresh install
# builds these through ``create_all`` and an upgraded one through this file,
# and the two must agree or a later migration that drops one by name misses.
_INDEXES: tuple[tuple[str, str, list[str]], ...] = (
    (_PROGRAMME, "ix_oe_funding_programme_country", ["country"]),
    (_PROGRAMME, "ix_oe_funding_programme_status", ["status"]),
    (_PROGRAMME, "ix_oe_funding_programme_country_status", ["country", "status"]),
    (_APPLICATION, "ix_oe_funding_application_project_id", ["project_id"]),
    (_APPLICATION, "ix_oe_funding_application_programme_id", ["programme_id"]),
    (_APPLICATION, "ix_oe_funding_application_status", ["status"]),
    (_APPLICATION, "ix_oe_funding_application_project_id_status", ["project_id", "status"]),
    (_DISBURSEMENT, "ix_oe_funding_disbursement_application_id", ["application_id"]),
    (_DISBURSEMENT, "ix_oe_funding_disbursement_status", ["status"]),
    (_DISBURSEMENT, "ix_oe_funding_disbursement_app_status", ["application_id", "status"]),
    (_PROOF, "ix_oe_funding_proof_of_use_application_id", ["application_id"]),
    (_PROOF, "ix_oe_funding_proof_of_use_status", ["status"]),
    (_PROOF, "ix_oe_funding_proof_app_status", ["application_id", "status"]),
    (_OBLIGATION, "ix_oe_funding_obligation_application_id", ["application_id"]),
    (_OBLIGATION, "ix_oe_funding_obligation_status", ["status"]),
    # The deadline list is read across every application at once, so the due
    # date leads this one rather than the application.
    (_OBLIGATION, "ix_oe_funding_obligation_due", ["due_on", "status"]),
    (_OBLIGATION, "ix_oe_funding_obligation_app_kind", ["application_id", "kind"]),
    (_ALLOCATION, "ix_oe_funding_cost_allocation_application_id", ["application_id"]),
    (_ALLOCATION, "ix_oe_funding_alloc_app_eligibility", ["application_id", "eligibility"]),
)


def upgrade() -> None:
    """Create the six funding tables and their indexes (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Order matters: the application references the programme, and everything
    # else references the application.
    _create_programme(inspector)
    inspector = sa.inspect(bind)
    _create_application(inspector)
    inspector = sa.inspect(bind)
    _create_disbursement(inspector)
    _create_proof(inspector)
    _create_obligation(inspector)
    _create_allocation(inspector)

    inspector = sa.inspect(bind)
    existing: dict[str, set[str]] = {}
    for table, name, columns in _INDEXES:
        if table not in existing:
            existing[table] = _index_names(inspector, table)
        if name not in existing[table]:
            op.create_index(name, table, columns)
            existing[table].add(name)


def downgrade() -> None:
    """Drop the six tables, children before the parents they reference."""
    bind = op.get_bind()
    for table in (_ALLOCATION, _OBLIGATION, _PROOF, _DISBURSEMENT, _APPLICATION, _PROGRAMME):
        inspector = sa.inspect(bind)
        if _has_table(inspector, table):
            op.drop_table(table)
