// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The vector snapshot restore button could not report success, in two
// independent ways, and both of them told the user the opposite of what had
// happened.
//
// The budget. `POST /v1/costs/vector/restore-snapshot/{db_id}` ran on the 45s
// default mutation budget. Server side that call downloads roughly 1.1 GB with
// a 600s budget and then hands the file to Qdrant with `timeout_s=1800`, and
// neither half watches the client - the download runs in an executor, the
// restore in `asyncio.to_thread`. So the browser aborted long before the work
// finished, and the abort was reported as "failed to load vectors" for a
// restore that was still running and would still land. `longRunning` alone
// would not have fixed it: five minutes against forty is still a lie, just a
// slower one.
//
// The field. The restore endpoint answers with `vectors_count` and carries no
// `indexed` field at all, while the neighbouring `load-github` endpoint answers
// with `indexed`. Both callers read `indexed`, so a finished restore of tens of
// thousands of vectors reported one vector on the setup page and "the backend
// indexed 0 vectors" on the modules page. TypeScript could not see it because
// the field was declared optional.
//
// Run: npx vitest run --pool=forks src/features/costs/__tests__/snapshotRestoreBudget.test.ts

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join, relative, sep } from 'node:path';
import { describe, it, expect, vi, afterEach } from 'vitest';
import { apiPost } from '@/shared/lib/api';
import {
  describeSnapshotRestore,
  SNAPSHOT_RESTORE_TIMEOUT_MS,
  type SnapshotRestoreResponse,
} from '../vectorIndex';

const SRC = resolve(__dirname, '..', '..', '..');
const SELF = resolve(__dirname, 'snapshotRestoreBudget.test.ts');
const ROUTER_PY = resolve(SRC, '..', '..', 'backend', 'app', 'modules', 'costs', 'router.py');

/** Every call site that POSTs the snapshot-restore endpoint. */
const EXPECTED_SITES = 2;

const SITE_RE = /(['"`])\/v1\/costs\/vector\/restore-snapshot\//g;

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    if (entry === 'node_modules') continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      walk(full, out);
    } else if (/\.(ts|tsx)$/.test(entry) && full !== SELF) {
      out.push(full);
    }
  }
  return out;
}

interface CallSite {
  where: string;
  file: string;
  callee: string;
  args: string;
}

/** Slice out the call expression enclosing `at`: the callee text just before
 *  its opening paren, and everything between the parens. */
function enclosingCall(source: string, at: number): { callee: string; args: string } {
  let depth = 0;
  let open = -1;
  for (let i = at; i >= 0; i--) {
    const ch = source[i];
    if (ch === ')') depth++;
    else if (ch === '(') {
      if (depth === 0) {
        open = i;
        break;
      }
      depth--;
    }
  }
  if (open < 0) return { callee: '', args: '' };

  let d = 1;
  let close = source.length;
  for (let i = open + 1; i < source.length; i++) {
    const ch = source[i];
    if (ch === '(') d++;
    else if (ch === ')') {
      d--;
      if (d === 0) {
        close = i;
        break;
      }
    }
  }
  return { callee: source.slice(Math.max(0, open - 80), open), args: source.slice(open + 1, close) };
}

function collectSites(): CallSite[] {
  const sites: CallSite[] = [];
  for (const file of walk(SRC)) {
    const source = readFileSync(file, 'utf-8');
    SITE_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = SITE_RE.exec(source)) !== null) {
      const line = source.slice(0, match.index).split('\n').length;
      const { callee, args } = enclosingCall(source, match.index);
      sites.push({
        where: `${relative(SRC, file).split(sep).join('/')}:${line}`,
        file,
        callee,
        args,
      });
    }
  }
  return sites;
}

