# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Backfill oe_costs_item.currency from the region code that already names it.

``CostItem.currency`` is ``String(10), nullable=False, default=""`` and a CWICR
parquet carries no currency column, so the importer has to resolve the code
from the region it is loading and stamp it on every row. Its lookup table did
not cover every region it would accept, and an import of one of the missing
ones resolved to ``''`` and wrote a whole catalogue of rates with no unit of
money on them. The write path is fixed separately; this repairs the rows it
already wrote.

Measured on a real database before this was written, not inferred: 55 718 of
123 485 cost rows carried a blank currency, and every one of them was
``source = 'cwicr'`` with ``region = 'ZH_SHANGHAI'``. The other three regions
in the same table - RU_STPETERSBURG, TR_ISTANBUL and the Universal starter set
- were complete, so this is one import rather than a systemic write. That is
also what makes it repairable rather than guesswork: the region code is not a
hint about the currency, it IS the currency. A CWICR catalogue is imported one
region at a time and every rate in it is denominated in that region's local
money.

Why this is safe to run over customer data:

* **Only empty or NULL rows are touched.** A row carrying any currency is
  never rewritten, whatever its value. An install whose items were imported
  rather than ingested from CWICR is therefore untouched. Verified on a seeded
  row: a ``ZH_SHANGHAI`` item already carrying USD came through the run still
  carrying USD.
* **Nothing is invented.** The region-to-currency pairs below are a frozen
  snapshot of ``app/modules/costs/base_registry.py``'s ``_GLOBAL_MARKETS``
  table, which is where the application itself gets the answer. A row whose
  region is not in that table keeps its blank currency, and the count of such
  rows is logged rather than papered over. Verified the same way: a row under a
  region no base declares stayed blank.
* **Frozen on purpose.** The pairs are inlined rather than imported. A
  migration that imports application code breaks the moment that code moves
  on, and this revision has to keep running against the schema and the
  registry as they were when it was written.
* **Idempotent.** The predicate stops matching once a row is filled, so a
  second run updates zero rows. Run twice against the measured database: the
  first pass reported 55 718 filled, the second 0 blank before and 0 filled.

One thing this deliberately does **not** do. There is a separate, open question
about the same recipe carrying an identical amount in several currencies. This
revision only writes the *label*; it changes no amount, so it neither fixes nor
hides that. If anything it makes it easier to see, because identical numbers now
carry different currency codes instead of none. Repricing is a separate decision
and is not taken here.

**Why the writes go through a second connection.** The first shape of this
revision issued one ``UPDATE`` per region on the migration's own connection.
That reads as batching and is not. Alembic wraps an entire ``upgrade`` in a
single transaction -- ``env.py`` calls ``context.run_migrations()`` inside one
``context.begin_transaction()`` and never sets ``transaction_per_migration`` --
so every superseded row version from every region, and from every other revision
in the same run, stays on disk until the last one commits. Postgres keeps those
versions until vacuum, so peak demand was the whole table rewritten, roughly
twice the table plus comparable WAL, no matter how many regions the loop had.

Measured when that bit: on a 1724 MB table with 553 360 of 592 825 rows to fill
and 804 MB free, it died with ``DiskFull`` extending a relation while updating
``AU_SYDNEY``. Worse than the arithmetic, the ``WHERE`` predicate below makes
the work look resumable and inside one transaction it is not: the abort rolled
back the regions that had already succeeded, leaving exactly the same 553 360
rows pending. Every retry started from zero and needed the entire peak at once,
so freeing a little space and running again could never make progress.

Chunked commits on a connection of our own fix both halves. Each chunk is
durable the moment it lands, so an interrupted run keeps what it did and a
re-run continues from there, and dead tuples become reclaimable as we go instead
of at the end. Committing only makes them *eligible*, though, and autovacuum
will not keep pace with chunks issued back to back, so this vacuums explicitly
on a row budget rather than per chunk -- a vacuum scans the whole table, and one
per chunk would cost a hundred full scans to save the same space.

