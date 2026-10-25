/**
 * A dashboard viewer's runs (#1117), as the page drives them
 * (providers/flow/useDashboardRun.ts):
 *
 * - the values sent are every control the pinned tiles show, but a read-only kind;
 * - on open, a tile with no saved output runs the nodes before it, and a page
 *   whose tiles all have theirs asks nothing;
 * - each step reaches its node as a canvas run's does (useStepOutcomes),
 *   restored as a load restores an output, and its artifacts are read on the
 *   dashboard's own routes with the run's token;
 * - a node a later run does not reach, and every node when nothing needs to
 *   run, shows its saved output again;
 * - Save layout gets the widgets as the page opened with them, never a tried value;
 * - a step only a browser runs is the page's: it runs the node, sends what it
 *   made, and starts the run again on that with the same values and token; a
 *   node it cannot run leaves the nodes below saying so.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

import { dashboardRunRead, forgetDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { askedOfPage } from "../../services/runs/dashboardRunSteps";
import { useDashboardRun } from "../../providers/flow/useDashboardRun";
import { dashboardValues } from "../../utils/widgets/dashboardControls";

const mockStart = jest.fn();
const mockFollow = jest.fn();
const mockKeepStep = jest.fn();

jest.mock("../../services/runs/dashboardRunsApi", () => ({
    ...jest.requireActual("../../services/runs/dashboardRunsApi"),
    dashboardRunsApi: {
        start: (...args: unknown[]) => mockStart(...args),
        follow: (...args: unknown[]) => mockFollow(...args),
        keepStep: (...args: unknown[]) => mockKeepStep(...args),
    },
}));

const period = {
    name: "period", type: "choice", label: "Period", default: "Date",
    options: { choices: ["Date", "Month", "Year"], display: "radio" },
};
const note = { name: "note", type: "text", default: "" };

function makeNodes(): any[] {
    return [
        { id: "param", data: { nodeId: "param", dashboardPinned: true, widgets: [{ ...period }] } },
        { id: "notes", data: { nodeId: "notes", dashboardPinned: true, widgets: [{ ...note }] } },
        { id: "grid", data: { nodeId: "grid", code: "return [!! @period !!]", widgets: [] } },
        { id: "chart", data: { nodeId: "chart", dashboardPinned: true } },
    ];
}
const EDGES = [{ id: "grid-chart", source: "grid", target: "chart" }];
const SAVED_GRID = { nodeId: "grid", output: { path: "saved-grid", dataType: "str" } };

function setUp({ saved = [SAVED_GRID], playNodes = jest.fn(() => true) }: { saved?: any[]; playNodes?: jest.Mock } = {}) {
    const nodes = makeNodes();
    const outcomes = { showOnNode: jest.fn(), showResult: jest.fn(), showSkipped: jest.fn() };
    const showToast = jest.fn();
    const reactFlow: any = {
        getNodes: () => nodes,
        getEdges: () => EDGES,
        getNode: (id: string) => nodes.find((node) => node.id === id),
    };
    const outputsRef: { current: any[] } = { current: [...saved] };
    const hook = renderHook(() => useDashboardRun({
        enabled: true, reactFlow, outcomes, outputsRef, showToast, playNodes,
    }));
    return { nodes, outcomes, showToast, hook, outputsRef, playNodes };
}

/** The stream of the run the last start answered, held open until the test ends it. */
function followed() {
    const calls = mockFollow.mock.calls;
    const [projectId, runId, token, onEvent] = calls[calls.length - 1] as [string, string, string, (e: any) => void];
    return { projectId, runId, token, emit: (event: any) => act(() => { onEvent(event); }) };
}

beforeEach(() => {
    mockStart.mockReset();
    mockFollow.mockReset().mockImplementation(() => new Promise(() => {}));
    mockKeepStep.mockReset();
    forgetDashboardRunFiles();
});

describe("the values a viewer's run takes", () => {
    test("are every control the pinned tiles show, but a read-only kind and an unpinned node's", () => {
        const nodes = makeNodes();
        nodes[2].data.widgets = [{ ...period, name: "unpinned" }] as any;
        expect(dashboardValues(nodes)).toEqual({ param: { period: "Date" } });
        nodes[0].data.widgets[0] = { ...period, value: "Month" } as any;
        expect(dashboardValues(nodes)).toEqual({ param: { period: "Month" } });
    });
});

describe("on open", () => {
    test("a page whose tiles all have their saved output asks nothing", async () => {
        const { hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        expect(mockStart).not.toHaveBeenCalled();
    });

    test("a tile with no saved output runs the nodes before it, with the saved values", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { hook } = setUp({ saved: [] });
        await act(async () => { hook.result.current.opened("dash-1"); });
        expect(mockStart).toHaveBeenCalledWith("dash-1", { param: { period: "Date" } });
        expect(followed()).toMatchObject({ projectId: "dash-1", runId: "r1", token: "t1" });
        expect(hook.result.current.active).toBe(true);
    });
});

