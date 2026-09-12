import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

/**
 * Does a locale key actually resolve, or does it only look present?
 *
 * Every other locale check we own reads the file as text and asks whether a
 * line for the key exists. That question has a right answer and a wrong one
 * that look identical. A locale file is one object holding one member,
 * `translation`, and `i18n.ts` hands i18next that member alone:
 *
 *     const resource = (mod.default ?? mod) as { translation: ... };
 *     i18n.addResourceBundle(code, 'translation', resource.translation, false, true);
 *
 * A key written one level higher, as a sibling of `translation`, is in the
 * file and not in the bundle. Three shipped modules went out exactly that way:
 * 6969 translated keys across 30 languages, every gate green, and every screen
 * in English, because a failed lookup falls back to the `defaultValue` each
 * call site passes rather than showing a raw key.
 *
 * `check_i18n_key_nesting.py` now gates the shape. This asserts the behaviour,
 * which is the part that was never in doubt visually and never true.
 *
 * The locale is read from source and evaluated rather than imported. These
 * files are three megabytes of object literal and handing one to the vitest
 * transform pipeline times the worker out before a single assertion runs.
 * Evaluating the literal is also closer to what is being tested: it asks what
 * the file says, not what a bundler made of it.
 */

/** The object a locale file exports, read the way `i18n.ts` consumes it. */
function loadLocale(code: string): { translation: Record<string, string> } {
  // Resolved from the working directory rather than `import.meta.url`, which
  // this vitest config rewrites to a bare drive root on Windows. Runs from
  // `frontend/` under `npm test` and from the repo root under a workspace run.
  const candidates = [
    resolve(process.cwd(), 'src/app/locales', `${code}.ts`),
    resolve(process.cwd(), 'frontend/src/app/locales', `${code}.ts`),
  ];
  const path = candidates.find(existsSync);
  if (!path) throw new Error(`cannot find ${code}.ts, looked in ${candidates.join(' and ')}`);
  const src = readFileSync(path, 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  // Not JSON: these carry trailing commas, single-quoted values and comments.
  return new Function(`return ${src.slice(start, end + 1)}`)();
}

/** A bundle built exactly as i18n.ts builds one. */
function bundleFor(code: string, resource: { translation: Record<string, string> }) {
  const instance = i18next.createInstance();
  void instance.init({ lng: code, resources: {}, initAsync: false });
  instance.addResourceBundle(code, 'translation', resource.translation, false, true);
  return instance;
}

const LOCALES = ['de', 'ru', 'ja'];

/**
 * One key per module that shipped its keys outside `translation`, with the
 * English every call site passes as a defaultValue. When a key does not
 * resolve, i18next returns exactly this string, so comparing against it is
 * the same question the screen asks.
 */
const STATUTORY: Array<[string, string]> = [
  ['tax_withholding.taxable_base_label', 'Taxable base'],
  ['einvoice_clearance.action_cancel', 'Cancel'],
  ['payment_clock.days_late_one', '{{count}} day late'],
];

describe('locale keys resolve through the bundle the app builds', () => {
  for (const code of LOCALES) {
    it(`${code} keeps every key inside translation, with nothing beside it`, () => {
      const resource = loadLocale(code);
      expect(Object.keys(resource)).toEqual(['translation']);
      expect(Object.keys(resource.translation).length).toBeGreaterThan(30000);
    });

    it(`${code} resolves the statutory module keys to its own language`, () => {
      const instance = bundleFor(code, loadLocale(code));
      for (const [key, english] of STATUTORY) {
        const value = instance.t(key, { defaultValue: english, count: 1 });
        expect(value, `${code} fell back to English for ${key}`).not.toBe(english);
        expect(value.length).toBeGreaterThan(0);
      }
    });
  }

  it('de resolves the keys of the three register-shaped modules', () => {
    const instance = bundleFor('de', loadLocale('de'));
    const keys: Array<[string, string]> = [
      ['cost_match.tier_exact', 'Exact'],
      ['fx.tab_convert', 'Convert'],
      ['full_evm.band_ahead', 'Ahead of schedule'],
      ['nav.cost_match', 'Cost Match'],
    ];
    for (const [key, english] of keys) {
      expect(instance.t(key, { defaultValue: english }), `de fell back for ${key}`).not.toBe(
        english,
      );
    }
  });
});
