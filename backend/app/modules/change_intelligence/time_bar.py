# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure contractual notice and time-bar clock engine.

Missing a contractual notice deadline can forfeit an entire claim or an
extension-of-time entitlement: a FIDIC claim-notice window, an NEC compensation
event notification, a JCT delay notice, an AIA claim window. This engine turns
the event date already recorded on a change / variation / EOT record into a
countdown: it adds the applicable notice or response period, produces the
deadline, and classifies where the clock stands (met / upcoming / due-soon /
overdue). It is the deterministic core behind a per-project "notice register".

The mapping from a contract standard to its notice periods is a code-level
config (:data:`NOTICE_PERIODS`): a small table of standard -> {notice_type:
period_days}. The standards named here (FIDIC, NEC, JCT, AIA, ConsensusDocs,
CCDC) are international contract standards, named as such; none is a commercial
product.
The day counts encode the well-known windows for each standard and are documented
inline; a deployment can localise them without touching the engine's logic.

Calendar days and working days
------------------------------
A notice period is either a run of calendar days or a run of working days, and
which one it is moves the deadline by several days on any period long enough to
cross a weekend. Every period therefore carries a basis alongside its day count
(:data:`NOTICE_PERIOD_BASES`), and the counting itself is done by
:func:`app.core.day_basis.add_days` - the same function the statutory payment
clock counts with, so the two engines cannot drift apart. Working days are
Monday to Friday minus a calendar the deployment supplies; no holiday list is
shipped here, for the reasons argued in that module.

No database, no ORM, no ``app.modules.*`` imports - the standard library plus
that one pure ``app.core`` helper, which itself imports nothing but the standard
library - so it unit-tests on the local runner exactly like the cycle-time, SLA
and dispute-risk engines. It reads no clock: the caller supplies ``now`` and the
already-parsed dates, so identical inputs always produce an identical register.

Proof of notice
---------------
For a notice that must actually be served (a claim notice, an EOT notice) the
caller passes ``proof_on_file`` - whether a matching notice document was found in
the correspondence record. A required notice with nothing on file is flagged
:attr:`NoticeClock.entitlement_at_risk` regardless of the internal status,
because a change proceeding with no notice on file is the classic way an
entitlement is lost. Response-style clocks (a quotation window, an assessment
window, an early-warning response) do not require a served notice and are never
flagged for a missing proof document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.core.day_basis import BUSINESS, CALENDAR
from app.core.day_basis import add_days as _add_days_on_basis

# --------------------------------------------------------------------------- #
# Contract standards (international standards, named as such - not products).
# --------------------------------------------------------------------------- #

STANDARD_FIDIC = "FIDIC"
STANDARD_NEC = "NEC"
STANDARD_JCT = "JCT"
STANDARD_AIA = "AIA"
STANDARD_CONSENSUSDOCS = "CONSENSUSDOCS"
#: The Canadian CCDC family (CCDC 2-2020 Stipulated Price Contract).
STANDARD_CCDC = "CCDC"
STANDARD_UNKNOWN = "UNKNOWN"

# --------------------------------------------------------------------------- #
# Notice types (the clocks). A record maps onto one or more of these.
# --------------------------------------------------------------------------- #

#: Notice of a claim / compensation event - the entitlement time-bar.
NOTICE_CLAIM = "claim_notice"
#: Notice of a delay event for an extension-of-time claim.
NOTICE_EOT = "eot_notice"
#: The window to submit a quotation for an instructed change.
NOTICE_QUOTATION = "quotation"
#: The window for the assessing party to respond to / assess a submission.
NOTICE_ASSESSMENT = "assessment"
#: A generic response-due window (early-warning response, change-order response).
NOTICE_RESPONSE = "response"

# --------------------------------------------------------------------------- #
# Clock statuses.
# --------------------------------------------------------------------------- #

#: The required action was recorded on or before the deadline - clock stopped.
STATUS_MET = "met"
#: Not yet due and further out than the due-soon window.
STATUS_UPCOMING = "upcoming"
#: Not yet due but inside the due-soon window - act now.
STATUS_DUE_SOON = "due_soon"
#: Past the deadline with no action recorded, or served after the deadline.
STATUS_OVERDUE = "overdue"
#: No deadline could be derived (missing dates and no configured period).
STATUS_UNKNOWN = "unknown"

