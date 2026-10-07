# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects: timestamped project-status history.

Additive only. Creates ``oe_project_status_history`` - one row per change to a
project's ``status`` (e.g. active -> on_hold, active -> archived, archived ->
active). ``from_status`` is null for the initial status recorded at creation;
``changed_by`` references the acting user with ``ON DELETE SET NULL`` so removing
a user never erases the history. The table lets the UI show who changed status
from X to Y and when. Money-free.

Every operation is guarded so the migration is a safe no-op on a fresh install
that already built the table via ``Base.metadata.create_all``. The downgrade
drops the table.

Revision ID: v3214_project_status_history
Revises: v3213_value_time_factor
Create Date: 2026-06-28
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3214_project_status_history"
down_revision: Union[str, Sequence[str], None] = "v3213_value_time_factor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "oe_project_status_history"
_IX_PROJECT = "ix_project_status_history_project"
_IX_PROJECT_CREATED = "ix_project_status_history_project_created"

_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (_IX_PROJECT, ("project_id",)),
    (_IX_PROJECT_CREATED, ("project_id", "created_at")),
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

    if not _table_exists(bind, _TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("from_status", sa.String(50), nullable=True),
            sa.Column("to_status", sa.String(50), nullable=False),
            sa.Column(
                "changed_by",
                guid_type,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("note", sa.String(500), nullable=True),
        )

    # Inspector cache is stale after CREATE TABLE - re-probe per index.
    for name, cols in _INDEXES:
        if _table_exists(bind, _TABLE) and not _index_exists(bind, _TABLE, name):
            op.create_index(name, _TABLE, list(cols))

    logger.info("v3214 project status history: schema ensured")


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, _TABLE):
        return
    for name, _cols in _INDEXES:
        if _index_exists(bind, _TABLE, name):
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
    logger.info("v3214 project status history: reverted")
