// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A claim's period is printed by one component, in the claims list and in the
// claim's own header. The list used to format the typed period_start while
// the header preferred the parsed period_from, so one claim could read as two
// different periods, or as a dash, depending on where it was opened.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const api = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
}));

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'p-1',
}));

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), insights: [], kpis: [], series: [] }),
}));

import { DateDisplay } from '@/shared/ui/DateDisplay';
import { ClaimPeriod } from './ClaimPeriod';
import { ContractsPage } from './ContractsPage';
import type { ProgressClaimItem } from './api';

/** What the app's date formatter prints for `value`, so no locale is assumed. */
function formatted(value: string): string {
  const { container, unmount } = render(<DateDisplay value={value} />);
  const text = container.textContent ?? '';
  unmount();
  return text;
}

function periodText(claim: Parameters<typeof ClaimPeriod>[0]['claim']): string {
  const { container, unmount } = render(<ClaimPeriod claim={claim} />);
  const text = container.textContent ?? '';
  unmount();
  return text;
}

const TYPED_AND_PARSED = {
  period_start: 'first of May',
  period_end: 'end of May',
  period_from: '2026-05-01',
  period_to: '2026-05-31',
};

afterEach(() => cleanup());

describe('ClaimPeriod', () => {
  it('prints the parsed dates through the date formatter, not the typed string', () => {
    const text = periodText(TYPED_AND_PARSED);
    expect(text).toBe(`${formatted('2026-05-01')} → ${formatted('2026-05-31')}`);
    expect(text).not.toContain('first of May');
  });

  it('formats a typed ISO date when the parsed one is missing', () => {
    // A claim written before the parsed dates existed.
    const text = periodText({ period_start: '2026-05-01', period_end: '2026-05-31' });
    expect(text).toBe(`${formatted('2026-05-01')} → ${formatted('2026-05-31')}`);
  });

  it('shows a string the server could not read as it was typed, not as a dash', () => {
    const text = periodText({ period_start: 'Mai 2026', period_end: '', period_from: null, period_to: null });
    expect(text).toBe('Mai 2026 → —');
  });
});

describe('the claims list', () => {
  const CONTRACT = {
    id: 'ctr-1',
    code: 'C-001',
    title: 'Main works',
    contract_type: 'lump_sum',
    counterparty_type: 'client',
    counterparty_id: null,
    project_id: 'p-1',
    status: 'active',
    currency: 'EUR',
    total_value: '1000',
    retention_percent: '5',
    metadata: {},
  };
  const CLAIM: ProgressClaimItem = {
    id: 'claim-7',
    contract_id: 'ctr-1',
    claim_number: 'PC-0007',
    ...TYPED_AND_PARSED,
    claim_date: null,
    gross_amount: '400',
    retention_amount: '20',
    prior_claims_total: '0',
    net_due: '380',
    status: 'draft',
    submitted_at: null,
    approved_at: null,
    paid_at: null,
    currency: 'EUR',
    metadata: {},
    created_at: '2026-05-01T00:00:00Z',
    updated_at: '2026-05-01T00:00:00Z',
  } as ProgressClaimItem;

  const page = <T,>(items: T[]) => Promise.resolve({ items, total: items.length, offset: 0, limit: 200 });

  // The register and the claims list answer with a page envelope, and
  // listContracts / listProgressClaims type the call as Page<T>. Both routes
  // spell the envelope out below rather than build it with the helper above,
  // so the shape is readable beside the route it belongs to - by a person,
  // and by scripts/check_page_envelope_consumers.py, which judges a call site
  // by the text around it and can follow neither a helper nor a long comment.
  beforeEach(() => {
    api.apiGet.mockReset();
    api.apiGet.mockImplementation((path: string) => {
      if (path.startsWith('/v1/projects/')) return Promise.resolve([{ id: 'p-1', name: 'Riverside', currency: 'EUR' }]);
      if (path.startsWith('/v1/contracts/progress-claims/?'))
        return Promise.resolve({ items: [CLAIM], total: 1, offset: 0, limit: 200 });
      if (path.startsWith('/v1/contracts/contracts/?'))
        return Promise.resolve({ items: [CONTRACT], total: 1, offset: 0, limit: 200 });
      if (path.includes('?')) return page([]);
      return Promise.resolve([]);
    });
  });

  it("prints the claim's period the way the claim's own header does", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/contracts?tab=claims']}>
          <ContractsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    const row = (await screen.findByText('PC-0007')).closest('tr') as HTMLElement;
    const periodCell = within(row).getAllByRole('cell')[1] as HTMLElement;
    expect(periodCell.textContent?.trim()).toBe(periodText(CLAIM));
    expect(periodCell.textContent).not.toContain('first of May');
  });
});
