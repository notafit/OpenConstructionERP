// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Print the population next to the verdict.
 *
 * `profileDifference.test.ts` asserts things about "the profiles this
 * repository ships", and every one of those assertions passes just as happily
 * against two profiles as against twenty-two. A parser that quietly stopped
 * matching would turn the whole block into a green no-op, which is the failure
 * mode that gate exists to prevent. This file pins the count and the shape of
 * what the parser returns, so a silent narrowing has somewhere to fail.
 */
import { readFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

import { profileShapes, type ProfileFacts } from '../profileDifference';

const SRC = join(process.cwd(), '..', 'backend', 'app', 'core', 'onboarding_presets.py');

function parse(): { profiles: ProfileFacts[]; core: string[] } {
  if (!existsSync(SRC)) return { profiles: [], core: [] };
  const text = readFileSync(SRC, 'utf8');
  const coreBlock = /_CORE_MODULES:\s*list\[str\]\s*=\s*\[([\s\S]*?)\n\]/.exec(text)?.[1] ?? '';
  const core = [...coreBlock.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]!);
  const profiles: ProfileFacts[] = [];
  for (const match of text.matchAll(/"([a-z_]+)":\s*CompanyPreset\(/g)) {
    const after = text.slice(match.index);
    const listed = /enabled_modules=\[([\s\S]*?)\n\s*\],/.exec(after);
    if (!listed) continue;
    const modules = [...listed[1]!.matchAll(/"([a-z0-9_]+)"/g)].map((m) => m[1]!);
    if (modules.length > 0) profiles.push({ key: match[1]!, enabled_modules: modules });
  }
  return { profiles, core };
}

describe('the preset parser sees the whole file', () => {
  const { profiles, core } = parse();

  it('reads the core list at its declared length', () => {
    // Eighteen today. Written as a range rather than a constant because the
    // list grows, but a parser that returned three would be caught here and
    // nowhere else.
    expect(core.length).toBeGreaterThanOrEqual(15);
    expect(core).toContain('projects');
    expect(core).toContain('assemblies');
  });

  it('reads every company profile, not a prefix of them', () => {
    // The size presets use the same CompanyPreset constructor, so the parser
    // may legitimately pick up a few more than the company profiles alone.
    expect(profiles.length).toBeGreaterThanOrEqual(21);
    const keys = profiles.map((p) => p.key);
    for (const expected of [
      'general_contractor',
      'estimator',
      'sustainability_esg',
      'full_enterprise',
      'government_agency',
    ]) {
      expect(keys, `${expected} was not parsed`).toContain(expected);
    }
  });

  it('reads whole module lists, not the first line of each', () => {
    const gc = profiles.find((p) => p.key === 'general_contractor');
    expect(gc, 'general_contractor missing').toBeDefined();
    expect(gc!.enabled_modules.length).toBeGreaterThan(25);
    const esg = profiles.find((p) => p.key === 'sustainability_esg');
    expect(esg!.enabled_modules.length).toBeGreaterThan(5);
    // The narrow profile must really be narrower than the broad one, which is
    // the relation every signature on the page depends on.
    expect(esg!.enabled_modules.length).toBeLessThan(gc!.enabled_modules.length);
  });

  it('produces a signature for the named profiles a reader will recognise', () => {
    const shapes = profileShapes(profiles, core);
    // These four are the ones whose whole reason to exist is a handful of
    // modules nobody else needs. If any of them comes back with nothing to
    // show, the signature machinery has stopped working even though every
    // other assertion still passes.
    for (const key of ['mep_contractor', 'bim_vdc', 'estimator', 'hse_manager']) {
      const shape = shapes.get(key);
      expect(shape, `${key} missing from shapes`).toBeDefined();
      expect(shape!.rare.length, `${key} has no distinguishing module`).toBeGreaterThan(0);
    }
  });
});
