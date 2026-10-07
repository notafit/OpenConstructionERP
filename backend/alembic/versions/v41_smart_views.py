# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Smart Views — rule-based, re-evaluating BIM viewer presets.

Adds a single strictly-additive table ``oe_smart_view`` carrying the
rule list (JSON), default action, scope, and authoring user. There is
no FK on ``scope_id`` because the target table varies with
``scope_type`` (user / project / federation); the service layer
enforces referential integrity instead.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables/indexes.

Identity columns are ``VARCHAR(36)`` on every dialect, which is what
``Base.metadata.create_all`` builds and therefore the only shape this
table ever has in a live install. This file used to declare them as
native PostgreSQL ``UUID``, which made ``created_by`` a ``uuid``
referencing ``oe_users_user.id`` — a ``character varying`` — and
PostgreSQL refused the foreign key outright::

    fk_oe_smart_view_created_by_oe_users_user cannot be implemented
    DETAIL: Key columns "created_by" and "id" are of incompatible types:
            uuid and character varying.

So a self-hoster who downgraded and re-upgraded this revision got a hard
stop, not a rebuilt table.

Revision ID: v41_smart_views
Revises: v41_clash_signature_smart_issues
Create Date: 2026-05-21
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import exc as sa_exc

# revision identifiers, used by Alembic.
revision: str = "v41_smart_views"
# Chained after the sibling v41 clash-signature head so the alembic
# graph keeps a single linear tip. Neither migration touches the
# other's tables — the only reason for the explicit ordering is to
# keep ``alembic upgrade head`` resolvable without a merge revision.
down_revision: Union[str, Sequence[str], None] = "v41_clash_signature_smart_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SMART_VIEW_TABLE = "oe_smart_view"

# The identity type the models use. ``GUID`` in ``app.database`` is a
# ``TypeDecorator`` whose ``impl`` is ``String(36)`` and which defines no
# ``load_dialect_impl``, so it renders as ``VARCHAR(36)`` on every dialect —
# including PostgreSQL. Spelling the width out rather than importing ``GUID``
# keeps this revision importable without the app settings and pins it to the
# shape the schema actually had when it shipped.
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
    """Create the ``oe_smart_view`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _SMART_VIEW_TABLE):
        op.create_table(
            _SMART_VIEW_TABLE,
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
                "scope_type",
                sa.String(16),
                nullable=False,
                server_default="user",
            ),
            sa.Column("scope_id", _GUID, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "rules",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "default_action",
                sa.String(16),
                nullable=False,
                server_default="show_all",
            ),
            sa.Column("color_legend", sa.JSON(), nullable=True),
            sa.Column(
                "created_by",
                _GUID,
                sa.ForeignKey(
                    "oe_users_user.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
        )
        existing_ix = _existing_index_names(inspector, _SMART_VIEW_TABLE)
        for ix_name, cols in (
            ("ix_smart_view_scope", ["scope_type", "scope_id"]),
            ("ix_smart_view_created_by", ["created_by"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _SMART_VIEW_TABLE, cols)
                except sa_exc.OperationalError:
                    # Already created in a partial re-run.
                    pass


def downgrade() -> None:
    """Drop the ``oe_smart_view`` table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _SMART_VIEW_TABLE):
        existing_ix = _existing_index_names(inspector, _SMART_VIEW_TABLE)
        for ix in ("ix_smart_view_scope", "ix_smart_view_created_by"):
            if ix in existing_ix:
                try:
                    op.drop_index(ix, table_name=_SMART_VIEW_TABLE)
                except sa_exc.OperationalError:
                    pass
        op.drop_table(_SMART_VIEW_TABLE)
