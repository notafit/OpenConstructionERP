// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What the funding client puts on the wire, and what it refuses to change
// on the way.
//
// Two invariants are worth a test each because nothing else in the stack
// would notice them breaking. Money travels as an exact decimal string, and
// a single `Number()` anywhere on the path turns a grant of 1 234 567.89
// into an amount an auditor can query. And "today" is the reader's calendar
// day, not the server's and not UTC, because every deadline in this module
// is judged against it and a date that is a day out marks a report late that
// is not.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient } from '@tanstack/react-query';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(() => Promise.resolve({})),
  apiPost: vi.fn(() => Promise.resolve({})),
  apiPatch: vi.fn(() => Promise.resolve({})),
  apiDelete: vi.fn(() => Promise.resolve(undefined)),
}));

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';

import {
  confirmReceipt,
  createApplication,
  createCostAllocation,
  createProgramme,
  declaresAmount,
  declaresPercent,
  fundingKeys,
  listProgrammes,
  listProjectObligations,
  localToday,
  percentDecimals,
  percentLabel,
  percentText,
  recordAward,
  toMoney,
  updateApplication,
} from './api';

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
});

/** The body of the single POST the call under test made. */
function postedBody(): Record<string, unknown> {
  expect(apiPost).toHaveBeenCalledTimes(1);
  return vi.mocked(apiPost).mock.calls[0]![1] as Record<string, unknown>;
}

/** The URL of the single GET the call under test made. */
function requestedUrl(): string {
  expect(apiGet).toHaveBeenCalledTimes(1);
  return vi.mocked(apiGet).mock.calls[0]![0] as string;
}

describe('money never stops being a string', () => {
  it('sends an awarded amount exactly as it was given', async () => {
    await recordAward('app-1', { approved: true, approved_amount: '1234567.89' });

    const body = postedBody();
    expect(body.approved_amount).toBe('1234567.89');
    expect(typeof body.approved_amount).toBe('string');
  });

  it('keeps the trailing zeroes a decimal string carries', async () => {
    // 350000.10 and 350000.1 are the same number and different amounts. The
    // second is what a float round trip leaves behind.
    await confirmReceipt('draw-1', { received_on: '2027-01-15', amount_received: '350000.10' });

    expect(postedBody().amount_received).toBe('350000.10');
  });

  it('sends the eligible base and the requested amount as strings', async () => {
    await createApplication({
      project_id: 'p1',
      programme_id: 'prog-1',
      code: 'A-1',
      title: 'Envelope',
      eligible_cost_base: '1000000.00',
      requested_amount: '400000.00',
    });

    const body = postedBody();
    expect(body.eligible_cost_base).toBe('1000000.00');
    expect(body.requested_amount).toBe('400000.00');
  });

  it('sends an allocation and the part of it the programme will count as strings', async () => {
    await createCostAllocation('app-1', {
      cost_group: '300',
      amount: '250000.55',
      eligible_amount: '180000.45',
      eligibility: 'partially_eligible',
    });

    const body = postedBody();
    expect(body.amount).toBe('250000.55');
    expect(body.eligible_amount).toBe('180000.45');
  });

  it('does not coerce an amount on the way through a patch', async () => {
    await updateApplication('app-1', { own_share_amount: '200000.01' });

    expect(apiPatch).toHaveBeenCalledTimes(1);
    const body = vi.mocked(apiPatch).mock.calls[0]![1] as Record<string, unknown>;
    expect(body.own_share_amount).toBe('200000.01');
  });
});

