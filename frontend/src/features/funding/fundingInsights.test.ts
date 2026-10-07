// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The Insights panel reads the rows the page already loaded, so its whole
// risk is in the reading. Three things here are decisions rather than
// plumbing and each is pinned below: a deadline carries no money and must
// not be formatted as an amount, an application whose programme has gone is
// the one somebody needs to see rather than the one to drop, and the gap
// between asked for and granted is floored at zero because a negative
// shortfall is not a thing a funding officer can act on.

import { describe, it, expect } from 'vitest';

import { buildFundingInsights } from './fundingInsights';
import type { FundingApplication, FundingObligation, FundingProgramme } from './api';

/** Renders whatever inline default the caller supplied, as i18next would. */
const t = ((key: string, opts?: { defaultValue?: string }) =>
  opts?.defaultValue ?? key) as unknown as Parameters<typeof buildFundingInsights>[3];

function application(overrides: Partial<FundingApplication> = {}): FundingApplication {
  return {
    id: 'a1',
    project_id: 'p1',
    programme_id: 'prog-1',
    code: 'A-1',
    title: 'Envelope',
    status: 'approved',
    currency: 'EUR',
    eligible_cost_base: '1000000.00',
    requested_amount: '400000.00',
    approved_amount: '350000.00',
    own_share_amount: '200000.00',
    ...overrides,
  } as FundingApplication;
}

function programme(overrides: Partial<FundingProgramme> = {}): FundingProgramme {
  return {
    id: 'prog-1',
    code: 'KFW-261',
    name: 'Efficient building',
    authority_name: 'Federal funding bank',
    instrument: 'grant',
    country: 'DE',
    status: 'open',
    ...overrides,
  } as FundingProgramme;
}

function obligation(overrides: Partial<FundingObligation> = {}): FundingObligation {
  return {
    id: 'o1',
    application_id: 'a1',
    kind: 'final_report',
    title: 'Final proof of use',
    due_on: '2027-06-29',
    source: 'programme_rule',
    status: 'open',
    overdue: false,
    ...overrides,
  } as FundingObligation;
}

const catalogue = new Map<string, FundingProgramme>([['prog-1', programme()]]);

function build(
  applications: FundingApplication[],
  obligations: FundingObligation[] = [],
  programmes: Map<string, FundingProgramme> = catalogue,
) {
  return buildFundingInsights(applications, obligations, programmes, t);
}

/** Row at `index`, asserted to exist so the test reads as a claim about it. */
function at<T>(rows: T[], index = 0): T {
  const row = rows[index];
  expect(row, `no row at index ${index}`).toBeDefined();
  return row as T;
}

function dataset(result: ReturnType<typeof build>, id: string) {
  const found = result.datasets.find((row) => row.id === id);
  expect(found, `no dataset called ${id}`).toBeDefined();
  return found!;
}

describe('the applications dataset', () => {
  it('carries one row per application, named by its reference', () => {
    const result = build([application(), application({ id: 'a2', code: 'A-2' })]);

    const rows = dataset(result, 'funding_applications').rows;
    expect(rows).toHaveLength(2);
    expect(rows.map((row) => row.code)).toEqual(['A-1', 'A-2']);
  });

  it('resolves the programme, its authority and its instrument for grouping', () => {
    const row = at(dataset(build([application()]), 'funding_applications').rows);

    expect(row.programme).toBe('Efficient building');
    expect(row.authority).toBe('Federal funding bank');
    expect(row.instrument).toBe('grant');
  });

  it('falls back to the programme code when the entry has no name', () => {
    const programmes = new Map([['prog-1', programme({ name: '' })]]);

    const row = at(dataset(build([application()], [], programmes), 'funding_applications').rows);

    expect(row.programme).toBe('KFW-261');
  });

  it('shows an application whose programme has gone rather than dropping it', () => {
    // That application is exactly the one somebody needs to look at, and a
    // silently shorter chart is how it stops being looked at.
    const result = build([application()], [], new Map());

    const rows = dataset(result, 'funding_applications').rows;
    expect(rows).toHaveLength(1);
    expect(at(rows).programme).toBe('prog-1');
    expect(at(rows).authority).toBe('');
  });

  it('computes what was asked for and not granted', () => {
    const row = at(dataset(build([application()]), 'funding_applications').rows);

    expect(row.requested).toBe(400000);
    expect(row.approved).toBe(350000);
    expect(row.shortfall).toBe(50000);
  });

  it('floors the shortfall at zero when more was granted than asked for', () => {
    const rows = dataset(
      build([application({ requested_amount: '100000.00', approved_amount: '120000.00' })]),
      'funding_applications',
    ).rows;

    expect(at(rows).shortfall).toBe(0);
  });

  it('reads an undecided application as nothing approved rather than as missing', () => {
    const rows = dataset(
      build([application({ status: 'submitted', approved_amount: '0' })]),
      'funding_applications',
    ).rows;

    expect(at(rows).approved).toBe(0);
    expect(at(rows).shortfall).toBe(400000);
  });

  it('takes its currency from the applications it was given', () => {
    expect(dataset(build([application({ currency: 'PLN' })]), 'funding_applications').currency).toBe('PLN');
  });

  it('formats every money field as currency and nothing else', () => {
    const fields = dataset(build([application()]), 'funding_applications').fields;
    const currencyFields = fields.filter((field) => field.format === 'currency').map((field) => field.key);

    expect(currencyFields.sort()).toEqual(
      ['approved', 'eligible_base', 'own_share', 'requested', 'shortfall'].sort(),
    );
  });
});

