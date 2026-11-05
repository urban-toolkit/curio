/**
 * A narrow node's header shows its title before its whole pills
 * (`useHeaderPillsFit`): the pills go compact only while the title would show
 * less than its floor beside them whole, and are whole again once the header
 * has room for both. The layout is faked: jsdom measures nothing.
 */
import React, { useState } from "react";
import { act, render, screen } from "@testing-library/react";

import { TITLE_FLOOR_PX, useHeaderPillsFit } from "../../components/nodes/useHeaderPillsFit";

/** What the fake layout measures: the header's width, the title's whole width,
 *  and how much of it shows beside the whole pills and beside compact ones. */
const layout = { header: 340, whole: 250, besideWhole: 0, besideCompact: 60 };

const observers: Array<() => void> = [];
class FakeResizeObserver {
  constructor(private readonly callback: () => void) {}
  observe() {
    observers.push(this.callback);
  }
  disconnect() {}
}

function Header() {
  const [header, setHeader] = useState<HTMLElement | null>(null);
  const compact = useHeaderPillsFit(header, "title");
  return (
    <div ref={setHeader} data-testid="header">
      <span data-curio-node-title="true">Mean accumulated shadow by scenario</span>
      <span data-testid="pills" data-compact={compact ? "true" : "false"}>
        {compact ? "icon" : "VIZ PACKAGE"}
      </span>
    </div>
  );
}

const compactPills = () => screen.getByTestId("pills").getAttribute("data-compact") === "true";

const resize = (width: number) =>
  act(() => {
    layout.header = width;
    observers.forEach((callback) => callback());
  });

beforeAll(() => {
  (globalThis as any).ResizeObserver = FakeResizeObserver;
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get(this: HTMLElement) {
      if (this.dataset.testid === "header") return layout.header;
      if (this.hasAttribute("data-curio-node-title")) {
        const pills = this.closest('[data-testid="header"]')?.querySelector('[data-testid="pills"]');
        return pills?.getAttribute("data-compact") === "true" ? layout.besideCompact : layout.besideWhole;
      }
      return 0;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "scrollWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.hasAttribute("data-curio-node-title") ? layout.whole : 0;
    },
  });
});

afterAll(() => {
  delete (globalThis as any).ResizeObserver;
  delete (HTMLElement.prototype as any).clientWidth;
  delete (HTMLElement.prototype as any).scrollWidth;
});

beforeEach(() => {
  observers.length = 0;
  Object.assign(layout, { header: 340, whole: 250, besideWhole: 0, besideCompact: 60 });
});

test("a narrow header shows its pills compact, so its title shows", () => {
  render(<Header />);
  expect(compactPills()).toBe(true);
});

test("a header with room for both keeps its pills whole", () => {
  layout.besideWhole = TITLE_FLOOR_PX + 80;
  render(<Header />);
  expect(compactPills()).toBe(false);
});

test("a short title that shows whole keeps the pills whole", () => {
  Object.assign(layout, { whole: 30, besideWhole: 30 });
  render(<Header />);
  expect(compactPills()).toBe(false);
});

test("compact pills are whole again once the header has room for them and the title's floor, not before", () => {
  render(<Header />);
  expect(compactPills()).toBe(true);
  // The pills went compact on a 340 px header with the title at 0: whole, they
  // fit back beside the floor at 340 + 64.
  resize(340 + TITLE_FLOOR_PX - 10);
  expect(compactPills()).toBe(true);
  layout.besideWhole = TITLE_FLOOR_PX + 10;
  resize(340 + TITLE_FLOOR_PX + 10);
  expect(compactPills()).toBe(false);
});
