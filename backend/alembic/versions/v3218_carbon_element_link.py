# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""carbon 6D - link an embodied-carbon entry to a BIM element.

Adds three additive columns to ``oe_carbon_embodied_entry``:

    element_id        - optional link to oe_bim_element.id (plain GUID, NO
                        ForeignKey, per the cross-module-ref convention) so an
                        entry's quantity comes from model geometry, not text
    source            - 'manual' | 'auto_enriched' | 'boq_derived'
    match_confidence  - 'high' | 'medium' | 'low' for auto-matched factors

plus an index on element_id. ``element_ref`` is kept for back-compat.

Idempotent - safe to re-run on a DB where Base.metadata.create_all has already
produced the columns / index. The downgrade drops the index then the columns.

Revision ID: v3218_carbon_element_link
Revises: v3217_contracts_depth
Create Date: 2026-06-30
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3218_carbon_element_link"
down_revision: Union[str, Sequence[str], None] = "v3217_contracts_depth"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLE = "oe_carbon_embodied_entry"
_IX_ELEMENT_ID = "ix_oe_carbon_embodied_entry_element_id"


def _has_table(inspector: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # ``String(36)`` on PostgreSQL too. ``GUID`` in ``app.database`` is a
    # ``TypeDecorator`` over ``String(36)`` with no ``load_dialect_impl``, so
    # ``create_all`` builds every identity column as ``character varying(36)``
    # and a native uuid here cannot carry a foreign key to one: PostgreSQL
    # answers ``DatatypeMismatch`` as soon as the chain is walked, not stamped.
    guid_type = sa.String(36)

    if not _has_table(inspector, _TABLE):
        # Fresh install where create_all has not yet built the table - the
        # model definition already carries the new columns, so nothing to do.
        logger.info("v3218 carbon element link: table %s absent, skipping", _TABLE)
        return

    if not _has_column(inspector, _TABLE, "element_id"):
        op.add_column(_TABLE, sa.Column("element_id", guid_type, nullable=True))
    if not _has_column(inspector, _TABLE, "source"):
        op.add_column(
            _TABLE,
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        )
    if not _has_column(inspector, _TABLE, "match_confidence"):
        op.add_column(_TABLE, sa.Column("match_confidence", sa.String(16), nullable=True))

    # Refresh the inspector - add_column above invalidates the cached metadata.
    inspector = sa.inspect(bind)
    if _has_column(inspector, _TABLE, "element_id") and not _has_index(inspector, _TABLE, _IX_ELEMENT_ID):
        try:
            op.create_index(_IX_ELEMENT_ID, _TABLE, ["element_id"])
        except sa.exc.OperationalError:
            # Tolerate a race with another upgrade or a pre-existing index that
            # did not show up in the cached inspector data.
            pass

    logger.info("v3218 carbon element link: schema ensured")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, _TABLE, _IX_ELEMENT_ID):
        try:
            op.drop_index(_IX_ELEMENT_ID, table_name=_TABLE)
        except sa.exc.OperationalError:
            pass

    for column in ("match_confidence", "source", "element_id"):
        if _has_column(inspector, _TABLE, column):
            try:
                op.drop_column(_TABLE, column)
            except (sa.exc.OperationalError, NotImplementedError):
                # Dropping a column on SQLite needs batch mode; tolerate failure
                # on that backend (dev only - production is PostgreSQL).
                pass

    logger.info("v3218 carbon element link: reverted")
