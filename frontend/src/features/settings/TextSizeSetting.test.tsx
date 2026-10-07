// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Component tests for the Settings "Text size" control.
 *
 * Two things a screenshot cannot show are asserted: that the browser build
 * offers no buttons it could not honour, and that in the desktop app a choice
 * is only remembered once the shell has actually applied it. A size saved
 * after a refused call would be re-sent on every start and never take effect.
 */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

type TauriWindow = { __TAURI__?: unknown };

/** `isTauri` is fixed when desktop.ts loads, so each case renders a fresh module graph. */
async function renderSetting(tauriGlobal?: unknown) {
  vi.resetModules();
  const w = window as unknown as TauriWindow;
  if (tauriGlobal === undefined) delete w.__TAURI__;
  else w.__TAURI__ = tauriGlobal;
  const { TextSizeSetting } = await import('./TextSizeSetting');
  return render(<TextSizeSetting />);
}

afterEach(() => {
  delete (window as unknown as TauriWindow).__TAURI__;
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe('<TextSizeSetting>', () => {
  it('points to browser zoom in the web app and offers no buttons', async () => {
    await renderSetting();
    expect(screen.getByText('Text size')).toBeInTheDocument();
    expect(screen.getByText(/Your browser sets the text size/)).toBeInTheDocument();
    expect(screen.queryAllByRole('button')).toHaveLength(0);
  });

  it('lights the saved size and applies a new one natively in the desktop app', async () => {
    window.localStorage.setItem('oe_ui_scale', '1.1');
    const invoke = vi.fn().mockResolvedValue(undefined);
    await renderSetting({ core: { invoke } });

    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(5);
    expect(buttons.filter((b) => b.getAttribute('aria-pressed') === 'true')).toHaveLength(1);
    expect(screen.getByRole('button', { name: '110%' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: '125%' }));
    await waitFor(() =>
      expect(screen.getByRole('button', { name: '125%' })).toHaveAttribute('aria-pressed', 'true'),
    );
    expect(invoke).toHaveBeenCalledWith('plugin:webview|set_webview_zoom', { value: 1.25 });
    expect(window.localStorage.getItem('oe_ui_scale')).toBe('1.25');
  });

  it('keeps the previous size when the shell refuses the zoom', async () => {
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const invoke = vi.fn().mockRejectedValue('not allowed');
    await renderSetting({ core: { invoke } });

    fireEvent.click(screen.getByRole('button', { name: '150%' }));
    await waitFor(() => expect(invoke).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByRole('button', { name: '150%' })).not.toBeDisabled());
    expect(screen.getByRole('button', { name: '100%' })).toHaveAttribute('aria-pressed', 'true');
    expect(window.localStorage.getItem('oe_ui_scale')).toBeNull();
  });
});