describe("a change", () => {
    test("reruns the dashboard, and each step reaches its node as a canvas run's does", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { nodes, outcomes, hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        nodes[0].data.widgets = [{ ...period, value: "Month" }] as any;

        await act(async () => { await hook.result.current.start(); });
        expect(mockStart).toHaveBeenCalledWith("dash-1", { param: { period: "Month" } });
        const run = followed();
        run.emit({ kind: "step_started", nodeId: "grid", startedAt: 1 });
        expect(outcomes.showOnNode).toHaveBeenCalledWith("grid", { code: "exec", content: "" });
        run.emit({
            kind: "step_finished", nodeId: "grid", status: "ok",
            output: { path: "art-1", dataType: "outputs" }, artifactIds: ["art-1", "art-1-part"],
        });

        // Restored as a load restores an output: passed on, the dataflow unchanged.
        expect(outcomes.showResult).toHaveBeenCalledWith(
            "grid",
            expect.objectContaining({ kind: "result", reply: expect.objectContaining({ output: { path: "art-1", dataType: "outputs" } }) }),
            { live: false },
        );
        // Every artifact the output holds is read on the dashboard's route, with the token.
        const read = dashboardRunRead("art-1-part", "get", new URLSearchParams({ fileName: "art-1-part" }));
        expect(read?.url).toContain("/api/projects/dash-1/dashboard/outputs/get?fileName=art-1-part");
        expect(read?.headers).toEqual({ "X-Curio-Run-Token": "t1" });
        expect(dashboardRunRead("someone-elses", "get", new URLSearchParams())).toBeUndefined();

        run.emit({ kind: "run_finished", status: "succeeded", ok: 1, failed: 0, skipped: 0, waiting: 0 });
        expect(hook.result.current.active).toBe(false);
    });

    test("back to the saved values, every node a run changed shows its saved output again", async () => {
        mockStart.mockResolvedValueOnce({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { outcomes, hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });
        const run = followed();
        run.emit({ kind: "step_finished", nodeId: "grid", status: "ok", output: { path: "art-1", dataType: "str" } });
        run.emit({ kind: "run_finished", status: "succeeded", ok: 1, failed: 0, skipped: 0, waiting: 0 });
        outcomes.showResult.mockClear();

        mockStart.mockResolvedValueOnce({ runId: null, token: null, joined: false, nodeIds: [] });
        await act(async () => { await hook.result.current.start(); });

        expect(outcomes.showResult).toHaveBeenCalledWith(
            "grid",
            { kind: "result", reply: { stdout: [], stderr: "", output: SAVED_GRID.output } },
            { live: false },
        );
        expect(mockFollow).toHaveBeenCalledTimes(1);
        expect(hook.result.current.active).toBe(false);
    });

    test("a run that could not start says why, and nothing waits on it", async () => {
        mockStart.mockRejectedValue(Object.assign(new Error("Too many runs from here at once"), { status: 429 }));
        const { showToast, hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });
        expect(showToast).toHaveBeenCalledWith("Too many runs from here at once", "warning");
        expect(hook.result.current.active).toBe(false);
    });
});

