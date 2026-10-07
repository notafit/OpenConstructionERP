/**
 * The delete warning has to be able to name every module it can be handed.
 *
 * The backend registry (`backend/app/modules/documents/references.py`) decides
 * which module keys the endpoint emits. The panel maps those keys to the i18n
 * keys those modules already use for their own headings. A key the map does
 * not know falls through to the raw module key, so the user confirming a
 * delete would be told that "plan_room 1" is at stake.
 *
 * Nothing else catches that. The endpoint keeps working, the panel keeps
 * rendering, tsc is happy because the map is a plain `Record<string, string>`,
 * and the defect is only visible to somebody who deletes a document that a
 * newly-registered module happens to reference.
 *
 * These read both sides off disk so the comparison is with what ships rather
 * than with a copy of the list kept here. They fail in both directions: a
 * module added to the registry and not to the map fails, and a map entry for
 * a module the registry dropped fails too.
 */
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const HERE = join(process.cwd(), 'src', 'features', 'documents');
const PANEL = join(HERE, 'DocumentDeleteWarning.tsx');
const REGISTRY = join(
  process.cwd(),
  '..',
  'backend',
  'app',
  'modules',
  'documents',
  'references.py',
);
const EN_LOCALE = join(process.cwd(), 'src', 'app', 'locales', 'en.ts');

/** Module keys the backend registry can put in a response. */
function registryModules(): string[] {
  const source = readFileSync(REGISTRY, 'utf8');
  const block = source.slice(source.indexOf('DOCUMENT_REFERENCES: tuple['));
  const names = [...block.matchAll(/DocumentReference\(\s*"([a-z_]+)"/g)]
    .map((m) => m[1])
    .filter((m): m is string => Boolean(m));
  return [...new Set(names)].sort();
}

/** Module key to i18n key, as the panel declares it. */
function panelLabelKeys(): Record<string, string> {
  const source = readFileSync(PANEL, 'utf8');
  const start = source.indexOf('const MODULE_LABEL_KEYS');
  const block = source.slice(start, source.indexOf('};', start));
  const out: Record<string, string> = {};
  for (const m of block.matchAll(/^\s*([a-z_]+):\s*'([^']+)'/gm)) {
    const key = m[1];
    const value = m[2];
    if (key && value) out[key] = value;
  }
  return out;
}

describe('DocumentDeleteWarning module labels', () => {
  it('reads a real population from both sides', () => {
    // Emptiness would make every comparison below pass vacuously.
    expect(registryModules().length).toBeGreaterThan(15);
    expect(Object.keys(panelLabelKeys()).length).toBeGreaterThan(15);
  });

  it('names every module the registry can emit', () => {
    const missing = registryModules().filter((module) => !(module in panelLabelKeys()));
    expect(missing, `modules the panel would show as a raw key: ${missing.join(', ')}`).toEqual([]);
  });

  it('carries no label for a module the registry dropped', () => {
    const modules = new Set(registryModules());
    const stale = Object.keys(panelLabelKeys()).filter((module) => !modules.has(module));
    expect(stale, `label entries nothing can reach: ${stale.join(', ')}`).toEqual([]);
  });

  it('points every label at a translation key that exists', () => {
    const locale = readFileSync(EN_LOCALE, 'utf8');
    const absent = Object.entries(panelLabelKeys())
      .filter(([, key]) => !locale.includes(`"${key}"`))
      .map(([module, key]) => `${module} -> ${key}`);
    expect(absent, `label keys missing from en.ts: ${absent.join(', ')}`).toEqual([]);
  });

  it('ships the strings the panel itself renders', () => {
    const locale = readFileSync(EN_LOCALE, 'utf8');
    // The plural pair matters: i18next resolves `_one`/`_other`, and a bare
    // key would leave every count rendering the singular.
    const required = [
      'documents.references.title',
      // The failure state has its own string on purpose: an absent panel reads
      // as "nothing links to this file", which a failed check is not.
      'documents.references.unavailable',
      'documents.references.strands_one',
      'documents.references.strands_other',
      'documents.references.unlinks_one',
      'documents.references.unlinks_other',
      'documents.references.retains_one',
      'documents.references.retains_other',
    ];
    const absent = required.filter((key) => !locale.includes(`"${key}"`));
    expect(absent, `panel strings missing from en.ts: ${absent.join(', ')}`).toEqual([]);
  });
});

