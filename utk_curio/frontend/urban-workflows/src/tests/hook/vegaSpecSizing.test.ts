/**
 * How a Vega-Lite spec gets sized to its node (#202).
 *
 * `compileGrammar` set `width`/`height` to `"container"` unconditionally, which
 * is wrong twice: vega-lite's `normalizeAutoSize` throws both away for
 * multi-view specs (leaving `autosize: pad`, so the natural size wins and a
 * ~750px chart was clipped into a ~292px pane), and a spec that deliberately
 * declared its own size had it overwritten with no opt-out.
 *
 * Tested as a pure function because `vega` and `vega-lite` are ESM and
 * unloadable under jest — extracting it is what makes this assertable at all.
 */
import {
  MAX_SETTLE_PASSES,
  applyContainerSizing,
  createFlipGuard,
  fitsItsContainer,
  isMultiViewSpec,
  refitToContainer,
  settleFit,
} from "../../utils/vegaSpecSizing";

describe("isMultiViewSpec", () => {
  test.each(["vconcat", "hconcat", "concat", "facet", "repeat"])(
    "a top-level %s is multi-view",
    (key) => {
      expect(isMultiViewSpec({ [key]: [] })).toBe(true);
    },
  );

  test("a unit spec is not", () => {
    expect(isMultiViewSpec({ mark: "bar" })).toBe(false);
  });

  test("a layer spec is not — vega-lite honours container sizing there", () => {
    expect(isMultiViewSpec({ layer: [{ mark: "bar" }] })).toBe(false);
  });

  test.each([null, undefined, "nope"])("%p is not a spec", (value) => {
    expect(isMultiViewSpec(value as never)).toBe(false);
  });
});

describe("applyContainerSizing on a unit spec", () => {
  test("fills the container and asks the view to follow it", () => {
    const spec: Record<string, unknown> = { mark: "bar" };

    applyContainerSizing(spec);

    expect(spec.width).toBe("container");
    expect(spec.height).toBe("container");
    expect(spec.autosize).toEqual({
      type: "fit",
      contains: "padding",
      resize: true,
    });
  });

  test("a layer spec is sized the same way", () => {
    const spec: Record<string, unknown> = { layer: [{ mark: "line" }] };
    applyContainerSizing(spec);
    expect(spec.width).toBe("container");
  });
});

describe("applyContainerSizing on a spec that sized itself", () => {
  test("keeps an explicit width", () => {
    const spec: Record<string, unknown> = { mark: "bar", width: 800 };

    applyContainerSizing(spec);

    // The secondary defect: the author's own sizing was clobbered.
    expect(spec.width).toBe(800);
    // The dimension they did NOT set is still filled in.
    expect(spec.height).toBe("container");
  });

  test("keeps an explicit height", () => {
    const spec: Record<string, unknown> = { mark: "bar", height: 300 };
    applyContainerSizing(spec);
    expect(spec.height).toBe(300);
  });

  test("keeps an explicit autosize", () => {
    const spec: Record<string, unknown> = { mark: "bar", autosize: "pad" };
    applyContainerSizing(spec);
    expect(spec.autosize).toBe("pad");
  });

  test("a zero width counts as declared, not as absent", () => {
    const spec: Record<string, unknown> = { mark: "bar", width: 0 };
    applyContainerSizing(spec);
    expect(spec.width).toBe(0);
  });
});

/**
 * #1097: a size the author set is the plot's size. `fit` on such a size fitted
 * the whole chart into it, so the axes and the legend squeezed the plot, and
 * `resize: true` laid it out again on every hover. `autosize` now fits only
 * the sizes that are "container" once filled, whether the author left them
 * out or wrote "container"; with none, Vega-Lite's own `pad` lays the axes,
 * title and legend out around the plot.
 */