The second connection cannot be taken for granted, which is why
:func:`_open_side_connection` probes instead of assuming. A database older than
the costs module creates ``oe_costs_item`` in a revision that runs in this same
uncommitted transaction, and a second connection cannot see a table that has not
been committed: merely querying it would block on the catalog lock rather than
fail. (A *blank* database never reaches that state, because ``env.py`` short
circuits it into ``create_all`` plus a stamp to head and never runs the chain at
all. The case that matters is the upgrade that crosses the revision introducing
this table, not the fresh install.) ``to_regclass`` answers from the second
connection's own catalog snapshot and takes no lock, so it says which case we
are in without hanging, and ``lock_timeout`` turns any future revision that
locks this table ahead of us into a clean fallback rather than a wedged upgrade.
When the probe says no, the original in-transaction loop runs, which is correct
precisely because that case means the table was created in this run and is
therefore empty or small.

Revision ID: v3273_backfill_cost_item_currency
Revises: v3272_assignment_activity_link
Create Date: 2026-08-03
"""

from __future__ import annotations

import logging
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3273_backfill_cost_item_currency"
down_revision: Union[str, Sequence[str], None] = "v3272_assignment_activity_link"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_ITEM = "oe_costs_item"

# Frozen snapshot of base_registry._GLOBAL_MARKETS (region -> ISO 4217 code).
_REGION_CURRENCY: tuple[tuple[str, str], ...] = (
    ("USA_USD", "USD"),
    ("UK_GBP", "GBP"),
    ("DE_BERLIN", "EUR"),
    ("ENG_TORONTO", "CAD"),
    ("FR_PARIS", "EUR"),
    ("SP_BARCELONA", "EUR"),
    ("PT_SAOPAULO", "BRL"),
    ("RU_STPETERSBURG", "RUB"),
    ("AR_DUBAI", "AED"),
    ("HI_MUMBAI", "INR"),
    ("AU_SYDNEY", "AUD"),
    ("NZ_AUCKLAND", "NZD"),
    ("IT_ROME", "EUR"),
    ("NL_AMSTERDAM", "EUR"),
    ("PL_WARSAW", "PLN"),
    ("CS_PRAGUE", "CZK"),
    ("HR_ZAGREB", "EUR"),
    ("BG_SOFIA", "BGN"),
    ("RO_BUCHAREST", "RON"),
    ("SV_STOCKHOLM", "SEK"),
    ("JA_TOKYO", "JPY"),
    ("KO_SEOUL", "KRW"),
    ("TH_BANGKOK", "THB"),
    ("VI_HANOI", "VND"),
    ("ID_JAKARTA", "IDR"),
    ("MX_MEXICOCITY", "MXN"),
    ("ZA_JOHANNESBURG", "ZAR"),
    ("NG_LAGOS", "NGN"),
    ("ZH_SHANGHAI", "CNY"),
    ("TR_ISTANBUL", "TRY"),
)


# A row is roughly 3 KB on the database this was measured against (1724 MB
# over 592 825 rows), and an updated row costs a second copy until vacuum.
# 5 000 rows is therefore about 15 MB of dead tuples per chunk, small enough
# that the smallest disk we have seen in the field absorbs one comfortably.
_CHUNK_ROWS = 5_000

# Vacuum on a row budget, not per chunk. At ~3 KB a row this caps dead tuples
# near 400 MB between vacuums, which is the intended peak: the 553 360 pending
# rows on the demo box cost about five vacuums. Per chunk would be correct and
# far slower, since a vacuum scans the whole table however little it reclaims.
_VACUUM_EVERY_ROWS = 130_000

# Long enough to ride out an ordinary concurrent statement, short enough that a
# future revision holding this table ahead of us fails over instead of hanging.
_LOCK_TIMEOUT = "5s"

_BLANK = "(currency IS NULL OR TRIM(currency) = '')"


def _has_column(inspector: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    """True when ``table`` exists and carries ``column``."""
    if table not in inspector.get_table_names():
        return False
    return any(col["name"] == column for col in inspector.get_columns(table))


def _open_side_connection(bind: sa.engine.Connection) -> sa.engine.Connection | None:
    """An autocommit connection that can write ``_ITEM``, or ``None``.

    ``None`` means "do it on the migration's own connection instead", and the
    caller must honour that rather than treating it as an error. Three ways to
    get it, all legitimate:

    * The dialect is not PostgreSQL, so neither ``to_regclass`` nor the chunked
      strategy's ``VACUUM`` applies.
    * ``_ITEM`` is invisible to a second connection because an earlier revision
      in this same uncommitted transaction created it. That is an upgrade
      crossing the revision that introduces the costs module, where the table
      is new and the peak is negligible either way.
    * A lock on ``_ITEM`` is held elsewhere and ``lock_timeout`` fired.

    The probe is ``to_regclass``, which answers from this connection's own
    catalog snapshot and takes no lock, so it distinguishes those cases without
    blocking. Querying the table itself would not: against an uncommitted
    ``CREATE TABLE`` it waits on the catalog lock forever rather than failing.
    """
    try:
        conn = bind.engine.connect().execution_options(isolation_level="AUTOCOMMIT")
    except Exception as exc:  # pragma: no cover - driver/pool specific
        logger.info("no second connection available (%s), filling in-transaction", exc)
        return None

    try:
        conn.execute(sa.text(f"SET lock_timeout = '{_LOCK_TIMEOUT}'"))
        if conn.execute(sa.text("SELECT to_regclass(:t)"), {"t": _ITEM}).scalar() is None:
            logger.info("%s not visible to a second connection, filling in-transaction", _ITEM)
            conn.close()
            return None
        # Visible is not the same as reachable, and only this second probe can
        # tell them apart. ``to_regclass`` deliberately takes no lock, so it
        # answers just as promptly when the migration's own transaction is
        # sitting on an ACCESS EXCLUSIVE lock from an earlier ALTER TABLE in
        # the same run - which is the third case this function documents and,
        # until this line, could never actually reach. Touching one row takes
        # ACCESS SHARE, so it waits on that lock and ``lock_timeout`` turns the
        # wait into the clean in-transaction fallback rather than an
        # OperationalError raised out of the backfill further down.
        conn.execute(sa.text(f"SELECT 1 FROM {_ITEM} LIMIT 1"))  # noqa: S608 - constant
    except Exception as exc:
        logger.info("second connection unusable (%s), filling in-transaction", exc)
        conn.close()
        return None

    return conn


def _vacuum(conn: sa.engine.Connection) -> None:
    """Reclaim what the committed chunks made eligible. Never fatal.

    ``VACUUM`` requires ownership of the table, so an install whose migration
    role does not own ``oe_costs_item`` raises here. That must not abort a
    backfill which is otherwise correct: without the vacuum the fill still
    completes and still commits as it goes, it simply carries more dead tuples
    while it runs. Losing the peak bound is worth a warning, not an upgrade.
    """
    try:
        conn.execute(sa.text(f"VACUUM {_ITEM}"))  # noqa: S608 - constant
    except Exception as exc:
        logger.warning(
            "could not vacuum %s between chunks (%s); the backfill continues, but "
            "peak disk is no longer bounded by the chunk budget",
            _ITEM,
            exc,
        )


def _fill_chunked(conn: sa.engine.Connection) -> int:
    """Fill in committed chunks, vacuuming on a row budget. Returns rows filled."""
    filled = 0
    unvacuumed = 0

    for region, code in _REGION_CURRENCY:
        while True:
            # ctid rather than the primary key: this path only runs on
            # PostgreSQL, every row has one, and it commits us to nothing about
            # what the key is called or how it is typed. An updated row stops
            # matching the predicate, so each pass selects fresh rows and the
            # loop ends on its own without a cursor to carry between chunks.
            result = conn.execute(
                sa.text(
                    f"UPDATE {_ITEM} SET currency = :code WHERE ctid IN "  # noqa: S608 - constants
                    f"(SELECT ctid FROM {_ITEM} WHERE {_BLANK} AND region = :region LIMIT :chunk)"
                ),
                {"code": code, "region": region, "chunk": _CHUNK_ROWS},
            )
            done = result.rowcount or 0
            if not done:
                break
            filled += done
            unvacuumed += done
            if unvacuumed >= _VACUUM_EVERY_ROWS:
                _vacuum(conn)
                logger.info("cost item currency backfill: %s filled, vacuumed", filled)
                unvacuumed = 0

    if unvacuumed:
        _vacuum(conn)
    return filled


def _fill_in_transaction(conn: sa.engine.Connection) -> int:
    """Fill in one statement per region, inside the caller's transaction."""
    filled = 0
    for region, code in _REGION_CURRENCY:
        result = conn.execute(
            sa.text(
                f"UPDATE {_ITEM} SET currency = :code "  # noqa: S608 - constants
                f"WHERE {_BLANK} AND region = :region"
            ),
            {"code": code, "region": region},
        )
        filled += result.rowcount or 0
    return filled


