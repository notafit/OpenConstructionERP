// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A workspace names screens by route. The sidebar drops a row it cannot
// resolve (`resolveWorkspace`), and both pages behind the tab rows open their
// default tab on a `?tab=` value they do not know. So a renamed route or tab
// would take a screen out of a general contractor's menu, or quietly send the
// Pay-application row to the Contracts list, and nothing on screen would say
// so. These tests are where that shows up instead.
//
// Whether a menu row's own route mounts is `navCatalog.test.ts`'s question;
// here the question is only whether every workspace row lands on a menu row.

import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { CONTRACTS_TABS, DEFAULT_CONTRACTS_TAB } from '@/features/contracts/contractsTabs';
import { DEFAULT_FINANCE_TAB, FINANCE_TABS } from '@/features/finance/financeTabs';
import {
  NAV_ITEM_BY_ROUTE,
  PAGE_TABS,
  PRESET_WORKSPACES,
  WORKSPACE_BASICS,
  resolveWorkspace,
  resolveWorkspaceRow,
  shownTab,
  workspaceFor,
} from './workspaces';

/** Read a repo file relative to `frontend/` or the repo root, the way
 *  `navCatalog.test.ts` does (`import.meta.url` is not usable under this
 *  vitest config on Windows). */
function readRepoFile(fromFrontend: string): string {
  const candidates = [
    resolve(process.cwd(), fromFrontend),
    resolve(process.cwd(), 'frontend', fromFrontend),
  ];
  const found = candidates.find(existsSync);
  if (!found) throw new Error(`cannot find ${fromFrontend}, looked in ${candidates.join(' and ')}`);
  return readFileSync(found, 'utf8');
}

const allRows = Object.values(PRESET_WORKSPACES).flatMap((workspace) =>
  workspace.rows.map((row) => ({ workspace: workspace.presetKey, row })),
);

describe('workspace rows', () => {
  it('each land on a menu row, as the row itself or as a tab of it', () => {
    const lost: string[] = [];
    for (const { workspace, row } of allRows) {
      if (resolveWorkspaceRow(row) === null) lost.push(`${workspace}: ${row.to}`);
    }
    expect(lost).toEqual([]);
  });

  it('name their own label and icon only when they are a tab, and a real tab', () => {
    const wrong: string[] = [];
    for (const { workspace, row } of allRows) {
      const [path, query] = row.to.split('?');
      if (!query) continue;
      if (NAV_ITEM_BY_ROUTE.has(row.to)) {
        wrong.push(`${workspace}: ${row.to} is a menu row already, list it without a label`);
        continue;
      }
      if (!row.labelKey || !row.defaultLabel || !row.icon) {
        wrong.push(`${workspace}: ${row.to} is a tab row and needs labelKey, defaultLabel and icon`);
      }
      const params = new URLSearchParams(query);
      const tab = params.get('tab');
      if (tab === null || [...params.keys()].length !== 1) {
        wrong.push(`${workspace}: ${row.to} may carry ?tab= and nothing else`);
        continue;
      }
      // PAGE_TABS is also what lets the plain page address light its default
      // tab row, so a page missing there fails here rather than in the menu.
      const tabs = PAGE_TABS.get(path!)?.tabs;
      if (!tabs) {
        wrong.push(`${workspace}: ${row.to} opens a page with no entry in PAGE_TABS`);
      } else if (!tabs.includes(tab)) {
        wrong.push(`${workspace}: ${row.to} names tab '${tab}', the page has ${tabs.join(', ')}`);
      }
    }
    expect(wrong).toEqual([]);
  });

  it('list each screen once per workspace', () => {
    for (const workspace of Object.values(PRESET_WORKSPACES)) {
      const routes = workspace.rows.map((row) => row.to);
      expect(new Set(routes).size, workspace.presetKey).toBe(routes.length);
    }
  });

  it('open with the basics every workspace shares', () => {
    for (const workspace of Object.values(PRESET_WORKSPACES)) {
      expect(workspace.rows.slice(0, WORKSPACE_BASICS.length), workspace.presetKey).toEqual(
        WORKSPACE_BASICS,
      );
    }
  });
});

