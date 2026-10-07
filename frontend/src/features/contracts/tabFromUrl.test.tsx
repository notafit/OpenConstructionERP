// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The register's tab lives in ?tab=, so a menu row, a guide step or a case
// can open it straight on Progress Claims (/contracts?tab=claims) and a
// reload keeps the tab. These tests run the real router, not a stubbed
// useSearchParams: what they pin is the round trip, mount reads the URL, a
// click writes it, and a link followed while the page is open switches the
// tab it names.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate, useNavigationType } from 'react-router-dom';

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

import { ContractsPage } from './ContractsPage';
import { CONTRACTS_TABS, DEFAULT_CONTRACTS_TAB } from './contractsTabs';

const PROJECT = { id: 'p-1', name: 'Riverside', currency: 'EUR' };

/** Every list answers empty: which tab is showing does not depend on rows. */
function routeGet(): void {
  api.apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/projects/')) return Promise.resolve([PROJECT]);
    if (path.includes('?')) return Promise.resolve({ items: [], total: 0, offset: 0, limit: 200 });
    return Promise.resolve([]);
  });
}

/** Prints the live URL and the last history action, and follows a link on demand. */
function Probe({ follow }: { follow?: string }) {
  const location = useLocation();
  const navigationType = useNavigationType();
  const navigate = useNavigate();
  return (
    <>
      <span data-testid="search">{location.search}</span>
      <span data-testid="nav-type">{navigationType}</span>
      {follow && (
        <button type="button" onClick={() => navigate(follow)}>
          follow link
        </button>
      )}
    </>
  );
}

function renderAt(entry: string, follow?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[entry]}>
        <ContractsPage />
        <Probe follow={follow} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const statusFilter = () =>
  screen.getByLabelText('Filter contracts by status') as HTMLSelectElement;
const searchBox = () => screen.getByPlaceholderText('Search…') as HTMLInputElement;

beforeEach(() => {
  api.apiGet.mockReset();
  routeGet();
});

afterEach(() => cleanup());

describe('the contracts register tab in the URL', () => {
  it('opens on Progress Claims when the link says ?tab=claims', async () => {
    renderAt('/contracts?tab=claims');

    // The header action follows the tab: only the claims tab offers a new claim.
    expect(await screen.findByRole('button', { name: /New Claim/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /New Contract/ })).toBeNull();
    // Read, not consumed: the param is still there for a reload or a menu row.
    expect(screen.getByTestId('search').textContent).toBe('?tab=claims');
  });

  it('falls back to the Contracts tab on a value it does not know', async () => {
    renderAt('/contracts?tab=pay-apps');

    expect(await screen.findByRole('button', { name: /New Contract/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /New Claim/ })).toBeNull();
  });

  it('opens on the Contracts tab without a tab param, and writes nothing', async () => {
    renderAt('/contracts');

    expect(await screen.findByRole('button', { name: /New Contract/ })).toBeTruthy();
    expect(screen.getByTestId('search').textContent).toBe('');
    expect(screen.getByTestId('nav-type').textContent).toBe('POP');
  });

  it('writes a tab click back to the URL, replacing, and keeps the other params', async () => {
    renderAt('/contracts?counterparty=sub-9');

    fireEvent.click(await screen.findByRole('button', { name: /Final Accounts/ }));

    const params = new URLSearchParams(screen.getByTestId('search').textContent ?? '');
    expect(params.get('tab')).toBe('final_accounts');
    expect(params.get('counterparty')).toBe('sub-9');
    expect(screen.getByTestId('nav-type').textContent).toBe('REPLACE');
  });

  it('offers exactly the tabs contractsTabs.ts lists, so a link checked against it is real', async () => {
    renderAt('/contracts');

    const claimsButton = await screen.findByRole('button', { name: /Progress Claims/ });
    const tabNav = claimsButton.closest('nav') as HTMLElement;
    const written: string[] = [];
    for (const button of within(tabNav).getAllByRole('button')) {
      fireEvent.click(button);
      written.push(new URLSearchParams(screen.getByTestId('search').textContent ?? '').get('tab') ?? '');
    }
    expect(written).toEqual([...CONTRACTS_TABS]);
    expect(CONTRACTS_TABS).toContain(DEFAULT_CONTRACTS_TAB);
  });

  it('switches tab and clears the filters when a link is followed while the page is open', async () => {
    renderAt('/contracts', '/contracts?tab=claims');

    await screen.findByRole('button', { name: /New Contract/ });
    fireEvent.change(searchBox(), { target: { value: 'MC-01' } });
    fireEvent.change(statusFilter(), { target: { value: 'active' } });
    expect(searchBox().value).toBe('MC-01');
    expect(statusFilter().value).toBe('active');

    fireEvent.click(screen.getByRole('button', { name: 'follow link' }));

    expect(await screen.findByRole('button', { name: /New Claim/ })).toBeTruthy();
    // The search box is the witness that the state was cleared: a select whose
    // value has no option on the new tab reads '' in the DOM either way. A
    // contract status carried onto the claims list would hide every claim.
    expect(searchBox().value).toBe('');
    expect(statusFilter().value).toBe('');
  });
});
