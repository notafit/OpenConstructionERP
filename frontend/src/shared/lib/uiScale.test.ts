// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for the interface size ("Text size") logic.
 *
 * The stored value is read before the app mounts and fed straight into a
 * native zoom call, so the cases that matter are the ones where storage is
 * wrong or unavailable: a stale or hand-edited value must land on an offered
 * step, and a storage that throws must neither stop the boot nor lose the
 * default. The bridge cases pin that the web build never reaches for Tauri and
 * that the desktop build calls the command the capability grants.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';

type TauriWindow = { __TAURI__?: unknown };

/** `isTauri` is fixed when desktop.ts loads, so each bridge case imports fresh. */
async function loadUiScale(tauriGlobal?: unknown) {
  vi.resetModules();
  const w = window as unknown as TauriWindow;
  if (tauriGlobal === undefined) delete w.__TAURI__;
  else w.__TAURI__ = tauriGlobal;
  return import('./uiScale');
}

afterEach(() => {
  delete (window as unknown as TauriWindow).__TAURI__;
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('UI_SCALE_STEPS', () => {
  it('offers ascending steps that include the default', async () => {
    const { UI_SCALE_STEPS, DEFAULT_UI_SCALE } = await loadUiScale();
    expect([...UI_SCALE_STEPS]).toEqual([...UI_SCALE_STEPS].sort((a, b) => a - b));
    expect(UI_SCALE_STEPS).toContain(DEFAULT_UI_SCALE);
    expect(DEFAULT_UI_SCALE).toBe(1);
  });
});

describe('normalizeUiScale', () => {
  it('keeps every offered step as it is, from a number or a stored string', async () => {
    const { UI_SCALE_STEPS, normalizeUiScale } = await loadUiScale();
    for (const step of UI_SCALE_STEPS) {
      expect(normalizeUiScale(step)).toBe(step);
      expect(normalizeUiScale(String(step))).toBe(step);
    }
  });

  it('clamps values outside the range to the nearest end', async () => {
    const { UI_SCALE_STEPS, normalizeUiScale } = await loadUiScale();
    const lowest = UI_SCALE_STEPS[0];
    const highest = UI_SCALE_STEPS[UI_SCALE_STEPS.length - 1];
    expect(normalizeUiScale(0.2)).toBe(lowest);
    expect(normalizeUiScale(9)).toBe(highest);
    expect(normalizeUiScale('10')).toBe(highest);
  });

  it('snaps values between steps to the nearest one', async () => {
    const { normalizeUiScale } = await loadUiScale();
    expect(normalizeUiScale(1.2)).toBe(1.25);
    expect(normalizeUiScale(1.17)).toBe(1.1);
    expect(normalizeUiScale(0.97)).toBe(1);
  });

  it('falls back to the default for anything that is not a positive number', async () => {
    const { normalizeUiScale } = await loadUiScale();
    for (const junk of [null, undefined, '', 'large', Number.NaN, Infinity, -1.25, 0, {}, true]) {
      expect(normalizeUiScale(junk)).toBe(1);
    }
  });
});

describe('persistence', () => {
  it('reads the default when nothing is stored', async () => {
    const { readUiScale } = await loadUiScale();
    expect(readUiScale()).toBe(1);
  });

  it('round-trips a chosen size and stores the default as no entry', async () => {
    const { readUiScale, writeUiScale, UI_SCALE_STORAGE_KEY } = await loadUiScale();
    writeUiScale(1.25);
    expect(window.localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBe('1.25');
    expect(readUiScale()).toBe(1.25);
    writeUiScale(1);
    expect(window.localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBeNull();
    expect(readUiScale()).toBe(1);
  });

  it('never stores a value that is not an offered step', async () => {
    const { writeUiScale, UI_SCALE_STORAGE_KEY } = await loadUiScale();
    writeUiScale(9);
    expect(window.localStorage.getItem(UI_SCALE_STORAGE_KEY)).toBe('1.5');
  });

  it('reads a stale or hand-edited value as the nearest step', async () => {
    const { readUiScale, UI_SCALE_STORAGE_KEY } = await loadUiScale();
    window.localStorage.setItem(UI_SCALE_STORAGE_KEY, 'huge');
    expect(readUiScale()).toBe(1);
    window.localStorage.setItem(UI_SCALE_STORAGE_KEY, '3');
    expect(readUiScale()).toBe(1.5);
  });

  it('survives a storage that throws on read and on write', async () => {
    const { readUiScale, writeUiScale } = await loadUiScale();
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('QuotaExceededError');
    });
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('SecurityError');
    });
    expect(readUiScale()).toBe(1);
    expect(() => writeUiScale(1.25)).not.toThrow();
    expect(() => writeUiScale(1)).not.toThrow();
  });
});

describe('applying the size', () => {
  it('does nothing in a browser, where only the browser can zoom', async () => {
    const { applyStoredUiScale, applyUiScale, canSetUiScale, UI_SCALE_STORAGE_KEY } = await loadUiScale();
    window.localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.25');
    expect(canSetUiScale).toBe(false);
    expect(applyStoredUiScale()).toBeNull();
    await expect(applyUiScale(1.25)).resolves.toBe(false);
  });

  it('zooms the calling webview through the granted Tauri command in the desktop app', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { applyStoredUiScale, UI_SCALE_STORAGE_KEY } = await loadUiScale({ core: { invoke } });
    window.localStorage.setItem(UI_SCALE_STORAGE_KEY, '1.25');
    await expect(applyStoredUiScale()).resolves.toBe(true);
    expect(invoke).toHaveBeenCalledWith('plugin:webview|set_webview_zoom', { value: 1.25 });
  });

  it('snaps before calling, so the shell never sees an unoffered factor', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { applyUiScale } = await loadUiScale({ core: { invoke } });
    await applyUiScale(7);
    expect(invoke).toHaveBeenCalledWith('plugin:webview|set_webview_zoom', { value: 1.5 });
  });

  it('has nothing to wait for at the default size', async () => {
    const invoke = vi.fn().mockResolvedValue(undefined);
    const { applyStoredUiScale } = await loadUiScale({ core: { invoke } });
    expect(applyStoredUiScale()).toBeNull();
    expect(invoke).not.toHaveBeenCalled();
  });

  it('reports a refused command as false instead of throwing', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const invoke = vi.fn().mockRejectedValue('webview.set_webview_zoom not allowed');
    const { applyUiScale } = await loadUiScale({ core: { invoke } });
    await expect(applyUiScale(1.1)).resolves.toBe(false);
  });
});