describe('workspace keys', () => {
  it('are company preset keys the backend registry knows', () => {
    const registry = readRepoFile('../backend/app/core/onboarding_presets.py');
    const unknown = Object.keys(PRESET_WORKSPACES).filter(
      (key) => !registry.includes(`"${key}": CompanyPreset(`),
    );
    expect(unknown).toEqual([]);
  });

  it('match the preset each workspace says it belongs to', () => {
    for (const [key, workspace] of Object.entries(PRESET_WORKSPACES)) {
      expect(workspace.presetKey).toBe(key);
      expect(workspaceFor(key)).toBe(workspace);
    }
    expect(workspaceFor(null)).toBeNull();
    expect(workspaceFor('estimator')).toBeNull();
    // Not an own key, so not a workspace, however the object is built.
    expect(workspaceFor('toString')).toBeNull();
  });
});

describe('the general contractor workspace', () => {
  it('is the monthly billing cycle, in this order', () => {
    const workspace = workspaceFor('general_contractor');
    expect(workspace).not.toBeNull();
    expect(resolveWorkspace(workspace!).map((item) => [item.to, item.labelKey])).toEqual([
      ['/', 'nav.dashboard'],
      ['/inbox', 'nav.inbox'],
      ['/projects', 'projects.title'],
      ['/boq', 'boq.title'],
      ['/finance?tab=budgets', 'finance.budgets'],
      ['/contracts', 'nav.contracts'],
      ['/subcontractors', 'nav.subcontractors'],
      ['/changeorders', 'nav.change_orders'],
      ['/contracts?tab=claims', 'contracts.tab_claims'],
      ['/finance?tab=payments', 'finance.payments'],
      ['/finance?tab=retention', 'finance.retention_tab'],
      ['/schedule', 'schedule.title'],
      ['/daily-diary', 'nav.daily_diary'],
      ['/punchlist', 'nav.punchlist'],
      ['/closeout', 'closeout.title'],
    ]);
  });

});

describe('resolving a row', () => {
  const scheduleRow = NAV_ITEM_BY_ROUTE.get('/schedule')!;

  it('keeps a menu row whole, so its module gate and tour hook still apply', () => {
    expect(resolveWorkspaceRow({ to: '/schedule' })).toEqual(scheduleRow);
    expect(resolveWorkspaceRow({ to: '/boq' })?.tourId).toBe('boq');
  });

  it('gives a tab row the gates of the screen it opens and nothing else', () => {
    const tab = resolveWorkspaceRow({
      to: '/schedule?tab=gantt',
      labelKey: 'schedule.title',
      defaultLabel: 'Schedule',
      icon: scheduleRow.icon,
    });
    expect(tab).toEqual({
      labelKey: 'schedule.title',
      defaultLabel: 'Schedule',
      to: '/schedule?tab=gantt',
      icon: scheduleRow.icon,
      moduleKey: 'schedule',
      roleGate: undefined,
      adminOnly: undefined,
    });
  });

  it('refuses a tab row with no label of its own, and a route with no menu row', () => {
    expect(resolveWorkspaceRow({ to: '/schedule?tab=gantt' })).toBeNull();
    expect(resolveWorkspaceRow({ to: '/no-such-screen' })).toBeNull();
  });
});

describe('the tab a page shows', () => {
  it('comes from the pages\' own tab lists and defaults, not a copy', () => {
    expect(PAGE_TABS.get('/contracts')?.tabs).toBe(CONTRACTS_TABS);
    expect(PAGE_TABS.get('/contracts')?.defaultTab).toBe(DEFAULT_CONTRACTS_TAB);
    expect(PAGE_TABS.get('/finance')?.tabs).toBe(FINANCE_TABS);
    expect(PAGE_TABS.get('/finance')?.defaultTab).toBe(DEFAULT_FINANCE_TAB);
    for (const [path, page] of PAGE_TABS) {
      expect(page.tabs, path).toContain(page.defaultTab);
    }
  });

  it('is the default when the address names no tab, or one the page does not have', () => {
    expect(shownTab('/finance', new URLSearchParams(''))).toBe('budgets');
    expect(shownTab('/finance', new URLSearchParams('tab=no-such-tab'))).toBe('budgets');
    expect(shownTab('/finance', new URLSearchParams('tab=retention'))).toBe('retention');
    expect(shownTab('/contracts', new URLSearchParams(''))).toBe('contracts');
  });

  it('is the address as written on a page it knows nothing about', () => {
    expect(shownTab('/takeoff', new URLSearchParams('tab=measurements'))).toBe('measurements');
    expect(shownTab('/takeoff', new URLSearchParams(''))).toBeNull();
  });
});
