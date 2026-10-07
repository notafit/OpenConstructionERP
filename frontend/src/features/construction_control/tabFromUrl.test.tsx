// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Construction Control's tab lives in ?tab=. It used to be component state,
 * so /projects/:projectId/construction-control?tab=handover opened on
 * Inspections and a closeout case could only say "open the Handover tab".
 * These tests pin that the link opens the tab it names, that the param stays,
 * that a click writes it back (replacing, keeping the other params), and that
 * a link followed while the page is open switches the tab.
 *
 * Run:  npx vitest run src/features/construction_control/tabFromUrl.test.tsx
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, cleanup, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, useLocation, useNavigate, useNavigationType } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { tabIds } from '@/shared/ui';

// Every section is rendered through the automocked API, as in
// ConstructionControlPage.test.tsx; the list endpoints are set below.
vi.mock('./api');

import {
  listCriteria,
  listInspections,
  listMaterials,
  listTestResults,
  listAsBuilt,
  listGates,
  listHandoverPackages,
} from './api';
import { ConstructionControlPage } from './ConstructionControlPage';
import { CONSTRUCTION_CONTROL_TABS, DEFAULT_CONSTRUCTION_CONTROL_TAB } from './constructionControlTabs';

const PROJECT_ID = 'proj-1';

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
        <ConstructionControlPage />
        <Probe follow={follow} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const selected = (id: string) => screen.getByTestId(`cc-tab-${id}`).getAttribute('aria-selected');

const PAGE = `/projects/${PROJECT_ID}/construction-control`;

beforeEach(() => {
  vi.clearAllMocks();
  for (const list of [listCriteria, listInspections, listMaterials, listTestResults, listAsBuilt, listGates, listHandoverPackages]) {
    (list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
  }
  useProjectContextStore.getState().setActiveProject(PROJECT_ID, 'Riverside HQ');
});

afterEach(() => cleanup());

describe('the Construction Control tab in the URL', () => {
  it('opens on the Handover tab a link names, and leaves the param in place', async () => {
    renderAt(`${PAGE}?tab=handover`);

    expect(selected('handover')).toBe('true');
    expect(selected('inspections')).toBe('false');
    await waitFor(() => expect(listHandoverPackages).toHaveBeenCalledWith(PROJECT_ID));
    expect(listInspections).not.toHaveBeenCalled();
    expect(screen.getByTestId('search').textContent).toBe('?tab=handover');
  });

  it('falls back to Inspections on a value it does not know', () => {
    renderAt(`${PAGE}?tab=closeout`);

    expect(selected('inspections')).toBe('true');
  });

  it('opens on Inspections without a tab param, and writes nothing', () => {
    renderAt(PAGE);

    expect(selected('inspections')).toBe('true');
    expect(screen.getByTestId('search').textContent).toBe('');
    expect(screen.getByTestId('nav-type').textContent).toBe('POP');
  });

  it('writes a tab click back to the URL, replacing, and keeps the other params', () => {
    renderAt(`${PAGE}?highlight=h-1&tab=gates`);

    fireEvent.click(screen.getByTestId('cc-tab-handover'));

    expect(selected('handover')).toBe('true');
    const params = new URLSearchParams(screen.getByTestId('search').textContent ?? '');
    expect(params.get('tab')).toBe('handover');
    expect(params.get('highlight')).toBe('h-1');
    expect(screen.getByTestId('nav-type').textContent).toBe('REPLACE');
  });

  it('renders exactly the tabs constructionControlTabs.ts lists, so a link checked against it is real', () => {
    renderAt(PAGE);

    const tablist = screen.getByRole('tablist', { name: 'Construction control sections' });
    const rendered = within(tablist).getAllByRole('tab').map((tab) => tab.id);
    expect(rendered).toEqual(CONSTRUCTION_CONTROL_TABS.map((id) => tabIds('construction-control').tabId(id)));
    expect(CONSTRUCTION_CONTROL_TABS).toContain(DEFAULT_CONSTRUCTION_CONTROL_TAB);
  });

  it('switches tab when a link is followed while the page is open', () => {
    renderAt(`${PAGE}?tab=materials`, `${PAGE}?tab=handover`);

    expect(selected('materials')).toBe('true');

    fireEvent.click(screen.getByRole('button', { name: 'follow link' }));

    expect(selected('handover')).toBe('true');
    expect(selected('materials')).toBe('false');
  });
});
