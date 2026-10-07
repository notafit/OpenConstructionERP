// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The Modules page states how many menu entries Simple mode hides. If that
 * number is wrong the notice is worse than absent, because it invites the user
 * to trust a figure that does not match what the sidebar does.
 */
import { describe, it, expect } from 'vitest';
import { navGroups } from '@/app/layout/navCatalog';
import type { NavGroup } from '@/app/layout/navCatalog';
import { countAdvancedOnlyEntries } from './advancedModeGap';

const icon = (() => null) as unknown as NavGroup['items'][number]['icon'];

function group(id: string, items: Partial<NavGroup['items'][number]>[], hideInSimple = false): NavGroup {
  return {
    id,
    labelKey: `sidebar.group.${id}`,
    items: items.map((item, index) => ({
      labelKey: `nav.${id}_${index}`,
      to: `/${id}/${index}`,
      icon,
      ...item,
    })),
    defaultOpen: false,
    ...(hideInSimple ? { hideInSimple: true } : {}),
  };
}

describe('countAdvancedOnlyEntries', () => {
  it('counts an entry hidden by its own advancedOnly flag', () => {
    const gap = countAdvancedOnlyEntries([group('a', [{ advancedOnly: true }, {}])]);
    expect(gap).toEqual({ hidden: 1, total: 2 });
  });

  it('counts every entry of a group hidden as a whole', () => {
    const gap = countAdvancedOnlyEntries([group('a', [{}, {}, {}], true)]);
    expect(gap).toEqual({ hidden: 3, total: 3 });
  });

  it('does not double-count an advancedOnly entry inside a hidden group', () => {
    const gap = countAdvancedOnlyEntries([group('a', [{ advancedOnly: true }, {}], true)]);
    expect(gap).toEqual({ hidden: 2, total: 2 });
  });

  it('reports nothing hidden when neither rule applies', () => {
    const gap = countAdvancedOnlyEntries([group('a', [{}, {}])]);
    expect(gap).toEqual({ hidden: 0, total: 2 });
  });

  /**
   * The two assertions below are what make the notice honest against the live
   * catalogue, and they fail in both directions on purpose.
   *
   * If every entry became visible in Simple mode the notice would be a lie and
   * `hidden > 0` fails. If someone flagged the whole catalogue `advancedOnly`
   * the Simple mode would be empty and `hidden < total` fails. Either way the
   * page stops claiming a gap that does not match the sidebar.
   */
  it('finds a real gap in the shipped catalogue', () => {
    const { hidden, total } = countAdvancedOnlyEntries();
    expect(total).toBeGreaterThan(0);
    expect(hidden).toBeGreaterThan(0);
    expect(hidden).toBeLessThan(total);
  });

  /**
   * The group rule is easy to drop, because `advancedOnly` alone reads like the
   * whole story. Recount with only the item flag and assert the two disagree:
   * the day they stop disagreeing, either the catalogue changed or the function
   * quietly lost half its job, and both deserve a red test.
   */
  it('counts strictly more than the per-entry flag alone', () => {
    const itemFlagOnly = navGroups.reduce(
      (sum, g) => sum + g.items.filter((item) => item.advancedOnly).length,
      0,
    );
    expect(countAdvancedOnlyEntries().hidden).toBeGreaterThan(itemFlagOnly);
  });
});
