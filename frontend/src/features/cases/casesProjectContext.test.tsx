// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// #413 - the Cases hub read "No project selected" while the top-bar switcher
// held a project.
//
// The hub kept its own copy of "which project" in `useCasesStore`
// (localStorage `oe_cases_pin_project`). Nothing outside the hub ever wrote
// that key, so the app-wide project the header switcher sets
// (`useProjectContextStore`) was invisible here. The picker now reads the
// shared context, and selecting in it writes the same store the header does.
//
// The project is put in place through `setActiveProject` - the exact call the
// header switcher makes - and the assertions are on the rendered <select>,
// not on the store, so they cannot pass while the wiring is wrong.
//
// Run:  npx vitest run src/features/cases/casesProjectContext.test.tsx

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import React from "react";

import { useProjectContextStore } from "@/stores/useProjectContextStore";
import { useCasesStore } from "./useCasesStore";
import { CasesPage } from "./CasesPage";

const PROJECTS = [
  { id: "p-canary", name: "One Canary Square", currency: "GBP" },
  { id: "p-depot", name: "Riverside Depot", currency: "EUR" },
];

/* ── Stable `t` ────────────────────────────────────────────────────────
   The shared test setup mocks `react-i18next` with a `useTranslation()` that
   builds a fresh object - and a fresh `t` - on every call. `CasesList`'s
   `visible` memo lists `t` in its dependencies and feeds a render-time
   `setState` guard (`lastVisible !== visible`), so an unstable `t` makes the
   component re-render without end before any assertion runs. Overriding the
   mock here with one frozen instance keeps that harness detail out of the
   defect under test; the `t` behaviour itself (defaultValue + `{{var}}`
   interpolation) matches the shared setup exactly. */

vi.mock("react-i18next", () => {
  const stableT = (key: string, opts?: Record<string, unknown>) => {
    if (typeof opts === "object" && opts !== null && "defaultValue" in opts) {
      let template = opts.defaultValue as string;
      if (
        "count" in opts &&
        opts.count !== 1 &&
        typeof opts.defaultValue_other === "string"
      ) {
        template = opts.defaultValue_other;
      }
      return template.replace(/\{\{(\w+)\}\}/g, (_m, name: string) =>
        name in opts ? String(opts[name]) : `{{${name}}}`,
      );
    }
    return key;
  };
  const translation = {
    t: stableT,
    i18n: { language: "en", changeLanguage: vi.fn() },
  };
  return {
    useTranslation: () => translation,
    Trans: ({ children }: { children: React.ReactNode }) => children,
    initReactI18next: { type: "3rdParty", init: () => {} },
    I18nextProvider: ({ children }: { children: React.ReactNode }) => children,
  };
});

/* ── Mock @/app/i18n to prevent i18next initialization side-effects ───── */

vi.mock("@/app/i18n", () => ({
  CORE_LANGUAGES: [{ code: "en", name: "English", flag: "gb", country: "gb" }],
  EXTRA_LANGUAGES: [],
  SUPPORTED_LANGUAGES: [
    { code: "en", name: "English", flag: "gb", country: "gb" },
  ],
  getLanguageByCode: () => ({
    code: "en",
    name: "English",
    flag: "gb",
    country: "gb",
  }),
  default: {
    use: () => ({ use: () => ({ use: () => ({ init: vi.fn() }) }) }),
    t: (key: string) => key,
    language: "en",
    changeLanguage: vi.fn(),
  },
}));

/* ── Mock react-query - the hub's only fetch is the project list ───────── */

vi.mock("@tanstack/react-query", () => {
  const settled = (data: unknown) => ({
    data,
    isLoading: false,
    isError: false,
    isSuccess: true,
    error: null,
    refetch: vi.fn(),
  });
  return {
    useQuery: (opts: { queryKey?: unknown[] }) => {
      const root = String(opts?.queryKey?.[0] ?? "");
      if (root === "projects") return settled(PROJECTS);
      return { ...settled(undefined), isSuccess: false };
    },
    useMutation: () => ({
      mutate: vi.fn(),
      mutateAsync: vi.fn(),
      isPending: false,
    }),
    useQueryClient: () => ({
      invalidateQueries: vi.fn(),
      setQueryData: vi.fn(),
    }),
    QueryClient: vi.fn(),
    QueryClientProvider: ({ children }: { children: React.ReactNode }) =>
      children,
  };
});

/* ── Mock @/shared/lib/api to prevent real network calls ──────────────── */