/**
 * Plural completeness is a question about the language, not about its neighbours.
 *
 * The first version of this gate listed the locales that already carried a
 * dense `_few` set and demanded those forms. That probe finds the Slavic
 * shapes and misses three others - the Arabic dual and zero, the Hebrew dual,
 * and the Romance `many` - so ten files carried a counted string with fewer
 * forms than their language asks for. Nothing said so: the key resolves, a
 * string appears, and only a reader of that language sees `{{count}}` take the
 * wrong noun. `check_i18n_orphan_keys.py` cannot catch it by construction,
 * because it asks whether a key is reachable in any form at all.
 *
 * So the authority here is `Intl.PluralRules`, which is the list i18next
 * consults at render time. The population is every locale file that carries
 * these keys, asserted alongside the verdict so that a gate which quietly
 * stopped looking at anything cannot pass: `en-GB` and `en-US` are overlays
 * that inherit from `en` and are meant to carry nothing here.
 */
const COUNTED_STEMS = ['strands', 'unlinks', 'retains'];

describe('DocumentDeleteWarning plural coverage', () => {
  const LOCALE_DIR = join(process.cwd(), 'src', 'app', 'locales');
  const carriers = readdirSync(LOCALE_DIR)
    .filter((file) => file.endsWith('.ts') && file !== 'index.ts')
    .map((file) => file.slice(0, -'.ts'.length))
    .filter((code) =>
      readFileSync(join(LOCALE_DIR, `${code}.ts`), 'utf8').includes(
        '"documents.references.strands_',
      ),
    );

  it('asks every locale that carries these keys, not a chosen few', () => {
    expect(
      carriers.length,
      `only ${carriers.length} locale files carry the counted keys`,
    ).toBeGreaterThan(40);
    expect(carriers, 'en-US is an overlay and inherits these strings from en').not.toContain(
      'en-US',
    );
  });

  it('gives every counted string the forms its language asks for', () => {
    const missing: string[] = [];
    for (const code of carriers) {
      const text = readFileSync(join(LOCALE_DIR, `${code}.ts`), 'utf8');
      const forms = new Intl.PluralRules(code).resolvedOptions().pluralCategories;
      for (const stem of COUNTED_STEMS) {
        for (const form of forms) {
          const key = `documents.references.${stem}_${form}`;
          if (!text.includes(`"${key}"`)) missing.push(`${code}: ${key}`);
        }
      }
    }
    expect(missing, `plural forms absent: ${missing.join(', ')}`).toEqual([]);
  });
});

/**
 * The panel has to be rendered by something a user can reach.
 *
 * This was first wired into `DocumentsPage.tsx`, which looks like the
 * documents screen and is not: `/documents` redirects to `/files`, and
 * `App.tsx` says in as many words that nothing imports `DocumentsPage`
 * today. Every test above passed against that wiring, the build was clean,
 * and the panel could never appear. Only opening the app showed it.
 *
 * So this asserts the consumer, not the component. The live delete is the
 * file manager's context menu, and it lists eight file kinds against an
 * endpoint that answers for one, hence the kind gate is part of the
 * contract rather than a detail of the caller.
 */
describe('DocumentDeleteWarning is reachable', () => {
  const MENU = join(
    process.cwd(),
    'src',
    'features',
    'file-manager',
    'components',
    'FileContextMenu.tsx',
  );

  it('is imported and rendered by the file manager context menu', () => {
    const source = readFileSync(MENU, 'utf8');
    expect(source, 'FileContextMenu no longer imports the panel').toContain(
      "import { DocumentDeleteWarning } from '@/features/documents/DocumentDeleteWarning'",
    );
    expect(source, 'FileContextMenu imports the panel but never renders it').toContain(
      '<DocumentDeleteWarning',
    );
  });

  it('renders it only for document rows', () => {
    const source = readFileSync(MENU, 'utf8');
    // The other seven kinds have no references endpoint; asking would draw
    // "Could not check what links to this file" on most rows in the manager.
    expect(
      source,
      'the panel is rendered without a kind gate - seven of eight kinds would 404',
    ).toContain("{row.kind === 'document' && <DocumentDeleteWarning");
  });
});

/**
 * The count is read at the moment someone reaches for Delete, so it has to
 * belong to this open of the menu. `staleTime: 0` does not deliver that on its
 * own: it schedules a refetch while React Query still hands the previous value
 * to the first render, and re-opening the menu on the same file paints the old
 * count for the length of the round trip. Measured in the browser with the
 * request held for three seconds: the count was on screen in 300ms.
 *
 * `gcTime: 0` drops the entry when the menu unmounts, so the next open has no
 * answer to show until its own request lands. Nothing else in the tree notices
 * if the pair comes apart - the panel still renders, the tests still pass, and
 * the only symptom is a number that quietly belongs to an earlier open.
 */
describe('DocumentDeleteWarning answers for the open it is drawn in', () => {
  it('drops the cached count between menu opens', () => {
    const source = readFileSync(PANEL, 'utf8');
    expect(source, 'the references query no longer marks its data stale').toContain(
      'staleTime: 0,',
    );
    expect(
      source,
      'staleTime alone still paints the previous count on the next open - gcTime: 0 is what drops it',
    ).toContain('gcTime: 0,');
  });
});