# data-rewrite-ack: table=oe_costs_item growth=tenure rows=core cost-estimation line items across every project; already 1724 MB in the field, see #126
# boot-repair: gap - backfills each cost row's currency from the region code that names it, a per-row lookup no server_default can express; the importer is fixed, the rows it already wrote are not
def upgrade() -> None:
    """Fill blank cost-item currencies from the region code. Never overwrite."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # The costs module can be absent on a partial install, and this revision
    # must not be the thing that stops an upgrade over such a database.
    if not _has_column(inspector, _ITEM, "currency"):
        logger.info("%s.currency absent, nothing to backfill", _ITEM)
        return
    if not _has_column(inspector, _ITEM, "region"):
        logger.info("%s.region absent, nothing to backfill from", _ITEM)
        return

    side = _open_side_connection(bind)
    worker = side if side is not None else bind

    try:
        before = worker.execute(
            sa.text(f"SELECT COUNT(*) FROM {_ITEM} WHERE {_BLANK}")  # noqa: S608 - constants
        ).scalar_one()

        try:
            filled = _fill_chunked(side) if side is not None else _fill_in_transaction(bind)
        except Exception:
            if side is not None:
                # Worth saying out loud, because it is the whole point of the
                # second connection: what has been filled so far is committed,
                # and running the upgrade again continues from here rather than
                # starting over.
                logger.error(
                    "cost item currency backfill interrupted; rows filled before this point are "
                    "committed and a re-run resumes from them"
                )
            raise

        remaining = worker.execute(
            sa.text(f"SELECT COUNT(*) FROM {_ITEM} WHERE {_BLANK}")  # noqa: S608 - constants
        ).scalar_one()
    finally:
        if side is not None:
            side.close()

    logger.info(
        "cost item currency backfill: %s blank before, %s filled, %s still blank",
        before,
        filled,
        remaining,
    )
    if remaining:
        # Flag rather than guess. A row whose region is not in the frozen
        # market table has no derivable currency, and writing a default would
        # be inventing money.
        logger.warning(
            "%s rows in %s still carry no currency; their region is not in the "
            "known market table and no currency can be derived for them",
            remaining,
            _ITEM,
        )


def downgrade() -> None:
    """Deliberately a no-op.

    A currency code this migration wrote is indistinguishable from one a user
    or an import set: both are just a code sitting in the column. Blanking the
    rows this revision touched would therefore destroy values that may have
    been corrected by hand since. Downgrading a schema is reversible;
    downgrading a backfill is not, so this side is intentionally empty.
    """
