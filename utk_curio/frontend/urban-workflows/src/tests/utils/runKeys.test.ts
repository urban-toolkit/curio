/**
 * A node's run key (#662): `nodeRunKey` for code that names no selection tag,
 * so a saved result stays current, and what the tags its code names hold
 * beside it. No chip names another node's widget, so no other node's value
 * is part of the key.
 */
import { parseReference } from "../../utils/references/codeReferences";
import { runKeyOf, runKeyOfData, runKeysOf } from "../../utils/references/runKeys";
import { nodeRunKey, type WidgetDef } from "../../utils/widgets/widgetModel";

const factor: WidgetDef = { name: "factor", type: "number", default: 2 };
const picked = { name: "picked", node: "chart", column: "osm_id", ids: [101, 104] };

describe("the run key", () => {
  test("is nodeRunKey's for code that names no selection tag, so saved results stay current", () => {
    expect(runKeyOf("return 1", [factor])).toBe(nodeRunKey("return 1", [factor]));
    expect(runKeyOf("return 1", undefined)).toBe("return 1");
    expect(runKeyOf("return 1", [factor], [picked])).toBe(nodeRunKey("return 1", [factor]));
  });

  test("changes with what a selection tag the code names holds", () => {
    const code = "return [!! selection picked !!]";
    expect(runKeyOf(code, undefined, [{ ...picked, ids: [101] }])).not.toBe(runKeyOf(code, undefined, [picked]));
  });

  test("reads no other node: [!! @factor !!] is a widget's name that no widget can have", () => {
    expect(parseReference("@factor")).toEqual({ kind: "widget", name: "@factor" });
    expect(runKeyOf("x = [!! @factor !!]", undefined)).toBe(nodeRunKey("x = [!! @factor !!]", undefined));
  });

  test("of a node's data, and of every node at once, is the same key", () => {
    const data = { code: "return [!! selection picked !!]", widgets: [factor], selections: [picked] };
    expect(runKeyOfData(data)).toBe(runKeyOf(data.code, data.widgets, data.selections));
    expect(runKeysOf([{ id: "a", data }, { id: "b", data: { code: "return 1" } }])).toEqual(
      new Map([
        ["a", runKeyOfData(data)],
        ["b", "return 1"],
      ]),
    );
  });
});
