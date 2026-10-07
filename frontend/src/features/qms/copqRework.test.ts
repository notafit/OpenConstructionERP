// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The COPQ card printed the rework figure and nothing else, so "Rework est.
 * 0 EUR" was the same screen for a project with no open snags, a project
 * whose snags nobody has priced, and a euro project whose snags are all
 * priced in dollars. The server tells those apart; what is pinned here is
 * that the card says which one it is, and never stays silent on a figure
 * that left something out.
 *
 * Run:  npx vitest run src/features/qms/copqRework.test.ts
 */

import { describe, it, expect, afterAll } from 'vitest';
import i18next from 'i18next';
import { reworkNotes } from './copqRework';
import type { COPQReport } from './api';

void i18next.init({ lng: 'en', resources: {}, initAsync: false });
const originalLanguage = i18next.language;
afterAll(() => {
  void i18next.changeLanguage(originalLanguage);
});

function report(over: Partial<COPQReport> = {}): COPQReport {
  return {
    project_id: 'proj-1',
    ncr_cost_total: '0',
    open_punch_count: 0,
    rework_cost_estimate: '0',
    copq_total: '0',
    currency: 'EUR',
    rework_cost_basis: 'recorded',
    rework_priced_count: 0,
    rework_unpriced_count: 0,
    rework_unreadable_count: 0,
    rework_by_currency: {},
    rework_currency_mixed: false,
    ...over,
  };
}

const keys = (r: COPQReport) => reworkNotes(r).map((n) => n.key);

describe('what the COPQ card says under the rework figure', () => {
  it('says nothing when every open item is priced in this currency', () => {
    expect(
      reworkNotes(report({ rework_priced_count: 4, rework_by_currency: { EUR: '4000' } })),
    ).toEqual([]);
  });

  it('separates an empty figure that means nobody priced anything', () => {
    const notes = reworkNotes(report({ rework_cost_basis: 'none_priced', rework_unpriced_count: 7 }));
    expect(notes).toHaveLength(1);
    expect(notes[0]?.key).toBe('qms.rework_note_none_priced');
    expect(notes[0]?.params).toEqual({ total: 7 });
  });

  it('separates an empty figure that means nothing is priced in this currency', () => {
    const notes = reworkNotes(
      report({
        rework_cost_basis: 'currency_mismatch',
        rework_priced_count: 2,
        rework_unpriced_count: 1,
        rework_by_currency: { USD: '1200.5' },
      }),
    );
    expect(notes[0]?.key).toBe('qms.rework_note_currency_mismatch');
    expect(notes[0]?.params).toEqual({ priced: 2, total: 3, currency: 'EUR' });
    // And it names the money it would not blend.
    expect(notes[1]?.key).toBe('qms.rework_other_currencies');
    expect(String(notes[1]?.params?.amounts)).toMatch(/1,200\.50/);
    expect(String(notes[1]?.params?.amounts)).toMatch(/\$/);
  });

  it('separates an empty figure that means there is nothing to measure', () => {
    expect(keys(report({ rework_cost_basis: 'no_open_punch_items' }))).toEqual([
      'qms.rework_note_no_items',
    ]);
  });

  it('says when the figure came from an assumption rather than from records', () => {
    expect(keys(report({ rework_cost_basis: 'override' }))).toEqual(['qms.rework_note_override']);
  });

  it('says when the currency or the punch list itself is missing', () => {
    expect(keys(report({ rework_cost_basis: 'currency_unknown', currency: '' }))).toEqual([
      'qms.rework_note_currency_unknown',
    ]);
    expect(keys(report({ rework_cost_basis: 'source_unavailable' }))).toEqual([
      'qms.rework_note_unavailable',
    ]);
  });

  it('counts the unpriced items behind a figure that did add something up', () => {
    const notes = reworkNotes(
      report({
        rework_priced_count: 3,
        rework_unpriced_count: 5,
        rework_by_currency: { EUR: '900' },
      }),
    );
    expect(notes[0]?.key).toBe('qms.rework_note_recorded');
    expect(notes[0]?.params).toEqual({ priced: 3, total: 8 });
  });

  it('names the other currencies even when this one was counted', () => {
    const notes = reworkNotes(
      report({
        rework_priced_count: 4,
        rework_currency_mixed: true,
        rework_by_currency: { EUR: '900', USD: '1200', GBP: '300' },
      }),
    );
    expect(notes.map((n) => n.key)).toEqual(['qms.rework_other_currencies']);
    const amounts = String(notes[0]?.params?.amounts);
    expect(amounts).toContain('$');
    expect(amounts).toContain('£');
    expect(amounts).not.toContain('€');
  });

  it('joins those currencies the way the reader’s language joins a list', async () => {
    // Asserted against a non-Latin language, because an English assertion
    // passes just as well against the hardcoded ", " this replaced.
    const mixed = report({
      rework_priced_count: 2,
      rework_by_currency: { EUR: '900', USD: '1200', GBP: '300' },
    });

    await i18next.changeLanguage('en');
    const english = String(reworkNotes(mixed)[0]?.params?.amounts);

    await i18next.changeLanguage('zh');
    const chinese = String(reworkNotes(mixed)[0]?.params?.amounts);

    await i18next.changeLanguage('en');
    expect(chinese).not.toBe(english);
    expect(english).toContain(', ');
    expect(chinese).not.toContain(', ');
  });

  it('reports amounts it could not read, which are neither priced nor unpriced', () => {
    const notes = reworkNotes(
      report({ rework_priced_count: 1, rework_unreadable_count: 2, rework_by_currency: { EUR: '10' } }),
    );
    expect(notes.map((n) => n.key)).toEqual(['qms.rework_note_recorded', 'qms.rework_unreadable']);
    expect(notes[1]?.params).toEqual({ items: 2 });
  });

  it('survives a server that does not send the provenance fields at all', () => {
    const bare: COPQReport = {
      project_id: 'proj-1',
      ncr_cost_total: '0',
      open_punch_count: 0,
      rework_cost_estimate: '0',
      copq_total: '0',
      currency: 'EUR',
    };
    expect(reworkNotes(bare)).toEqual([]);
  });
});
