import type React from "react";

/**
 * How far the output mount stays from an edge that carries a port marker.
 *
 * The input and output markers are 17 px boxes at the node's edges, over its
 * 5 px padding, so each covers 12 px of the output pane and sat on a chart's
 * y-axis title (#522).
 */
export const PORT_MARKER_INSET = 14;

/**
 * The output mount's style, inset from whichever edges carry a port marker.
 *
 * A margin rather than padding: vega sizes a `"container"` chart from the
 * mount's `clientWidth`, which counts padding, so padding would have made the
 * chart overflow by exactly the inset.
 */
export function outputMountStyle(inputMarker: boolean, outputMarker: boolean): React.CSSProperties {
  const left = inputMarker ? PORT_MARKER_INSET : 0;
  const right = outputMarker ? PORT_MARKER_INSET : 0;
  return {
    textAlign: "center",
    width: left + right ? `calc(100% - ${left + right}px)` : "100%",
    marginLeft: left,
    marginRight: right,
    height: "100%",
    overflow: "auto",
  };
}
