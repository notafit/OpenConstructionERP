# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Billing periods as dates rather than strings.

A progress claim stores its period as three strings, ``period_start``,
``period_end`` and ``claim_date``. They are the API contract and they stay, but
nothing can order, compare or window a string period: "which claims came before
this one" and "which sub pay apps fall inside this month" are date questions.
Since ``v42_contracts_billing_depth`` the claim also carries ``period_from``,
``period_to`` and ``application_date`` as real dates, parsed from the strings
by :func:`parse_iso_day`. This module is that parser plus the two small period
helpers the monthly cycle needs. It is pure and stdlib only, so the boot repair,
the service and the rules all read a string the same way.

What the parser accepts is deliberately narrow. Every write path has been
pattern-gated to ``YYYY-MM-DD`` since the claim schemas existed, and both seeders
write ISO dates, so the realistic legacy population is an ISO day, NULL or an
empty string. The parser also takes an ISO timestamp (some importers write one)
and a bare ``YYYY-MM`` month, and nothing else. In particular it never guesses
between ``DD/MM`` and ``MM/DD``: a guess that is wrong one time in two moves a
claim into another month, which is worse than leaving the date empty and letting
the ``pay_application.period_unparsed`` rule say so.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH = re.compile(r"^\d{4}-\d{2}$")

Bound = Literal["start", "end"]


