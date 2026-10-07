// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The global query error handler reports the silent case and nothing else.
 *
 * Two halves. First that a query which fails with no data on screen produces a
 * message at all, because before this handler existed it produced none and the
 * user read an empty table as an empty project. Then that each deliberate
 * silence holds, since the failure mode of a global handler is noise: every
 * skip below has a surface that already reports the same failure, and a second
 * toast for it is the flood we fixed once in `api.ts`.
 *
 * Time is faked so the throttle can be crossed on purpose rather than waited
 * out, and so one test cannot silence the next through module state.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

import { useToastStore } from '@/stores/useToastStore';

import { ApiError } from './api';
import { notifyQueryError, type FailedQuery } from './queryErrorToast';

/** A query that has never resolved: the case a failure leaves blank. */
const EMPTY: FailedQuery = { state: {} };

function toasts() {
  return useToastStore.getState().toasts;
}

/** Push time past the 12s throttle so the next call is judged on its merits. */
function skipThrottle(): void {
  vi.setSystemTime(Date.now() + 60_000);
}

// The throttle lives in module state, which no reset can reach from here. Each
// test therefore starts an hour after the last one rather than at a fixed
// instant: pinning every test to the same clock reading would hand the throttle
// from one test to the next and mute it.
const BASE = new Date('2026-07-26T10:00:00Z').getTime();
let testIndex = 0;

beforeEach(() => {
  vi.useFakeTimers();
  testIndex += 1;
  vi.setSystemTime(BASE + testIndex * 3_600_000);
  useToastStore.setState({ toasts: [], history: [] });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('notifyQueryError', () => {
  it('reports a server failure that left the screen empty', () => {
    notifyQueryError(
      new ApiError(500, 'Internal Server Error', { detail: 'Database connection refused' }),
      EMPTY,
    );

    const raised = toasts();
    expect(raised).toHaveLength(1);
    // Carrying the reason is the point; a bare "something failed" would leave
    // the user no better off than the empty table did.
    expect(raised[0]).toMatchObject({ type: 'error', message: 'Database connection refused' });
  });

  it('reports a failure that carries no status at all', () => {
    // Unreachable server: no response, so no status to reason about. This is
    // the case a status-only rule would drop, and it is the commonest one.
    notifyQueryError(new TypeError('Failed to fetch'), EMPTY);

    expect(toasts()).toHaveLength(1);
  });

  it('says one thing when a whole screen of queries fails at once', () => {
    // Ten queries against a dead backend fail within the same tick. Without
    // the throttle this is ten stacked toasts, which is how the timeout flood
    // looked before `api.ts` grew the same guard.
    for (let i = 0; i < 10; i += 1) {
      notifyQueryError(new ApiError(503, 'Service Unavailable', undefined), EMPTY);
    }

    expect(toasts()).toHaveLength(1);
  });

  it('speaks again once the throttle window has passed', () => {
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);
    skipThrottle();
    // Flush the dismiss timer so the first toast leaves the store. Without
    // this the store deduplicates on type+title and merges the second toast
    // into the still-visible first one, which is the right behaviour for a
    // burst but hides the throttle reopening.
    vi.advanceTimersByTime(60_000);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    // The throttle has to coalesce a burst, not mute the handler for good.
    expect(toasts()).toHaveLength(1);
    // And the history records both: one toast is not the same as one failure.
    expect(useToastStore.getState().history).toHaveLength(2);
  });

  it('stays quiet when the query already has data on screen', () => {
    // A background refetch failing over live data. The numbers are real, only
    // older than the user thinks, so there is nothing misleading to correct.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: { data: [{ id: 1 }] },
    });

    expect(toasts()).toEqual([]);
  });

  it('treats an empty array as data, not as nothing', () => {
    // `[]` is a loaded, genuinely empty list. Reporting it would fire on every
    // refetch failure over an empty table, which is most of them.
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: { data: [] },
    });

    expect(toasts()).toEqual([]);
  });

  it('honours the same opt-out the mutation handler honours', () => {
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), {
      state: {},
      meta: { suppressGlobalErrorToast: true },
    });

    expect(toasts()).toEqual([]);
  });

  it('leaves timeouts to api.ts, which has already toasted them', () => {
    const timeout = Object.assign(new Error('Request timeout'), { isTimeout: true });

    notifyQueryError(timeout, EMPTY);

    expect(toasts()).toEqual([]);
  });

  it('leaves aborts alone for the same reason', () => {
    const aborted = Object.assign(new Error('The operation was aborted'), {
      name: 'AbortError',
    });

    notifyQueryError(aborted, EMPTY);

    expect(toasts()).toEqual([]);
  });

  it.each([
    [401, 'auth redirects on its own'],
    [403, 'the permission screen says it better'],
    [404, 'features render their own not-found state'],
    [422, 'validation belongs to the form that submitted it'],
    [429, 'api.ts already toasts rate limits'],
  ])('stays quiet on %i, because %s', (status) => {
    notifyQueryError(new ApiError(status, 'Client error', undefined), EMPTY);

    expect(toasts()).toEqual([]);
  });

  it('does not let a skipped failure consume the throttle window', () => {
    // The skips return before the clock is touched. If they did not, one 404
    // would buy twelve seconds of silence for the 500 behind it.
    notifyQueryError(new ApiError(404, 'Not Found', undefined), EMPTY);
    notifyQueryError(new ApiError(500, 'Internal Server Error', undefined), EMPTY);

    expect(toasts()).toHaveLength(1);
  });
});
