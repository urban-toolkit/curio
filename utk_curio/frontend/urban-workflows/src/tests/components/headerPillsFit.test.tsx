/**
 * A narrow node's header shows its title before its pills
 * (`useHeaderPillsFit`): the pills give way only while the title would show
 * less than its floor, and come back once the header has room for both. The
 * layout is faked: jsdom measures nothing.
 */
import React, { useState } from "react";
import { act, render, screen } from "@testing-library/react";

import { TITLE_FLOOR_PX, useHeaderPillsFit } from "../../components/nodes/useHeaderPillsFit";

/** What the fake layout measures: the header's width, the title's whole width,
 *  and how much of it shows with the pills and without them. */
const layout = { header: 340, whole: 250, withPills: 0, withoutPills: 60 };

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
  const hidden = useHeaderPillsFit(header, "title");
  return (
    <div ref={setHeader} data-testid="header">
      <span data-curio-node-title="true">Mean accumulated shadow by scenario</span>
      {hidden ? null : <span data-testid="pills">VIZ PACKAGE</span>}
    </div>
  );
}

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
        const withPills = !!this.closest('[data-testid="header"]')?.querySelector('[data-testid="pills"]');
        return withPills ? layout.withPills : layout.withoutPills;
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
  Object.assign(layout, { header: 340, whole: 250, withPills: 0, withoutPills: 60 });
});

test("a narrow header hides its pills, so its title shows", () => {
  render(<Header />);
  expect(screen.queryByTestId("pills")).toBeNull();
});

test("a header with room for both keeps its pills", () => {
  layout.withPills = TITLE_FLOOR_PX + 80;
  render(<Header />);
  expect(screen.getByTestId("pills")).toBeTruthy();
});

test("a short title that shows whole keeps the pills", () => {
  Object.assign(layout, { whole: 30, withPills: 30 });
  render(<Header />);
  expect(screen.getByTestId("pills")).toBeTruthy();
});

test("hidden pills come back once the header has room for them and the title's floor, not before", () => {
  render(<Header />);
  expect(screen.queryByTestId("pills")).toBeNull();
  // The pills came off a 340 px header with the title at 0: they fit back
  // beside the floor at 340 + 64.
  resize(340 + TITLE_FLOOR_PX - 10);
  expect(screen.queryByTestId("pills")).toBeNull();
  layout.withPills = TITLE_FLOOR_PX + 10;
  resize(340 + TITLE_FLOOR_PX + 10);
  expect(screen.getByTestId("pills")).toBeTruthy();
});