describe('toMoney is for arithmetic only', () => {
  it('reads a plain decimal string', () => {
    expect(toMoney('1234567.89')).toBe(1234567.89);
    expect(toMoney('0.01')).toBe(0.01);
    expect(toMoney(42)).toBe(42);
  });

  it.each([null, undefined, '', 'n/a', 'NaN', '  '])('degrades %p to zero rather than to NaN', (value) => {
    // A NaN reaching a chart draws nothing and says nothing about why.
    const result = toMoney(value as string | number | null | undefined);
    expect(result).toBe(0);
    expect(Number.isFinite(result)).toBe(true);
  });

  it('degrades an infinity to zero', () => {
    expect(toMoney('Infinity')).toBe(0);
    expect(toMoney(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it('is never the value that goes back to the screen', () => {
    // The point of the helper's contract, stated as a test: the string holds
    // a cent that the number has already lost.
    const exact = '9007199254740993.01';
    expect(String(toMoney(exact))).not.toBe(exact);
  });
});

describe('a percentage on the screen', () => {
  it('drops the trailing zeros the column stores', () => {
    // The rate column holds three decimals, so twenty arrives as "20.000".
    // Printed as it stands, a German or Spanish reader parses the dot as a
    // thousands separator and reads a rate of twenty thousand percent.
    expect(percentLabel('20.000')).toBe('20');
    expect(percentLabel('60.000')).toBe('60');
    expect(percentLabel('0.000')).toBe('0');
  });

  it('keeps every digit that carries meaning', () => {
    expect(percentLabel('12.500')).toBe('12.5');
    expect(percentLabel('66.667')).toBe('66.667');
    expect(percentLabel('0.001')).toBe('0.001');
  });

  it('leaves a whole number alone', () => {
    expect(percentLabel('20')).toBe('20');
    expect(percentLabel(45)).toBe('45');
  });

  it.each([null, undefined, '', 'n/a', 'NaN', '1e3', '2,5'])(
    'says nothing at all about %p',
    (value) => {
      expect(percentLabel(value as string | number | null | undefined)).toBe('');
    },
  );

  it('never rounds, because the number it is given is already the answer', () => {
    // A float round trip turns this into 0.30000000000000004 and the screen
    // then claims a precision the authority never granted.
    expect(percentLabel('0.30')).toBe('0.3');
    expect(percentLabel('33.333')).toBe('33.333');
  });

  it('counts the decimals that survived, which is what the formatter needs', () => {
    // `percentLabel` decides which digits carry meaning; this reads the answer
    // off it so the two can never disagree about how many to print.
    expect(percentDecimals('20.000')).toBe(0);
    expect(percentDecimals('12.500')).toBe(1);
    expect(percentDecimals('66.667')).toBe(3);
    expect(percentDecimals('45')).toBe(0);
    expect(percentDecimals('n/a')).toBe(0);
  });
});

describe('a percentage written for the reader', () => {
  // `percentText` hands the figure to `fmtPercent`, which writes it in the
  // reader's own digits and puts the percent sign where their language puts
  // it. Under test the locale is English, so the assertions below are the
  // English rendering; what matters is that the sign is no longer something
  // the call site glued on, because that glue is what left Western digits
  // beside the Arabic-Indic ones the amounts on the same page were using.
  it('keeps exactly the digits the stored value carries', () => {
    expect(percentText('20.000')).toBe('20%');
    expect(percentText('12.500')).toBe('12.5%');
    expect(percentText('66.667')).toBe('66.667%');
  });

  it('writes a declared zero rather than nothing', () => {
    expect(percentText('0.000')).toBe('0%');
    expect(percentText(0)).toBe('0%');
  });

  it.each([null, undefined, '', 'n/a', '2,5'])('says nothing at all about %p', (value) => {
    // Empty, not "0%": a rate of nothing and no rate at all are different
    // answers, and the caller is the one that knows which to show.
    expect(percentText(value as string | number | null | undefined)).toBe('');
  });

  it('carries the sign itself, so no caller has to append one', () => {
    expect(percentText('40')).toContain('%');
  });
});

describe('whether a percentage was declared at all', () => {
  it('reads the stored zero as nothing declared', () => {
    // Zero is the column default. A programme that never named a ceiling and
    // one that named a ceiling of nothing must both stay silent.
    expect(declaresPercent('0.000')).toBe(false);
    expect(declaresPercent('0')).toBe(false);
    expect(declaresPercent('')).toBe(false);
    expect(declaresPercent(undefined)).toBe(false);
  });

  it('reads any real share as declared', () => {
    expect(declaresPercent('0.001')).toBe(true);
    expect(declaresPercent('20.000')).toBe(true);
    expect(declaresPercent(100)).toBe(true);
  });

  it('does not treat junk as a declaration', () => {
    expect(declaresPercent('n/a')).toBe(false);
    expect(declaresPercent('Infinity')).toBe(false);
  });
});

describe('whether an amount was set at all', () => {
  it('reads the stored zero as nothing set', () => {
    // The receipt form offers the approved amount and falls back to the
    // requested one. Money is a string, so the unset "0.00" is truthy and a
    // plain `approved || requested` hands the reader a receipt for nothing
    // against a draw they asked six figures for.
    expect(declaresAmount('0.00')).toBe(false);
    expect(declaresAmount('0')).toBe(false);
    expect(declaresAmount('')).toBe(false);
    expect(declaresAmount(null)).toBe(false);
    expect(declaresAmount(undefined)).toBe(false);
  });

  it('reads any real money as set', () => {
    expect(declaresAmount('0.01')).toBe(true);
    expect(declaresAmount('60000.00')).toBe(true);
    expect(declaresAmount(1)).toBe(true);
  });

  it('does not treat junk or an infinity as money', () => {
    expect(declaresAmount('n/a')).toBe(false);
    expect(declaresAmount('Infinity')).toBe(false);
    expect(declaresAmount(Number.POSITIVE_INFINITY)).toBe(false);
  });

  it('chooses the requested amount when nothing was approved yet', () => {
    // The rule the receipt form applies, stated as the test that would have
    // caught it: a draw in draft has approved "0.00" and requested "60000.00".
    const approved = '0.00';
    const requested = '60000.00';
    expect(declaresAmount(approved) ? approved : requested).toBe('60000.00');
  });
});

describe('a new catalogue entry', () => {
  it('sends the rates as strings and the day counts as numbers', async () => {
    // The API reads the percentages as decimals and the day counts as
    // integers. A day count arriving as "180" is a validation error the
    // person filling the form cannot act on.
    await createProgramme({
      code: 'KFW-261',
      funding_rate_percent: '20',
      aid_intensity_cap_percent: '60',
      own_share_percent: '10',
      proof_of_use_due_days: 180,
      disbursement_spend_days: 90,
      retention_years: 10,
    });

    const body = postedBody();
    expect(body.funding_rate_percent).toBe('20');
    expect(typeof body.proof_of_use_due_days).toBe('number');
    expect(body.proof_of_use_due_days).toBe(180);
    expect(body.retention_years).toBe(10);
  });
});

describe('today is the reader’s calendar day', () => {
  /** An independent formatter for the local day; en-CA renders YYYY-MM-DD. */
  const localDay = (at: Date) =>
    new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(at);

  it('matches the local day at every hour of a day, wherever the machine is', () => {
    // Stepping through 24 hours means that in any timezone offset from UTC at
    // least one of these instants falls on a different UTC day, which is the
    // case a toISOString-based implementation gets wrong. In UTC none of them
    // do, and passing there is the correct answer rather than a weaker test.
    vi.useFakeTimers();
    for (let hour = 0; hour < 24; hour += 1) {
      const instant = new Date(Date.UTC(2026, 2, 15, hour, 30, 0));
      vi.setSystemTime(instant);
      expect(localToday()).toBe(localDay(instant));
    }
  });

  it('is always zero padded to ten characters', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 0, 5, 12, 0, 0));
    expect(localToday()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(localToday()).toBe('2026-01-05');
  });

  it('sends a date with every deadline question rather than letting the server pick', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(2026, 5, 1, 9, 0, 0));

    await listProjectObligations('p1');

    const url = requestedUrl();
    expect(url).toContain('today=2026-06-01');
    expect(url).toContain('project_id=p1');
  });
});