#: Default number of days before a deadline at which a clock turns "due_soon".
DEFAULT_DUE_SOON_DAYS = 7

# --------------------------------------------------------------------------- #
# Notice periods per contract standard, in calendar days. Standard ->
# {notice_type: period_days}. The values encode the well-known windows for each
# standard; where a standard expresses a duty without a fixed day-count (JCT's
# "forthwith" delay notice), a practical reminder window is used and noted. A
# deployment can override these per contract without changing the engine logic.
# --------------------------------------------------------------------------- #

NOTICE_PERIODS: dict[str, dict[str, int]] = {
    # FIDIC (1999 Red Book Sub-Clause 20.1 / 2017 Clause 20.2): the Contractor
    # gives notice of a claim within 28 days of the event or of becoming aware;
    # the fully detailed claim follows within 42 days; the Engineer responds in
    # 42 days.
    STANDARD_FIDIC: {
        NOTICE_CLAIM: 28,
        NOTICE_EOT: 28,
        NOTICE_QUOTATION: 42,
        NOTICE_ASSESSMENT: 42,
        NOTICE_RESPONSE: 28,
    },
    # NEC4 ECC: a compensation event is notified within 8 weeks of the
    # Contractor becoming aware (Clause 61.3 time-bar); quotations are submitted
    # within 3 weeks of instruction (Clause 62.3) and the Project Manager replies
    # within 2 weeks (Clause 62.3 / 62.5).
    STANDARD_NEC: {
        NOTICE_CLAIM: 56,
        NOTICE_EOT: 56,
        NOTICE_QUOTATION: 21,
        NOTICE_ASSESSMENT: 14,
        NOTICE_RESPONSE: 14,
    },
    # JCT SBC 2016: the delay notice under Clause 2.27.1 is given "forthwith",
    # with no fixed statutory day-count, so the claim / EOT windows below are
    # practical reminder windows, not hard bars; the quotation window mirrors the
    # Schedule 2 variation-quotation practice.
    STANDARD_JCT: {
        NOTICE_CLAIM: 14,
        NOTICE_EOT: 14,
        NOTICE_QUOTATION: 21,
        NOTICE_ASSESSMENT: 14,
        NOTICE_RESPONSE: 14,
    },
    # AIA A201-2017: a Claim is initiated within 21 days after the event or after
    # the claimant first recognises the condition (Section 15.1.3), which also
    # governs time claims (Section 15.1.6).
    STANDARD_AIA: {
        NOTICE_CLAIM: 21,
        NOTICE_EOT: 21,
        NOTICE_QUOTATION: 21,
        NOTICE_ASSESSMENT: 21,
        NOTICE_RESPONSE: 14,
    },
    # ConsensusDocs 200: notice of a change / claim is given within 14 days
    # (Articles 6 and 8); a time extension follows the same notice discipline.
    STANDARD_CONSENSUSDOCS: {
        NOTICE_CLAIM: 14,
        NOTICE_EOT: 21,
        NOTICE_QUOTATION: 21,
        NOTICE_ASSESSMENT: 14,
        NOTICE_RESPONSE: 14,
    },
    # CCDC 2-2020 (Stipulated Price Contract). Claims notice within 10 working
    # days of the event (GC 6.6). Change orders: the Contractor proceeds and
    # adjusts the price within 14 calendar days (GC 6.1). EOT notice follows
    # the same 10-working-day discipline as claims (GC 6.5). The Consultant
    # responds within 15 calendar days of receiving a quotation (GC 6.3).
    STANDARD_CCDC: {
        NOTICE_CLAIM: 10,
        NOTICE_EOT: 10,
        NOTICE_QUOTATION: 14,
        NOTICE_ASSESSMENT: 15,
        NOTICE_RESPONSE: 15,
    },
}

#: Standards that are recognised but deliberately carry no periods yet, so a
#: clock reports "no period is registered for this form" instead of counting
#: down a window nothing supports.
#:
#: This is the distinction the payment-clock registry already draws between a
#: value, a categorised reason for having none, and a search that has not
#: finished. A standard here is not the same as an unknown one: an unrecognised
#: contract form still falls through to :data:`GENERIC_PERIODS`, because a
#: standard-neutral reminder window is the best available answer when nothing
#: is known about the contract at all. A standard *named* on the record is a
#: different case - the reader can see which contract governs, so a number
#: presented next to that name reads as that contract's number.
NOTICE_PERIODS_HELD: frozenset[str] = frozenset()

