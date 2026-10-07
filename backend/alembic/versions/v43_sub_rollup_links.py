# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors - link subcontractor pay applications to the GC's progress claim.

A general contractor's monthly bill to the owner is, line by line, largely the
sum of what its subcontractors billed it that month. Until now nothing recorded
that relationship: a work package pointed at nothing on the GC's schedule of
values, a pay application could not say which GC claim it went into, and a lien
waiver carried only the day it was signed, not the day of work it releases.

It also records what finance approved to pay. Approval now confirms an amount
per line, and a line can be approved below its claim, so the claimed header of
a pay application is no longer what gets paid.

Eight nullable columns, all additive:

``oe_subcontractors_work_package.contract_line_id``
    The GC schedule-of-values line this scope bills under by default.
``oe_subcontractors_payment_application_line.contract_line_id``
    A per-line override of that default.
``oe_subcontractors_payment_application.progress_claim_id``
    The GC progress claim a person included this pay application in.
``oe_subcontractors_lien_waiver.through_date``
    The last day of work the waiver releases.
``oe_subcontractors_agreement.prime_contract_id``
    The GC prime contract this subcontract sits under.
``oe_subcontractors_payment_application.approved_gross_amount``,
``approved_retention_amount`` and ``approved_net_amount``
    The payable side, set at finance approval: the claimed gross less what
    was not approved on the lines, retention on that, and the net paid.

The three link columns that the rollup filters on get the index their model
declares with ``index=True``, created here under exactly the auto-generated
name so a database that ``create_all`` already built does not get a second one.

The link columns are plain ``VARCHAR(36)`` with no foreign key, matching
``GUID`` and the cross-module convention: the contracts tables are owned by
another module. The amounts are ``NUMERIC(18, 2)`` like the header they sit
beside.

DDL only, nothing is backfilled: every existing row is correctly "not linked",
and a pay application approved before this revision has no approved figures,
which readers take as "paid as claimed", the only approval there was then.
Inspector-guarded, so an install whose schema came from ``create_all`` plus the
boot heal reaches this revision and adds nothing.

Revision ID: v43_sub_rollup_links
Revises: v42_contracts_billing_depth
Create Date: 2026-09-22
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v43_sub_rollup_links"
down_revision: Union[str, Sequence[str], None] = "v42_contracts_billing_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, column type, index name or None). The index names are the
# ones ``index=True`` produces on the models, read off ``__table__.indexes``.
_COLUMNS: tuple[tuple[str, str, sa.types.TypeEngine, str | None], ...] = (
    (
        "oe_subcontractors_work_package",
        "contract_line_id",
        sa.String(length=36),
        "ix_oe_subcontractors_work_package_contract_line_id",
    ),
    (
        "oe_subcontractors_payment_application_line",
        "contract_line_id",
        sa.String(length=36),
        "ix_oe_subcontractors_payment_application_line_contract_line_id",
    ),
    (
        "oe_subcontractors_payment_application",
        "progress_claim_id",
        sa.String(length=36),
        "ix_oe_subcontractors_payment_application_progress_claim_id",
    ),
    ("oe_subcontractors_lien_waiver", "through_date", sa.Date(), None),
    ("oe_subcontractors_agreement", "prime_contract_id", sa.String(length=36), None),
    ("oe_subcontractors_payment_application", "approved_gross_amount", sa.Numeric(18, 2), None),
    ("oe_subcontractors_payment_application", "approved_retention_amount", sa.Numeric(18, 2), None),
    ("oe_subcontractors_payment_application", "approved_net_amount", sa.Numeric(18, 2), None),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, column_type, index_name in _COLUMNS:
        if table not in tables:
            # The revision that creates the table has not run on this
            # database, so there is nothing to extend; adding to an absent
            # table would stop the upgrade for a module it does not use.
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing_columns:
            op.add_column(table, sa.Column(column, column_type, nullable=True))
        if index_name is None:
            continue
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table, [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, _column_type, index_name in reversed(_COLUMNS):
        if table not in tables:
            continue
        if index_name is not None and index_name in {ix["name"] for ix in inspector.get_indexes(table)}:
            op.drop_index(index_name, table_name=table)
        if column in {c["name"] for c in inspector.get_columns(table)}:
            op.drop_column(table, column)