vi.mock("@/shared/lib/api", () => ({
  API_BASE: "/api",
  getAuthToken: () => "mock-token",
  extractErrorMessageFromBody: () => null,
  getErrorMessage: (err: unknown) => String(err),
  apiGet: vi.fn().mockResolvedValue([]),
  apiPost: vi.fn().mockResolvedValue({}),
  apiPatch: vi.fn().mockResolvedValue({}),
  apiPut: vi.fn().mockResolvedValue({}),
  apiDelete: vi.fn().mockResolvedValue(undefined),
  triggerDownload: vi.fn(),
  ApiError: class ApiError extends Error {},
}));

// Every test here mounts the whole hub, two hundred and more cards. On a
// saturated CPU one mount alone can outlast the 15s default, so the file
// gets the room a lighter file does not need.
vi.setConfig({ testTimeout: 60_000 });

/* ── Helpers ──────────────────────────────────────────────────────────── */

/** Exactly what the top-bar project switcher does when a user picks one. */
function selectProjectInTopBar(id: string, name: string) {
  useProjectContextStore.getState().setActiveProject(id, name);
}

function renderHub(): HTMLElement {
  const { container } = render(
    <MemoryRouter initialEntries={["/cases"]}>
      <CasesPage />
    </MemoryRouter>,
  );
  return container;
}

function renderCases(): HTMLSelectElement {
  const picker = renderHub().querySelector<HTMLSelectElement>(
    "#cases-pin-project",
  );
  if (!picker) throw new Error("Cases project picker did not render");
  return picker;
}

/** The first case card in the grid. Cards are the only elements on the hub
 *  carrying an explicit `role="button"`; every other control is a real
 *  `<button>` and so has the role implicitly, not as an attribute. */
function firstCard(container: HTMLElement): HTMLElement {
  const card = container.querySelector<HTMLElement>('[role="button"]');
  if (!card) throw new Error("No case card rendered");
  return card;
}

/** The panel a card reveals over itself while it is hovered or focused.
 *  Found by the behaviour that defines it - it is the element whose opacity
 *  is driven by the card's hover state - rather than by a layout class, so a
 *  restyle of the panel does not quietly turn this lookup into `null`. */
function hoverPanel(card: HTMLElement): HTMLElement {
  const panel = card.querySelector<HTMLElement>(
    '[class*="group-hover:opacity-100"]',
  );
  if (!panel) throw new Error("Card hover panel not found");
  return panel;
}

/** The per-card pin control, found by its accessible name. */
function pinControl(card: HTMLElement, pinned = false): HTMLElement {
  const label = pinned ? "Unpin from project" : "Pin to project";
  const button = card.querySelector<HTMLElement>(`[aria-label="${label}"]`);
  if (!button) throw new Error(`No control named "${label}" on the card`);
  return button;
}

/** The stacking level an element paints at inside its card, read off the
 *  Tailwind `z-<n>` utility that puts it there, plus whether the element
 *  carrying that utility is positioned (a z-index on a static element does
 *  nothing at all). The walk stops at the card, so the level is found whether
 *  it sits on the control itself or on a wrapper around it. It returns the
 *  FIRST level it meets on the way up, not the highest: the nearest one is
 *  the one the browser resolves against, and a wrapper further up cannot
 *  lift a child that already sits in its stacking context.
 *
 *  JSDOM has no layout and no Tailwind stylesheet, so it cannot answer "does
 *  this element paint over that one". This reads the class that decides it
 *  instead: a structural proxy for the paint order, not a rendering check. */
function stackingLevel(
  el: Element,
  stop: Element,
): { level: number; positioned: boolean } {
  for (let node: Element | null = el; node && node !== stop; ) {
    const classes = (node.getAttribute("class") ?? "").split(/\s+/);
    const z = classes.find((c) => /^z-\d+$/.test(c));
    if (z) {
      return {
        level: Number(z.slice(2)),
        positioned: classes.some((c) =>
          ["relative", "absolute", "fixed", "sticky"].includes(c),
        ),
      };
    }
    node = node.parentElement;
  }
  return { level: 0, positioned: false };
}

beforeEach(() => {
  localStorage.clear();
  useProjectContextStore.getState().clearProject();
  // The pin map is read from localStorage once, when the store module is
  // first imported, so clearing storage does not reach the live state.
  useCasesStore.setState({ pins: {} });
});

/* ── Tests ────────────────────────────────────────────────────────────── */

