// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A call that names a plural form itself has already made the choice, and it
 * can only choose between the forms English happens to have.
 *
 * The connector card used to write this:
 *
 *   created === 1 ? t('connectors.just_imported_one') : t('connectors.just_imported_many')
 *
 * Correct in English, which owns exactly two forms. Eight of the languages
 * shipped here own three or more, and the branch could never reach the third.
 * Measured against the tree's own translations, the category a reader needs at
 * two and three carries genuinely different words in ar, cs, he, hr, pl, ro, ru
 * and uk: Polish wants "2 wierszE" and got "wierszY", Russian wants
 * "2 новых документА" and got "документОВ". Two or three imported files is the
 * ordinary case, not an edge, so those readers saw broken grammar every time.
 *
 * Passing the bare key and `count` instead lets i18next apply CLDR, which is
 * the only thing that knows a language has a dual, or that Russian selects
 * `one` again at twenty one.
 *
 * The check deliberately looks at the literal key inside the `t(` call and
 * nowhere else. An earlier probe tried walking backwards from an option value
 * to the key that owned it and mis-attributed nine call sites out of twenty
 * one, once blaming a template for a key whose English reads "SLA". Reading the
 * key where it is written has no such failure mode.
 *
 * A suffix alone proves nothing, because `_other`, `_few`, `_two` and `_zero`
 * are also ordinary English: the tree spells an enum value `finding_cat_other`
 * and an error `err_div_by_zero`. Requiring the base to carry two or more
 * distinct categories somewhere in the locales is what separates a plural
 * family from a word that ends in one of those letters. Without that rule the
 * same scan reported 605 defects, all of them false.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(__dirname, '..', '..');
const LOCALE_DIR = join(SRC, 'app', 'locales');
const PAIR = /"((?:[^"\\]|\\.)*)":\s*"(?:[^"\\]|\\.)*"/g;
const CATEGORIES = ['zero', 'one', 'two', 'few', 'many', 'other'] as const;

/** Every `t('literal'` in the tree, with the file and line it sits on. */
const T_CALL = /\bt\(\s*['"]([A-Za-z0-9_.-]+)['"]/g;

function suffixOf(key: string): string | undefined {
  return CATEGORIES.find((c) => key.endsWith(`_${c}`));
}

/**
 * A base is a plural family when some locale writes it in two or more distinct
 * categories. One suffix on its own is just a word.
 */
function pluralFamilies(): Set<string> {
  const perBase = new Map<string, Set<string>>();
  for (const file of readdirSync(LOCALE_DIR)) {
    if (!file.endsWith('.ts') || file === 'index.ts') continue;
    const text = readFileSync(join(LOCALE_DIR, file), 'utf8');
    for (const match of text.matchAll(PAIR)) {
      const key = match[1]!;
      const category = suffixOf(key);
      if (category === undefined) continue;
      const base = key.slice(0, -(category.length + 1));
      let seen = perBase.get(base);
      if (seen === undefined) {
        seen = new Set<string>();
        perBase.set(base, seen);
      }
      seen.add(category);
    }
  }
  const families = new Set<string>();
  for (const [base, categories] of perBase) {
    if (categories.size >= 2) families.add(base);
  }
  return families;
}

interface Offence {
  where: string;
  key: string;
}

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules' || entry === 'dist' || entry === 'locales') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
      continue;
    }
    if (!/\.tsx?$/.test(entry)) continue;
    if (/\.(test|spec)\.tsx?$/.test(entry) || entry.endsWith('.d.ts')) continue;
    out.push(full);
  }
  return out;
}

const families = pluralFamilies();
const sourceFiles = walk(SRC);

const offences: Offence[] = [];
let callsInspected = 0;
for (const file of sourceFiles) {
  const text = readFileSync(file, 'utf8');
  for (const match of text.matchAll(T_CALL)) {
    callsInspected += 1;
    const key = match[1]!;
    const category = suffixOf(key);
    if (category === undefined) continue;
    const base = key.slice(0, -(category.length + 1));
    if (!families.has(base)) continue;
    const line = text.slice(0, match.index).split('\n').length;
    offences.push({ where: `${relative(SRC, file).split(sep).join('/')}:${line}`, key });
  }
}

describe('plural forms are chosen by i18next, not by JavaScript', () => {
  it('inspected a population big enough for the verdict to mean something', () => {
    // The denominator is asserted next to the verdict so a scan that silently
    // stops finding files cannot pass by looking at nothing.
    expect(sourceFiles.length, 'no source files were scanned').toBeGreaterThan(500);
    expect(callsInspected, 'no t() calls were found at all').toBeGreaterThan(5000);
    expect(families.size, 'no plural families were detected in the locales').toBeGreaterThan(50);
  });

  it('still recognises a known plural family, so the filter cannot pass by matching nothing', () => {
    expect(families, 'the connector import message stopped looking like a plural family').toContain(
      'connectors.just_imported',
    );
  });

  it('never hands i18next a key that already names its own plural form', () => {
    const lines = offences.map((o) => `${o.where}  ${o.key}`);
    expect(
      lines,
      `these calls pick the plural form in JavaScript, so CLDR never runs and every\n` +
        `language with more than two forms reads the wrong one. Pass the base key and\n` +
        `count instead, with defaultValue_one and defaultValue_other:\n  ${lines.join('\n  ')}`,
    ).toEqual([]);
  });
});
