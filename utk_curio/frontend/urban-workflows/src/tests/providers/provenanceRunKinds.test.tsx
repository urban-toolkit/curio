/**
 * #1022: each of a node's runs in the provenance drawer reads "In: ... | Out: ...",
 * the kinds of data the run read and returned (utils/nodeRuns.ts). Every node
 * names them through `mapTypes` (utils/formatters), and the provider files a
 * run's kinds only as a list (ProvenanceProvider.tsx).
 *
 * `mapTypes` answered an object of flags, which the provider dropped, so every
 * run was filed with no kinds and both sides of every card read a dash. A code
 * node's reply and a chart's input also name their kind as one string, which
 * `mapTypes` read letter by letter, and a code node that wrote a warning was
 * filed as having failed.
 *
 * Each test runs a node's own code into the real provider. Nothing here mocks
 * `formatters`: a stand-in `mapTypes` would pass any kinds through.
 */
import React from "react";
import { act, render, renderHook } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";

// Only what useVega calls on the library, as vegaRedrawOutcome.test.tsx has it.
jest.mock("vega", () => {
  const changeset = () => {
    const cs: any = {
      remove: () => cs,
      insert: () => cs,
      modify: () => cs,
    };
    return cs;
  };
  class View {
    logLevel() { return this; }
    renderer() { return this; }
    initialize() { return this; }
    hover() { return this; }
    width() { return this; }
    height() { return this; }
    resize() { return this; }
    runAsync() { return Promise.resolve(this); }
    scenegraph() { return { root: { marktype: "rect", items: [{}, {}, {}] } }; }
    getState() { return { signals: {} }; }
    addSignalListener() {}
    change() { return this; }
  }
  return { changeset, View, parse: (spec: any) => spec, Warn: 2 };
}, { virtual: true });
jest.mock("vega-lite", () => ({ compile: () => ({ spec: {} }) }), { virtual: true });

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ workflowNameRef: { current: "wf" }, updateDataNode: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));
jest.mock("../../services/api", () => ({ fetchData: jest.fn(), fetchPreviewData: jest.fn() }));
jest.mock("../../utils/authApi", () => ({ getToken: () => "test-token" }));

import ProvenanceProvider, { useProvenanceContext, NodeExecRecord } from "../../providers/ProvenanceProvider";
import { mapTypes } from "../../utils/formatters";
import { PythonInterpreter } from "../../PythonInterpreter";
import { JavaScriptInterpreter } from "../../JavaScriptInterpreter";
import { useVega } from "../../hook/useVega";
import useTableData from "../../hook/useTableData";
import { useSimpleVisBehavior } from "../../adapters/node/simpleVisBehavior";

const CODE_ID = "3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57";
const CHART_ID = "8c1d2e3f-4a5b-4c6d-8e7f-9a0b1c2d3e4f";
const POOL_ID = "5e6f7a8b-9c0d-4e1f-8a2b-3c4d5e6f7a8b";
const VIEW_ID = "1a2b3c4d-5e6f-4a7b-8c9d-0e1f2a3b4c5d";

/** A code node's input as the backend names it in its reply: one table. */
const INPUT = { path: "art-in", dataType: "dataframe" };

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <ProvenanceProvider>{children}</ProvenanceProvider>
);

const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

/** The last run filed under *nodeId*. */
function lastRun(filed: Record<string, NodeExecRecord[]>, nodeId: string): NodeExecRecord {
  const runs = filed[nodeId] ?? [];
  expect(runs.length).toBeGreaterThan(0);
  return runs[runs.length - 1];
}

function frame(labels: string[]) {
  return {
    dataType: "dataframe",
    data: {
      label: labels,
      value: labels.map((_, i) => i + 1),
      interacted: Object.fromEntries(labels.map((_, i) => [String(i), "0"])),
    },
  };
}

function layer(name: string) {
  return {
    dataType: "geodataframe",
    data: {
      type: "FeatureCollection",
      features: [{ type: "Feature", geometry: { type: "Point", coordinates: [0, 0] }, properties: { name } }],
    },
  };
}

beforeAll(() => {
  (globalThis as any).ResizeObserver ??= class { observe() {} disconnect() {} };
});

const realFetch = global.fetch;
afterEach(() => {
  global.fetch = realFetch;
});

describe("mapTypes names the kinds of data a run read or returned", () => {
  test("each kind once, in the order of the port types", () => {
    expect(mapTypes(["geodataframe", "dataframe", "geodataframe"])).toEqual(["DATAFRAME", "GEODATAFRAME"]);
  });

  test("a number, a string or a boolean is a VALUE, a list a LIST, a dict JSON, a raster a RASTER", () => {
    expect(mapTypes(["int", "str", "float", "bool"])).toEqual(["VALUE"]);
    expect(mapTypes(["list"])).toEqual(["LIST"]);
    expect(mapTypes(["dict"])).toEqual(["JSON"]);
    expect(mapTypes(["raster"])).toEqual(["RASTER"]);
  });

  test("what a failed run returned is an ERROR", () => {
    expect(mapTypes(["error"])).toEqual(["ERROR"]);
  });

  test("a type that names no kind adds none", () => {
    // A bundle of several values ("outputs") does not say what it holds, and a
    // file reference does not say what is in the file.
    expect(mapTypes(["outputs", "file", "null", "unknown", "", "toString"])).toEqual([]);
    expect(mapTypes([])).toEqual([]);
  });
});

