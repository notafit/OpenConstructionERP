# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Coordination Hub — per-project alert thresholds.

Adds one strictly-additive table:

* ``oe_coordination_threshold`` — one row per (project, metric) pair
  carrying ``warn_value`` / ``error_value`` / ``enabled``. Default
  rows are seeded lazily by the service the first time a project's
  thresholds endpoint is read, so this migration creates the SCHEMA
  only.

Idempotent — inspector-guarded so re-runs on a partially-migrated DB
skip the create. SQLite-safe.

Revision ID: v41_coordination_thresholds
Revises: v41_smart_views_share
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import exc as sa_exc

# revision identifiers, used by Alembic.
revision: str = "v41_coordination_thresholds"
# Chain off the current tip ``v41_smart_views_share`` so the migration
# graph stays linear (``v41_smart_views_share`` itself branched off
# ``v41_clash_ai_triage`` for the share-by-link column). This new table
# is strictly additive and has no dependency on the smart-views table —
# we just append to whichever head exists.
down_revision: Union[str, Sequence[str], None] = "v41_smart_views_share"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_coordination_threshold"

# The identity type the models use. ``GUID`` in ``app.database`` is a
# ``TypeDecorator`` whose ``impl`` is ``String(36)`` and which defines no
# ``load_dialect_impl``, so it renders as ``VARCHAR(36)`` on every dialect —
# including PostgreSQL. Declaring native ``UUID`` here instead made
# ``project_id`` a ``uuid`` pointing at ``oe_projects_project.id``, which
# ``create_all`` builds as ``character varying``, and PostgreSQL refused
# ``fk_oe_coordination_threshold_project_id_oe_projects_project`` with
# ``DatatypeMismatch``.
_GUID = sa.String(36)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    """Return the names of the indexes on ``table``.

    Args:
        inspector: Reflection handle bound to the migration's connection.
        table: Table to inspect; an absent table yields an empty set.

    Returns:
        Every index name reflected for ``table``. ``ReflectedIndex.name`` is
        ``Optional[str]`` because a dialect may report an index it cannot
        name; those are dropped rather than carried through as ``None``,
        since every caller uses this set for a membership test against a
        name it is about to create or drop, and an unnamed index can never
        match one.
    """
    if not _has_table(inspector, table):
        return set()
    return {name for ix in inspector.get_indexes(table) if (name := ix["name"]) is not None}


def upgrade() -> None:
    """Create ``oe_coordination_threshold`` (idempotent)."""
    bind = op.get_bind()
    # Still needed below: SQLite has no boolean literal, PostgreSQL does.
    is_sqlite = bind.dialect.name == "sqlite"
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        return

    op.create_table(
        _TABLE,
        sa.Column("id", _GUID, primary_key=True),
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
        sa.Column(
            "project_id",
            _GUID,
            sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column(
            "warn_value",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "error_value",
            sa.Numeric(18, 4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1") if is_sqlite else sa.text("true"),
        ),
        sa.UniqueConstraint(
            "project_id",
            "metric",
            name="uq_coordination_threshold_project_metric",
        ),
    )

    existing_ix = _existing_index_names(inspector, _TABLE)
    if "ix_coordination_threshold_project" not in existing_ix:
        try:
            op.create_index(
                "ix_coordination_threshold_project",
                _TABLE,
                ["project_id"],
            )
        except sa_exc.OperationalError:
            pass


def downgrade() -> None:
    """Drop ``oe_coordination_threshold`` and its indexes."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _has_table(inspector, _TABLE):
        return
    existing_ix = _existing_index_names(inspector, _TABLE)
    if "ix_coordination_threshold_project" in existing_ix:
        try:
            op.drop_index(
                "ix_coordination_threshold_project",
                table_name=_TABLE,
            )
        except sa_exc.OperationalError:
            pass
    op.drop_table(_TABLE)
