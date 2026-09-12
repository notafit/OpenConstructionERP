// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import i18next from 'i18next';
import { describe, expect, it } from 'vitest';

import { SUPPORTED_LANGUAGES, normalizePackLocale } from '../i18n';

/**
 * `en-US.ts` holds only the words American practice names differently. Every
 * other key it does not carry has to be answered by `en.ts`, or an American
 * reader loses about 32,000 strings the moment they pick the locale.
 *
 * That property is a claim about i18next's resolution order, not about the file,
 * and it is invisible on screen: every call site in this codebase passes a
 * `defaultValue`, so a key that resolves and a key that fails outright both
 * render the same English text. The assertions below therefore call `t()` with
 * no `defaultValue` at all, which is the only way the two outcomes differ - a
 * failed lookup returns the key itself.
 *
 * The bundles are read from source and evaluated rather than imported, for the
 * reason `localeKeyResolution.test.ts` gives: these files are megabytes of
 * object literal and the vitest transform pipeline times out on them.
 */

/** The object a locale file exports, read the way `i18n.ts` consumes it. */
function loadLocale(code: string): { translation: Record<string, string> } {
  const candidates = [
    resolve(process.cwd(), 'src/app/locales', `${code}.ts`),
    resolve(process.cwd(), 'frontend/src/app/locales', `${code}.ts`),
  ];
  const path = candidates.find(existsSync);
  if (!path) throw new Error(`cannot find ${code}.ts, looked in ${candidates.join(' and ')}`);
  const src = readFileSync(path, 'utf8');
  const start = src.indexOf('{', src.indexOf('const resource'));
  const end = src.lastIndexOf('} as ');
  return new Function(`return ${src.slice(start, end + 1)}`)();
}

const en = loadLocale('en').translation;
const enUS = loadLocale('en-US').translation;

/**
 * One instance carrying both bundles, initialised the way `i18n.ts` initialises
 * the real one. `fallbackLng` is copied from there deliberately: it names no
 * en-US branch, so this also asserts that the `default` branch is enough and no
 * configuration change was needed to make the chain work.
 */
function americanInstance() {
  const instance = i18next.createInstance();
  void instance.init({
    lng: 'en-US',
    fallbackLng: {
      'es-MX': ['es', 'en'],
      'es-CL': ['es', 'en'],
      'es-CO': ['es', 'en'],
      'pt-BR': ['pt', 'en'],
      default: ['en'],
    },
    keySeparator: false,
    nsSeparator: false,
    resources: {},
    initAsync: false,
  });
  instance.addResourceBundle('en', 'translation', en, false, true);
  instance.addResourceBundle('en-US', 'translation', enUS, false, true);
  return instance;
}

describe('en-US carries overrides and English answers the rest', () => {
  it('is registered under the spelling i18next resolves, region upper case', () => {
    const entry = SUPPORTED_LANGUAGES.find((l) => l.code === 'en-US');
    expect(entry, 'en-US is not in SUPPORTED_LANGUAGES').toBeDefined();
    // loadLocaleResource passes this exact string to addResourceBundle, and
    // i18next looks the bundle up as 'en-US'. A lower-case region would register
    // a bundle nothing ever reads.
    expect(entry!.code).toBe('en-US');
  });

  it('is an override file, not a copy of en.ts', () => {
    expect(Object.keys(en).length).toBeGreaterThan(30000);
    // The number that matters is the ratio, not the count: a file approaching the
    // size of en.ts means the override discipline has been lost and every future
    // key has to be added twice.
    expect(Object.keys(enUS).length).toBeLessThan(Object.keys(en).length / 10);
    expect(Object.keys(enUS).length).toBeGreaterThan(500);
  });

  it('overrides no key that en.ts does not have, and repeats none of its values', () => {
    const unknown = Object.keys(enUS).filter((key) => !(key in en));
    expect(unknown, 'these keys exist only in en-US, so nothing else can answer them').toEqual([]);
    const identical = Object.keys(enUS).filter((key) => enUS[key] === en[key]);
    expect(identical, 'these keys say exactly what en.ts says and are dead weight').toEqual([]);
  });

  it('answers a key that only en.ts carries, with no defaultValue to hide behind', () => {
    const instance = americanInstance();
    // Named so the failure is readable, and this key is deliberately one no
    // American reader needs changed.
    expect('nav.dashboard' in enUS).toBe(false);
    expect(instance.t('nav.dashboard')).toBe(en['nav.dashboard']);
    expect(instance.t('nav.dashboard')).not.toBe('nav.dashboard');
  });

  it('answers every en-only key it was asked for, not just the named one', () => {
    const instance = americanInstance();
    // A value carrying {{a}} placeholder or a $t() nesting is rewritten on the
    // way out, so it cannot be compared against its own source. Those are not
    // what this test is about, and dropping them keeps the comparison honest.
    const enOnly = Object.keys(en).filter(
      (key) => !(key in enUS) && !en[key]!.includes('{{') && !en[key]!.includes('$t('),
    );
    expect(enOnly.length).toBeGreaterThan(20000);
    // A sample, because resolving every key one by one is slower than the
    // information is worth. Spread across the file rather than taken off the top,
    // so a bundle that merged only its first pages would still be caught.
    const step = Math.max(1, Math.floor(enOnly.length / 400));
    const unresolved = enOnly
      .filter((_, index) => index % step === 0)
      .filter((key) => instance.t(key) !== en[key]);
    expect(unresolved).toEqual([]);
  });

  it('prefers the American word where the file states one', () => {
    const instance = americanInstance();
    for (const key of ['nav.boq', 'modules.catalog.boq', 'punch.header_subtitle']) {
      expect(instance.t(key)).toBe(enUS[key]);
      expect(instance.t(key)).not.toBe(en[key]);
    }
    // The property, rather than the word: whatever the priced document ends up
    // being called here, an American reader must not meet the British name for
    // it. Asserting the word itself would make a term decision unreviewable.
    expect(instance.t('nav.boq')).not.toMatch(/BOQ|Bill of Quantities/i);
    expect(instance.t('punch.header_subtitle')).not.toMatch(/\bsnags?\b/i);
  });

  it('leaves a reader on en.ts untouched', () => {
    // The whole point of a separate file: adding it must not move a single word
    // for anybody who did not ask for it. These two keys are the ones en-US
    // overrides most visibly, so if any of this leaked into the base they would
    // be the first to show it.
    const base = i18next.createInstance();
    void base.init({
      lng: 'en',
      fallbackLng: { default: ['en'] },
      keySeparator: false,
      nsSeparator: false,
      resources: {},
      initAsync: false,
    });
    base.addResourceBundle('en', 'translation', en, false, true);
    expect(base.t('nav.boq')).toBe('Bill of Quantities');
    expect(base.t('punch.header_subtitle')).toMatch(/\bsnags\b/);
  });

  it('gives a pack that asked for American English the American locale', () => {
    // commercial-denver names en-US in its manifest. Before this locale existed
    // that request was answered with 'en'.
    expect(normalizePackLocale('en-US')).toBe('en-US');
    expect(SUPPORTED_LANGUAGES.some((l) => l.code === normalizePackLocale('en-US'))).toBe(true);
  });
});
