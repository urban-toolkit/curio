/**
 * Run All, a node's play and Ctrl+Enter run on the server (useServerRun): the
 * canvas saves, starts a run of the saved revision, and follows its stream.
 *
 * - each event becomes the node state a run in the browser leaves;
 * - the nodes only a browser can run start in the tick the server's part ends,
 *   and each is reported to the run;
 * - Stop gives the button back at once and cancels the run;
 * - a dataflow that already runs is followed rather than refused;
 * - a canvas opened later shows only the outputs whose code it still holds and
 *   that the saved outputs did not restore, saving nothing;
 * - a run waiting for the canvas offers "Finish run".
 */
import { act, renderHook } from "@testing-library/react";

jest.mock("../../services/runs/runsApi", () => {
  const actual = jest.requireActual("../../services/runs/runsApi");
  return {
    ...actual,
    runsApi: {
      start: jest.fn(),
      get: jest.fn(),
      listForProject: jest.fn(),
      cancel: jest.fn(),
      reportStep: jest.fn(),
      follow: jest.fn(),
    },
  };
});

import { runsApi } from "../../services/runs/runsApi";
import type { Run, RunEvent, RunStep } from "../../services/runs/runsApi";
import { useServerRun } from "../../providers/flow/useServerRun";
import {
  STOPPED_MESSAGE,
  browserWalk,
  nodeChangeFor,
  stepsToRestore,
} from "../../providers/flow/serverRunSteps";

const api = runsApi as jest.Mocked<typeof runsApi>;

function step(nodeId: string, fields: Partial<RunStep> = {}): RunStep {
  return {
    nodeId, label: nodeId, nodeType: "curio.builtin/computation-analysis", level: 0,
    role: "run", status: "pending", startedAt: null, finishedAt: null, durationMs: null,
    outputPath: null, outputType: null, installedDatasetId: null, codeSha256: null,
    stdoutTail: null, stderrTail: null, skipReason: null, ...fields,
  };
}

function run(id: string, steps: RunStep[], fields: Partial<Run> = {}): Run {
  return {
    id, projectId: "p1", projectName: "Flow", trigger: "all", targetNodeId: null,
    wholeDataflow: true, rerunOf: null, specRevision: 3, status: "queued",
    createdAt: null, startedAt: null, finishedAt: null,
    counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 }, error: null, live: true,
    steps, ...fields,
  };
}

const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

/** The hook over a canvas of plain nodes, with every dependency a spy. */
function harness(initial: Array<{ id: string; data?: any }>, edges: any[] = []) {
  let nodes = initial.map((n) => ({ id: n.id, position: { x: 0, y: 0 }, data: { ...(n.data ?? {}) } }));
  const setNodes = jest.fn((next: any) => { nodes = typeof next === "function" ? next(nodes) : next; });
  const reactFlow: any = {
    getNode: (id: string) => nodes.find((n) => n.id === id),
    getNodes: () => nodes,
    getEdges: () => edges,
  };
  const deps = {
    reactFlow,
    setNodes,
    showToast: jest.fn(),
    requestProjectSave: jest.fn().mockResolvedValue({ id: "p1", spec_revision: 3 }),
    applyNewOutput: jest.fn(),
    setOutputs: jest.fn(),
    hydrateRestoredOutputs: jest.fn(),
    markNodeErroredRef: { current: jest.fn() },
    playNodes: jest.fn().mockReturnValue(true),
    playAllStateRef: { current: null },
    emittedForInputRef: { current: new Map() },
    outputsRef: { current: [] as any[] },
    workflowNameRef: { current: "Flow" },
    nodeExecProv: jest.fn(),
    flushInstallSyncRef: { current: jest.fn() },
  };
  const hook = renderHook(() => useServerRun(deps as any));
  const shown = (id: string) => nodes.find((n) => n.id === id)?.data?.serverOutput?.output;
  const node = (id: string) => nodes.find((n) => n.id === id);
  return { hook, deps, shown, node };
}

/** Follow the run through a stream the test drives. */
function stream() {
  const handle: { emit: (e: RunEvent) => void; runIds: string[] } = { emit: () => {}, runIds: [] };
  api.follow.mockImplementation((runId, onEvent, signal) => {
    handle.runIds.push(runId);
    handle.emit = (event) => act(() => onEvent(event));
    return new Promise<void>((resolve) => signal?.addEventListener("abort", () => resolve()));
  });
  return handle;
}