describe("applyContainerSizing fits only the sizes left to the node (#1097)", () => {
  test("an author's width leaves only the height to fit", () => {
    const spec: Record<string, unknown> = { mark: "bar", width: 800 };
    applyContainerSizing(spec);
    expect(spec.autosize).toEqual({ type: "fit-y", contains: "padding", resize: true });
  });

  test("an author's height leaves only the width to fit", () => {
    const spec: Record<string, unknown> = { mark: "bar", height: 300 };
    applyContainerSizing(spec);
    expect(spec.autosize).toEqual({ type: "fit-x", contains: "padding", resize: true });
  });

  test("an author's width and height get no autosize, so the plot keeps them", () => {
    const spec: Record<string, unknown> = { mark: "bar", width: 420, height: 220 };
    applyContainerSizing(spec);
    expect(spec.width).toBe(420);
    expect(spec.height).toBe(220);
    expect(spec.autosize).toBeUndefined();
  });

  test("a height in steps counts as set, so only the width fits", () => {
    const spec: Record<string, unknown> = { mark: "bar", height: { step: 14 } };
    applyContainerSizing(spec);
    expect(spec.autosize).toEqual({ type: "fit-x", contains: "padding", resize: true });
  });

  test("a width and a height in steps get no autosize", () => {
    // Scout's "dots with a range" template: 300 wide, a step per row.
    const spec: Record<string, unknown> = { layer: [{ mark: "point" }], width: 300, height: { step: 13 } };
    applyContainerSizing(spec);
    expect(spec.autosize).toBeUndefined();
  });

  test("an author's own \"container\" width fits, as a width left out does", () => {
    const spec: Record<string, unknown> = { mark: "bar", width: "container", height: 300 };
    applyContainerSizing(spec);
    expect(spec.autosize).toEqual({ type: "fit-x", contains: "padding", resize: true });
  });
});

describe("applyContainerSizing on a multi-view spec", () => {
  test("injects nothing — vega-lite would discard it, and the pane scrolls", () => {
    // The reported repro: docs/examples/05-vega-lite-multi-view-drilldown.json
    // is a top-level vconcat of 650x400 and 650x300 sub-views.
    const spec: Record<string, unknown> = {
      vconcat: [
        { mark: "bar", width: 650, height: 400 },
        { mark: "line", width: 650, height: 300 },
      ],
    };

    applyContainerSizing(spec);

    expect(spec.width).toBeUndefined();
    expect(spec.height).toBeUndefined();
    expect(spec.autosize).toBeUndefined();
  });

  test("the sub-views keep their own sizes untouched", () => {
    const spec: Record<string, unknown> = {
      vconcat: [{ mark: "bar", width: 650, height: 400 }],
    };

    applyContainerSizing(spec);

    expect((spec.vconcat as Record<string, unknown>[])[0]).toEqual({
      mark: "bar",
      width: 650,
      height: 400,
    });
  });

  test.each(["hconcat", "concat", "facet", "repeat"])(
    "%s is left alone too",
    (key) => {
      const spec: Record<string, unknown> = { [key]: [{ mark: "bar" }] };
      applyContainerSizing(spec);
      expect(spec.width).toBeUndefined();
    },
  );
});

describe("applyContainerSizing hands back what it was given", () => {
  test("returns the same object, so callers can use it inline", () => {
    const spec: Record<string, unknown> = { mark: "bar" };
    expect(applyContainerSizing(spec)).toBe(spec);
  });
});

/**
 * #496: vega-lite reads the container's size into the width/height signals at
 * start and on window:resize only, and `view.resize()` never re-reads it, so a
 * chart kept its first width after a scrollbar appeared or the node was resized.
 */
describe("refitToContainer", () => {
  const fakeView = () => ({ width: jest.fn(), height: jest.fn() });
  const mount = { clientWidth: 489, clientHeight: 250 };

  test("gives a container-width view the mount's current width", () => {
    const view = fakeView();
    refitToContainer(view, mount, applyContainerSizing({ mark: "bar", height: { step: 14 } }));
    expect(view.width).toHaveBeenCalledWith(489);
    expect(view.height).not.toHaveBeenCalled();
  });

  test("and a container-height view its height", () => {
    const view = fakeView();
    refitToContainer(view, mount, applyContainerSizing({ mark: "bar" }));
    expect(view.width).toHaveBeenCalledWith(489);
    expect(view.height).toHaveBeenCalledWith(250);
  });

  test("leaves a size the author declared alone", () => {
    const view = fakeView();
    refitToContainer(view, mount, applyContainerSizing({ mark: "bar", width: 800, height: 300 }));
    expect(view.width).not.toHaveBeenCalled();
    expect(view.height).not.toHaveBeenCalled();
  });

  test("does nothing for a multi-view spec, which keeps its natural size", () => {
    const view = fakeView();
    refitToContainer(view, mount, applyContainerSizing({ vconcat: [{ mark: "bar" }] }));
    expect(view.width).not.toHaveBeenCalled();
  });

  test("does nothing for a mount that is not laid out", () => {
    const view = fakeView();
    refitToContainer(view, { clientWidth: 0, clientHeight: 0 }, applyContainerSizing({ mark: "bar" }));
    expect(view.width).not.toHaveBeenCalled();
    expect(view.height).not.toHaveBeenCalled();
  });
});

