// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Numbers typed outside the main Quantity / Unit Rate cells.
 *
 * The resource rows, the manual resource dialog and the FX popover each parsed
 * with `parseFloat(s.replace(',', '.'))`. A string replace swaps only the FIRST
 * comma and parseFloat stops at the first character it cannot read, so a
 * grouped amount lost everything after its first separator: `1.234,56` became
 * 1.234 and `1 234,56` became 1. The three hidden tier-rate columns had no
 * parser at all and sent "12,50" to the API, which answered 422. All of them
 * now read typed text with the same grammar as the main cells.
 */
import { describe, it, expect } from 'vitest';

import { parseTypedAmount } from '../BOQGrid';
import { parseInlineNumber } from '../grid/cellRenderers';
import { getColumnDefs, tierRateValueParser } from '../grid/columnDefs';

describe('resource row quantity / rate (parseInlineNumber)', () => {
  it.each([
    ['1.234,56', 1234.56],
    ['1 234,56', 1234.56],
    ['1 234,56', 1234.56],
    ['1,234.56', 1234.56],
    ['12,50', 12.5],
    ['12.50', 12.5],
    ['0,125', 0.125],
    ['  7  ', 7],
  ])('%s -> %d', (typed, expected) => {
    expect(parseInlineNumber(typed)).toBeCloseTo(expected, 10);
  });

  it('still evaluates formulas', () => {
    expect(parseInlineNumber('=2*3')).toBe(6);
    expect(parseInlineNumber('12.5 * 4')).toBe(50);
  });

  it('rejects input that is not wholly a number instead of keeping a prefix', () => {
    expect(parseInlineNumber('10abc')).toBeNaN();
    expect(parseInlineNumber('')).toBeNaN();
  });
});

describe('manual resource dialog (parseTypedAmount)', () => {
  it('reads grouped amounts in full', () => {
    expect(parseTypedAmount('1.234,56', 0)).toBeCloseTo(1234.56, 10);
    expect(parseTypedAmount('1 234,56', 0)).toBeCloseTo(1234.56, 10);
    expect(parseTypedAmount('12,5', 1)).toBeCloseTo(12.5, 10);
  });

  it('keeps the old fallback for empty, zero and unreadable input', () => {
    // Quantity falls back to 1, the rate to 0, exactly as `parseFloat(...) || n` did.
    expect(parseTypedAmount('', 1)).toBe(1);
    expect(parseTypedAmount('0', 1)).toBe(1);
    expect(parseTypedAmount('abc', 1)).toBe(1);
    expect(parseTypedAmount('', 0)).toBe(0);
  });
});

describe('tier rate columns (net cost, target, sale)', () => {
  // AG Grid types `newValue` as a string, but a number editor hands over a
  // number and a cleared cell null, so the parser is exercised with all three.
  const parse = (newValue: unknown, oldValue: unknown = '5.00') =>
    tierRateValueParser({ newValue: newValue as string, oldValue });

  it('turns a comma decimal into the dot-decimal string the API accepts', () => {
    expect(parse('12,50')).toBe('12.50');
    expect(parse('1.234,56')).toBe('1234.56');
    expect(parse('1 234,56')).toBe('1234.56');
    expect(parse('12.50')).toBe('12.50');
  });

  it('reads a rate typed with its currency sign', () => {
    expect(parse('12,50 €')).toBe('12.50');
    expect(parse('€ 1.234,56')).toBe('1234.56');
    expect(parse('$12.50')).toBe('12.50');
    expect(parse('12 EUR')).toBe('5.00');
  });

  it('keeps the previous value for unreadable input and clears on empty', () => {
    expect(parse('12,50 abc')).toBe('5.00');
    expect(parse('')).toBeNull();
    expect(parse('   ')).toBeNull();
    expect(parse(null)).toBeNull();
  });

  it('passes a number straight through', () => {
    expect(parse(7.25)).toBe(7.25);
    expect(parse(Number.NaN)).toBe('5.00');
  });

  it('is wired to all three columns', () => {
    const t = (key: string, opts?: Record<string, unknown>) => String(opts?.defaultValue ?? key);
    const fmt = new Intl.NumberFormat('hr-HR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    const defs = getColumnDefs({ currencySymbol: '€', currencyCode: 'EUR', locale: 'hr-HR', fmt, t } as unknown as Parameters<typeof getColumnDefs>[0]);
    for (const field of ['net_cost_rate', 'target_rate', 'sale_rate']) {
      const col = defs.find((d) => d.field === field);
      expect(col, field).toBeDefined();
      expect(col?.valueParser, field).toBe(tierRateValueParser);
    }
  });
});