describe('POST /v1/costs/vector/restore-snapshot/ runs on the server\'s budget', () => {
  const sites = collectSites();
  const listed = sites.map((s) => s.where).join('\n  ');

  it('finds every known call site - the census the budget check is measured against', () => {
    expect(
      sites.length,
      `Expected ${EXPECTED_SITES} snapshot-restore call sites, found ${sites.length}:\n  ${listed}\n` +
        "A LOWER number means this test's matcher went blind, not that the code got cleaner.",
    ).toBe(EXPECTED_SITES);
  });

  it('routes every call site through the api wrapper, never a raw fetch', () => {
    for (const site of sites) {
      expect(
        /\bapiPost\b[^(]*$/.test(site.callee),
        `${site.where} does not POST through apiPost. A raw fetch() carries no client ` +
          'timeout at all and skips the 401 refresh, so it hangs instead of failing.',
      ).toBe(true);
    }
  });

  it('gives every call site the explicit restore budget, not a default and not longRunning', () => {
    const missing = sites
      .filter((s) => !s.args.includes('timeoutMs: SNAPSHOT_RESTORE_TIMEOUT_MS'))
      .map((s) => s.where);
    expect(
      missing,
      `These restore calls do not carry the derived budget: ${missing.join(', ')}. ` +
        'The 45s default cannot see the end of a 1.1 GB download, and the 5-min ' +
        'longRunning budget cannot see the end of the Qdrant restore behind it.',
    ).toEqual([]);
  });

  it('hands the timeout reporting to the caller at every call site', () => {
    const missing = sites.filter((s) => !s.args.includes('suppressTimeoutToast: true')).map((s) => s.where);
    expect(
      missing,
      `These restore calls leave the global timeout toast on: ${missing.join(', ')}. ` +
        "Its wording - cancelled - is false about a restore the server is still running.",
    ).toEqual([]);
  });

  it('reports an abort as work still running, at every call site', () => {
    // The budget is only half the fix. A caller that suppresses the global
    // toast and then lets the abort fall through to its own error branch is
    // strictly worse than before: no banner, and still "it failed".
    for (const site of sites) {
      const source = readFileSync(site.file, 'utf-8');
      expect(
        source.includes('mayStillBeRunning') && source.includes('costs.snapshot_restore_running_title'),
        `${site.where} posts the restore but does not recognise an abort and say the ` +
          'work is still running. Suppressing the toast without that leaves the user ' +
          'with a silent failure message for a restore that is still going.',
      ).toBe(true);
    }
  });

  it('never polls the vector count to prove a restore landed', () => {
    // `readVectorCount` and `pollVectorIndexLanded` read the `cost_items`
    // collection, which is what indexing writes. A restore writes
    // `cwicr_<region>`. Pointing the index poll at a restore would return null
    // every time and report failure a minute later - a blind instrument that
    // reads as a measurement. There is no status endpoint for the per-region
    // collection, which is precisely why the honest answer here is a message
    // and not a poll.
    for (const site of sites) {
      const { args } = site;
      expect(
        /pollVectorIndexLanded|readVectorCount/.test(args),
        `${site.where} polls the vector index to judge a snapshot restore. Those ` +
          'helpers watch cost_items; a restore writes cwicr_<region>, so the poll ' +
          'can only ever come back empty.',
      ).toBe(false);
    }
  });
});

describe('the client budget covers what the server is allowed to spend', () => {
  // A ratchet across the layer boundary. If the handler's own budgets are
  // raised, the number on this side is wrong the same day, and it fails here
  // rather than in front of a user forty minutes into a restore.
  it('is at least the download budget plus the Qdrant restore budget', () => {
    let source: string;
    try {
      source = readFileSync(ROUTER_PY, 'utf-8');
    } catch (err) {
      throw new Error(
        `Could not read ${ROUTER_PY} to check the server budget this constant is derived from: ${String(err)}. ` +
          'An unreadable source is a blind instrument, not a pass.',
      );
    }

    const download = /_download_to_file,\s*\n\s*url,\s*\n\s*local_path,\s*\n\s*([\d.]+),/.exec(source);
    const restore = /"timeout_s":\s*(\d+),/.exec(source);
    expect(
      download,
      'Could not find the snapshot download budget in the restore handler. The matcher ' +
        'went blind, so this test proves nothing until it is fixed.',
    ).not.toBeNull();
    expect(
      restore,
      'Could not find the Qdrant restore timeout in the restore handler. The matcher ' +
        'went blind, so this test proves nothing until it is fixed.',
    ).not.toBeNull();

    const serverBudgetMs = (Number(download![1]) + Number(restore![1])) * 1000;
    expect(
      SNAPSHOT_RESTORE_TIMEOUT_MS,
      `The server may spend ${serverBudgetMs} ms on a restore and the client gives up ` +
        `after ${SNAPSHOT_RESTORE_TIMEOUT_MS} ms. Whatever falls in that gap is a ` +
        'success the user is told was a failure.',
    ).toBeGreaterThanOrEqual(serverBudgetMs);
  });
});

/**
 * Capture the signal `api.ts` attaches to the request under test, and reject
 * the way fetch does on abort. Only the restore request is recorded: a client
 * timeout also makes the error reporter POST /api/v1/client-errors/ through
 * this same global, and recording that would count the reporter as a second
 * attempt.
 */
function stubHangingFetch(): AbortSignal[] {
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((url: string, init: RequestInit) => {
      if (!String(url).includes('/v1/costs/vector/restore-snapshot/')) {
        return Promise.resolve({ ok: true, status: 204, statusText: 'No Content' } as Response);
      }
      return new Promise<Response>((_resolve, reject) => {
        const signal = init.signal as AbortSignal;
        signals.push(signal);
        signal.addEventListener('abort', () => {
          const err = new Error('The operation was aborted.');
          err.name = 'AbortError';
          reject(err);
        });
      });
    }),
  );
  return signals;
}

