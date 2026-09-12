import i18next from 'i18next';
import { afterAll, beforeEach, describe, expect, it } from 'vitest';

import { formatCompactCurrency } from '../money';
import { fmtPercent } from '../formatters';
import { usePreferencesStore } from '@/stores/usePreferencesStore';

// The percent helper reads the live UI language off the i18next singleton,
// which nothing else in this file needs, so it is initialised here with no
// resources at all - the language tag is the whole input.
void i18next.init({ lng: 'en', resources: {}, initAsync: false });
const original = i18next.language;
afterAll(() => {
  void i18next.changeLanguage(original);
});

/**
 * A German cost report printed "203.1M EUR".
 *
 * Both halves of that are wrong for the reader it was printed for: the point
 * is a thousands separator in German, so 203.1 reads as two hundred and three
 * thousand, and M is not a magnitude letter that language uses. Four screens
 * had each grown a private compact formatter and every one of them wrote
 * `.toFixed(1)` and an English suffix, which no locale check can see because
 * the string is assembled in code rather than looked up.
 *
 * The locale is passed explicitly here rather than switched globally: what is
 * under test is the formatter, not i18next. The assertions avoid pinning the
 * exact spacing and symbol placement, which belong to the engine's CLDR data
 * and change between ICU versions - what they pin is the part that was
 * wrong, which is the separator and the magnitude word of the reader's own
 * language.
 */
describe('formatCompactCurrency', () => {
  it('gives a German reader their own separator and magnitude word', () => {
    const text = formatCompactCurrency(203_100_000, 'EUR', 'de-DE');
    expect(text).toContain('203,1');
    expect(text).toContain('Mio');
    expect(text).not.toContain('203.1');
    expect(text).not.toMatch(/\dM\b/);
  });

  it('still reads as English in English', () => {
    const text = formatCompactCurrency(203_100_000, 'EUR', 'en-US');
    expect(text).toContain('203.1M');
  });

  it('keeps the currency out when there is no usable code', () => {
    // Callers pass "" on purpose where the unit is unknown; inventing a
    // symbol there would misstate the money rather than omit it.
    const text = formatCompactCurrency(1_500_000, '', 'en-US');
    expect(text).toContain('1.5M');
    expect(text).not.toMatch(/[€$£]/);
  });

  it('does not compact what is already short', () => {
    expect(formatCompactCurrency(842, 'EUR', 'de-DE')).toContain('842');
    expect(formatCompactCurrency(842, 'EUR', 'de-DE')).not.toMatch(/K|Tsd/);
  });

  it('compacts a negative amount as one number, not as a sign and a number', () => {
    const text = formatCompactCurrency(-1_300_000, 'EUR', 'de-DE');
    expect(text).toContain('1,3');
    expect(text).toMatch(/^-|-\s?\d/u);
  });

  it('survives a wire value that arrives as a Decimal string', () => {
    expect(formatCompactCurrency('4200000.00', 'EUR', 'en-US')).toContain('4.2M');
  });

  it('never throws on a malformed locale tag', () => {
    expect(() => formatCompactCurrency(5_000_000, 'EUR', 'not a locale')).not.toThrow();
  });
});

/**
 * The same failure in the other half of the same screens: `${n.toFixed(1)}%`
 * printed 68.3% to a reader whose language writes 68,3 %, and put the sign on
 * the wrong side of the digits for Turkish.
 */
describe('fmtPercent', () => {
  // `fmtPercent` reads the format preference, not the language, and `auto`
  // is what makes those the same answer. These four assertions are about
  // the language, so they set the preference that entitles them to be.
  beforeEach(() => {
    usePreferencesStore.setState({ numberLocale: 'auto' });
  });

  it('writes the separator of the reader, not of the author', () => {
    void i18next.changeLanguage('de');
    expect(fmtPercent(68.3)).toContain('68,3');
    expect(fmtPercent(68.3)).not.toContain('68.3');
  });

  it('puts the sign where the language puts it', () => {
    void i18next.changeLanguage('tr');
    expect(fmtPercent(68.3).trimStart().startsWith('%')).toBe(true);
    void i18next.changeLanguage('en');
    expect(fmtPercent(68.3).trimEnd().endsWith('%')).toBe(true);
  });

  it('keeps a negative percentage negative', () => {
    void i18next.changeLanguage('de');
    expect(fmtPercent(-36.7)).toMatch(/36,7/);
    expect(fmtPercent(-36.7)).toMatch(/-/);
  });

  it('honours the digit count it is given', () => {
    void i18next.changeLanguage('en');
    expect(fmtPercent(85, 0)).toBe('85%');
    expect(fmtPercent(85)).toBe('85.0%');
  });
});