describe("a code node's run is filed with the kinds it read and returned", () => {
  type Interpreter = typeof PythonInterpreter | typeof JavaScriptInterpreter;

  /** Run a code node of *language* on INPUT, the backend answering *reply*, and return the run filed. */
  async function runCodeNode(language: Interpreter, nodeType: string, reply: object): Promise<NodeExecRecord> {
    global.fetch = jest.fn().mockResolvedValue({ ok: true, json: async () => reply }) as any;
    const { result } = renderHook(() => useProvenanceContext(), { wrapper });
    await act(async () => {
      new language().interpretCode(
        "return input_0", "return input_0", INPUT as any, ["dataframe"], jest.fn(),
        nodeType, CODE_ID, "wf", result.current.nodeExecProv,
      );
      await flushPromises();
    });
    return lastRun(result.current.provenanceGraphNodes, CODE_ID);
  }

  test("a Python node that read a table and returned a GeoDataFrame", async () => {
    const run = await runCodeNode(PythonInterpreter, "curio.builtin/computation-analysis@1", {
      stdout: [], stderr: "", input: INPUT, output: { path: "art-out", dataType: "geodataframe" },
    });

    expect(run.inputs).toEqual(["DATAFRAME"]);
    expect(run.outputs).toEqual(["GEODATAFRAME"]);
  });

  test("a JavaScript node that read a table and returned a number", async () => {
    const run = await runCodeNode(JavaScriptInterpreter, "curio.builtin/js-computation@1", {
      stdout: [], stderr: "", input: INPUT, output: { path: "art-out", dataType: "int" },
    });

    expect(run.inputs).toEqual(["DATAFRAME"]);
    expect(run.outputs).toEqual(["VALUE"]);
  });

  test("a run that wrote a warning and returned a table returned the table", async () => {
    const run = await runCodeNode(PythonInterpreter, "curio.builtin/computation-analysis@1", {
      stdout: [],
      stderr: "FutureWarning: the default of observed=False is deprecated",
      input: INPUT,
      output: { path: "art-out", dataType: "dataframe" },
    });

    expect(run.outputs).toEqual(["DATAFRAME"]);
  });

  test("a run that failed returned an error", async () => {
    const run = await runCodeNode(PythonInterpreter, "curio.builtin/computation-analysis@1", {
      stdout: [],
      stderr: "Traceback (most recent call last):\nKeyError: 'pop'",
      input: INPUT,
      output: { path: "", dataType: "str" },
    });

    expect(run.inputs).toEqual(["DATAFRAME"]);
    expect(run.outputs).toEqual(["ERROR"]);
  });
});

test("a Vega-Lite chart's draw is filed with the kind of the table it drew, which it passes on", async () => {
  document.body.innerHTML = `<div id="vega${CHART_ID}"></div>`;
  const spec = JSON.stringify({
    mark: "bar",
    encoding: { x: { field: "label", type: "nominal" }, y: { field: "value", type: "quantitative" } },
  });
  const data = { nodeId: CHART_ID, interactionsCallback: jest.fn(), outputCallback: jest.fn(), input: frame(["a", "b"]) };
  const { result } = renderHook(
    () => ({ vega: useVega({ data, code: spec, onRedraw: jest.fn() }), provenance: useProvenanceContext() }),
    { wrapper },
  );

  await act(async () => {
    await result.current.vega.handleCompileGrammar(spec);
  });

  const run = lastRun(result.current.provenance.provenanceGraphNodes, CHART_ID);
  expect(run.inputs).toEqual(["DATAFRAME"]);
  expect(run.outputs).toEqual(["DATAFRAME"]);
});

test("a Data Pool's run is filed with the kind of the layer it holds, which it passes on", () => {
  const { result, rerender } = renderHook(
    ({ input }: { input: any }) => ({
      table: useTableData({ data: { nodeId: POOL_ID, input } as any }),
      provenance: useProvenanceContext(),
    }),
    { wrapper, initialProps: { input: layer("first") } },
  );

  // The pool files a run each time new data reaches it.
  act(() => rerender({ input: layer("second") }));

  const run = lastRun(result.current.provenance.provenanceGraphNodes, POOL_ID);
  expect(run.inputs).toEqual(["GEODATAFRAME"]);
  expect(run.outputs).toEqual(["GEODATAFRAME"]);
});

test("a Simple View's run is filed with the kind of the table it shows, which it passes on", async () => {
  const seen: { provenance?: ReturnType<typeof useProvenanceContext> } = {};
  const nodeState = { setOutput: jest.fn() } as any;
  const base = { nodeId: VIEW_ID, outputCallback: jest.fn(), interactionsCallback: jest.fn() };
  const Probe = ({ input }: { input: any }) => {
    seen.provenance = useProvenanceContext();
    useSimpleVisBehavior({ ...base, input } as any, nodeState);
    return null;
  };
  const tree = (input: any) => (
    <ReactFlowProvider>
      <ProvenanceProvider>
        <Probe input={input} />
      </ProvenanceProvider>
    </ReactFlowProvider>
  );
  const { rerender } = render(tree(frame(["a"])));

  // The view files a run each time new data reaches it.
  await act(async () => {
    rerender(tree(frame(["a", "b"])));
  });

  const run = lastRun(seen.provenance!.provenanceGraphNodes, VIEW_ID);
  expect(run.inputs).toEqual(["DATAFRAME"]);
  expect(run.outputs).toEqual(["DATAFRAME"]);
});
