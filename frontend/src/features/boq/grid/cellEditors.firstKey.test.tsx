/**
 * The key that opens an editor is the first character of what is typed.
 *
 * Tab from quantity only moves the focus to the rate cell; the next keystroke
 * opens the rate editor. AG Grid cancels that keystroke and hands it to the
 * editor as ``eventKey``, and the editors ignored it, so typing 12,50 after Tab
 * saved 2,50 with nothing on screen to say a digit had gone. It was found by
 * driving the real grid in a browser, and it is the same for quantity and unit.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, cleanup, screen, fireEvent } from '@testing-library/react';

import { editorSeed, FormulaCellEditor, RateCellEditor, UnitCellEditor } from './cellEditors';
import type { FormulaCellEditorParams } from './cellEditors';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { useDisplayQuantity, type DisplayQuantityApi } from '@/shared/hooks/useDisplayQuantity';

function metricApi(): DisplayQuantityApi {
  usePreferencesStore.getState().setPreference('measurementSystem', 'metric');
  let api!: DisplayQuantityApi;
  function Probe() {
    api = useDisplayQuantity();
    return null;
  }
  render(<Probe />);
  cleanup();
  return api;
}

function mockApi() {
  return { stopEditing: vi.fn(), tabToNextCell: vi.fn(), tabToPreviousCell: vi.fn() };
}

// The editors listen natively, so events go to the node, not through React.
function typeInto(input: HTMLInputElement, text: string) {
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function pressEnter(input: HTMLInputElement) {
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
}

function renderRate(eventKey: string | null) {
  const setDataValue = vi.fn();
  const params = {
    value: 50,
    eventKey,
    data: { unit: 'm' },
    context: { displayQuantity: metricApi() },
    node: { data: { unit: 'm', unit_rate: 50 }, setDataValue },
    api: mockApi(),
    column: { getColId: () => 'unit_rate' },
  } as unknown as FormulaCellEditorParams;
  render(<RateCellEditor {...params} />);
  return { input: screen.getByRole('textbox') as HTMLInputElement, setDataValue };
}

describe('editorSeed', () => {
  it('starts from a printable key, replacing the stored value', () => {
    expect(editorSeed('1', '50')).toEqual({ text: '1', typed: true });
    expect(editorSeed('€', '50')).toEqual({ text: '€', typed: true });
  });

  it('opens empty on Backspace and Delete', () => {
    expect(editorSeed('Backspace', '50')).toEqual({ text: '', typed: true });
    expect(editorSeed('Delete', '50')).toEqual({ text: '', typed: true });
  });

  it('opens on the stored value for Enter, F2 and a click', () => {
    expect(editorSeed('Enter', '50')).toEqual({ text: '50', typed: false });
    expect(editorSeed('F2', '50')).toEqual({ text: '50', typed: false });
    expect(editorSeed(null, '50')).toEqual({ text: '50', typed: false });
    expect(editorSeed(undefined, '50')).toEqual({ text: '50', typed: false });
  });
});

describe('the rate editor keeps the key that opened it', () => {
  beforeEach(() => cleanup());

  it('saves 12,50 as 12.5 when the 1 opened the editor', () => {
    const { input, setDataValue } = renderRate('1');
    expect(input.value).toBe('1');
    // The caret sits after the seed, so the rest of the number follows it.
    expect(input.selectionStart).toBe(1);
    expect(input.selectionEnd).toBe(1);
    typeInto(input, '12,50');
    pressEnter(input);
    expect(setDataValue).toHaveBeenCalledWith('unit_rate', 12.5);
  });

  it('opens on the stored rate, selected, when a click or Enter opened it', () => {
    const { input } = renderRate(null);
    expect(input.value).toBe('50');
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(2);
  });

  it('takes a rate typed with its currency sign', () => {
    const { input, setDataValue } = renderRate('1');
    typeInto(input, '12,50 €');
    pressEnter(input);
    expect(setDataValue).toHaveBeenCalledWith('unit_rate', 12.5);
  });
});

describe('Escape cancels the edit', () => {
  // Escape stops editing with cancel=true, and removing the editor blurs its
  // input. The blur handler commits, so without a guard the typed value was
  // saved anyway: click, type 6, Escape sent {"unit_rate": 6} in the browser.
  beforeEach(() => cleanup());

  function pressEscape(input: HTMLInputElement) {
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
  }

  it('the rate editor saves nothing when Escape is followed by the blur', () => {
    const { input, setDataValue } = renderRate('9');
    pressEscape(input);
    input.dispatchEvent(new FocusEvent('blur'));
    expect(setDataValue).not.toHaveBeenCalled();
  });

  it('the quantity editor saves nothing when Escape is followed by the blur', () => {
    const setDataValue = vi.fn();
    const api = mockApi();
    const params = {
      value: 4,
      eventKey: '7',
      data: { unit: 'm2' },
      context: { displayQuantity: metricApi() },
      node: { data: { unit: 'm2', quantity: 4 }, setDataValue },
      api,
      column: { getColId: () => 'quantity' },
    } as unknown as FormulaCellEditorParams;
    render(<FormulaCellEditor {...params} />);
    const input = screen.getByRole('textbox') as HTMLInputElement;
    pressEscape(input);
    input.dispatchEvent(new FocusEvent('blur'));
    expect(api.stopEditing).toHaveBeenCalledWith(true);
    expect(setDataValue).not.toHaveBeenCalled();
  });

  it('the unit editor saves nothing when Escape is followed by the blur', () => {
    vi.useFakeTimers();
    try {
      const setDataValue = vi.fn();
      const api = mockApi();
      const params = {
        value: 'm2',
        eventKey: 'k',
        data: { unit: 'm2' },
        node: { id: 'row-esc', data: { unit: 'm2' }, setDataValue },
        api,
        column: { getColId: () => 'unit' },
      } as unknown as FormulaCellEditorParams;
      render(<UnitCellEditor {...params} />);
      const input = screen.getByRole('combobox') as HTMLInputElement;
      // The first Escape may only close the suggestion list; the next one leaves.
      fireEvent.keyDown(input, { key: 'Escape' });
      if (!api.stopEditing.mock.calls.length) fireEvent.keyDown(input, { key: 'Escape' });
      expect(api.stopEditing).toHaveBeenCalledWith(true);
      fireEvent.blur(input);
      vi.advanceTimersByTime(500);
      expect(setDataValue).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe('quantity and unit keep the key that opened them too', () => {
  beforeEach(() => cleanup());

  it('quantity starts from the typed digit', () => {
    const params = {
      value: 4,
      eventKey: '7',
      data: { unit: 'm2' },
      context: { displayQuantity: metricApi() },
      node: { data: { unit: 'm2', quantity: 4 }, setDataValue: vi.fn() },
      api: mockApi(),
      column: { getColId: () => 'quantity' },
    } as unknown as FormulaCellEditorParams;
    render(<FormulaCellEditor {...params} />);
    expect((screen.getByRole('textbox') as HTMLInputElement).value).toBe('7');
  });

  it('unit starts its search from the typed letter', () => {
    const params = {
      value: 'm2',
      eventKey: 'k',
      data: { unit: 'm2' },
      node: { data: { unit: 'm2' }, setDataValue: vi.fn() },
      api: mockApi(),
      column: { getColId: () => 'unit' },
    } as unknown as FormulaCellEditorParams;
    render(<UnitCellEditor {...params} />);
    expect((screen.getByRole('combobox') as HTMLInputElement).value).toBe('k');
  });
});