/** The signal of the one request under test - absent means fetch was never
 *  reached, which would make every abort assertion below vacuous. */
function only(signals: AbortSignal[]): AbortSignal {
  const signal = signals[0];
  if (!signal) throw new Error('apiPost never called fetch - nothing to time.');
  return signal;
}

describe('timeoutMs is not a token - it really outranks both defaults', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it('holds the restore request open past the 5-min long budget and aborts at its own', async () => {
    vi.useFakeTimers();
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/restore-snapshot/DE_BERLIN', undefined, {
      timeoutMs: SNAPSHOT_RESTORE_TIMEOUT_MS,
      suppressTimeoutToast: true,
    }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(45_000);
    expect(only(signals).aborted, 'The 45s default mutation budget killed the restore.').toBe(false);

    // Past where `longRunning: true` would have given up. This is the step
    // that separates the fix from the half-fix.
    await vi.advanceTimersByTimeAsync(300_000);
    expect(
      only(signals).aborted,
      'Aborted at the 5-min long budget, so the explicit budget is not being read.',
    ).toBe(false);

    await vi.advanceTimersByTimeAsync(SNAPSHOT_RESTORE_TIMEOUT_MS - 345_000 - 1_000);
    expect(only(signals).aborted).toBe(false);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(only(signals).aborted).toBe(true);
    await expect(settled).resolves.toBe('rejected');
  });

  it('reads an explicit budget as a value, not as something truthy', async () => {
    // `init.timeoutMs ? ... : ...` looks right and quietly turns 0 into the 45s
    // default, which is the one number a caller passing 0 cannot have meant.
    // Nothing ships 0 today; the point is that the option is read by presence,
    // so the next caller gets what it wrote rather than what it coerced to.
    vi.useFakeTimers();
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/restore-snapshot/DE_BERLIN', undefined, {
      timeoutMs: 0,
      suppressTimeoutToast: true,
    }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(1_000);
    expect(
      only(signals).aborted,
      'A budget of 0 was discarded for a default. An explicit timeout has to be read ' +
        'as given, or a caller can only ever raise the budget and never lower it.',
    ).toBe(true);
    await expect(settled).resolves.toBe('rejected');
  });

  it('still aborts the same request at 90 s without it', async () => {
    // The control: without `timeoutMs` the budget really is the short one, so
    // the case above measures the option and not some ambient default.
    vi.useFakeTimers();
    const signals = stubHangingFetch();
    const settled = apiPost('/v1/costs/vector/restore-snapshot/DE_BERLIN', undefined, {
      suppressTimeoutToast: true,
    }).then(
      () => 'resolved',
      () => 'rejected',
    );

    await vi.advanceTimersByTimeAsync(89_000);
    expect(only(signals).aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(2_000);
    expect(only(signals).aborted).toBe(true);
    await expect(settled).resolves.toBe('rejected');
  });
});