describe("useVega re-reads the mount before every resize (#496)", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require("path") as typeof import("path");
  const source = fs.readFileSync(path.resolve(__dirname, "../../hook/useVega.ts"), "utf8");

  test("every view.resize() follows a refitToContainer", () => {
    // useVega cannot be rendered under jest (vega is ESM), so the wiring is
    // read from the source: each resize call must come right after a refit.
    const lines = source.split("\n");
    const resizes = lines
      .map((line, index) => ({ line, index }))
      .filter(({ line }) => /\.resize\(\)\.runAsync\(\)/.test(line));
    expect(resizes.length).toBeGreaterThanOrEqual(2);
    for (const { index } of resizes) {
      expect(lines[index - 1]).toMatch(/refitToContainer\(/);
    }
  });

  test("the resize observer checks for a scrollbar flip before it refits", () => {
    expect(source).toMatch(/if \(!flipping\(`\$\{el\.clientWidth\}x\$\{el\.clientHeight\}`\)\) refitToContainer\(/);
  });
});

/**
 * Vega fits a plot to its container in one pass: laid out for the axis labels
 * it makes at the size it starts from, it draws the labels its fitted size
 * makes. A dashboard chart of five rows (up to 9) fitted from its tile's full
 * height kept the room of labels "0.0" to "9.0" beside the "0" to "9" its plot
 * draws, while the same rows given to the chart in place fitted. After a pick
 * the tile showed one or the other, by which of its two redraws came last.
 */
describe("settleFit", () => {
  type Layout = [width: number, height: number, x: number, y: number];

  /** A view each fit pass of which moves it to the next of *layouts*, the
   * last one holding, or with *cycle* starting them over. */
  const fakeView = (layouts: Layout[], cycle = false) => {
    let at = 0;
    const view = {
      passes: 0,
      width: () => layouts[at][0],
      height: () => layouts[at][1],
      origin: () => [layouts[at][2], layouts[at][3]],
      resize: () => view,
      runAsync: async () => {
        view.passes += 1;
        at = cycle ? (at + 1) % layouts.length : Math.min(at + 1, layouts.length - 1);
        return view;
      },
    };
    return view;
  };

  test("a plot laid out for wider labels than it draws moves once, then holds", async () => {
    const view = fakeView([[782, 467, 36, 5], [790, 467, 28, 5]]);
    await settleFit(view);
    expect([view.width(), view.height(), view.origin()]).toEqual([790, 467, [28, 5]]);
    expect(view.passes).toBe(2);
  });

  test("a plot that fits what it draws takes one pass", async () => {
    const view = fakeView([[790, 467, 28, 5]]);
    await settleFit(view);
    expect(view.passes).toBe(1);
  });

  test("a move of the height alone, or of the origin alone, is a move", async () => {
    const taller = fakeView([[790, 440, 28, 5], [790, 467, 28, 5]]);
    await settleFit(taller);
    expect(taller.passes).toBe(2);
    const lower = fakeView([[790, 467, 28, 5], [790, 467, 28, 9]]);
    await settleFit(lower);
    expect(lower.passes).toBe(2);
  });

  test("labels that flip back and forth stop after MAX_SETTLE_PASSES", async () => {
    const view = fakeView([[782, 467, 36, 5], [790, 467, 28, 5]], true);
    await settleFit(view);
    expect(view.passes).toBe(MAX_SETTLE_PASSES);
  });

  test("no view, nothing to settle", async () => {
    await expect(settleFit(null)).resolves.toBeUndefined();
  });

  test("a stand-in view that cannot say where its plot is is left as it is", async () => {
    const runAsync = jest.fn(async () => undefined);
    const trimmed: any = { width: () => 0, height: () => 0, resize: () => ({ runAsync }) };
    await settleFit(trimmed);
    expect(runAsync).not.toHaveBeenCalled();
  });
});

describe("fitsItsContainer", () => {
  test("a spec sized to its node fits it", () => {
    expect(fitsItsContainer(applyContainerSizing({ mark: "bar" }))).toBe(true);
    expect(fitsItsContainer(applyContainerSizing({ mark: "bar", width: 400 }))).toBe(true);
    expect(fitsItsContainer(applyContainerSizing({ mark: "bar", height: 300 }))).toBe(true);
  });

  test("an author's autosize says it, as a word or an object", () => {
    expect(fitsItsContainer({ mark: "bar", autosize: "fit" })).toBe(true);
    expect(fitsItsContainer({ mark: "bar", autosize: { type: "pad" } })).toBe(false);
  });

  test("a spec that keeps its own size, or a multi-view one, does not", () => {
    expect(fitsItsContainer(applyContainerSizing({ mark: "bar", width: 400, height: 300 }))).toBe(false);
    expect(fitsItsContainer(applyContainerSizing({ vconcat: [{ mark: "bar" }] }))).toBe(false);
    expect(fitsItsContainer(null)).toBe(false);
  });
});

describe("useVega settles the fit after every draw and resize", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require("path") as typeof import("path");
  const source = fs.readFileSync(path.resolve(__dirname, "../../hook/useVega.ts"), "utf8");

  test("a compile settles after its refit, before its marks are counted", () => {
    expect(source).toMatch(
      /return view\.resize\(\)\.runAsync\(\);\s*\}\)\.then\(\(\) => \((\s*\/\/[^\n]*)*\s*settleView\(view, specObj\)\s*\)\)\.then\(\(\) => \{\s*const map = buildVgsidMap\(view\);/,
    );
  });

  test("new rows given in place settle before the chart says what it drew", () => {
    expect(source).toMatch(/\.runAsync\(\)\.then\(\(\) => settleView\(prevView, sizedSpec\)\)\.then\(/);
  });

  test("a mount or window resize settles after vega's own refit", () => {
    expect(source).toMatch(/view\.resize\(\)\.runAsync\(\);\s*settleSoon\(\);/);
    expect(source).toMatch(/window\.addEventListener\("resize", settleSoon\)/);
    expect(source).toMatch(/window\.setTimeout\(\(\) => \{\s*settleView\(currentViewRef\.current, sizedSpecRef\.current\)/);
  });
});

/**
 * #496's refit must not loop. In a browser with classic scrollbars a
 * container-sized chart that overflowed by a few pixels flipped between two
 * sizes every frame: the refit shrank it to the box the scrollbars left, which
 * removed the scrollbars, which grew the box, which grew the chart.
 */
describe("createFlipGuard", () => {
  test("lets new sizes through", () => {
    const flipping = createFlipGuard();
    expect(flipping("472x300")).toBe(false);
    expect(flipping("457x300")).toBe(false);
    expect(flipping("440x300")).toBe(false);
  });

  test("stops the A, B, A flip", () => {
    const flipping = createFlipGuard();
    expect(flipping("472x300")).toBe(false);
    expect(flipping("457x285")).toBe(false);
    expect(flipping("472x300")).toBe(true);
  });

  test("a repeated size is not a flip", () => {
    const flipping = createFlipGuard();
    expect(flipping("472x300")).toBe(false);
    expect(flipping("472x300")).toBe(false);
    expect(flipping("457x300")).toBe(false);
  });
});

describe("the Vega canvas has no baseline gap (#496)", () => {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const fs = require("fs") as typeof import("fs");
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const path = require("path") as typeof import("path");
  const css = fs.readFileSync(path.resolve(__dirname, "../../components/editing/NodeEditor.css"), "utf8");

  test("the output mount's canvas is a block", () => {
    // Inline, it left a descender gap that made a container-sized chart 4 px
    // taller than its mount, so the mount scrolled both ways.
    expect(css).toMatch(/\.curio-vega-mount > canvas \{[^}]*display:\s*block;/);
  });
});