beforeEach(() => {
  jest.clearAllMocks();
  api.cancel.mockResolvedValue(run("r1", []));
  api.reportStep.mockResolvedValue(run("r1", []));
});

describe("what an event does to its node", () => {
  const ran = { role: "run" as const, status: "running" as const };

  it("a started step runs, a finished one shows its reply, a skipped one says why", () => {
    expect(nodeChangeFor({ kind: "step_started", nodeId: "a", startedAt: 1 }, ran, { started: false }))
      .toEqual({ kind: "running" });
    const reply = { stdout: ["hi"], stderr: "", output: { path: "art-a", dataType: "dataframe" } };
    expect(nodeChangeFor({ kind: "step_finished", nodeId: "a", status: "ok", reply }, ran, { started: true }))
      .toMatchObject({ kind: "result", reply });
    expect(nodeChangeFor({ kind: "step_finished", nodeId: "a", status: "skipped", skipReason: "No data yet" }, ran, { started: false }))
      .toEqual({ kind: "skipped", reason: "No data yet" });
  });

  it("a failure the engine made, with no reply, shows its stderr as a failed run", () => {
    const change = nodeChangeFor(
      { kind: "step_finished", nodeId: "a", status: "error", stderrTail: "Unknown reference" }, ran, { started: true },
    );
    expect(change).toMatchObject({ kind: "result", reply: { stderr: "Unknown reference", output: { path: "" } } });
  });

  it("a stopped node that never started keeps what it showed", () => {
    const stopped = { kind: "step_finished" as const, nodeId: "a", status: "cancelled" as const };
    expect(nodeChangeFor(stopped, ran, { started: true })).toEqual({ kind: "stopped" });
    expect(nodeChangeFor(stopped, ran, { started: false })).toBeNull();
  });

  it("a forwarded node, a browser node and a waiting one are left to the canvas", () => {
    for (const status of ["forwarded", "browser", "waiting"] as const) {
      expect(nodeChangeFor({ kind: "step_finished", nodeId: "a", status }, ran, { started: false })).toBeNull();
    }
  });
});

describe("which nodes the browser still runs", () => {
  it("browser and waiting nodes, and the forwarded nodes above them", () => {
    const steps = new Map([
      ["code", { role: "run" as const, status: "ok" as const }],
      ["pool", { role: "forward" as const, status: "forwarded" as const }],
      ["map", { role: "browser" as const, status: "browser" as const }],
      ["after", { role: "run" as const, status: "waiting" as const }],
      ["chart", { role: "forward" as const, status: "forwarded" as const }],
    ]);
    const edges: any[] = [
      { source: "code", target: "pool" }, { source: "pool", target: "map" },
      { source: "map", target: "after" }, { source: "code", target: "chart" },
    ];
    expect(new Set(browserWalk(steps, edges))).toEqual(new Set(["pool", "map", "after"]));
    // A played chart the run only forwarded is drawn by the browser, as its play draws it.
    expect(browserWalk(new Map([["chart", { role: "forward" as const, status: "forwarded" as const }]]), [], "chart"))
      .toEqual(["chart"]);
  });
});

