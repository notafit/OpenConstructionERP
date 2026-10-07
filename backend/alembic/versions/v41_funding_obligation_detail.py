# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""funding - say what an obligation means in a form that can be translated.

``oe_funding_obligation.detail`` holds an English sentence the service wrote
when it derived the deadline from a programme's terms. Nobody using the
React client ever sees it, because that client renders the ``kind`` enum
through its own locales, but the REST response carries the sentence to every
other caller, in a product that ships in 42 languages. There is no later
moment at which that sentence can be translated: the words are data by then.

So the sentence gains the two things that make it translatable, stored beside
it rather than in place of it:

``detail_key``
    The message key the sentence renders from, for example
    ``funding.obligation_detail.final_report``. It is stored rather than
    derived from ``kind`` because one kind produces two different sentences:
    a retention deadline counted from the end of the award period reads
    differently from the same deadline recounted from the day the proof of
    use was accepted, and a caller must not have to guess which it is
    holding.

``detail_params``
    The values that key interpolates - the day count, the year count, the
    programme code, the sequence number of the draw. These are stored for
    the same reason ``due_on`` is stored rather than recomputed: a deadline
    already communicated to somebody must not be quietly reworded when the
    programme's terms are edited afterwards.

``detail`` stays exactly as it is and keeps its English. It is now the
rendered convenience for a caller with no message bundle, and the key with
its parameters is the contract.

Both columns are empty on an obligation somebody typed in. Those are their
own words, not a key into anything, and translating them would be losing
what they wrote.

Additive: two new columns on one table, nothing existing dropped or retyped.
Inspector-guarded, so an install whose tables ``env.py`` already built through
``Base.metadata.create_all`` reaches this revision and adds neither column.

On that install the guards used to make the revision a complete no-op, and that
was the bug. The boot heal adds a column with a DDL default only when the model
default has a literal spelling. ``detail_key`` has ``default=""`` and lands NOT
NULL DEFAULT ''; ``detail_params`` has ``default=dict``, a callable with no DDL
spelling, and lands nullable with no default, so rows written before the model
grew the column keep it NULL and nothing ever came back for them. The backfill
at the end of ``upgrade()`` therefore sits outside both column guards and runs
on every path through this function. It writes only where the value IS NULL, so
it rewrites no row that carries parameters and a second run updates nothing.

Every path through this function is a narrower promise than it sounds, and the
first version of this revision leaned on it as though it were the whole one.
The product never calls ``alembic upgrade``; it heals the schema at boot and
stamps head, so nothing below runs on an ordinary install at all. The repair
that does run there is ``funding_obligation_detail_params_not_null`` in
``app/modules/funding/repairs.py``, and the model has gained the
``server_default`` that stops the bare column being created again.

Revision ID: v41_funding_obligation_detail
Revises: v41_funding_module
Create Date: 2026-09-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v41_funding_obligation_detail"
down_revision: Union[str, Sequence[str], None] = "v41_funding_module"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_funding_obligation"
_KEY_COLUMN = "detail_key"
_PARAMS_COLUMN = "detail_params"