#: Fallback periods used when the project's contract standard is unknown, so a
#: clock can still be derived from an event date. Conservative, standard-neutral
#: windows; a real standard on the record always takes precedence.
GENERIC_PERIODS: dict[str, int] = {
    NOTICE_CLAIM: 28,
    NOTICE_EOT: 28,
    NOTICE_QUOTATION: 28,
    NOTICE_ASSESSMENT: 21,
    NOTICE_RESPONSE: 14,
}

# --------------------------------------------------------------------------- #
# The basis each period is counted on. Deliberately dense rather than sparse:
# every standard and notice type in the tables above appears here too, even
# where the answer is the default, and :func:`period_bases_are_complete` gates
# that. A sparse table would let a new standard arrive with day counts and no
# basis and silently count in calendar days, which is the exact defect this
# table exists to remove.
#
# Every entry below resolves to "calendar" because every standard currently
# configured counts in calendar days, verified against each one's own
# definition of a day: FIDIC Sub-Clause 1.1.3.3 defines a day as a calendar
# day; the NEC periods here derive from weeks; AIA A201-2017 Section 8.1.4
# defines "day" as calendar day unless otherwise stated; ConsensusDocs 200
# likewise. The JCT rows are the one qualified case - JCT SBC 2016 clause 1.5.2
# excludes public holidays from a reckoned period, which is
# calendar-minus-holidays rather than working days - but those rows are
# practical reminder windows rather than a statutory bar (the delay notice is
# due "forthwith", with no day count at all), so "calendar" remains the honest
# label for what they are.
#
# A standard whose periods mix working and calendar days - the Canadian CCDC
# family counts claims and EOT in working days, others in calendar - is
# expressed by overriding the relevant entries after the comprehension.
# --------------------------------------------------------------------------- #

NOTICE_PERIOD_BASES: dict[str, dict[str, str]] = {
    standard: dict.fromkeys(periods, CALENDAR) for standard, periods in NOTICE_PERIODS.items()
}

# CCDC counts claims and EOT in working days (GC 6.5, GC 6.6), while the
# quotation, assessment and response windows are calendar days (GC 6.1, 6.3).
# The comprehension above defaulted every entry to CALENDAR; override the two
# working-day periods here.
NOTICE_PERIOD_BASES[STANDARD_CCDC][NOTICE_CLAIM] = BUSINESS
NOTICE_PERIOD_BASES[STANDARD_CCDC][NOTICE_EOT] = BUSINESS

#: Basis for each fallback period, in the same shape as :data:`GENERIC_PERIODS`.
GENERIC_PERIOD_BASES: dict[str, str] = dict.fromkeys(GENERIC_PERIODS, CALENDAR)


def period_bases_are_complete() -> list[str]:
    """Names of every configured period that has a day count but no basis.

    An empty list means every period in :data:`NOTICE_PERIODS` and
    :data:`GENERIC_PERIODS` states the basis it is counted on. A non-empty one
    names periods that would fall back to calendar days without anyone having
    said so, which is how a working-day standard comes to show a deadline
    several days early. Exposed as a function rather than asserted at import so
    the failure surfaces as a named test rather than a crash on startup.
    """
    missing: list[str] = []
    for standard, periods in NOTICE_PERIODS.items():
        bases = NOTICE_PERIOD_BASES.get(standard, {})
        missing.extend(f"{standard}.{notice_type}" for notice_type in periods if notice_type not in bases)
    missing.extend(
        f"GENERIC.{notice_type}" for notice_type in GENERIC_PERIODS if notice_type not in GENERIC_PERIOD_BASES
    )
    return sorted(missing)


