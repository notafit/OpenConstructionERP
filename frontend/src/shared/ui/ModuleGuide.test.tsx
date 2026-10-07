// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tests for ModuleGuide, the card-by-card walkthrough behind the blue
 * "How it works" pill.
 *
 * This is the second of two mechanisms that explain a module. The other one,
 * `CollapsibleSection` with a `<module>.how` storage key, answers "what is
 * this module and where does it lead" and stays on the page; this one answers
 * "walk me through doing it here", spotlights real controls and traps focus.
 * They are complementary, and eight pages deliberately carry both.
 *
 * Until now only the first had a test. This one is the richer of the two: a
 * modal dialog with a focus trap, a body scroll lock, keyboard navigation and
 * a right-to-left mirror, spread over 99 content files. None of that was
 * covered by anything, and three of the behaviours below are invisible to a
 * reader who never leaves English.
 *
 * The suite drives `ModuleGuide` directly rather than `ModuleGuideButton`,
 * because the button also renders the route-derived Cases pill and would drag
 * a router into a test about keyboard handling. Every behaviour worth pinning
 * lives here.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import { ModuleGuide, type ModuleGuideContent } from './ModuleGuide';

const CONTENT: ModuleGuideContent = {
  titleKey: 'guide.boq.title',
  titleDefault: 'How the bill of quantities works',
  introKey: 'guide.boq.intro',
  introDefault: 'Positions come from a takeoff and end up priced.',
  sections: [
    {
      titleKey: 'guide.boq.s1.title',
      titleDefault: 'Start from a takeoff',
      bodyKey: 'guide.boq.s1.body',
      bodyDefault: 'Measured quantities arrive here as draft positions.',
    },
    {
      titleKey: 'guide.boq.s2.title',
      titleDefault: 'Price each position',
      bodyKey: 'guide.boq.s2.body',
      bodyDefault: 'Attach a resource assembly or type a unit rate.',
    },
    {
      titleKey: 'guide.boq.s3.title',
      titleDefault: 'Send it out',
      bodyKey: 'guide.boq.s3.body',
      bodyDefault: 'Export to GAEB or publish to a tender.',
    },
  ],
};

/** The body copy of the card currently on screen. */
function visibleCard(): string {
  return screen.getByTestId('module-guide-card').textContent ?? '';
}

function renderGuide(overrides: Partial<Parameters<typeof ModuleGuide>[0]> = {}) {
  const onClose = vi.fn();
  const onCta = vi.fn();
  const utils = render(
    <ModuleGuide open onClose={onClose} content={CONTENT} {...overrides} />,
  );
  return { onClose, onCta, ...utils };
}

beforeEach(() => {
  document.documentElement.dir = 'ltr';
});

afterEach(() => {
  document.documentElement.dir = 'ltr';
});

describe('ModuleGuide', () => {
  it('announces itself as a modal dialog named by a real heading', () => {
    renderGuide();
    const card = screen.getByTestId('module-guide-card');

    expect(card).toHaveAttribute('role', 'dialog');
    expect(card).toHaveAttribute('aria-modal', 'true');

    // A label that points at nothing is worse than no label, because a screen
    // reader announces an empty dialog instead of falling back to the content.
    const labelledBy = card.getAttribute('aria-labelledby');
    expect(labelledBy).toBeTruthy();
    const heading = document.getElementById(labelledBy!);
    expect(heading, `aria-labelledby="${labelledBy}" matches no element`).not.toBeNull();
    expect(heading!.tagName).toBe('H2');
    expect(heading!.textContent).toContain('How the bill of quantities works');
  });

  it('renders nothing at all when closed', () => {
    render(<ModuleGuide open={false} onClose={vi.fn()} content={CONTENT} />);
    expect(screen.queryByTestId('module-guide-card')).toBeNull();
  });

  it('renders nothing when the content has no sections', () => {
    render(<ModuleGuide open onClose={vi.fn()} content={{ ...CONTENT, sections: [] }} />);
    expect(screen.queryByTestId('module-guide-card')).toBeNull();
  });

  it('closes on Escape', () => {
    const { onClose } = renderGuide();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('walks forward and back with the arrow keys', () => {
    renderGuide();
    expect(visibleCard()).toContain('Measured quantities arrive here');

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(visibleCard()).toContain('Attach a resource assembly');

    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(visibleCard()).toContain('Measured quantities arrive here');
  });

  it('mirrors the arrow keys when the page reads right to left', () => {
    // Arabic, Hebrew, Persian and Urdu all ship here. In an RTL layout the
    // card that sits "forward" is to the LEFT, so a guide that kept the
    // Latin mapping would walk backwards under the reader's hand. The
    // direction is read at mount, so it is set before rendering.
    document.documentElement.dir = 'rtl';
    renderGuide();
    expect(visibleCard()).toContain('Measured quantities arrive here');

    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(visibleCard()).toContain('Attach a resource assembly');

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(visibleCard()).toContain('Measured quantities arrive here');
  });

  it('does not walk past either end', () => {
    renderGuide();
    fireEvent.keyDown(document, { key: 'ArrowLeft' });
    expect(visibleCard()).toContain('Measured quantities arrive here');

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(visibleCard()).toContain('Export to GAEB');
  });

  it('finishes from the last card, closing once and running the call to action', () => {
    const onClose = vi.fn();
    const onCta = vi.fn();
    render(<ModuleGuide open onClose={onClose} content={CONTENT} onCta={onCta} />);

    fireEvent.click(screen.getByTestId('module-guide-next'));
    fireEvent.click(screen.getByTestId('module-guide-next'));
    fireEvent.click(screen.getByTestId('module-guide-finish'));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onCta).toHaveBeenCalledTimes(1);
  });

  it('starts again from the first card every time it reopens', () => {
    const { rerender } = renderGuide();
    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(visibleCard()).toContain('Attach a resource assembly');

    rerender(<ModuleGuide open={false} onClose={vi.fn()} content={CONTENT} />);
    rerender(<ModuleGuide open onClose={vi.fn()} content={CONTENT} />);

    expect(visibleCard()).toContain('Measured quantities arrive here');
  });

  it('gives the page its scrolling back when it closes', () => {
    // The lock is set on document.body while the guide is open. If the
    // cleanup ever stops running, the page behind stays frozen and the only
    // cure a user has is a reload.
    document.body.style.overflow = 'auto';
    const { rerender } = renderGuide();
    expect(document.body.style.overflow).toBe('hidden');

    rerender(<ModuleGuide open={false} onClose={vi.fn()} content={CONTENT} />);
    expect(document.body.style.overflow).toBe('auto');
  });

  it('shows the intro on the first card only', () => {
    renderGuide();
    expect(visibleCard()).toContain('Positions come from a takeoff');

    fireEvent.keyDown(document, { key: 'ArrowRight' });
    expect(visibleCard()).not.toContain('Positions come from a takeoff');
  });
});