describe('a restore result is read with the field the restore endpoint answers', () => {
  it('reads the real success body - the one that carries no `indexed` at all', () => {
    // Copied field for field from the handler's return in
    // backend/app/modules/costs/router.py. There is no `indexed` key here, and
    // that absence is the whole defect: `?? 0` on a missing field reported a
    // finished restore as zero vectors indexed.
    const body = {
      restored: true,
      collection: 'cwicr_de_berlin',
      database: 'DE_BERLIN',
      vectors_count: 55719,
      source: 'github_snapshot',
      duration_seconds: 412.4,
    };
    expect(describeSnapshotRestore(body)).toEqual({ kind: 'restored', vectors: 55719, duration: 412.4 });
  });

  it('ignores `indexed` even when a body carries one', () => {
    // The negative control for the case above. Reading `vectors_count` has to
    // be a decision, not a coincidence of which field happens to be present:
    // if this returned 0 the reader would be back on the wrong field the
    // moment the two endpoints' bodies converge.
    const withIndexed: SnapshotRestoreResponse & { indexed: number } = {
      restored: true,
      indexed: 0,
      vectors_count: 55719,
    };
    const outcome = describeSnapshotRestore(withIndexed);
    expect(outcome.vectors).toBe(55719);
    expect(outcome.kind).toBe('restored');
  });

  it('calls a restore with an unreadable count a restore, not a failure', () => {
    // The handler swallows a failed collection-info read into `vectors_count:
    // null` after a restore that itself worked. Calling that "0 vectors
    // indexed" is the same lie in a rarer costume.
    expect(describeSnapshotRestore({ restored: true, vectors_count: null, duration_seconds: 300 })).toEqual({
      kind: 'restored_unknown_count',
      vectors: 0,
      duration: 300,
    });
  });

  it('calls a body that never claimed a restore a failure', () => {
    expect(describeSnapshotRestore({}).kind).toBe('not_restored');
    expect(describeSnapshotRestore(undefined).kind).toBe('not_restored');
    expect(describeSnapshotRestore({ restored: false, vectors_count: 0 }).kind).toBe('not_restored');
  });
});

describe('the summary panel says which of the two things happened', () => {
  // Reading the right field made the number correct and the sentence around it
  // wrong. The setup page's result strip is written for the loaders that build
  // an index, and a restore reaches it with a count that was never indexed by
  // anything. The small wrong number the old read produced at least did not
  // travel; a confident 55,719 under the word "indexed" does.
  const PAGE = resolve(SRC, 'features', 'costs', 'ImportDatabasePage.tsx');
  const source = readFileSync(PAGE, 'utf-8');

  it('records which loader produced the count', () => {
    expect(
      source.includes('restore: outcome.kind'),
      'The restore path stores its count without saying it came from a restore, so ' +
        'nothing downstream can tell the two apart.',
    ).toBe(true);
  });

  it('keeps the indexing wording behind a check for the restore', () => {
    // The result strip specifically, addressed by the state it reads. The
    // page says "vectors indexed in" twice and the other one is a toast on the
    // LanceDB branch, which really did index what it counted.
    const NEEDLE = 'vectors indexed in ${lastResult.duration}s';
    const at = source.indexOf(NEEDLE);
    expect(at, 'The result strip no longer carries the indexing wording this test guards.').toBeGreaterThan(-1);
    expect(
      source.indexOf(NEEDLE, at + 1),
      'The result strip renders that wording in more than one place; this test only ' +
        'checked the first and would miss a second going unguarded.',
    ).toBe(-1);

    const before = source.slice(Math.max(0, at - 800), at);
    expect(
      before.includes("lastResult.restore === 'restored'") && before.includes('costs.snapshot_restored_msg'),
      'The result strip reaches its "vectors indexed" wording without first ruling out ' +
        'a restore, so a restored snapshot is reported as an index that was built here.',
    ).toBe(true);
  });
});