#: Default governing-clause reference per standard and notice type, used to label
#: a clock when the source record did not record its own clause reference. These
#: mirror the clause book the change-request clarifier surfaces, so a register row
#: names the same provision the clarifier advises on (for example FIDIC 20.1 /
#: NEC 61.3).
DEFAULT_CLAUSE_REFS: dict[str, dict[str, str]] = {
    STANDARD_FIDIC: {
        NOTICE_CLAIM: "20.1",
        NOTICE_EOT: "20.1",
        NOTICE_QUOTATION: "20.1",
        NOTICE_ASSESSMENT: "3.5",
        NOTICE_RESPONSE: "3.5",
    },
    STANDARD_NEC: {
        NOTICE_CLAIM: "61.3",
        NOTICE_EOT: "61.3",
        NOTICE_QUOTATION: "62.3",
        NOTICE_ASSESSMENT: "62.3",
        NOTICE_RESPONSE: "13.3",
    },
    STANDARD_JCT: {
        NOTICE_CLAIM: "2.27",
        NOTICE_EOT: "2.27",
        NOTICE_QUOTATION: "5.3",
        NOTICE_ASSESSMENT: "2.28",
        NOTICE_RESPONSE: "2.28",
    },
    STANDARD_AIA: {
        NOTICE_CLAIM: "15.1.3",
        NOTICE_EOT: "15.1.6",
        NOTICE_QUOTATION: "7.3",
        NOTICE_ASSESSMENT: "15.2",
        NOTICE_RESPONSE: "15.2",
    },
    STANDARD_CONSENSUSDOCS: {
        NOTICE_CLAIM: "6.3",
        NOTICE_EOT: "6.3",
        NOTICE_QUOTATION: "6",
        NOTICE_ASSESSMENT: "6",
        NOTICE_RESPONSE: "6",
    },
    STANDARD_CCDC: {
        NOTICE_CLAIM: "GC 6.6",
        NOTICE_EOT: "GC 6.5",
        NOTICE_QUOTATION: "GC 6.1",
        NOTICE_ASSESSMENT: "GC 6.3",
        NOTICE_RESPONSE: "GC 6.3",
    },
}


def normalize_standard(raw: str | None) -> str:
    """Map a free-text contract-standard hint onto a canonical standard token.

    Recognises the family name anywhere in the string case-insensitively, so
    ``"NEC4 ECC Option A"`` / ``"nec3"`` both map to :data:`STANDARD_NEC` and
    ``"fidic_red_1999"`` maps to :data:`STANDARD_FIDIC`. An empty, missing or
    unrecognised value yields :data:`STANDARD_UNKNOWN`.
    """
    if not raw:
        return STANDARD_UNKNOWN
    text = raw.strip().lower()
    if not text:
        return STANDARD_UNKNOWN
    if "fidic" in text:
        return STANDARD_FIDIC
    if "nec" in text:
        return STANDARD_NEC
    if "jct" in text:
        return STANDARD_JCT
    if "aia" in text:
        return STANDARD_AIA
    if "consensus" in text:
        return STANDARD_CONSENSUSDOCS
    if "ccdc" in text:
        return STANDARD_CCDC
    return STANDARD_UNKNOWN


def period_for(standard: str, notice_type: str) -> int | None:
    """Notice period in days for a standard + notice type, or ``None``.

    Uses the standard's own table when present, falling back to the
    standard-neutral :data:`GENERIC_PERIODS` for an unknown standard or a notice
    type the standard does not list, so a clock can still be derived from an
    event date.

    A standard in :data:`NOTICE_PERIODS_HELD` is the one case that refuses
    instead of falling back: it is recognised, so the register names the
    contract governing the clock, and a generic window shown beside that name
    would read as that contract's window. ``None`` makes the clock report an
    unknown deadline rather than count down an invented one.
    """
    if standard in NOTICE_PERIODS_HELD:
        return None
    table = NOTICE_PERIODS.get(standard)
    if table is not None:
        days = table.get(notice_type)
        if days is not None:
            return days
    return GENERIC_PERIODS.get(notice_type)


def basis_for(standard: str, notice_type: str) -> str:
    """Day basis for a standard + notice type; ``"calendar"`` unless stated.

    Resolves in the same order as :func:`period_for` - the standard's own table
    first, then the standard-neutral fallback - so the day count and the basis
    it is counted on always come from the same row. An unknown standard or
    notice type yields ``"calendar"``, which is what every currently configured
    period uses, so a missing entry changes no existing deadline.
    """
    table = NOTICE_PERIOD_BASES.get(standard)
    if table is not None:
        basis = table.get(notice_type)
        if basis is not None:
            return basis
    return GENERIC_PERIOD_BASES.get(notice_type, CALENDAR)