describe('query filters', () => {
  it('leaves an unset filter out of the query instead of sending it empty', async () => {
    // `country=` is not "no country", it is a request for programmes whose
    // country is the empty string, and the catalogue would come back empty.
    await listProgrammes({ country: '', status: 'open', search: undefined });

    const url = requestedUrl();
    expect(url).toContain('status=open');
    expect(url).not.toContain('country=');
    expect(url).not.toContain('search=');
  });

  it('asks for the whole catalogue when nothing is filtered', async () => {
    await listProgrammes({});

    expect(requestedUrl()).toBe('/v1/funding/programmes/');
  });
});

describe('cache keys', () => {
  it('keeps one project’s funding out of another’s cache', () => {
    expect(fundingKeys.applications('p1')).not.toEqual(fundingKeys.applications('p2'));
    expect(fundingKeys.obligations('p1')).not.toEqual(fundingKeys.obligations('p2'));
    expect(fundingKeys.projectSummary('p1')).not.toEqual(fundingKeys.projectSummary('p2'));
  });

  it('keeps the different questions about one project apart', () => {
    const keys = [
      fundingKeys.applications('p1'),
      fundingKeys.obligations('p1'),
      fundingKeys.projectSummary('p1'),
      fundingKeys.application('p1'),
    ].map((key) => JSON.stringify(key));

    expect(new Set(keys).size).toBe(keys.length);
  });

  it('varies the programme key with the filters, so a filtered list is not served unfiltered', () => {
    expect(fundingKeys.programmes({ country: 'DE' })).not.toEqual(fundingKeys.programmes({ country: 'FR' }));
  });

  it('keeps an application per language, so a language switch fetches findings in the new language', () => {
    expect(fundingKeys.applicationIn('a1', 'de')).not.toEqual(fundingKeys.applicationIn('a1', 'fr'));
  });

  it('lets an invalidation of the application reach every language it was read in', async () => {
    const qc = new QueryClient();
    qc.setQueryData(fundingKeys.applicationIn('a1', 'de'), { id: 'a1' });
    qc.setQueryData(fundingKeys.applicationIn('a1', 'ja'), { id: 'a1' });
    qc.setQueryData(fundingKeys.applicationIn('a2', 'de'), { id: 'a2' });

    await qc.invalidateQueries({ queryKey: fundingKeys.application('a1') });

    const invalidated = (key: readonly unknown[]) => qc.getQueryState(key)?.isInvalidated;
    expect(invalidated(fundingKeys.applicationIn('a1', 'de'))).toBe(true);
    expect(invalidated(fundingKeys.applicationIn('a1', 'ja'))).toBe(true);
    expect(invalidated(fundingKeys.applicationIn('a2', 'de'))).toBe(false);
  });
});
