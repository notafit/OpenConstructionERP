# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""design_options: alternative design options paired with priced BOQs.

Additive only. Creates the two tables behind the Design Options module:

    oe_design_options_set    - a set of alternative options compared for a
                               project. ``project_id`` is a real foreign key to
                               ``oe_projects_project`` (ON DELETE CASCADE);
                               ``baseline_option_id`` is a plain GUID soft
                               pointer to the chosen option (no constraint, to
                               avoid a circular set<->option foreign key).
    oe_design_options_option - one option inside a set, paired with its own
                               priced bill of quantities. ``set_id`` is a real
                               foreign key to the set (ON DELETE CASCADE);
                               ``project_id`` is a denormalised plain-GUID copy
                               for IDOR-safe option scoping; ``bim_model_id`` /
                               ``boq_id`` / ``source_document_id`` /
                               ``match_session_id`` are plain-GUID cross-module
                               references with no foreign key. Money, quantity
                               and ratio columns are strings (the platform
                               Decimal-as-string convention).

Every operation is inspector-guarded and dialect-aware, so the migration is a
safe no-op on a fresh install that already built the tables via
``Base.metadata.create_all`` and is safe to re-run. The downgrade drops the
indexes then the tables. Index names match the metadata naming convention so a
create_all database and an alembic-upgraded database converge on one schema.

Revision ID: v3235_design_options
Revises: v3234_cost_search_trgm
Create Date: 2026-07-10
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3235_design_options"
down_revision: Union[str, Sequence[str], None] = "v3234_cost_search_trgm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_SET_TABLE = "oe_design_options_set"
_OPT_TABLE = "oe_design_options_option"

# Index names follow the metadata naming convention ("ix_%(column_0_label)s"),
# i.e. ix_<table>_<column>, so they match what create_all builds and the guard
# below correctly skips a database that already has them.
_SET_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (("ix_oe_design_options_set_project_id", ("project_id",)),)
_OPT_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ix_oe_design_options_option_set_id", ("set_id",)),
    ("ix_oe_design_options_option_project_id", ("project_id",)),
    ("ix_oe_design_options_option_bim_model_id", ("bim_model_id",)),
    ("ix_oe_design_options_option_boq_id", ("boq_id",)),
)


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def _index_exists(bind: sa.engine.Connection, table: str, index: str) -> bool:
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index for ix in insp.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    # ``String(36)`` on PostgreSQL too. ``GUID`` in ``app.database`` is a
    # ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
    # ``create_all`` builds every identity column as ``character varying(36)``
    # and a native uuid here cannot carry a foreign key to one: PostgreSQL
    # answers ``DatatypeMismatch`` as soon as the chain is walked, not stamped.
    guid_type = sa.String(36)

    if not _table_exists(bind, _SET_TABLE):
        op.create_table(
            _SET_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("baseline_option_id", guid_type, nullable=True),
            sa.Column("comparison_currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("decision_criteria", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", guid_type, nullable=True),
        )

    if not _table_exists(bind, _OPT_TABLE):
        op.create_table(
            _OPT_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "set_id",
                guid_type,
                sa.ForeignKey(f"{_SET_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("source_document_id", guid_type, nullable=True),
            sa.Column("bim_model_id", guid_type, nullable=True),
            sa.Column("boq_id", guid_type, nullable=True),
            sa.Column("match_session_id", guid_type, nullable=True),
            sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
            sa.Column("error", sa.String(500), nullable=False, server_default=""),
            sa.Column("direct_cost", sa.String(50), nullable=False, server_default="0"),
            sa.Column("markups_total", sa.String(50), nullable=False, server_default="0"),
            sa.Column("grand_total", sa.String(50), nullable=False, server_default="0"),
            sa.Column("cost_per_m2", sa.String(50), nullable=False, server_default="0"),
            sa.Column("gfa", sa.String(50), nullable=False, server_default="0"),
            sa.Column("gfa_unit", sa.String(20), nullable=False, server_default="m2"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("element_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("position_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("breakdown", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("validation_status", sa.String(50), nullable=False, server_default="pending"),
            sa.Column("validation_score", sa.String(10), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # Inspector cache is stale after CREATE TABLE - re-probe per index.
    for table, indexes in ((_SET_TABLE, _SET_INDEXES), (_OPT_TABLE, _OPT_INDEXES)):
        for name, cols in indexes:
            if _table_exists(bind, table) and not _index_exists(bind, table, name):
                op.create_index(name, table, list(cols))

    logger.info("v3235 design options: schema ensured")


def downgrade() -> None:
    bind = op.get_bind()

    # Drop child (option) first so the set can be removed, then the set.
    for table, indexes in ((_OPT_TABLE, _OPT_INDEXES), (_SET_TABLE, _SET_INDEXES)):
        if not _table_exists(bind, table):
            continue
        for name, _cols in indexes:
            if _index_exists(bind, table, name):
                op.drop_index(name, table_name=table)
        op.drop_table(table)

    logger.info("v3235 design options: reverted")
