/**
 * Shared tags (#662): a Parameter node holds one widget, and any node's code
 * names it as `[!! @name !!]`. It has no edge, so the nodes it reaches, the
 * run keys it changes and the code a rename rewrites are all found by reading
 * the nodes' code.
 */
import {
  PARAMETER_NODE_TYPE,
  isParameterNode,
  nodesUsingShared,
  runKeyWithShared,
  sharedWidgetsOf,
  sharedWidgetsOfSpec,
  withSharedRenamed,
} from "../../utils/references/sharedParameters";
import {
  parseReference,
  renameSharedReferences,
  resolveReferences,
  sharedNamesIn,
} from "../../utils/references/codeReferences";
import { nodeRunKey, type WidgetDef } from "../../utils/widgets/widgetModel";
import { CURIO_UNIVERSAL_NODE_TYPE } from "../../constants";

const season: WidgetDef = { name: "season", type: "text", default: "summer" };
const factor: WidgetDef = { name: "factor", type: "number", default: 2 };

function canvasNode(id: string, nodeType: string, data: Record<string, unknown> = {}) {
  return { id, type: CURIO_UNIVERSAL_NODE_TYPE, data: { nodeId: id, nodeType, ...data } as Record<string, any> };
}

const parameter = (id: string, widget: WidgetDef) =>
  canvasNode(id, `${PARAMETER_NODE_TYPE}@1`, { widgets: [widget] });
const code = (id: string, text: string, extra: Record<string, unknown> = {}) =>
  canvasNode(id, "curio.builtin/computation-analysis@1", { code: text, ...extra });

describe("the reference", () => {
  test("[!! @name !!] is a shared reference, not a widget or an input", () => {
    expect(parseReference("@season")).toEqual({ kind: "shared", name: "season" });
    expect(parseReference("season")).toEqual({ kind: "widget", name: "season" });
    expect(parseReference("input 0")).toEqual({ kind: "input", slot: 0 });
  });

  test("the names a code uses, each once", () => {
    expect(sharedNamesIn("a = [!! @k !!] + [!! k !!] + [!! @j !!] * [!! @k !!]")).toEqual(["k", "j"]);
    expect(sharedNamesIn("a = [!! k !!]")).toEqual([]);
  });
});

describe("the shared tags of a dataflow", () => {
  test("are the widgets its Parameter nodes hold, versioned type or not", () => {
    const nodes = [
      parameter("p1", season),
      code("c1", "return 1", { widgets: [factor] }),
      canvasNode("p2", PARAMETER_NODE_TYPE, { widgets: [factor] }),
    ];
    expect(nodes.map(isParameterNode)).toEqual([true, false, true]);
    expect(sharedWidgetsOf(nodes).map((w) => w.name)).toEqual(["season", "factor"]);
  });

  test("keep two Parameter nodes with one name, so a reference to it says so", () => {
    const shared = sharedWidgetsOf([parameter("p1", factor), parameter("p2", { ...factor, default: 3 })]);
    expect(shared).toHaveLength(2);
    const { problems } = resolveReferences("x = [!! @factor !!]", { widgets: [], inputs: [], shared }, "python");
    expect(problems.map((p) => p.message)).toEqual([
      "[!! @factor !!]: 2 Parameter nodes are named factor. Rename all but one.",
    ]);
  });

  test("of a saved spec are read from metadata.widgets", () => {
    const spec = [
      { id: "p1", type: "curio.builtin/parameter@1", metadata: { widgets: [season] } },
      { id: "c1", type: "curio.builtin/computation-analysis@1", metadata: { widgets: [factor] } },
    ];
    expect(sharedWidgetsOfSpec(spec)).toEqual([season]);
  });
});

describe("the nodes that use a Parameter node", () => {
  test("are those whose code names it, not those with a widget of that name", () => {
    const nodes = [
      parameter("p1", season),
      code("uses", "s = [!! @season !!]"),
      code("own-widget", "s = [!! season !!]", { widgets: [season] }),
      code("other", "s = 1"),
      canvasNode("grammar", "curio.builtin/vis-vega@1", { code: '{"title": "[!! @season !!]"}' }),
    ];
    expect(nodesUsingShared(nodes, "season").map((n) => n.id)).toEqual(["uses", "grammar"]);
  });
});

describe("the run key", () => {
  const shared = [season, factor];

  test("is nodeRunKey's for code that names no shared tag, so saved results stay current", () => {
    expect(runKeyWithShared("return 1", [factor], shared)).toBe(nodeRunKey("return 1", [factor]));
    expect(runKeyWithShared("return 1", undefined, shared)).toBe("return 1");
  });

  test("changes with the value of a shared tag the code names", () => {
    const before = runKeyWithShared("x = [!! @factor !!]", undefined, shared);
    const after = runKeyWithShared("x = [!! @factor !!]", undefined, [season, { ...factor, value: 5 }]);
    expect(after).not.toBe(before);
  });

  test("does not change with a shared tag the code does not name", () => {
    const before = runKeyWithShared("x = [!! @factor !!]", undefined, shared);
    const after = runKeyWithShared("x = [!! @factor !!]", undefined, [{ ...season, value: "winter" }, factor]);
    expect(after).toBe(before);
  });
});

describe("renaming a Parameter node", () => {
  test("rewrites its references and keeps every other reference and the text around them", () => {
    expect(renameSharedReferences("a = [!! @k !!] + [!! k !!] + [!!  @k !!] + [!! @kk !!]", "k", "rate")).toBe(
      "a = [!! @rate !!] + [!! k !!] + [!! @rate !!] + [!! @kk !!]",
    );
    expect(renameSharedReferences("a = 1", "k", "rate")).toBe("a = 1");
  });

  test("rewrites the code and the editor's text of each node that uses it, and no other node", () => {
    const user = code("uses", "x = [!! @season !!]");
    const other = code("other", "x = [!! season !!]", { widgets: [season] });
    const param = parameter("p1", season);
    const out = withSharedRenamed([param, user, other], "season", "period");
    expect(out[0]).toBe(param);
    expect(out[2]).toBe(other);
    expect(out[1].data.code).toBe("x = [!! @period !!]");
    expect(out[1].data.defaultCode).toBe("x = [!! @period !!]");
    expect(user.data.code).toBe("x = [!! @season !!]");
  });
});
