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
 * The width and margins that keep a mount clear of whichever edges carry a
 * port marker.
 *
 * A margin rather than padding: vega sizes a `"container"` chart from the
 * mount's `clientWidth`, which counts padding, so padding would have made the
 * chart overflow by exactly the inset.
 */
function portMarkerInset(inputMarker: boolean, outputMarker: boolean): React.CSSProperties {
  const left = inputMarker ? PORT_MARKER_INSET : 0;
  const right = outputMarker ? PORT_MARKER_INSET : 0;
  return {
    width: left + right ? `calc(100% - ${left + right}px)` : "100%",
    marginLeft: left,
    marginRight: right,
  };
}

/** The Vega-Lite output mount's style, inset from the port markers. */
export function outputMountStyle(inputMarker: boolean, outputMarker: boolean): React.CSSProperties {
  return {
    textAlign: "center",
    ...portMarkerInset(inputMarker, outputMarker),
    height: "100%",
    overflow: "auto",
  };
}

/**
 * A content node's mount (an Autark map or plot, a Data Pool table, ...): the
 * same inset and nothing more, since each content component lays out and
 * scrolls its own body (#631).
 */
export function contentMountStyle(inputMarker: boolean, outputMarker: boolean): React.CSSProperties {
  return {
    ...portMarkerInset(inputMarker, outputMarker),
    height: "100%",
  };
}