describe('the deadlines dataset', () => {
  it('groups deadlines into the month they fall in, sortably', () => {
    const result = build(
      [application()],
      [obligation({ due_on: '2027-06-29' }), obligation({ id: 'o2', due_on: '2027-11-02' })],
    );

    expect(dataset(result, 'funding_obligations').rows.map((row) => row.month)).toEqual(['2027-06', '2027-11']);
  });

  it('drops a deadline with no usable date instead of charting it as a blank month', () => {
    const result = build(
      [application()],
      [obligation({ due_on: '' }), obligation({ id: 'o2', due_on: 'later' }), obligation({ id: 'o3' })],
    );

    expect(dataset(result, 'funding_obligations').rows).toHaveLength(1);
  });

  it('carries no currency, because a deadline is not an amount of money', () => {
    // A currency-formatted count of deadlines reads as euros on the screen
    // and invites somebody to add it to a budget.
    const deadlines = dataset(build([application()], [obligation()]), 'funding_obligations');

    expect(deadlines.currency).toBe('');
    expect(deadlines.fields.some((field) => field.format === 'currency')).toBe(false);
  });

  it('counts each deadline once so the measure is a number of deadlines', () => {
    const result = build([application()], [obligation(), obligation({ id: 'o2', due_on: '2027-06-30' })]);

    const rows = dataset(result, 'funding_obligations').rows;
    expect(rows.every((row) => row.count === 1)).toBe(true);
    expect(rows).toHaveLength(2);
  });

  it('says overdue in place of the status, because that is the thing to act on', () => {
    const result = build(
      [application()],
      [obligation({ overdue: true }), obligation({ id: 'o2', due_on: '2027-07-01', status: 'done' })],
    );

    const rows = dataset(result, 'funding_obligations').rows;
    expect(at(rows).status).toBe('Overdue');
    expect(at(rows, 1).status).toBe('done');
  });
});

describe('what the panel draws on its own', () => {
  it('ships four charts, each pointing at a dataset that exists', () => {
    const result = build([application()], [obligation()]);
    const ids = new Set(result.datasets.map((row) => row.id));

    expect(result.builtins).toHaveLength(4);
    for (const chart of result.builtins) {
      expect(chart.builtin).toBe(true);
      expect(ids.has(chart.datasetId)).toBe(true);
    }
  });

  it('only puts a money measure on the dataset that has money in it', () => {
    const result = build([application()], [obligation()]);

    for (const chart of result.builtins) {
      if (chart.datasetId === 'funding_obligations') {
        expect(chart.agg).toBe('count');
        expect(chart.measure).toBeUndefined();
      }
    }
  });

  it('gives every chart a distinct id and its own colour slot', () => {
    const result = build([application()], [obligation()]);

    expect(new Set(result.builtins.map((chart) => chart.id)).size).toBe(result.builtins.length);
    expect(new Set(result.builtins.map((chart) => chart.color)).size).toBe(result.builtins.length);
  });
});

describe('with nothing loaded', () => {
  it('draws no portfolio rather than inventing one', () => {
    const result = build([], []);

    expect(dataset(result, 'funding_applications').rows).toEqual([]);
    expect(dataset(result, 'funding_obligations').rows).toEqual([]);
    expect(dataset(result, 'funding_applications').currency).toBe('');
    // The charts are still declared, so the panel renders its empty state
    // rather than disappearing between one page load and the next.
    expect(result.builtins).toHaveLength(4);
  });
});
