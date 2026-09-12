import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

/**
 * The clash page names a severity and a status by building the key from the
 * value: t(`clash.severity.${s}`, { defaultValue: s }). Both vocabularies are
 * closed and both are decided by the server - CLASH_SEVERITIES and
 * CLASH_STATUSES in `backend/app/modules/clash/schemas.py` - so every value has
 * exactly one key and the set of keys is knowable.
 *
 * The severity half of that had no key in any of the 40 locales. Nothing
 * reported it: a missing key falls back to the defaultValue, which here is the
 * raw server value, so a German coordinator read "critical / high / medium /
 * low" on a screen that was otherwise entirely in German, and the orphan-key
 * scan cannot see a family whose keys are assembled at runtime.
 *
 * This asserts the vocabulary is complete in every locale, which is the part a
 * scan of call sites cannot answer, and that one locale really resolves it
 * through the bundle rather than only carrying the line.
 */

const LOCALES_DIR = ['src/app/locales', 'frontend/src/app/locales']
  .map((p) => resolve(process.cwd(), p))
  .find(existsSync);

/** Mirrors CLASH_SEVERITIES, worst to least. */
const SEVERITIES = ['critical', 'high', 'medium', 'low'];
/** Mirrors CLASH_STATUSES, in review order. */
const STATUSES = ['new', 'active', 'reviewed', 'approved', 'resolved', 'ignored'];
/** Mirrors TOLERANCE_PRESETS on the clash page. */
const TOLERANCES = ['coarse', 'standard', 'fine', 'precise'];
/** Mirrors the reason codes notified_sum returns. The payment clock assembles
 *  its sentence on the server, which can only assemble it in one language, so
 *  the same failure lives there: the page names the key from the code. */
const SUM_REASONS = [
  'payment_notice',
  'no_notice_sequence',
  'window_open_until',
  'window_open',
  'silence_does_not_fix',
  'default_payment_notice',
  'application',
];
const KEYS = [
  ...SEVERITIES.map((s) => `clash.severity.${s}`),
  ...STATUSES.map((s) => `clash.status.${s}`),
  ...TOLERANCES.map((s) => `clash.tol_${s}`),
  ...SUM_REASONS.map((s) => `payment_clock.sum_reason_${s}`),
];

function localeCodes(): string[] {
  if (!LOCALES_DIR) throw new Error('cannot find the locales directory');
  return readdirSync(LOCALES_DIR)
    .filter((f) => f.endsWith('.ts') && f !== 'index.ts')
    .map((f) => f.slice(0, -3))
    .sort();
}

function localeText(code: string): string {
  return readFileSync(resolve(LOCALES_DIR as string, `${code}.ts`), 'utf8');
}

/**
 * The base language a regional code falls back to, or null if there is none.
 *
 * The defect this suite catches is a reader seeing another language, which is
 * what happens when `de` has no key and i18next reaches `en`. A regional code
 * reaching its own base is a different thing: i18next resolves `en-US` through
 * ['en-US', 'en'], so the American reader gets English either way, and
 * `en-US.ts` is deliberately an overlay of about fifteen hundred words that
 * differ rather than a locale in its own right (see
 * `enUSFallsBackToEnglish.test.ts`). Requiring the full vocabulary of it asks
 * it to stop being an overlay.
 *
 * So the same-language hop is allowed and the cross-language one is not. That
 * also covers es-MX, es-CL, es-CO and pt-BR, which do carry the whole set
 * today: were one of them to lose a key, the reader would still be reading
 * Spanish or Portuguese, and that is not what this file is for.
 */
function baseLanguageOf(code: string): string | null {
  const dash = code.indexOf('-');
  return dash > 0 ? code.slice(0, dash) : null;
}

describe('the clash triage vocabulary is complete in every locale', () => {
  const codes = localeCodes();

  it('finds the locale files at all', () => {
    // A directory read that quietly returns nothing would make every
    // assertion below vacuous, which is the failure this suite exists to
    // catch in the locales themselves.
    expect(codes.length).toBeGreaterThan(30);
    expect(codes).toContain('de');
    expect(codes).toContain('en');
  });

  for (const code of codes) {
    it(`${code} names every value its screens build a key from`, () => {
      const text = localeText(code);
      const base = baseLanguageOf(code);
      const inherited = base && codes.includes(base) ? localeText(base) : '';
      const missing = KEYS.filter(
        (key) => !text.includes(`"${key}"`) && !inherited.includes(`"${key}"`),
      );
      expect(missing, `${code} has no key for ${missing.join(', ')}`).toEqual([]);
    });
  }
});

describe('the vocabulary resolves through the bundle, not just in the file', () => {
  it('de answers in German for every severity', () => {
    // Read and evaluated rather than imported: the file is megabytes of object
    // literal and the vitest transform pipeline times out on it. Same approach
    // as localeKeyResolution.test.ts, for the same reason.
    const source = localeText('de');
    const start = source.indexOf('{', source.indexOf('const resource'));
    const end = source.lastIndexOf('} as ');
    // Not JSON: trailing commas, single-quoted values and comments all appear.
    const resource = new Function(`return ${source.slice(start, end + 1)}`)() as {
      translation: Record<string, string>;
    };

    const instance = i18next.createInstance();
    void instance.init({ lng: 'de', resources: {}, initAsync: false });
    instance.addResourceBundle('de', 'translation', resource.translation, false, true);

    for (const severity of SEVERITIES) {
      const key = `clash.severity.${severity}`;
      const value = instance.t(key, { defaultValue: severity });
      expect(value, `de fell back to the raw value for ${key}`).not.toBe(severity);
      expect(value.length).toBeGreaterThan(0);
    }
  });
});