describe("Cases project picker follows the app-wide project (#413)", () => {
  it("shows the project the top bar has selected, not 'No project selected'", () => {
    selectProjectInTopBar("p-canary", "One Canary Square");

    const picker = renderCases();

    // The defect: the picker sat on the empty option while the header showed
    // "One Canary Square".
    expect(picker.value).toBe("p-canary");
  });

  it("still reads empty when no project is selected anywhere", () => {
    const picker = renderCases();

    expect(picker.value).toBe("");
  });

  it("writes the app-wide store when a project is picked here", () => {
    const picker = renderCases();

    fireEvent.change(picker, { target: { value: "p-depot" } });

    // Same store the header switcher uses - picking here moves the whole app,
    // rather than creating a second selection that silently disagrees with
    // the top bar.
    expect(useProjectContextStore.getState().activeProjectId).toBe("p-depot");
    expect(useProjectContextStore.getState().activeProjectName).toBe(
      "Riverside Depot",
    );
  });

  it("explains the zero on the pin toggle before the user clicks it", () => {
    // #414: the count beside that button is the user's own pin list, which is
    // empty until they pin something, so the hub says what the number is as
    // soon as a project is chosen rather than after the click.
    selectProjectInTopBar("p-canary", "One Canary Square");

    renderCases();

    expect(
      screen.getByText(
        "Pin a case to this project from its card, and it will show up here.",
      ),
    ).toBeInTheDocument();
  });
});

describe("The pin toggle is named after the number it shows (#414)", () => {
  it("says the count is the pin list, not a property of the project", () => {
    selectProjectInTopBar("p-canary", "One Canary Square");

    renderCases();

    // The number is `pins[projectId].length` out of localStorage - 0 on every
    // fresh project, for every project, until the user pins something. Under
    // the old label, "Cases for this project 0" beside a project name read as
    // "this project has no cases", and the explanatory sentence added with it
    // explained the zero rather than removing the claim.
    //
    // getByText, not getByRole: this page is large enough that computing an
    // accessible name for every element runs past the suite timeout.
    const toggle = screen.getByText("Pinned to this project");
    expect(toggle.tagName).toBe("BUTTON");
    expect(toggle).toHaveTextContent("0");
    expect(screen.queryByText("Cases for this project")).not.toBeInTheDocument();
  });

  it("counts the pins the user made, under the same label", () => {
    useCasesStore.getState().togglePin("p-canary", "estimate-a-fitout");
    useCasesStore.getState().togglePin("p-canary", "tender-a-package");
    useCasesStore.getState().togglePin("p-depot", "run-a-handover");
    selectProjectInTopBar("p-canary", "One Canary Square");

    renderCases();

    // Two here, one on the other project: the number tracks the pin list and
    // nothing else, which is what the label now claims.
    const toggle = screen.getByText("Pinned to this project");
    expect(toggle).toHaveTextContent("2");
  });
});

describe("The per-card pin control stays reachable while a card is hovered", () => {
  it("paints above the panel the card reveals on hover", () => {
    // Building a shortlist for a job means hovering a card to read what it
    // is and then pinning it. The card answers the first half by covering
    // itself with an opaque panel - and the panel used to swallow the pin,
    // so the control vanished at the exact moment a user reached for it. It
    // stayed clickable underneath (the panel takes no pointer events), which
    // is worse than gone: an invisible target you have to already know about.
    selectProjectInTopBar("p-canary", "One Canary Square");

    const card = firstCard(renderHub());
    const panel = hoverPanel(card);
    const pin = pinControl(card);

    // The pin is a sibling of the panel, never a child of it. It has to be
    // there at rest too, for touch and for a keyboard user tabbing through,
    // neither of which ever produces a hover.
    expect(panel.contains(pin)).toBe(false);

    // So paint order is what decides whether a hovering user can see it, and
    // the panel is both a later sibling and explicitly raised. The pin needs
    // a higher level than the panel, on an element that is positioned.
    const pinZ = stackingLevel(pin, card);
    const panelZ = stackingLevel(panel, card);
    expect(panelZ.level).toBeGreaterThan(0);
    expect(pinZ.level).toBeGreaterThan(panelZ.level);
    expect(pinZ.positioned).toBe(true);
  });

  it("pins the case without opening it, and says so", () => {
    selectProjectInTopBar("p-canary", "One Canary Square");

    const container = renderHub();
    const card = firstCard(container);
    const pin = pinControl(card);
    expect(pin).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(pin);

    // The click belongs to the pin, not to the card underneath it, so the
    // hub stays put instead of navigating into the runner.
    expect(useCasesStore.getState().pins["p-canary"]).toHaveLength(1);
    expect(container.querySelector("#cases-pin-project")).not.toBeNull();
    expect(pinControl(card, true)).toHaveAttribute("aria-pressed", "true");
  });
});