def parse_iso_day(raw: Any, *, bound: Bound = "start") -> date | None:
    """Read one stored period string as a calendar day.

    Args:
        raw: The stored value. A ``date`` passes through; a ``datetime`` gives
            its date part; anything else is read as text.
        bound: Which end of a period the value sits at. It only matters for a
            bare month, which maps to the first day for ``"start"`` and to the
            last day for ``"end"``, so a claim "for 2026-03" covers all of March.

    Returns:
        The day, or ``None`` for an empty or unreadable value. ``None`` never
        means "today" or any other default: an unknown date stays unknown.
    """
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    if _DAY.match(text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            # Shaped like a day and not one, such as 2026-02-30.
            return None
    if _MONTH.match(text):
        year, month = int(text[:4]), int(text[5:7])
        if not 1 <= month <= 12:
            return None
        day = 1 if bound == "start" else calendar.monthrange(year, month)[1]
        return date(year, month, day)
    # An ISO timestamp. ``fromisoformat`` on Python 3.11+ reads the "Z" suffix
    # itself, and it is replaced anyway so the intent is on the page. The date
    # part is taken as written: converting to UTC first would move a claim
    # dated late in the evening west of Greenwich into the next day.
    if len(text) > 10 and _DAY.match(text[:10]) and text[10] in "T ":
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


#: (string column, date column, bound) for each date a progress claim carries.
#: The bound only matters for a bare ``YYYY-MM`` value: a period that starts in
#: a month starts on its first day, and one that ends in a month ends on its last.
CLAIM_PERIOD_COLUMNS: tuple[tuple[str, str, Bound], ...] = (
    ("period_start", "period_from", "start"),
    ("period_end", "period_to", "end"),
    ("claim_date", "application_date", "start"),
)


def claim_dates_for_write(fields: dict[str, Any]) -> dict[str, date | None]:
    """The date columns a write to a claim's period strings has to carry with it.

    For every period string present in ``fields`` the matching date column is
    returned, parsed, and ``None`` when the new string is empty or unreadable.
    A string absent from ``fields`` is not being written, so its date is not
    touched. Every write path calls this, which is what keeps a date from ever
    disagreeing with the string beside it.
    """
    out: dict[str, date | None] = {}
    for text_column, date_column, bound in CLAIM_PERIOD_COLUMNS:
        if text_column in fields:
            out[date_column] = parse_iso_day(fields[text_column], bound=bound)
    return out


def claim_dates_to_backfill(row: dict[str, Any]) -> dict[str, date]:
    """The date columns a stored claim row is missing and whose string can be read.

    Only a NULL date is ever filled. A date that is already set is left alone
    even when the string beside it now says something else, because the write
    path keeps the two together and a disagreement is for a person to look at,
    not for a backfill to settle by picking one.
    """
    out: dict[str, date] = {}
    for text_column, date_column, bound in CLAIM_PERIOD_COLUMNS:
        if row.get(date_column) is not None:
            continue
        parsed = parse_iso_day(row.get(text_column), bound=bound)
        if parsed is not None:
            out[date_column] = parsed
    return out


def claim_order_key(claim: Any) -> tuple[date, float, str]:
    """Sort key that puts a contract's claims in billing order.

    Ordered by period end, then by when the claim was created, then by its
    number. Creation time breaks ties between claims closing on the same day,
    and the number is the last resort for rows created together.

    A claim with no period end is placed on the day it was raised. It used to
    sort after every dated claim, on the reasoning that an unplaceable claim
    should never become "previous" to one whose period is known, and that is
    exactly what it cost: an undated claim certified at forty per cent was
    invisible to the April claim that followed it, which read nothing as
    previously certified and billed the job for the whole sixty per cent on
    top. Dating it by creation is also a guess, but it is a guess in billing
    order, so the money adds up, and the claim still cannot be submitted
    undated (``pay_application.period_present`` blocks it). A row with
    neither a period nor a creation time sorts first and is ordered by its
    number, which keeps the order total and stable.

    This is the order that decides what a payment application counts as
    previously certified, which is why "prior" means the claims before this one
    in this order and never "every other claim on the contract".
    """
    period_to = getattr(claim, "period_to", None)
    created = getattr(claim, "created_at", None)
    if period_to is None and created is not None:
        period_to = created.date()
    return (
        period_to or date.min,
        created.timestamp() if created is not None else float("-inf"),
        str(getattr(claim, "claim_number", "") or ""),
    )


def claims_before(ordered: list[Any], claim_id: Any) -> list[Any]:
    """The claims strictly before ``claim_id`` in an already ordered list.

    Returns every claim when ``claim_id`` is not in the list, which is what a
    claim being created (and so not yet stored) should see.
    """
    for index, claim in enumerate(ordered):
        if getattr(claim, "id", None) == claim_id:
            return list(ordered[:index])
    return list(ordered)


@dataclass(frozen=True, slots=True)
class BillingPeriod:
    """A closed range of days, both ends included."""

    frm: date
    to: date

    def __post_init__(self) -> None:
        if self.frm > self.to:
            raise ValueError(f"billing period starts on {self.frm} after it ends on {self.to}")


def period_contains(period: BillingPeriod, day: date | None) -> bool:
    """Whether ``day`` falls inside ``period``; an unknown day falls in none."""
    if day is None:
        return False
    return period.frm <= day <= period.to


def _period_end_day(cycle: dict[str, Any] | None) -> int | None:
    """The fixed day of the month a cycle closes on, or ``None`` for month end."""
    spec = str((cycle or {}).get("period_end") or "month_end").strip().lower()
    if spec == "month_end":
        return None
    if spec.startswith("day:"):
        try:
            day = int(spec[4:])
        except ValueError:
            return None
        if 1 <= day <= 28:
            return day
        # Day 29, 30 or 31 does not exist in every month, and "the 31st" in
        # February has no honest reading other than the month end.
        return None
    return None


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def resolve_billing_period(as_of: date, cycle: dict[str, Any] | None = None) -> BillingPeriod:
    """The monthly billing period that contains ``as_of``.

    ``cycle`` is a pack's ``billing_cycle`` block, for example
    ``{"frequency": "monthly", "period_end": "day:25"}``. Only monthly cycles
    exist in the packs today; any other frequency is read as monthly rather
    than refused, because the answer is used to suggest a period to a person
    who confirms it, not to decide one.

    With ``period_end`` at month end (the default) the period is the calendar
    month. With ``day:N`` the period runs from the day after the N-th of the
    previous month to the N-th of this one, and a date after the N-th belongs to
    the period that closes next month.
    """
    close = _period_end_day(cycle)
    if close is None:
        last = calendar.monthrange(as_of.year, as_of.month)[1]
        return BillingPeriod(date(as_of.year, as_of.month, 1), date(as_of.year, as_of.month, last))
    if as_of.day <= close:
        end_year, end_month = as_of.year, as_of.month
    else:
        end_year, end_month = _add_months(as_of.year, as_of.month, 1)
    start_year, start_month = _add_months(end_year, end_month, -1)
    return BillingPeriod(
        date(start_year, start_month, close) + timedelta(days=1),
        date(end_year, end_month, close),
    )


__all__ = [
    "CLAIM_PERIOD_COLUMNS",
    "BillingPeriod",
    "claim_dates_for_write",
    "claim_dates_to_backfill",
    "claim_order_key",
    "claims_before",
    "parse_iso_day",
    "period_contains",
    "resolve_billing_period",
]