describe("a run started on the canvas", () => {
  it("saves first, then runs the saved revision", async () => {
    stream();
    api.start.mockResolvedValue(run("r1", [step("a")]));
    const { hook, deps } = harness([{ id: "a" }]);

    await act(async () => { await hook.result.current.startRun(); });

    expect(deps.requestProjectSave).toHaveBeenCalledTimes(1);
    expect(api.start).toHaveBeenCalledWith("p1", { specRevision: 3 });
    expect(deps.requestProjectSave.mock.invocationCallOrder[0])
      .toBeLessThan(api.start.mock.invocationCallOrder[0]);
    expect(hook.result.current.serverRunActive).toBe(true);
  });

  it("turns each event into the node state a run in the browser leaves", async () => {
    const live = stream();
    api.start.mockResolvedValue(run("r1", [step("a"), step("b"), step("c")]));
    const { hook, deps, shown, node } = harness([{ id: "a", data: { code: "return 1" } }, { id: "b" }, { id: "c" }]);
    await act(async () => { await hook.result.current.startRun(); });

    live.emit({ kind: "step_started", nodeId: "a", startedAt: 1700000000 });
    expect(shown("a")).toEqual({ code: "exec", content: "" });

    live.emit({
      kind: "step_finished", nodeId: "a", status: "ok", startedAt: 1700000000, finishedAt: 1700000002,
      reply: { stdout: ["ran a"], stderr: "", input: null, output: { path: "art-a", dataType: "dataframe" } },
    });
    expect(shown("a")).toEqual({ code: "success", content: "stdout:\nran a\nSaved to file: art-a" });
    expect(deps.applyNewOutput).toHaveBeenCalledWith({ nodeId: "a", output: { path: "art-a", dataType: "dataframe" } });
    expect(deps.nodeExecProv).toHaveBeenCalledTimes(1);
    expect(deps.nodeExecProv.mock.calls[0][3]).toBe("a");
    expect(deps.nodeExecProv.mock.calls[0][6]).toBe("return 1");

    live.emit({ kind: "step_finished", nodeId: "b", status: "error", stderrTail: "Traceback: boom" });
    expect(shown("b")).toMatchObject({ code: "error", content: "Traceback: boom" });
    expect(deps.markNodeErroredRef.current).toHaveBeenCalledWith("b");

    live.emit({ kind: "step_finished", nodeId: "c", status: "skipped", skipReason: 'No data yet: "b" failed.' });
    expect(node("c")?.data.skipExec).toBe(1);
    expect(node("c")?.data.skipReason).toBe('No data yet: "b" failed.');

    // A replayed event is not applied twice.
    live.emit({ kind: "step_finished", nodeId: "a", status: "ok", reply: { output: { path: "art-a" } } });
    expect(deps.applyNewOutput).toHaveBeenCalledTimes(1);
  });

  it("starts the browser's part in the tick the server's ends, and reports each node", async () => {
    const live = stream();
    api.start.mockResolvedValue(run("r1", [step("osm", { role: "browser" }), step("count", { level: 1 })]));
    const { hook, deps } = harness([{ id: "osm" }, { id: "count" }], [{ source: "osm", target: "count" }]);
    await act(async () => { await hook.result.current.startRun(); });

    live.emit({ kind: "step_finished", nodeId: "osm", status: "browser" });
    live.emit({ kind: "step_finished", nodeId: "count", status: "waiting", skipReason: "Waits for the canvas" });
    expect(deps.playNodes).not.toHaveBeenCalled();
    live.emit({ kind: "run_finished", status: "needs_canvas", ok: 0, failed: 0, skipped: 0, waiting: 1 });

    expect(hook.result.current.serverRunActive).toBe(false);
    expect(deps.playNodes).toHaveBeenCalledTimes(1);
    expect(new Set(deps.playNodes.mock.calls[0][0])).toEqual(new Set(["osm", "count"]));

    const { onNodeDone } = deps.playNodes.mock.calls[0][1];
    onNodeDone("osm", { failed: false });
    onNodeDone("count", { failed: true, skipReason: "The node feeding this one failed." });
    expect(api.reportStep).toHaveBeenCalledWith("r1", "osm", { status: "ok" });
    expect(api.reportStep).toHaveBeenCalledWith("r1", "count", {
      status: "error", message: "The node feeding this one failed.",
    });
  });

  it("Stop gives the button back at once, cancels the run, and a running node says it stopped", async () => {
    const live = stream();
    api.start.mockResolvedValue(run("r1", [step("a"), step("b", { level: 1 })]));
    const { hook, shown } = harness([{ id: "a" }, { id: "b" }]);
    await act(async () => { await hook.result.current.startRun(); });
    live.emit({ kind: "step_started", nodeId: "a", startedAt: 1 });

    act(() => hook.result.current.stopRun());

    expect(hook.result.current.serverRunActive).toBe(false);
    expect(api.cancel).toHaveBeenCalledWith("r1");
    expect(shown("a")).toEqual({ code: "error", content: STOPPED_MESSAGE });
    expect(shown("b")).toBeUndefined();
  });

  it("follows the run already going when the dataflow runs", async () => {
    const live = stream();
    api.start.mockRejectedValue(Object.assign(new Error("This dataflow is already running."), {
      status: 409, body: { runId: "r9" },
    }));
    api.get.mockResolvedValue(run("r9", [step("a")], { status: "running" }));
    const { hook, deps } = harness([{ id: "a" }]);

    await act(async () => { await hook.result.current.startRun(); });

    expect(api.get).toHaveBeenCalledWith("r9");
    expect(live.runIds).toEqual(["r9"]);
    expect(hook.result.current.serverRunActive).toBe(true);
    expect(deps.showToast).not.toHaveBeenCalled();
  });

  it("a played node says it runs from the click, and gets its output back if the save fails", async () => {
    const before = { code: "success", content: "Saved to file: old" };
    const { hook, deps, shown } = harness([{ id: "a", data: { output: before } }]);
    let failSave: (err: Error) => void = () => {};
    deps.requestProjectSave.mockReturnValue(new Promise((_, reject) => { failSave = reject; }));

    let started: Promise<void> = Promise.resolve();
    act(() => { started = hook.result.current.startRun("a"); });
    expect(shown("a")).toEqual({ code: "exec", content: "" });

    await act(async () => { failSave(new Error("Guest users cannot save projects")); await started; });

    expect(shown("a")).toEqual(before);
    expect(api.start).not.toHaveBeenCalled();
    expect(hook.result.current.serverRunActive).toBe(false);
    expect(deps.showToast).toHaveBeenCalledWith(expect.stringContaining("could not be saved"), "error");
  });
});

