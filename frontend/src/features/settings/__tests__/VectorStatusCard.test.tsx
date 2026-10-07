// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A reindex that wrote nothing must not be reported in green.
//
// The backend returns 200 with {"indexed": 0, "skipped": N} whenever the rows
// could not be encoded: index_many() catches the encode failure, logs it at
// debug and moves on, so an absent or unreachable embedding model produces a
// perfectly healthy response in which nothing was indexed. The card used to
// announce "Reindex complete" over that, which tells an operator the
// collection is searchable at the exact moment it is not.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import VectorStatusCard from '../VectorStatusCard';
import { useToastStore } from '@/stores/useToastStore';

const apiPost = vi.fn();
const fetchSearchStatus = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiPost: (...args: unknown[]) => apiPost(...args),
}));

// Partial: only the network call is stubbed. The card also imports
// `collectionLabel` to name each collection in the reader's language, and
// that one is a pure function this test wants the real behaviour of - a
// whole-module mock would have to restate the label table to say anything.
vi.mock('@/features/search/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/search/api')>()),
  fetchSearchStatus: (...args: unknown[]) => fetchSearchStatus(...args),
}));

// oe_tasks rather than an invented name: the card only renders a reindex
// button for collections it has an endpoint for, so a made-up collection
// would test the empty branch by accident.
const COLLECTION = 'oe_tasks';

function statusPayload() {
  return {
    engine: 'qdrant',
    model_name: 'intfloat/multilingual-e5-small',
    embedding_dim: 384,
    connected: true,
    collections: [
      { collection: COLLECTION, label: 'Tasks', ready: true, vectors_count: 0 },
    ],
  };
}

async function reindexReturning(result: Record<string, unknown>) {
  fetchSearchStatus.mockResolvedValue(statusPayload());
  apiPost.mockResolvedValue(result);

  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VectorStatusCard />
    </QueryClientProvider>,
  );

  fireEvent.click(await screen.findByRole('button', { name: /reindex/i }));

  await waitFor(() => {
    expect(useToastStore.getState().toasts.length).toBeGreaterThan(0);
  });
  return useToastStore.getState().toasts[0];
}

describe('VectorStatusCard reindex reporting', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useToastStore.setState({ toasts: [], history: [] });
  });

  it('does not call it a success when every record was skipped', async () => {
    const toast = await reindexReturning({
      indexed: 0,
      skipped: 1200,
      purged: false,
      collection: COLLECTION,
    });

    expect(toast.type).toBe('warning');
    // The count has to survive into the message. An operator who is told
    // something went wrong but not how much cannot tell a whole collection
    // failing from a handful of odd rows.
    expect(toast.message).toContain('1200');
  });

  it('says nothing was indexed rather than that indexing completed', async () => {
    const toast = await reindexReturning({
      indexed: 0,
      skipped: 1200,
      purged: false,
      collection: COLLECTION,
    });

    expect(toast.title).not.toMatch(/complete/i);
  });

  it('separates an empty collection from a failed one', async () => {
    // Nothing indexed and nothing skipped is not a failure, it is a
    // collection with no rows yet, and telling the operator to go looking
    // for a broken encoder would waste their time.
    const toast = await reindexReturning({
      indexed: 0,
      skipped: 0,
      purged: false,
      collection: COLLECTION,
    });

    expect(toast.type).toBe('info');
  });

  it('still reports a real reindex as a success', async () => {
    const toast = await reindexReturning({
      indexed: 900,
      skipped: 0,
      purged: false,
      collection: COLLECTION,
    });

    expect(toast.type).toBe('success');
    expect(toast.message).toContain('900');
  });

  it('does not call a truncated pass a success', async () => {
    // The backend walks a collection up to a ceiling and reports `truncated`
    // when it stopped there with rows left over. Those rows are not in the
    // search index and will not be found by a semantic search. The card used
    // to read `indexed` and `skipped` only, so this arrived as plain green
    // "Reindex complete" - the operator, who is the only party able to act on
    // it, was the only party not told.
    const toast = await reindexReturning({
      indexed: 100000,
      skipped: 0,
      purged: false,
      collection: COLLECTION,
      scanned: 100000,
      cap: 100000,
      truncated: true,
    });

    expect(toast.type).toBe('warning');
    expect(toast.title).not.toMatch(/complete/i);
  });

  it('says how far the truncated pass got and where it stopped', async () => {
    // A warning with no numbers cannot be acted on: what the operator needs is
    // how much was covered against the limit that cut it off, which is what
    // tells them the collection has to be reindexed a project at a time.
    const toast = await reindexReturning({
      indexed: 99000,
      skipped: 1000,
      purged: false,
      collection: COLLECTION,
      scanned: 100000,
      cap: 100000,
      truncated: true,
    });

    expect(toast.message).toContain('100000');
    expect(toast.message).toContain('99000');
  });

  it('leaves a note on the collection after the toast is gone', async () => {
    // A toast is read once. "Part of this collection is not indexed" is a
    // state of the system, not an event, so it has to outlive the toast.
    await reindexReturning({
      indexed: 100000,
      skipped: 0,
      purged: false,
      collection: COLLECTION,
      scanned: 100000,
      cap: 100000,
      truncated: true,
    });

    expect(await screen.findByText(/not reindexed/i)).toBeTruthy();
  });

  it('reports a complete pass as a success even though it now carries a limit', async () => {
    // Every response carries `cap` and `scanned` now, truncated or not. A pass
    // that fit inside the ceiling is an ordinary success and must not inherit
    // the warning from the presence of those keys.
    //
    // Deliberately green on both sides of the change - the other three in this
    // group fail against the previous card and this one does not. It is the
    // control: without it, "warn on truncation" could be satisfied by warning
    // on any response that carries the new keys at all, and the suite would
    // not notice.
    const toast = await reindexReturning({
      indexed: 900,
      skipped: 0,
      purged: false,
      collection: COLLECTION,
      scanned: 900,
      cap: 100000,
      truncated: false,
    });

    expect(toast.type).toBe('success');
    expect(screen.queryByText(/not reindexed/i)).toBeNull();
  });

  it('treats partial skipping as a success, because rows without text always skip', async () => {
    // The guard is deliberately narrow. Rows with no indexable text are
    // ordinary and skip on every healthy run, so warning about them would
    // cry wolf until the warning stopped meaning anything.
    const toast = await reindexReturning({
      indexed: 900,
      skipped: 300,
      purged: false,
      collection: COLLECTION,
    });

    expect(toast.type).toBe('success');
  });
});
