// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * `reuseNumberFormat` reuses `Intl.NumberFormat` instances.
 *
 * `formatCurrency` used to build a new formatter on every call, and the BOQ
 * grid calls it for every visible money cell and tooltip on every refresh
 * after a save. Reuse must change nothing a reader can see: same text for the
 * same input, a distinct instance for any input that changes the output, and
 * the malformed-locale fallback still reachable.
 */
import { describe, it, expect, vi } from 'vitest';

import { formatCurrency, reuseNumberFormat } from './money';

describe('reuseNumberFormat', () => {
  it('builds once per key and returns the same instance after that', () => {
    const build = vi.fn(() => new Intl.NumberFormat('hr-HR', { maximumFractionDigits: 2 }));
    const a = reuseNumberFormat('test.same|hr-HR', build);
    const b = reuseNumberFormat('test.same|hr-HR', build);
    expect(b).toBe(a);
    expect(build).toHaveBeenCalledTimes(1);
  });

  it('keeps instances apart when the key differs', () => {
    const hr = reuseNumberFormat('test.apart|hr-HR', () => new Intl.NumberFormat('hr-HR', { maximumFractionDigits: 2 }));
    const de = reuseNumberFormat('test.apart|de-DE', () => new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }));
    expect(de).not.toBe(hr);
    expect(hr.format(1234.5)).toBe(new Intl.NumberFormat('hr-HR', { maximumFractionDigits: 2 }).format(1234.5));
    expect(de.format(1234.5)).toBe(new Intl.NumberFormat('de-DE', { maximumFractionDigits: 2 }).format(1234.5));
  });

  it('caches nothing when the build throws, so the caller keeps its own fallback', () => {
    const bad = vi.fn(() => new Intl.NumberFormat('not a locale!', { maximumFractionDigits: 2 }));
    expect(() => reuseNumberFormat('test.throws|bad', bad)).toThrow(RangeError);
    expect(() => reuseNumberFormat('test.throws|bad', bad)).toThrow(RangeError);
    expect(bad).toHaveBeenCalledTimes(2);
  });
});

describe('formatCurrency on the shared formatters', () => {
  it('writes the same text on repeated calls, and the text a fresh formatter writes', () => {
    const first = formatCurrency(1234.56, 'EUR', 'hr-HR');
    expect(formatCurrency(1234.56, 'EUR', 'hr-HR')).toBe(first);
    expect(first).toBe(new Intl.NumberFormat('hr-HR', { style: 'currency', currency: 'EUR', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(1234.56));
  });

  it('does not let one currency, locale, sign or digit policy leak into another', () => {
    const eur = formatCurrency(1000, 'EUR', 'de-DE');
    const jpy = formatCurrency(1000, 'JPY', 'de-DE');
    const whole = formatCurrency(1000, 'EUR', 'de-DE', { maximumFractionDigits: 0 });
    const signed = formatCurrency(1000, 'EUR', 'de-DE', { signDisplay: 'always' });
    const us = formatCurrency(1000, 'EUR', 'en-US');
    expect(new Set([eur, jpy, whole, signed, us]).size).toBe(5);
    expect(formatCurrency(1000, 'EUR', 'de-DE')).toBe(eur);
  });

  it('still falls back to plain text for a malformed locale tag', () => {
    expect(formatCurrency(12.5, 'EUR', 'not a locale!')).toBe('12.50 EUR');
    expect(formatCurrency(12.5, 'EUR', 'not a locale!')).toBe('12.50 EUR');
  });
});
