// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pins how the architecture map loads its bundled manifest.
 *
 * The manifest is ~7 MB of JSON. Imported as a JSON module, TypeScript
 * (moduleResolution "bundler") parses it into the type program, which cost
 * about 190 MiB of tsc heap and helped push the CI type check past its
 * ceiling. Loading it through `?url` and `fetch` keeps it out of the program.
 * A plain `import('./architecture_manifest.json')` compiles and works, so
 * nothing else would notice it coming back until CI ran out of memory again.
 *
 * This is a source-text pin, not a behaviour test: it reads the files, it
 * does not render the page.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import manifestUrl from './architecture_manifest.json?url';

/** Resolve the feature directory whether vitest was started at `frontend/` or the repo root. */
const FEATURE_DIR = [
  resolve(process.cwd(), 'src/features/architecture'),
  resolve(process.cwd(), 'frontend/src/features/architecture'),
].find((p) => {
  try {
    return readdirSync(p).includes('ArchitectureMapPage.tsx');
  } catch {
    return false;
  }
});

const MANIFEST_SPECIFIER = /['"]\.\/architecture_manifest\.json(\?[\w&=]*)?['"]/g;

describe('architecture manifest import', () => {
  it('locates the feature directory', () => {
    expect(FEATURE_DIR, 'could not locate src/features/architecture from the test working directory').toBeTruthy();
  });

  it('is referenced only through ?url from the feature sources', () => {
    const sources = readdirSync(FEATURE_DIR!).filter(
      (f) => /\.(ts|tsx)$/.test(f) && !/\.test\.(ts|tsx)$/.test(f),
    );
    const found: string[] = [];
    for (const file of sources) {
      const text = readFileSync(join(FEATURE_DIR!, file), 'utf8');
      for (const match of text.matchAll(MANIFEST_SPECIFIER)) {
        found.push(`${file}: ${match[0]}`);
      }
    }
    // The page must still load it (an empty list would pass the check below vacuously).
    expect(found.length).toBeGreaterThan(0);
    const notUrl = found.filter((entry) => !entry.includes('?url'));
    expect(notUrl, 'import the manifest with ?url and fetch it, never as a JSON module').toEqual([]);
  });

  it('resolves ?url to the manifest file, which carries modules', () => {
    expect(typeof manifestUrl).toBe('string');
    expect(manifestUrl).toMatch(/architecture_manifest\.json$/);
    const data = JSON.parse(readFileSync(join(FEATURE_DIR!, 'architecture_manifest.json'), 'utf8')) as {
      modules?: unknown[];
    };
    expect(Array.isArray(data.modules) && data.modules.length > 0).toBe(true);
  });
});