describe("a canvas opened after a run", () => {
  it("shows only the outputs whose code it still holds and that were not restored, saving nothing", async () => {
    api.listForProject.mockResolvedValue([run("r1", [], { status: "succeeded" })]);
    api.get.mockResolvedValue(run("r1", [
      step("saved", { status: "ok", outputPath: "art-saved", codeCurrent: true }),
      step("edited", { status: "ok", outputPath: "art-edited", codeCurrent: false }),
      step("kept", { status: "ok", outputPath: "art-kept", outputType: "dataframe", codeCurrent: true, stdoutTail: "rows: 3" }),
      step("failed", { status: "error", codeCurrent: true }),
    ], { status: "succeeded" }));
    const { hook, deps, shown } = harness([{ id: "saved" }, { id: "edited" }, { id: "kept" }, { id: "failed" }]);

    await act(async () => { await hook.result.current.attachLatestRun("p1", new Set(["saved"])); });

    expect(shown("kept")).toEqual({ code: "success", content: "stdout:\nrows: 3\nSaved to file: art-kept" });
    expect(shown("saved")).toBeUndefined();
    expect(shown("edited")).toBeUndefined();
    expect(shown("failed")).toBeUndefined();
    expect(deps.hydrateRestoredOutputs).toHaveBeenCalledWith([
      { nodeId: "kept", output: { path: "art-kept", dataType: "dataframe" } },
    ]);
    // Opening a page saves nothing and records no run of its own.
    expect(deps.applyNewOutput).not.toHaveBeenCalled();
    expect(deps.nodeExecProv).not.toHaveBeenCalled();
    expect(api.follow).not.toHaveBeenCalled();
  });

  it("follows a run that is still going", async () => {
    const live = stream();
    api.listForProject.mockResolvedValue([run("r1", [], { status: "running" })]);
    api.get.mockResolvedValue(run("r1", [step("a")], { status: "running" }));
    const { hook } = harness([{ id: "a" }]);

    await act(async () => { await hook.result.current.attachLatestRun("p1", new Set()); });

    expect(live.runIds).toEqual(["r1"]);
    expect(hook.result.current.serverRunActive).toBe(true);
  });

  it("offers Finish run for a run waiting for the canvas, and finishes it in the browser", async () => {
    const waiting = run("r1", [
      step("osm", { role: "browser", status: "browser" }),
      step("count", { status: "waiting", level: 1 }),
    ], { status: "needs_canvas" });
    api.listForProject.mockResolvedValue([waiting]);
    api.get.mockResolvedValue(waiting);
    const { hook, deps } = harness([{ id: "osm" }, { id: "count" }], [{ source: "osm", target: "count" }]);

    await act(async () => { await hook.result.current.attachLatestRun("p1", new Set()); });

    expect(deps.playNodes).not.toHaveBeenCalled();
    const [, variant, options] = deps.showToast.mock.calls[0];
    expect(variant).toBe("info");
    expect(options.action.label).toBe("Finish run");

    await act(async () => { options.action.onClick(); });
    await flush();
    expect(new Set(deps.playNodes.mock.calls[0][0])).toEqual(new Set(["osm", "count"]));
    deps.playNodes.mock.calls[0][1].onNodeDone("count", { failed: false });
    expect(api.reportStep).toHaveBeenCalledWith("r1", "count", { status: "ok" });
  });

  it("picks the steps to show by the same rule as the hook", () => {
    const steps = [
      step("a", { status: "ok", outputPath: "x", codeCurrent: true }),
      step("b", { status: "ok", outputPath: "y", codeCurrent: true, role: "browser" }),
      step("c", { status: "ok", outputPath: null, codeCurrent: true }),
    ];
    expect(stepsToRestore(steps, new Set()).map((s) => s.nodeId)).toEqual(["a"]);
  });
});
