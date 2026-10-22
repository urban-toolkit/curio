/**
 * The drawing tools an Interaction node lends a map (#662,
 * `utils/editFeatures/mapEditBus`), kept by the map and the node: a map two
 * nodes feed keeps each one's session, and a node takes back its own alone.
 * And the picks between them (`mapEditSelection`): a selection names
 * features by the layer's id column, and is read back by it.
 */
import { mapSession, onMapSession, publishMapSession, type MapEditSession } from "../../utils/editFeatures/mapEditBus";
import { editSelection, selectedIdsIn, toggledIds } from "../../utils/editFeatures/mapEditSelection";

const session = (interactionId: string): MapEditSession => ({
  interactionId,
  active: null,
  onDrawn: jest.fn(),
  onReshape: jest.fn(),
});

test("a map two Interaction nodes feed keeps each one's session; a node takes back its own alone", () => {
  const heard = jest.fn();
  const off = onMapSession("map", heard);
  publishMapSession("map", "a", session("a"));
  publishMapSession("map", "b", session("b"));
  // The latest published is the one the map shows.
  expect(mapSession("map")?.interactionId).toBe("b");
  publishMapSession("map", "b", null);
  expect(mapSession("map")?.interactionId).toBe("a");
  // Taking back a session a node never published leaves the other's.
  publishMapSession("map", "c", null);
  expect(mapSession("map")?.interactionId).toBe("a");
  publishMapSession("map", "a", session("a"));
  publishMapSession("map", "a", null);
  expect(mapSession("map")).toBeUndefined();
  expect(heard).toHaveBeenCalledTimes(5);
  off();
});

test("a selection names the picked features by the layer's id column, on the map's table, and is read back by it", () => {
  const features = [119, 136, 200].map((id) => ({ id, properties: { building_id: id, height: id / 10 } }));
  const details = editSelection([200, 119], "building_id", "input_0", "curio.builtin/edit-features");
  expect(details.autk_selection).toMatchObject({ data: [{ building_id: 200 }, { building_id: 119 }], layerRef: "input_0", source: "curio.builtin/edit-features" });
  const incoming = [{ nodeId: "map", details, priority: 1 }];
  const fromMap = (from?: string, layer?: string) => from === "map" && (layer ?? "input_0") === "input_0";
  // In the features' order.
  expect(selectedIdsIn(incoming, fromMap, features)).toEqual([119, 200]);
  // Another node's, or another layer's, is no selection here.
  expect(selectedIdsIn([{ nodeId: "chart", details, priority: 1 }], fromMap, features)).toBeNull();
  expect(selectedIdsIn([{ nodeId: "map", details: editSelection([119], "building_id", "roads"), priority: 1 }], fromMap, features)).toBeNull();
  // A selection of nothing clears.
  expect(selectedIdsIn([{ nodeId: "map", details: editSelection([], "building_id", "input_0"), priority: 1 }], fromMap, features)).toEqual([]);
  // A shift-click adds, or takes out.
  expect(toggledIds([119], 136)).toEqual([119, 136]);
  expect(toggledIds([119, 136], 119)).toEqual([136]);
});