# data-rewrite-ack: table=oe_funding_obligation growth=bounded rows=one row per dated obligation on a funding application, eight derived kinds per award plus whatever conditions the award notice carries, so it tracks the number of applications rather than transaction history
# boot-repair: registry=funding_obligation_detail_params_not_null
def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _TABLE not in inspector.get_table_names():
        # Nothing to alter. The revision that creates this table runs
        # immediately before this one, so its absence means the chain never
        # got that far, and adding a column to a table that is not there
        # would stop the upgrade on a database this module does not use.
        return

    existing = {column["name"] for column in inspector.get_columns(_TABLE)}

    if _KEY_COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _KEY_COLUMN,
                sa.String(length=120),
                nullable=False,
                # The rows already in the table were written before this
                # column existed, so they have no key. An empty string is
                # what a hand written obligation carries too, and both mean
                # the same thing to a reader: render the prose, there is
                # nothing to translate.
                server_default="",
            ),
        )

    if _PARAMS_COLUMN not in existing:
        op.add_column(
            _TABLE,
            sa.Column(
                _PARAMS_COLUMN,
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
        )

    # Runs on both paths, and that is the whole point of it being out here.
    #
    # The guards above are what let this revision reach an installation whose
    # tables came from ``Base.metadata.create_all`` plus the boot heal rather
    # than from the chain. On such an installation both columns already exist
    # when this runs, so both ``add_column`` calls are skipped - and the two
    # columns do not arrive in the same state. The heal renders a column
    # default into DDL only when it can write the value as a literal:
    # ``detail_key`` carries ``default=""``, a scalar, so it lands NOT NULL
    # DEFAULT ''. ``detail_params`` carries ``default=dict``, a callable the
    # ORM evaluates per row, which has no DDL spelling, so it lands nullable
    # with no default and every row written before the model gained the column
    # keeps ``detail_params`` NULL. Measured on the local database: exactly
    # that split.
    #
    # Skipping the whole revision therefore left those rows NULL permanently,
    # because nothing else ever comes back for them. The UPDATE below is the
    # thing that closes it, so it must not sit inside the ``if`` that was
    # skipped. It matches only NULL rows, so a row already carrying parameters
    # is never rewritten and a second run updates nothing.
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET {_PARAMS_COLUMN} = '{{}}' WHERE {_PARAMS_COLUMN} IS NULL")  # noqa: S608
    )

    # The UPDATE alone does not make the two paths agree. It removes every
    # NULL, but on a healed database the column itself is still declared
    # nullable with no default, so the model and the schema go on disagreeing
    # about it and ``/api/health`` reports ``schema_matches_models=false`` for
    # the life of that installation. An operator reading a permanently
    # degraded status has no way to tell this one known column from a real
    # drift, which is the kind of standing false alarm that later hides a true
    # one. The two statements below close it, and they sit out here for the
    # same reason the UPDATE does: the ``if`` above is exactly the branch that
    # a healed database skips.
    #
    # Both are no-ops on the migration path, where ``add_column`` has already
    # supplied ``nullable=False`` and the same default. That is the point of
    # writing them unconditionally rather than under a second guard: one code
    # path, and the two populations end in the same shape instead of in two
    # shapes that happen to read alike. ``SET NOT NULL`` cannot fail here,
    # because the UPDATE immediately above has just removed the only rows that
    # could have made it fail, and both statements are idempotent, so a repeat
    # run changes nothing. The table holds a handful of rows per project, so
    # the scan ``SET NOT NULL`` performs is not worth deferring into a
    # ``NOT VALID`` CHECK and a later ``VALIDATE``.
    #
    # None of which reaches an ordinary installation, and the paragraphs above
    # were written as though it did. The product does not run ``alembic
    # upgrade``: it moves the schema at boot and then stamps head, so this
    # body executes only where an operator runs the revision by hand. Every
    # statement here is correct and none of them is sufficient. The half that
    # reaches the rest is the registered repair named in the ``boot-repair``
    # declaration above, which does the same backfill and the same two ALTERs
    # from the boot path and records each run in ``oe_data_repair_ledger``.
    #
    # The model now also carries ``server_default`` on ``detail_params``, which
    # is what stops a *new* healed install from arriving in the broken shape in
    # the first place. Without it the heal would keep producing bare columns
    # and the repair would keep cleaning up after it, forever.
    op.execute(sa.text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_PARAMS_COLUMN} SET DEFAULT '{{}}'"))  # noqa: S608
    op.execute(sa.text(f"ALTER TABLE {_TABLE} ALTER COLUMN {_PARAMS_COLUMN} SET NOT NULL"))  # noqa: S608


def downgrade() -> None:
    op.drop_column(_TABLE, _PARAMS_COLUMN)
    op.drop_column(_TABLE, _KEY_COLUMN)
