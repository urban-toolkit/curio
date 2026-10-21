/**
 * The Map Edits node's map says it is drawn only once the draw of its latest
 * input has ended (components/mapEdits/MapEditsMap). A draw started for the
 * input before an edit, and ending after it, leaves the map drawing, so a wait
 * for the drawn map never reads the map from before the edit.
 */
const mockStates: any[] = [];
jest.mock("../../adapters/node/autkGrammarBehavior", () => ({
  useAutkGrammarBehavior: (_data: any, state: any) => {
    mockStates.push(state);
    return { applyGrammar: jest.fn(), contentComponent: <div data-testid="autark-map" /> };
  },
}));

import React from "react";
import { act, render } from "@testing-library/react";
import MapEditsMap from "../../components/mapEdits/MapEditsMap";

const DOC = JSON.stringify({ map: { layerRefs: [{ dataRef: "table_osm_buildings", isPick: true }] } });

function stateOf(container: HTMLElement): string | null {
  return container.querySelector("[data-map-edits-map-state]")!.getAttribute("data-map-edits-map-state");
}

beforeEach(() => {
  mockStates.length = 0;
});

test("a draw that ends after an edit, started for the input before it, leaves the map drawing", () => {
  const before = { dataType: "list", data: [{ name: "table_osm_buildings", edits: "before" }] };
  const after = { dataType: "list", data: [{ name: "table_osm_buildings", edits: "after" }] };
  const view = render(<MapEditsMap nodeId="edit-1" input={before} docText={DOC} onPick={() => {}} />);
  const drawingBefore = mockStates[mockStates.length - 1];
  act(() => drawingBefore.setOutput({ code: "success", content: "" }));
  expect(stateOf(view.container)).toBe("drawn");

  // An edit: a new input, whose draw has not ended.
  view.rerender(<MapEditsMap nodeId="edit-1" input={after} docText={DOC} onPick={() => {}} />);
  expect(stateOf(view.container)).toBe("drawing");

  // A draw started for the input before the edit ends now.
  act(() => drawingBefore.setOutput({ code: "success", content: "" }));
  expect(stateOf(view.container)).toBe("drawing");

  // The edit's own draw ends.
  const drawingAfter = mockStates[mockStates.length - 1];
  act(() => drawingAfter.setOutput({ code: "success", content: "" }));
  expect(stateOf(view.container)).toBe("drawn");
});
