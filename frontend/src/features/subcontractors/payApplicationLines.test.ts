// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The route answering with a page is only half the promise. Its reader
// approves an amount on every line and totals what is payable, so handing it
// a first page would have someone confirm part of a payment on a screen that
// reads as the whole of it. What is pinned here:
//
//   * the whole set comes back, however many pages it took;
//   * the second request asks for what is still missing, not for the same
//     rows again;
//   * a page that comes back empty ends the walk rather than looping for ever
//     on an offset that is not moving.

import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet: vi.fn() };
});

import { apiGet } from '@/shared/lib/api';
import { listPaymentApplicationLines, type PaymentApplicationLine } from './api';

const getMock = vi.mocked(apiGet);

function line(id: string): PaymentApplicationLine {
  return {
    id,
    payment_application_id: 'pa-1',
    work_package_id: `wp-${id}`,
    claimed_amount: '100.00',
    certified_amount: '0.00',
    approved_amount: '0.00',
  } as PaymentApplicationLine;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('listPaymentApplicationLines', () => {
  it('returns the one page when the page holds the whole pay application', async () => {
    getMock.mockResolvedValue({ items: [line('a'), line('b')], total: 2, offset: 0, limit: 500 });
    expect((await listPaymentApplicationLines('pa-1')).map((l) => l.id)).toEqual(['a', 'b']);
    expect(getMock).toHaveBeenCalledTimes(1);
  });

  it('follows the pages to the end, asking each time for what it is missing', async () => {
    getMock
      .mockResolvedValueOnce({ items: [line('a'), line('b')], total: 3, offset: 0, limit: 2 })
      .mockResolvedValueOnce({ items: [line('c')], total: 3, offset: 2, limit: 2 });
    expect((await listPaymentApplicationLines('pa-1')).map((l) => l.id)).toEqual(['a', 'b', 'c']);
    expect(getMock).toHaveBeenCalledTimes(2);
    expect(String(getMock.mock.calls[1]?.[0])).toContain('offset=2');
  });

  it('stops when a page comes back empty, rather than asking for ever', async () => {
    // A total that no page can satisfy: without the guard this walks for ever.
    getMock.mockResolvedValue({ items: [], total: 7, offset: 0, limit: 500 });
    expect(await listPaymentApplicationLines('pa-1')).toEqual([]);
    // One ask for the rest, then it gives up: the offset would not move.
    expect(getMock).toHaveBeenCalledTimes(2);
  });
});
