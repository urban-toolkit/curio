/**
 * How a Vega-Lite spec is sized to its node (#202).
 *
 * `compileGrammar` used to set `width`/`height` to `"container"`
 * unconditionally. That is wrong twice over:
 *
 * 1. **Multi-view specs discard it.** vega-lite's `normalizeAutoSize` throws
 *    both away for `vconcat` / `hconcat` / `concat` / `facet` / `repeat` and
 *    leaves `autosize: pad`, so the natural size is authoritative. The repro
 *    spec (`docs/examples/05-vega-lite-multi-view-drilldown.json`) is a
 *    top-level `vconcat` of 650x400 and 650x300 sub-views: roughly 750px of
 *    chart into a ~292px pane, clipped, with the `ResizeObserver` unable to
 *    help because `autosize: pad` ignores the container.
 * 2. **It clobbers the author's own sizing.** A spec that deliberately says
 *    `width: 800` had it overwritten with no way to opt out.
 *
 * So: leave multi-view specs alone (vega-lite would discard the injection
 * anyway, and the mount container scrolls now), and for unit/layer specs fill
 * the container only where the author has not said otherwise.
 *
 * Kept as a pure function so it is testable without mocking `vega` /
 * `vega-lite`, which are ESM and unloadable under jest.
 */

/** Top-level keys whose presence makes a spec multi-view. */
const MULTI_VIEW_KEYS = ["vconcat", "hconcat", "concat", "facet", "repeat"] as const;

export function isMultiViewSpec(spec: Record<string, unknown> | null | undefined): boolean {
  if (!spec || typeof spec !== "object") return false;
  return MULTI_VIEW_KEYS.some((key) => spec[key] != null);
}

/**
 * Applies container sizing in place and returns the same object.
 *
 * - multi-view: untouched.
 * - unit/layer: `width`/`height` become `"container"` **only** if the author
 *   did not declare them, and `autosize` is set to fit-with-resize so the view
 *   actually follows the container it is now sized against.
 */
export function applyContainerSizing<T extends Record<string, unknown>>(spec: T): T {
  if (!spec || typeof spec !== "object") return spec;
  if (isMultiViewSpec(spec)) return spec;

  if (spec.width === undefined) {
    (spec as Record<string, unknown>).width = "container";
  }
  if (spec.height === undefined) {
    (spec as Record<string, unknown>).height = "container";
  }
  // Only meaningful once at least one dimension is "container"; harmless
  // otherwise, and it is what makes the ResizeObserver's re-render take effect.
  if (spec.autosize === undefined) {
    (spec as Record<string, unknown>).autosize = {
      type: "fit",
      contains: "padding",
      resize: true,
    };
  }
  return spec;
}
