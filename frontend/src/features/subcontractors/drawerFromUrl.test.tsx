// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// /subcontractors?sub=<id>&subtab=<tab> opens one firm's drawer on one tab,
// so a guide step or a case can link to that firm's payments or retention.
// Unlike ?highlight, which opens the drawer and then leaves the URL, ?sub
// stays while the drawer is open, a tab switch rewrites ?subtab, and closing
// takes both out. ?highlight keeps working exactly as before, and the last
// test here pins that. The real router runs underneath: these tests read the
// URL the page leaves behind, not the calls it made.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigationType } from 'react-router-dom';

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

vi.mock('@/features/insights', () => ({
  InsightsPanel: () => null,
  InsightsToggleButton: () => null,
  useModuleInsights: () => ({ open: false, toggle: vi.fn(), custom: [] }),
}));

import { SubcontractorsPage } from './SubcontractorsPage';
import type { Subcontractor } from './api';

const SUB: Subcontractor = {
  id: 's-1',
  legal_name: 'Keystone Drywall LLC',
  trade_name: null,
  tax_id: null,
  trade_categories: ['drywall'],
  prequalification_status: 'approved',
  rating_score: 4,
  country: 'US',
  is_active: true,
  insurance_expiry_date: null,
  is_blocked: false,
  metadata: {},
  created_at: '2026-01-01T09:00:00Z',
  updated_at: '2026-01-01T09:00:00Z',
};

/** The register lists one firm with no agreements. The per-firm rollups the
 *  drawer header reads (dashboard, award eligibility, prequal) are refused:
 *  each degrades on its own and none decides which tab is showing. */
function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/subcontractors/subcontractors/?')) {
      return Promise.resolve({ items: [SUB], total: 1, offset: 0, limit: 200 });
    }
    if (path === '/v1/subcontractors/subcontractors/s-1') return Promise.resolve(SUB);
    if (/\/(dashboard|award-eligibility|prequal)$/.test(path)) {
      return Promise.reject(new Error(`not served in this test: ${path}`));
    }
    // Agreements, ratings, certificates and lien waivers are lists on the wire.
    return Promise.resolve([]);
  });
}

/** Prints the live URL and the last history action. */
function Probe() {
  const location = useLocation();
  const navigationType = useNavigationType();
  return (
    <>
      <span data-testid="search">{location.search}</span>
      <span data-testid="nav-type">{navigationType}</span>
    </>
  );
}

function renderAt(entry: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <SubcontractorsPage />
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const params = () => new URLSearchParams(screen.getByTestId('search').textContent ?? '');

/** The drawer's heading carries the firm's name once its record has loaded. */
const drawerHeading = () => screen.findByRole('heading', { name: 'Keystone Drywall LLC' });

beforeEach(() => {
  api.apiGet.mockReset();
  routeGet();
});

afterEach(() => cleanup());

describe('a link into one subcontractor drawer tab', () => {
  it('opens the named firm on the named tab and keeps both params', async () => {
    renderAt('/subcontractors?sub=s-1&subtab=retention');

    await drawerHeading();
    expect(await screen.findByText('No retention ledger')).toBeTruthy();
    expect(screen.queryByText('No agreements yet')).toBeNull();
    expect(params().get('sub')).toBe('s-1');
    expect(params().get('subtab')).toBe('retention');
  });

  it('falls back to the Scope tab on a value it does not know', async () => {
    renderAt('/subcontractors?sub=s-1&subtab=waivers');

    await drawerHeading();
    expect(await screen.findByText('No agreements yet')).toBeTruthy();
  });

  it('writes a tab switch back to ?subtab, replacing, and keeps ?sub', async () => {
    renderAt('/subcontractors?sub=s-1');

    await drawerHeading();
    fireEvent.click(screen.getByRole('button', { name: 'Payments' }));

    expect(await screen.findByText('No payments yet')).toBeTruthy();
    expect(params().get('sub')).toBe('s-1');
    expect(params().get('subtab')).toBe('payments');
    expect(screen.getByTestId('nav-type').textContent).toBe('REPLACE');
  });

  it('takes ?sub and ?subtab out of the URL when the drawer is closed', async () => {
    renderAt('/subcontractors?sub=s-1&subtab=ratings&q=keep');

    await drawerHeading();
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));

    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Keystone Drywall LLC' })).toBeNull());
    expect(params().get('sub')).toBeNull();
    expect(params().get('subtab')).toBeNull();
    expect(params().get('q')).toBe('keep');
  });

  it('leaves ?highlight as it was: opens the drawer, drops the param, writes no ?sub', async () => {
    renderAt('/subcontractors?highlight=s-1');

    await drawerHeading();
    await waitFor(() => expect(params().get('highlight')).toBeNull());
    expect(params().get('sub')).toBeNull();

    // A drawer not opened by ?sub keeps its tab to itself.
    fireEvent.click(screen.getByRole('button', { name: 'Retention' }));
    expect(await screen.findByText('No retention ledger')).toBeTruthy();
    expect(params().get('subtab')).toBeNull();
  });
});
