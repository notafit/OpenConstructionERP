// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Every module the Unified Issue Hub reads from must be able to reach it back.
 *
 * The hub deep links into all five registers. Before this gate the reverse
 * direction did not exist anywhere: the only files in the tree naming
 * `/issues` were `App.tsx`, `navCatalog.ts`, `routeIcons.ts` and
 * `routePreload.ts`, which are the router, the menu and two lookup maps, not
 * a screen. A user inside one register could not discover the other four.
 *
 * The gate reads the `IssueSource` union straight out of `issueSources.ts`
 * rather than repeating it, because a second copy of the list is a thing that
 * drifts and a gate whose expectation drifts with the code it guards cannot
 * fail. It fails in both directions: a sixth source added to the union with no
 * page mapped to it fails here, and a mapping that outlives its source or its
 * file fails here too.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const FEATURES = resolve(HERE, '..');

/** The page a user stands on when they are working in each source register. */
const SOURCE_PAGES: Record<string, string> = {
  markup: 'markups/MarkupsPage.tsx',
  punch: 'punchlist/PunchListPage.tsx',
  ncr: 'ncr/NCRPage.tsx',
  // The BCF panel is reused inside the model viewer, so the link belongs to
  // the route wrapper rather than the panel: in the viewer the user has not
  // navigated to a register and a "back to the hub" button would be noise.
  bcf: 'bcf/BcfPage.tsx',
  clash: 'clash/ClashDetectionPage.tsx',
};

function declaredSources(): string[] {
  const src = readFileSync(resolve(HERE, 'issueSources.ts'), 'utf8');
  const m = src.match(/export type IssueSource =([^;]+);/);
  if (!m) throw new Error('IssueSource union not found - this gate is reading the wrong file');
  const union = m[1] ?? '';
  const names = [...union.matchAll(/'([a-z_]+)'/g)]
    .map((x) => x[1])
    .filter((x): x is string => Boolean(x));
  if (names.length < 2) throw new Error(`parsed only ${names.length} sources - the instrument is broken`);
  return names;
}

describe('issue hub back-links', () => {
  it('parses the source union from the file that defines it', () => {
    expect(declaredSources().sort()).toEqual(['bcf', 'clash', 'markup', 'ncr', 'punch']);
  });

  it('maps every declared source to a page', () => {
    expect(Object.keys(SOURCE_PAGES).sort()).toEqual(declaredSources().sort());
  });

  it('points every mapping at a file that exists', () => {
    for (const rel of Object.values(SOURCE_PAGES)) {
      expect(existsSync(resolve(FEATURES, rel)), `${rel} is missing`).toBe(true);
    }
  });

  it('renders the hub link on every source page', () => {
    const without = Object.entries(SOURCE_PAGES)
      .filter(([, rel]) => !/<IssueHubLink\b/.test(readFileSync(resolve(FEATURES, rel), 'utf8')))
      .map(([source, rel]) => `${source} (${rel})`);
    expect(without, `these sources feed the hub but cannot reach it: ${without.join(', ')}`).toEqual([]);
  });

  it('imports the component rather than hand-rolling a second link', () => {
    for (const rel of Object.values(SOURCE_PAGES)) {
      const src = readFileSync(resolve(FEATURES, rel), 'utf8');
      expect(src, `${rel} renders IssueHubLink without importing it`).toMatch(
        /import\s*\{[^}]*IssueHubLink[^}]*\}\s*from/,
      );
    }
  });
});
