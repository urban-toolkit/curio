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
  applyContainerSizing,
  isMultiViewSpec,
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
