/**
 * The Vega-Lite node and the Autark node take their input the same way.
 *
 * One table of situations, run through each node's own code: the same input
 * gets the same answer, the same flow state puts the same words in the node's
 * body, the starter fills an empty editor under the same conditions, and a
 * refused input gets the same verdict. Where the two nodes differ, the
 * difference is asserted as one; USAGE.md lists each ("Autark node").
 *
 * The redraw rule's table is in tests/components/universalNodeAutoRender.test.tsx,
 * which has the node harness it needs.
 */
import React from "react";
import { act, render } from "@testing-library/react";

jest.setTimeout(15000);

const mockFetchData = jest.fn();
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: (...args: any[]) => mockFetchData(...args),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

// The Vega-Lite node's own hook runs; only the library it hands a finished
// spec to is stubbed, and no case here gets that far.
const mockLiteCompile = jest.fn();
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({ compile: (...args: any[]) => mockLiteCompile(...args) }), { virtual: true });

let mockFlowEdges: any[] = [];
let mockNodeExecStatus: Record<string, string> = {};
jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({
    workflowNameRef: { current: "parity" },
    edges: mockFlowEdges,
    nodeExecStatus: mockNodeExecStatus,
  }),
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
  useProvenanceContext: () => ({ nodeExecProv: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("reactflow", () => ({
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  useStoreApi: () => ({
    subscribe: jest.fn().mockReturnValue(jest.fn()),
    getState: () => ({ edges: [] }),
  }),
  useEdges: () => [],
  useReactFlow: () => ({ getNode: () => undefined }),
}));
jest.mock("../../components/editing/OutputContent", () => ({ __esModule: true, default: () => null }));

const mockAutkRun = jest.fn();
jest.mock("@urban-toolkit/autk-grammar", () => ({
  AutkGrammar: jest.fn().mockImplementation(() => ({ run: (...args: any[]) => mockAutkRun(...args), data: {} })),
}), { virtual: true });
jest.mock("@urban-toolkit/autk-db", () => ({
  AutkDb: jest.fn(),
  DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395",
}), { virtual: true });

import { useVegaBehavior } from "../../adapters/node/vegaBehavior";
import { useAutkGrammarBehavior } from "../../adapters/node/autkGrammarBehavior";
import { prepareVegaInput, prepareVegaInputs } from "../../utils/vegaInput";
import { prepareAutkInput } from "../../utils/autkInput";
import { __resetWebGpuSupportCache } from "../../utils/webgpuSupport";

type Grammar = "vega" | "autk";
const GRAMMARS: Grammar[] = ["vega", "autk"];
const LABEL: Record<Grammar, string> = { vega: "the 2D Plot (Vega-Lite)", autk: "the Autark node" };
// A document of each grammar that draws its input's geometry.
const MAP: Record<Grammar, any> = {
  vega: { mark: "geoshape" },
  autk: { map: { layerRefs: [{ dataRef: "input_0" }] } },
};

const polygon = { type: "Polygon", coordinates: [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]] };
const point = { type: "Point", coordinates: [0.5, 0.5] };
const feature = (zip: string, geometry: any) => ({ type: "Feature", properties: { zip, pop: 1 }, geometry });

const INPUT = {
  gdf: {
    dataType: "geodataframe",
    data: {
      type: "FeatureCollection",
      geometry_name: "geometry",
      features: [feature("60601", polygon), feature("60602", polygon)],
    },
  },
  featureCollection: {
    dataType: "geodataframe",
    data: { type: "FeatureCollection", features: [feature("60601", polygon)] },
  },
  dfOneGeometry: { dataType: "dataframe", data: { zip: ["60601", "60602"], where: [polygon, polygon] } },
  dfNoGeometry: { dataType: "dataframe", data: { zip: ["60601", "60602"], pop: [1, 2] } },
  dfTwoGeometries: {
    dataType: "dataframe",
    data: { zip: ["60601", "60602"], area: [polygon, polygon], centre: [point, point] },
  },
  raster: { path: "art-raster", dataType: "raster" },
  // A type neither node reads: a code node's text.
  text: { path: "art-text", dataType: "str" },
  // A project saved before inputs carried their type restores as a bare path.
  untyped: { path: "art-untyped" },
  bundle: {
    dataType: "outputs",
    data: [
      { dataType: "geodataframe", data: INPUT_FC(), layerName: "zips" },
      { dataType: "geodataframe", data: INPUT_FC(), layerName: "centres" },
    ],
  },
};
function INPUT_FC() {
  return { type: "FeatureCollection", features: [feature("60601", polygon)] };
}

// Each node is handed its own copy: preparing an input writes into the spec
// (Vega-Lite's injected shape encoding), as it does in the app.
const fresh = <T,>(value: T): T => (value == null || value === "" ? value : JSON.parse(JSON.stringify(value)));

async function prepare(grammar: Grammar, input: any, doc: any = MAP[grammar]) {
  const prepared = grammar === "vega"
    ? await prepareVegaInput(fresh(input), fresh(doc))
    : await prepareAutkInput(fresh(input), fresh(doc));
  return { emptyReason: prepared.emptyReason ?? null, detail: prepared.detail ?? null };
}

beforeEach(() => {
  mockFetchData.mockReset();
  mockFetchPreviewData.mockReset();
  mockLiteCompile.mockReset();
  mockAutkRun.mockReset();
  mockFlowEdges = [];
  mockNodeExecStatus = {};
});

describe("the same input, the same answer", () => {
  const drawn = { emptyReason: null, detail: null };

  test.each([
    ["a GeoDataFrame", INPUT.gdf],
    ["a FeatureCollection that names no geometry column", INPUT.featureCollection],
    ["a DataFrame with one geometry column", INPUT.dfOneGeometry],
  ])("%s is drawn by both", async (_name, input) => {
    expect(await prepare("vega", input)).toEqual(drawn);
    expect(await prepare("autk", input)).toEqual(drawn);
  });

  test.each([
    ["a DataFrame with no geometry column", INPUT.dfNoGeometry, "geometry-unresolved"],
    ["a DataFrame with two geometry columns", INPUT.dfTwoGeometries, "geometry-ambiguous"],
  ])("%s is refused by both, for the same reason", async (_name, input, reason) => {
    expect((await prepare("vega", input)).emptyReason).toBe(reason);
    expect((await prepare("autk", input)).emptyReason).toBe(reason);
  });

  test("a type neither can read is refused before any fetch, in the same sentence", async () => {
    for (const grammar of GRAMMARS) {
      expect(await prepare(grammar, INPUT.text)).toEqual({
        emptyReason: "input-type-rejected",
        detail: `str is not a valid input type for ${LABEL[grammar]}.`,
      });
    }
    expect(mockFetchData).not.toHaveBeenCalled();
  });

  test("a restored input with no type is fetched, then judged by the type it turns out to be", async () => {
    mockFetchData.mockImplementation(async () => fresh(INPUT.gdf));
    for (const grammar of GRAMMARS) expect(await prepare(grammar, INPUT.untyped)).toEqual(drawn);

    mockFetchData.mockImplementation(async () => ({ dataType: "str", data: "a note" }));
    for (const grammar of GRAMMARS) {
      expect((await prepare(grammar, INPUT.untyped)).emptyReason).toBe("input-type-rejected");
    }
    expect(mockFetchData).toHaveBeenCalledTimes(4);
    expect(mockFetchData).toHaveBeenCalledWith("art-untyped");
  });

  test("nothing arrived: nothing to draw and nothing to say", async () => {
    for (const grammar of GRAMMARS) {
      expect(await prepare(grammar, "")).toEqual(drawn);
      expect(await prepare(grammar, null)).toEqual(drawn);
    }
  });

  describe("where they differ", () => {
    test("several inputs: Autark reads each as a table by its layer name; Vega-Lite as the datasets input_0, input_1", async () => {
      const autk = await prepareAutkInput(INPUT.bundle, { map: { layerRefs: [{ dataRef: "zips" }] } });
      expect(autk.tables).toEqual(["zips", "centres"]);
      expect(await prepare("vega", INPUT.bundle)).toEqual({ emptyReason: null, detail: null });
      const vega = await prepareVegaInputs(fresh(INPUT.bundle), fresh(MAP.vega));
      expect(vega.datasets.map((d) => [d.name, d.values.length])).toEqual([["input_0", 1], ["input_1", 1]]);
    });

    test("a raster: Autark reads it as the table input_0, unfetched; Vega-Lite refuses it before any fetch", async () => {
      expect(await prepare("vega", INPUT.raster)).toEqual({
        emptyReason: "input-type-rejected",
        detail: "raster is not a valid input type for the 2D Plot (Vega-Lite).",
      });
      const autk = await prepareAutkInput(fresh(INPUT.raster), fresh(MAP.autk));
      expect(autk).toMatchObject({
        sources: [],
        rasters: [{ outputTableName: "input_0", payload: { artifact: "art-raster" } }],
        tables: ["input_0"],
      });
      expect(autk.emptyReason).toBeUndefined();
      expect(mockFetchData).not.toHaveBeenCalled();
    });

    test("no geometry, no drawing: a Vega-Lite bar chart draws the frame no Autark document can", async () => {
      expect(await prepare("vega", INPUT.dfNoGeometry, { mark: "bar" })).toEqual(drawn);
      const plot = { plot: { dataRef: "input_0", type: "bar" } };
      expect((await prepare("autk", INPUT.dfNoGeometry, plot)).emptyReason).toBe("geometry-unresolved");
    });
  });
});

// ---------------------------------------------------------------------------
// The node in the canvas: each node's behavior, rendered the way UniversalNode
// renders it (Vega-Lite into the div it names, Autark as its own body).
// ---------------------------------------------------------------------------

type NodeProps = { code?: string; input?: any; defaultCode?: string };

function mountNode(grammar: Grammar, initialProps: NodeProps) {
  const initial = { ...initialProps, input: fresh(initialProps.input) };
  const latest: { current: any } = { current: null };
  // The node's output is state in the app: the same object until a run.
  const output = { code: "", content: "", outputType: "" };
  const setOutput = jest.fn();
  const callbacks = {
    outputCallback: jest.fn(),
    propagationCallback: jest.fn(),
    interactionsCallback: jest.fn(),
  };
  const useBehavior = grammar === "vega" ? useVegaBehavior : useAutkGrammarBehavior;
  const nodeType = grammar === "vega" ? "curio.builtin/vis-vega@1" : "curio.builtin/autk-grammar@1";

  function Node({ props }: { props: NodeProps }) {
    const code = props.code ?? "";
    const behavior = useBehavior(
      { nodeId: "n1", nodeType, input: props.input ?? "", code, defaultCode: props.defaultCode, ...callbacks } as any,
      { output, setOutput, code, setCode: jest.fn(), templateData: {} } as any,
    );
    latest.current = behavior;
    return grammar === "vega" ? <div id={behavior.outputIdOverride} /> : <>{behavior.contentComponent}</>;
  }

  let utils: ReturnType<typeof render>;
  const settle = () => act(async () => {});
  return {
    async mount() {
      await act(async () => {
        utils = render(<Node props={initial} />);
      });
      await settle();
      return this;
    },
    async update(props: NodeProps) {
      const next = { ...props, input: fresh(props.input) };
      await act(async () => {
        utils.rerender(<Node props={next} />);
      });
      await settle();
    },
    /** The state the node's body shows, and its words. */
    body() {
      const host = utils.container.querySelector("[data-curio-node-empty]");
      return { reason: host?.getAttribute("data-curio-node-empty") ?? null, words: host?.textContent ?? "" };
    },
    behavior: () => latest.current,
    setOutput,
  };
}

const connect = () => { mockFlowEdges = [{ id: "e", source: "up", target: "n1" }]; };

describe("both nodes, in the canvas", () => {
  // Autark refuses to run without a WebGPU adapter, and jsdom has none.
  beforeEach(() => {
    __resetWebGpuSupportCache();
    Object.defineProperty(navigator, "gpu", {
      configurable: true,
      value: { requestAdapter: jest.fn().mockResolvedValue({ name: "fake" }), getPreferredCanvasFormat: () => "bgra8unorm" },
    });
    (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
  });
  afterEach(() => {
    __resetWebGpuSupportCache();
    Object.defineProperty(navigator, "gpu", { configurable: true, value: undefined });
  });

  const doc = (grammar: Grammar) => JSON.stringify(MAP[grammar]);
  // An input with nothing either node could start a document from.
  const BARE = { dataType: "dataframe", data: { zip: [] } };

  describe("the same words in the body before anything is drawn", () => {
    const states: Array<[string, () => void, (g: Grammar) => NodeProps, string]> = [
      ["nothing connected", () => {}, (g) => ({ code: doc(g) }), "disconnected"],
      ["an empty editor with nothing connected", () => {}, () => ({ code: "" }), "disconnected"],
      ["connected to a node that has not run", connect, (g) => ({ code: doc(g) }), "upstream-not-run"],
      ["connected to a node that failed", () => { connect(); mockNodeExecStatus = { up: "errored" }; },
        (g) => ({ code: doc(g) }), "upstream-errored"],
      ["an input and an empty editor", connect, () => ({ code: "", input: BARE }), "no-spec"],
      ["an input and a document, not drawn yet", connect, (g) => ({ code: doc(g), input: BARE }), "not-run"],
    ];

    test.each(states)("%s", async (_name, arrange, props, reason) => {
      const bodies = [];
      for (const grammar of GRAMMARS) {
        arrange();
        const node = await mountNode(grammar, props(grammar)).mount();
        bodies.push(node.body());
      }
      expect(bodies[0].reason).toBe(reason);
      expect(bodies[1]).toEqual(bodies[0]);
    });

    test("a starter that filled the editor is a document, not an empty editor", async () => {
      connect();
      const bodies = [];
      for (const grammar of GRAMMARS) {
        const node = await mountNode(grammar, { code: "", input: INPUT.gdf }).mount();
        expect(node.behavior().defaultValueOverride).toBeDefined();
        bodies.push(node.body());
      }
      expect(bodies[0].reason).toBe("not-run");
      expect(bodies[1]).toEqual(bodies[0]);
    });

    test("where they differ: an Autark document that loads its own data needs no input", async () => {
      const own = JSON.stringify({
        data: [{ type: "json", jsonObject: [{ a: 1 }], outputTableName: "t" }],
        map: { layerRefs: [{ dataRef: "t" }] },
      });
      const autk = await mountNode("autk", { code: own }).mount();
      const vega = await mountNode("vega", { code: doc("vega") }).mount();
      expect(autk.body().reason).toBe("not-run");
      expect(vega.body().reason).toBe("disconnected");
    });
  });

  describe("the starter, under the same conditions", () => {
    const filled = async (grammar: Grammar, props: NodeProps) =>
      (await mountNode(grammar, props).mount()).behavior().defaultValueOverride !== undefined;

    test.each<[string, NodeProps, boolean]>([
      ["an input arriving on an empty editor fills it", { code: "", input: INPUT.gdf }, true],
      ["no input, no starter: an edge alone says nothing about the data", { code: "" }, false],
      ["an input with nothing to start from fills nothing", { code: "", input: BARE }, false],
      ["text already typed is never replaced", { code: '{"x": 1}', input: INPUT.gdf }, false],
      ["a document written in from outside is never replaced", { defaultCode: '{"x": 1}', input: INPUT.gdf }, false],
    ])("%s", async (_name, props, expected) => {
      expect(await filled("vega", props)).toBe(expected);
      expect(await filled("autk", props)).toBe(expected);
    });

    test("a document written in later wins over the starter", async () => {
      for (const grammar of GRAMMARS) {
        const node = await mountNode(grammar, { code: "", input: INPUT.gdf }).mount();
        expect(node.behavior().defaultValueOverride).toBeDefined();
        await node.update({ code: "", input: INPUT.gdf, defaultCode: '{"x": 1}' });
        expect(node.behavior().defaultValueOverride).toBeUndefined();
      }
    });

    test("filling the editor draws nothing", async () => {
      for (const grammar of GRAMMARS) await mountNode(grammar, { code: "", input: INPUT.gdf }).mount();
      expect(mockLiteCompile).not.toHaveBeenCalled();
      expect(mockAutkRun).not.toHaveBeenCalled();
    });
  });

  describe("the same verdict for an input it cannot read", () => {
    test("a refused type: the same kind of error, the same sentence, the upstream to blame", async () => {
      connect();
      const verdicts = [];
      for (const grammar of GRAMMARS) {
        const node = await mountNode(grammar, { code: doc(grammar), input: INPUT.text }).mount();
        await act(async () => {
          await node.behavior().applyGrammar(doc(grammar));
        });
        const error = node.setOutput.mock.calls.map((c) => c[0]).find((o) => o.code === "error");
        verdicts.push({ kind: error.kind, content: error.content.replace(LABEL[grammar], "<node>"), body: node.body() });
      }
      expect(verdicts[0].kind).toBe("empty-render:no-input-rows");
      expect(verdicts[0].content).toBe(
        "rendered nothing: str is not a valid input type for <node>. "
          + "The upstream node that feeds it is what must change; this document is not at fault.",
      );
      expect(verdicts[1].kind).toBe(verdicts[0].kind);
      expect(verdicts[1].content).toBe(verdicts[0].content);
      expect(verdicts.map((v) => v.body.reason)).toEqual(["input-type-rejected", "input-type-rejected"]);
      expect(mockFetchData).not.toHaveBeenCalled();
    });

    test("where they differ: a geometry the input lacks is the document's to fix in Vega-Lite, the upstream's in Autark", async () => {
      // A Vega-Lite spec could draw the same frame as a bar chart; no Autark
      // document can draw a table without geometry.
      connect();
      const kinds: Record<string, string> = {};
      for (const grammar of GRAMMARS) {
        const node = await mountNode(grammar, { code: doc(grammar), input: INPUT.dfNoGeometry }).mount();
        await act(async () => {
          await node.behavior().applyGrammar(doc(grammar));
        });
        kinds[grammar] = node.setOutput.mock.calls.map((c) => c[0]).find((o) => o.code === "error").kind;
        expect(node.body().reason).toBe("geometry-unresolved");
      }
      expect(kinds).toEqual({ vega: "empty-render:nothing-drawn", autk: "empty-render:no-input-rows" });
    });
  });
});