describe("Save layout", () => {
    test("gets each pinned node's widgets as the page opened with them, never a value tried since", async () => {
        const { nodes, hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        // A Widgets tab writes its value into the node's data in place.
        nodes[0].data.widgets[0].value = "Year" as any;
        const saved = hook.result.current.savedWidgets();
        expect(saved?.get("param")).toEqual([period]);
        expect(saved?.has("grid")).toBe(false);
    });
});

describe("a step only a browser runs", () => {
    const finished = (status: string) => ({ kind: "run_finished", status, ok: 1, failed: 0, skipped: 0, waiting: 2 });

    /**
     * A change whose run leaves "gpu" to the page, with "after" waiting below
     * it. *runsGpu* plays the node: what playNodes would make of it.
     */
    async function aRunLeavingTheGpuStep(runsGpu: (outputs: any[], hooks: any) => void) {
        const box: { outputs: any[] } = { outputs: [] };
        const playNodes = jest.fn((_nodeIds: string[], hooks: any) => {
            runsGpu(box.outputs, hooks);
            return true;
        });
        const setup = setUp({ playNodes });
        box.outputs = setup.outputsRef.current;
        mockStart.mockResolvedValueOnce({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "gpu", "after"] });
        await act(async () => { setup.hook.result.current.opened("dash-1"); });
        setup.nodes[0].data.widgets = [{ ...period, value: "Month" }] as any;
        await act(async () => { await setup.hook.result.current.start(); });
        const run = followed();
        run.emit({ kind: "step_finished", nodeId: "grid", status: "ok", output: { path: "art-grid", dataType: "str" } });
        run.emit({ kind: "step_finished", nodeId: "gpu", status: "browser" });
        run.emit({ kind: "step_finished", nodeId: "after", status: "waiting", skipReason: "Waits for the canvas" });
        return { ...setup, run };
    }

    test("the page runs it, and the run starts again on what it made, with the same values and token", async () => {
        let askedWhilePlaying = false;
        const { hook, playNodes, run, outcomes } = await aRunLeavingTheGpuStep((outputs, hooks) => {
            askedWhilePlaying = askedOfPage("gpu");
            // The node sent its layers to the run itself, as an Autark node does.
            outputs.push({ nodeId: "gpu", output: { path: "page-1", dataType: "dict" } });
            hooks.onNodeDone("gpu", { failed: false });
            hooks.onFinish();
        });
        mockStart.mockResolvedValueOnce({ runId: "r2", token: "t1", joined: false, nodeIds: ["after"] });

        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(2));

        expect(playNodes).toHaveBeenCalledWith(["gpu"], expect.anything());
        expect(askedWhilePlaying).toBe(true);
        expect(askedOfPage("gpu")).toBe(false);
        expect(mockStart).toHaveBeenLastCalledWith(
            "dash-1", { param: { period: "Month" } }, { token: "t1", browserOutputs: { gpu: "page-1" } },
        );
        // Waiting nodes keep what they show until the next run's steps land.
        expect(outcomes.showSkipped).not.toHaveBeenCalled();
        const next = followed();
        expect(next).toMatchObject({ projectId: "dash-1", runId: "r2", token: "t1" });
        expect(hook.result.current.active).toBe(true);

        next.emit({ kind: "step_finished", nodeId: "after", status: "ok", output: { path: "art-after", dataType: "str" } });
        next.emit(finished("succeeded"));
        expect(outcomes.showResult).toHaveBeenCalledWith("after", expect.objectContaining({ kind: "result" }), { live: false });
        expect(hook.result.current.active).toBe(false);
    });

    test("the page runs it once the results before it have reached its input, which they do a tick after they land", async () => {
        let reached = false;
        let reachedWhenPlayed: boolean | null = null;
        const playNodes = jest.fn((_nodeIds: string[], hooks: any) => {
            reachedWhenPlayed = reached;
            hooks.onFinish();
            return true;
        });
        const setup = setUp({ playNodes });
        // As useStepOutcomes hands a run's result down: a load's way, a tick later.
        setup.outcomes.showResult.mockImplementation(() => { setTimeout(() => { reached = true; }, 0); });
        mockStart.mockResolvedValueOnce({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "gpu", "after"] });
        await act(async () => { setup.hook.result.current.opened("dash-1"); });
        setup.nodes[0].data.widgets = [{ ...period, value: "Month" }] as any;
        await act(async () => { await setup.hook.result.current.start(); });
        const run = followed();
        // The whole stream at once, as a run that ended before the page read it.
        run.emit({ kind: "step_finished", nodeId: "grid", status: "ok", output: { path: "art-grid", dataType: "str" } });
        run.emit({ kind: "step_finished", nodeId: "gpu", status: "browser" });
        run.emit({ kind: "step_finished", nodeId: "after", status: "waiting", skipReason: "Waits for the canvas" });
        await act(async () => { run.emit(finished("needs_canvas")); });

        await waitFor(() => expect(playNodes).toHaveBeenCalledTimes(1));
        expect(reachedWhenPlayed).toBe(true);
    });

    test("rows the node holds on the page are sent to the run, and read back with the run's token", async () => {
        const rows = { dataType: "geodataframe", data: { type: "FeatureCollection", features: [] } };
        mockKeepStep.mockResolvedValue({ output: { path: "page-7", dataType: "dict" }, artifactIds: ["page-7"] });
        const { run } = await aRunLeavingTheGpuStep((outputs, hooks) => {
            // A Spatial Join hands its rows on as they are.
            outputs.push({ nodeId: "gpu", output: rows });
            hooks.onNodeDone("gpu", { failed: false });
            hooks.onFinish();
        });
        mockStart.mockResolvedValueOnce({ runId: "r2", token: "t1", joined: false, nodeIds: ["after"] });

        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(mockStart).toHaveBeenCalledTimes(2));

        expect(mockKeepStep).toHaveBeenCalledWith("dash-1", "r1", "t1", "gpu", rows);
        expect(mockStart.mock.calls[1][2]).toEqual({ token: "t1", browserOutputs: { gpu: "page-7" } });
        const read = dashboardRunRead("page-7", "get", new URLSearchParams({ fileName: "page-7" }));
        expect(read?.headers).toEqual({ "X-Curio-Run-Token": "t1" });
    });

    test("a step the page cannot run leaves the nodes below saying so, and nothing runs again", async () => {
        const { hook, run, outcomes, showToast } = await aRunLeavingTheGpuStep((_outputs, hooks) => {
            hooks.onNodeDone("gpu", { failed: true, message: "WebGPU is not available in this browser." });
            hooks.onFinish();
        });

        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(hook.result.current.active).toBe(false));

        expect(outcomes.showSkipped).toHaveBeenCalledWith("after", expect.stringContaining("could not run in this browser"));
        expect(mockStart).toHaveBeenCalledTimes(1);
        expect(mockKeepStep).not.toHaveBeenCalled();
        expect(showToast).not.toHaveBeenCalled();
        expect(askedOfPage("gpu")).toBe(false);
    });
});
