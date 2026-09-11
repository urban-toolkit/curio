/**
 * The edge drag-hover style (#296).
 *
 * The resting-state assertion is the load-bearing one: it is the guard against
 * this helper quietly restyling every edge on every canvas, which would move a
 * dozen committed screenshot baselines.
 */
import {
  EDGE_DROP_HOVER_STROKE,
  EDGE_DROP_HOVER_WIDTH,
  edgeDropHighlightStyle,
} from "../../components/edges/edgeDropHighlight";

describe("edgeDropHighlightStyle", () => {
  it("passes the base stroke through when nothing is hovering", () => {
    expect(edgeDropHighlightStyle("grey", false)).toEqual({ stroke: "grey" });
  });

  it("emits NO strokeWidth when resting", () => {
    // MainCanvas.css owns `path.react-flow__edge-path { stroke-width: 3 }` and
    // its `:hover` companion. An inline width here would beat both, for every
    // edge, on every canvas.
    expect(edgeDropHighlightStyle("red", false)).not.toHaveProperty("strokeWidth");
  });

  it("overrides stroke and width when hovered", () => {
    expect(edgeDropHighlightStyle("grey", true)).toEqual({
      stroke: EDGE_DROP_HOVER_STROKE,
      strokeWidth: EDGE_DROP_HOVER_WIDTH,
    });
  });

  it("highlights with a design token, not a colour literal", () => {
    expect(EDGE_DROP_HOVER_STROKE).toMatch(/^var\(--curio-[a-z-]+\)$/);
  });

  it("sits between the resting width and the pointer-hover width", () => {
    // 3 resting, 9 on pointer hover (MainCanvas.css). A drop target that read
    // as either of those would say nothing new.
    expect(EDGE_DROP_HOVER_WIDTH).toBeGreaterThan(3);
    expect(EDGE_DROP_HOVER_WIDTH).toBeLessThan(9);
  });
});
