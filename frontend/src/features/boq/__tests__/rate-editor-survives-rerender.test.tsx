// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * An open Unit Rate editor must survive a re-render of the grid.
 *
 * Reported as "when I put a price in the BOQ the app freezes". Clicking the
 * rate cell of a row that was not the active one opened the editor, reported
 * the row as active, and the editor page re-rendered BOQGrid. The grid then
 * handed AG Grid a freshly built `rowSelection` object, which AG Grid treats as
 * a settings change: it stopped the editor and rebuilt every rendered row. The
 * price typed next landed on the page body and was never saved.
 *
 * This drives the real grid. It re-renders BOQGrid with new callback
 * identities for the same data, exactly what the page does on a row click,
 * and checks that the editor is still open and still commits what was typed.
 */
import { describe, it, expect, vi, beforeAll, afterEach } from 'vitest';
import { render, cleanup, fireEvent, act } from '@testing-library/react';
import { createElement } from 'react';

import BOQGrid from '../BOQGrid';
import type { Position } from '../api';

vi.mock('@/features/collab_locks', () => ({
  acquireLock: vi.fn(async () => ({ ok: true, lock: { id: 'lock-test' } })),
  releaseLock: vi.fn(async () => undefined),
}));

// jsdom has no layout: give every element a viewport-sized box or AG Grid
// renders zero rows and the test passes for the wrong reason.
beforeAll(() => {
  for (const prop of ['clientHeight', 'offsetHeight'] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => 800 });
  }
  for (const prop of ['clientWidth', 'offsetWidth'] as const) {
    Object.defineProperty(HTMLElement.prototype, prop, { configurable: true, get: () => 1600 });
  }
  HTMLElement.prototype.getBoundingClientRect = function () {
    return {
      width: 1600, height: 800, top: 0, left: 0, bottom: 800, right: 1600,
      x: 0, y: 0, toJSON: () => ({}),
    } as DOMRect;
  };
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() { return this.parentElement; },
  });
});

afterEach(() => {
  cleanup();
});

function makePosition(n: number): Position {
  return {
    id: `pos-${n}`,
    boq_id: 'boq-1',
    ordinal: `01.0${n}`,
    description: `Position ${n}`,
    unit: 'm2',
    quantity: 10 + n,
    unit_rate: 0,
    total: 0,
    parent_id: null,
    position_type: 'position',
    validation_status: 'valid',
    metadata: {},
  } as unknown as Position;
}

const positions = [makePosition(1), makePosition(2), makePosition(3)];
const collapsedSections = new Set<string>();

function gridElement(onUpdatePosition: (...args: unknown[]) => void) {
  // Fresh arrow functions on every call, the way BOQEditorPage passes them
  // whenever it re-renders.
  return createElement(BOQGrid, {
    positions,
    onUpdatePosition,
    onDeletePosition: () => undefined,
    onAddPosition: () => undefined,
    onSelectSuggestion: () => undefined,
    onSaveToDatabase: () => undefined,
    onFormulaApplied: () => undefined,
    onActiveRowChange: () => undefined,
    collapsedSections,
    onToggleSection: () => undefined,
    currencySymbol: '€',
    currencyCode: 'EUR',
    locale: 'hr-HR',
    footerRows: [],
  });
}

function editingCells(): Element[] {
  return Array.from(document.querySelectorAll('.ag-cell-inline-editing, .ag-popup-editor'));
}

function activeEditorInput(): HTMLInputElement | null {
  return document.querySelector<HTMLInputElement>(
    '.ag-cell-inline-editing input, .ag-popup-editor input',
  );
}

async function flush(ms = 0) {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });
}

async function waitUntil(cond: () => boolean, what: string, timeoutMs = 4000) {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > timeoutMs) throw new Error(`timed out waiting for: ${what}`);
    await flush(25);
  }
}

async function openEditorByDoubleClick(rowId: string, colId: string) {
  const target = document.querySelector<HTMLElement>(
    `.ag-row[row-id="${rowId}"] .ag-cell[col-id="${colId}"]`,
  );
  if (!target) throw new Error(`cell ${rowId}/${colId} not rendered`);
  await act(async () => {
    fireEvent.mouseDown(target);
    fireEvent.mouseUp(target);
    fireEvent.click(target);
    fireEvent.mouseDown(target);
    fireEvent.mouseUp(target);
    fireEvent.click(target, { detail: 2 });
    fireEvent.doubleClick(target);
  });
  await flush(20);
}

describe('Unit Rate editor and parent re-renders', () => {
  it('stays open across a re-render and commits the typed price', async () => {
    const onUpdatePosition = vi.fn();
    const { rerender } = render(gridElement(onUpdatePosition));
    await waitUntil(() => !!document.querySelector('.ag-row[row-id="pos-2"]'), 'rows rendered');

    await openEditorByDoubleClick('pos-2', 'unit_rate');
    await waitUntil(() => editingCells().length > 0, 'rate editor open');
    const input = activeEditorInput();
    expect(input, 'rate editor input must exist').toBeTruthy();

    // The page re-renders the grid while the editor is open.
    rerender(gridElement(onUpdatePosition));
    await flush(50);
    rerender(gridElement(onUpdatePosition));
    await flush(50);

    expect(editingCells().length, 'a parent re-render must not close the rate editor').toBeGreaterThan(0);
    expect(activeEditorInput(), 'the same input must still be mounted').toBe(input);

    await act(async () => {
      fireEvent.input(input!, { target: { value: '12,50' } });
      fireEvent.keyDown(input!, { key: 'Enter' });
    });
    await waitUntil(
      () => onUpdatePosition.mock.calls.some((c) => c[0] === 'pos-2'),
      'price commit dispatched',
    );
    expect(onUpdatePosition).toHaveBeenCalledWith(
      'pos-2',
      expect.objectContaining({ unit_rate: 12.5 }),
      expect.anything(),
    );
  });
});
