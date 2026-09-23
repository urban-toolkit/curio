/**
 * The node container must never mix the `border` shorthand with a `border*`
 * longhand.
 *
 * It used to. `getNodeContainerStyles` supplied `borderLeft` (the node-type
 * accent stripe) and the inline style added the `border` shorthand when
 * dashboard mode was on, plus `borderWidth`/`borderStyle`/`borderColor` for a
 * suggested node. Toggling dashboard mode therefore changed which of the two
 * forms was present between renders, and React warned:
 *
 *   Warning: Removing a style property during rerender (border) when a
 *   conflicting property is set (borderLeft) can lead to styling bugs.
 *
 * A recorded user test caught it as a console error on the Dashboard Mode
 * toggle. Beyond the noise, mixing the two makes which border actually paints
 * depend on property order.
 *
 * The fix resolves the whole border in this one function, so that is what is
 * asserted here — rendering NodeContainer would need the entire provider tree
 * and would test React wiring rather than the invariant.
 */
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });
jest.mock("../../hook/useVega", () => ({
  useVega: () => ({ handleCompileGrammar: jest.fn() }),
}));

import { getNodeContainerStyles } from "../../components/styles";

const STATES: Array<{ name: string; state: Parameters<typeof getNodeContainerStyles>[1] }> = [
  { name: "on the canvas", state: {} },
  { name: "in dashboard mode", state: { dashboardOn: true } },
  { name: "as a suggestion", state: { suggested: true } },
  { name: "as an acceptable suggestion", state: { suggested: true, acceptable: true } },
  { name: "suggested inside dashboard mode", state: { dashboardOn: true, suggested: true } },
];

describe("getNodeContainerStyles", () => {
  test.each(STATES)("declares no border shorthand $name", ({ state }) => {
    const style = getNodeContainerStyles("curio.builtin/data-loading", state);
    // `border` and `borderRadius` are different properties; only the former is
    // the shorthand that conflicts with the longhands.
    expect(style).not.toHaveProperty("border");
  });

  test("keeps the node-type accent stripe on the canvas", () => {
    const style = getNodeContainerStyles("curio.builtin/data-loading", {});
    expect(style.borderLeftWidth).toBe("4px");
    expect(style.borderLeftStyle).toBe("solid");
    expect(style.borderLeftColor).toBeTruthy();
  });

  test("frames the node uniformly in dashboard mode", () => {
    // The point of this case is uniformity: on the dashboard a tile is content,
    // so it drops the per-kind accent the canvas uses to tell nodes apart. The
    // frame itself is a card (hairline border, rounded, resting shadow) rather
    // than the 2px black square it used to be, which read as a node lifted off
    // a canvas instead of as something published.
    const loader = getNodeContainerStyles("curio.builtin/data-loading", { dashboardOn: true });
    const chart = getNodeContainerStyles("curio.builtin/vis-vega", { dashboardOn: true });

    expect(chart).toEqual(loader);
    expect(loader.borderStyle).toBe("solid");
    expect(loader.borderWidth).toBe("1px");
    expect(loader.borderLeftWidth).toBeUndefined();
    expect(loader.borderColor).toBe("var(--curio-border)");
    expect(loader.borderRadius).toBe("var(--curio-radius-lg)");
    expect(loader.boxShadow).toBe("var(--curio-shadow-browse-card)");
  });

  test("resolves a versioned node type to the same accent as an unversioned one", () => {
    // Palette-dragged nodes persist `...@1`; an unnormalised lookup used to fall
    // back to grey (#159).
    const plain = getNodeContainerStyles("curio.builtin/data-loading", {});
    const versioned = getNodeContainerStyles("curio.builtin/data-loading@1", {});
    expect(versioned.borderLeftColor).toBe(plain.borderLeftColor);
  });
});