def clause_ref_for(standard: str, notice_type: str, explicit: str = "") -> str:
    """Governing-clause label for a clock.

    An explicit clause reference recorded on the source record always wins;
    otherwise the standard's default provision for this notice type is used
    (for example ``"NEC 61.3"``). Returns an empty string when neither is known.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    ref = DEFAULT_CLAUSE_REFS.get(standard, {}).get(notice_type, "")
    if ref:
        return f"{standard} {ref}"
    return ""


def parse_date(value: str | None) -> datetime | None:
    """Parse a stored date / datetime string to aware UTC, or ``None``.

    Accepts a plain date (``2026-07-01``) or a datetime with offset or trailing
    ``Z`` (``2026-07-01T09:00:00Z``). A naive datetime is assumed to be UTC.
    Never raises - a blank or malformed value yields ``None``.
    """
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(text[:10])  # date-only fallback
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_days(
    moment: datetime,
    days: int,
    basis: str = CALENDAR,
    holidays: tuple[date, ...] = (),
) -> datetime:
    """Return *moment* shifted by *days*, counted on *basis*.

    The counting is delegated to :func:`app.core.day_basis.add_days` rather
    than repeated here, so a working-day notice period and a working-day
    statutory payment period are counted by one implementation.

    That helper works in ``date`` while a clock works in an aware UTC
    ``datetime``, so the time of day is carried across unchanged: a five
    working-day notice raised at 16:00 expires at 16:00 exactly as a calendar
    one does, and :func:`classify_status` keeps comparing at the resolution it
    always did. ``parse_date`` has normalised every moment to UTC, which has no
    daylight-saving transition, so recombining the shifted date with the
    original time is exact rather than approximate.
    """
    shifted = _add_days_on_basis(moment.date(), days, basis, holidays)
    return datetime.combine(shifted, moment.timetz())


def derive_deadline(
    *,
    trigger_date: datetime | None,
    period_days: int | None,
    explicit_due: datetime | None,
    day_basis: str = CALENDAR,
    holidays: tuple[date, ...] = (),
) -> datetime | None:
    """Resolve the effective deadline for a clock.

    An explicit contractual due date recorded on the record always wins. Failing
    that, the deadline is the trigger (event) date plus the notice period,
    counted on ``day_basis``. When neither an explicit due date nor a
    (trigger + period) pair is available the deadline is ``None`` - the clock
    cannot be counted down.
    """
    if explicit_due is not None:
        return explicit_due
    if trigger_date is not None and period_days is not None:
        return add_days(trigger_date, period_days, day_basis, holidays)
    return None


def classify_status(
    *,
    deadline: datetime | None,
    now: datetime,
    satisfied_at: datetime | None,
    due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
) -> tuple[str, bool]:
    """Classify a clock and report whether the action was served late.

    Returns ``(status, served_late)``. With no deadline the status is
    :data:`STATUS_UNKNOWN`. When the action is recorded (``satisfied_at`` set)
    the clock is stopped: :data:`STATUS_MET` if it was on or before the deadline,
    else :data:`STATUS_OVERDUE` with ``served_late`` true. Otherwise the clock is
    :data:`STATUS_OVERDUE` past the deadline, :data:`STATUS_DUE_SOON` within the
    due-soon window, and :data:`STATUS_UPCOMING` beyond it.
    """
    if deadline is None:
        return STATUS_UNKNOWN, False
    if satisfied_at is not None:
        if satisfied_at > deadline:
            return STATUS_OVERDUE, True
        return STATUS_MET, False
    if now > deadline:
        return STATUS_OVERDUE, False
    if (deadline - now) <= timedelta(days=due_soon_days):
        return STATUS_DUE_SOON, False
    return STATUS_UPCOMING, False


@dataclass(frozen=True)
class ClockInput:
    """One derivable notice / response clock, assembled by the service layer.

    ``standard`` is already normalized (:func:`normalize_standard`). Exactly one
    of ``explicit_due`` (a due date the record carries) or the
    ``trigger_date`` + ``period_days`` pair needs to be present for a deadline to
    exist. ``satisfied_at`` is when the required action was recorded (the notice
    served, the quotation returned, the response received), or ``None``.
    ``requires_notice`` marks a clock whose entitlement depends on a served
    notice being on file; ``proof_on_file`` is whether such a document was found.

    ``day_basis`` says whether ``period_days`` is counted in calendar or working
    days, and ``holidays`` is the deployment's own calendar of non-working days
    beyond Saturday and Sunday. Both default to what every configured standard
    already does - calendar days, no holiday list - so a caller that sets
    neither gets exactly the deadline it got before they existed.
    """

    source_kind: str
    source_id: str
    source_ref: str
    title: str
    standard: str
    notice_type: str
    clause_ref: str
    trigger_date: datetime | None
    explicit_due: datetime | None
    period_days: int | None
    satisfied_at: datetime | None
    requires_notice: bool
    proof_on_file: bool
    is_open: bool
    # Defaulted and last so every existing construction of this input, keyword
    # or positional, keeps working and keeps its calendar-day answer.
    day_basis: str = CALENDAR
    holidays: tuple[date, ...] = ()


@dataclass(frozen=True)
class NoticeClock:
    """A single derived clock in the project notice register."""

    source_kind: str
    source_id: str
    source_ref: str
    title: str
    standard: str
    notice_type: str
    clause_ref: str
    trigger_date: datetime | None
    period_days: int | None
    deadline: datetime | None
    days_remaining: float | None
    status: str
    requires_notice: bool
    proof_on_file: bool
    satisfied_at: datetime | None
    served_late: bool
    entitlement_at_risk: bool
    is_open: bool
    #: Which basis ``period_days`` was counted on, so a reader can tell a
    #: ten-working-day deadline from a ten-calendar-day one instead of being
    #: shown a plausible date with nothing to contradict it.
    day_basis: str = CALENDAR


@dataclass(frozen=True)
class RegisterSummary:
    """Roll-up over a set of clocks in the register."""

    total: int
    open_total: int
    counts_by_status: dict[str, int]
    at_risk: int
    proof_missing: int
    overdue: int
    due_soon: int


def entitlement_at_risk(
    *,
    requires_notice: bool,
    status: str,
    served_late: bool,
    proof_on_file: bool,
    satisfied_at: datetime | None,
) -> bool:
    """Whether a clock signals a live risk of losing the entitlement.

    Only clocks that require a served notice can be at risk. Such a clock is at
    risk when the notice was served late, when the window lapsed with no action
    recorded, or when no proof-of-notice document is on file at all (a required
    notice proceeding without a document is the classic loss mode, so it is
    flagged even while the deadline is still upcoming or nominally met).
    """
    if not requires_notice:
        return False
    if served_late:
        return True
    if status == STATUS_OVERDUE and satisfied_at is None:
        return True
    return not proof_on_file


def build_clock(
    inp: ClockInput,
    *,
    now: datetime,
    due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
) -> NoticeClock:
    """Derive a :class:`NoticeClock` from one :class:`ClockInput`.

    Resolves the deadline, classifies the status against *now*, computes the
    signed days remaining (negative once overdue; ``None`` once the clock is
    stopped or undatable) and evaluates the entitlement-at-risk flag. Pure and
    deterministic: identical input and *now* always yield an identical clock.
    """
    deadline = derive_deadline(
        trigger_date=inp.trigger_date,
        period_days=inp.period_days,
        explicit_due=inp.explicit_due,
        day_basis=inp.day_basis,
        holidays=inp.holidays,
    )
    status, served_late = classify_status(
        deadline=deadline,
        now=now,
        satisfied_at=inp.satisfied_at,
        due_soon_days=due_soon_days,
    )
    days_remaining: float | None = None
    if deadline is not None and inp.satisfied_at is None:
        days_remaining = round((deadline - now).total_seconds() / 86400.0, 2)
    at_risk = entitlement_at_risk(
        requires_notice=inp.requires_notice,
        status=status,
        served_late=served_late,
        proof_on_file=inp.proof_on_file,
        satisfied_at=inp.satisfied_at,
    )
    return NoticeClock(
        source_kind=inp.source_kind,
        source_id=inp.source_id,
        source_ref=inp.source_ref,
        title=inp.title,
        standard=inp.standard,
        notice_type=inp.notice_type,
        clause_ref=inp.clause_ref,
        trigger_date=inp.trigger_date,
        period_days=inp.period_days,
        deadline=deadline,
        days_remaining=days_remaining,
        status=status,
        requires_notice=inp.requires_notice,
        proof_on_file=inp.proof_on_file,
        satisfied_at=inp.satisfied_at,
        served_late=served_late,
        entitlement_at_risk=at_risk,
        is_open=inp.is_open,
        day_basis=inp.day_basis,
    )


#: Sort priority per status: the clocks that need attention first float to the
#: top (overdue, then due-soon, then upcoming), stopped / undatable clocks last.
_STATUS_ORDER: dict[str, int] = {
    STATUS_OVERDUE: 0,
    STATUS_DUE_SOON: 1,
    STATUS_UPCOMING: 2,
    STATUS_UNKNOWN: 3,
    STATUS_MET: 4,
}


def sort_register(clocks: list[NoticeClock]) -> list[NoticeClock]:
    """Order clocks worst-first: by status urgency, at-risk first, soonest due.

    Ties break on the soonest deadline (smallest days remaining), then the
    source reference and id for a fully deterministic order.
    """

    def key(c: NoticeClock) -> tuple[int, bool, float, str, str]:
        remaining = c.days_remaining if c.days_remaining is not None else float("inf")
        return (
            _STATUS_ORDER.get(c.status, 5),
            not c.entitlement_at_risk,
            remaining,
            c.source_ref,
            c.source_id,
        )

    return sorted(clocks, key=key)


def summarize_register(clocks: list[NoticeClock]) -> RegisterSummary:
    """Roll a set of clocks into counts by status plus at-risk / proof gaps."""
    counts: dict[str, int] = {
        STATUS_OVERDUE: 0,
        STATUS_DUE_SOON: 0,
        STATUS_UPCOMING: 0,
        STATUS_UNKNOWN: 0,
        STATUS_MET: 0,
    }
    at_risk = 0
    proof_missing = 0
    open_total = 0
    for c in clocks:
        counts[c.status] = counts.get(c.status, 0) + 1
        if c.entitlement_at_risk:
            at_risk += 1
        if c.requires_notice and not c.proof_on_file:
            proof_missing += 1
        if c.is_open:
            open_total += 1
    return RegisterSummary(
        total=len(clocks),
        open_total=open_total,
        counts_by_status=counts,
        at_risk=at_risk,
        proof_missing=proof_missing,
        overdue=counts[STATUS_OVERDUE],
        due_soon=counts[STATUS_DUE_SOON],
    )


def build_register(
    inputs: list[ClockInput],
    *,
    now: datetime,
    due_soon_days: int = DEFAULT_DUE_SOON_DAYS,
) -> tuple[list[NoticeClock], RegisterSummary]:
    """Build every clock, order them worst-first, and summarise the set."""
    clocks = [build_clock(inp, now=now, due_soon_days=due_soon_days) for inp in inputs]
    ordered = sort_register(clocks)
    return ordered, summarize_register(ordered)


__all__ = [
    "STANDARD_FIDIC",
    "STANDARD_NEC",
    "STANDARD_JCT",
    "STANDARD_AIA",
    "STANDARD_CONSENSUSDOCS",
    "STANDARD_CCDC",
    "STANDARD_UNKNOWN",
    "NOTICE_CLAIM",
    "NOTICE_EOT",
    "NOTICE_QUOTATION",
    "NOTICE_ASSESSMENT",
    "NOTICE_RESPONSE",
    "STATUS_MET",
    "STATUS_UPCOMING",
    "STATUS_DUE_SOON",
    "STATUS_OVERDUE",
    "STATUS_UNKNOWN",
    "DEFAULT_DUE_SOON_DAYS",
    "NOTICE_PERIODS",
    "NOTICE_PERIODS_HELD",
    "NOTICE_PERIOD_BASES",
    "GENERIC_PERIODS",
    "GENERIC_PERIOD_BASES",
    "CALENDAR",
    "BUSINESS",
    "DEFAULT_CLAUSE_REFS",
    "ClockInput",
    "NoticeClock",
    "RegisterSummary",
    "normalize_standard",
    "period_for",
    "basis_for",
    "period_bases_are_complete",
    "clause_ref_for",
    "parse_date",
    "add_days",
    "derive_deadline",
    "classify_status",
    "entitlement_at_risk",
    "build_clock",
    "sort_register",
    "summarize_register",
    "build_register",
]
