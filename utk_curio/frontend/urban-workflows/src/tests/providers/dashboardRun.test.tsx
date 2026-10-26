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
 *   node it cannot run leaves the nodes below saying so;
 * - several such steps, as two scenarios of two GPU steps leave four, are
 *   played together, each one's result is sent, and the run starts again once,
 *   after the last; one the page cannot run leaves the nodes below naming it.
 */
import { act, renderHook, waitFor } from "@testing-library/react";

import { dashboardRunRead, forgetDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { askedOfPage, keepPageResult } from "../../services/runs/dashboardRunSteps";
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
const day = { name: "day", type: "date", label: "Day", default: "2027-12-21" };
const dayTile = () => ({ id: "day", data: { nodeId: "day", dashboardPinned: true, widgets: [{ ...day }] } });

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

function setUp(
    { saved = [SAVED_GRID], playNodes = jest.fn(() => true), extra = [] }: { saved?: any[]; playNodes?: jest.Mock; extra?: any[] } = {},
) {
    const nodes = [...makeNodes(), ...extra];
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

    test("hold a pinned date as its text, the saved one until a viewer picks another", () => {
        const nodes = [...makeNodes(), dayTile()];
        expect(dashboardValues(nodes)).toEqual({ param: { period: "Date" }, day: { day: "2027-12-21" } });
        nodes[4].data.widgets = [{ ...day, value: "2027-06-21" }];
        expect(dashboardValues(nodes)).toEqual({ param: { period: "Date" }, day: { day: "2027-06-21" } });
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

    test("a picked date reruns the dashboard with that date as its text", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { nodes, hook } = setUp({ extra: [dayTile()] });
        await act(async () => { hook.result.current.opened("dash-1"); });
        expect(mockStart).not.toHaveBeenCalled();
        nodes[4].data.widgets = [{ ...day, value: "2027-06-21" }];

        await act(async () => { await hook.result.current.start(); });
        expect(mockStart).toHaveBeenCalledWith("dash-1", { param: { period: "Date" }, day: { day: "2027-06-21" } });
        expect(followed()).toMatchObject({ projectId: "dash-1", runId: "r1", token: "t1" });
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
        // A tile left with nothing says so, where "Computing..." would wait for nothing.
        expect(hook.result.current.stopped).toBe("Too many runs from here at once");
    });

    test("a run the page loses track of leaves the tiles saying so, not computing", async () => {
        let lose: (err: Error) => void = () => {};
        mockFollow.mockImplementation(() => new Promise((_resolve, reject) => { lose = reject; }));
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { showToast, hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });

        await act(async () => { lose(new Error("stream closed")); });

        const lost = "Lost track of this dashboard's run. Change a control to run it again.";
        expect(showToast).toHaveBeenCalledWith(lost, "warning");
        expect(hook.result.current.stopped).toBe(lost);
        expect(hook.result.current.active).toBe(false);
    });

    test("a step that fails on the server leaves the tiles naming it, with no node to open (owner, 10-25)", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });
        const run = followed();

        run.emit({
            kind: "step_finished", nodeId: "grid", status: "error",
            output: { path: "", dataType: "str" }, stderrTail: "KeyError: 'count'",
        });
        expect(hook.result.current.stopped).toBeNull();
        run.emit({ kind: "run_finished", status: "failed", ok: 0, failed: 1, skipped: 1, waiting: 0 });

        expect(hook.result.current.stopped).toBe('"grid" failed.');
        expect(hook.result.current.active).toBe(false);
    });

    test("a run the server stopped leaves the tiles saying so, not computing", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });

        followed().emit({ kind: "run_finished", status: "interrupted", ok: 0, failed: 0, skipped: 0, waiting: 0 });

        expect(hook.result.current.stopped).toBe("This dashboard's run was interrupted. Change a control to run it again.");
        expect(hook.result.current.active).toBe(false);
    });

    test("a run that succeeds sets no reason", async () => {
        mockStart.mockResolvedValue({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", "chart"] });
        const { hook } = setUp();
        await act(async () => { hook.result.current.opened("dash-1"); });
        await act(async () => { await hook.result.current.start(); });

        followed().emit({ kind: "run_finished", status: "succeeded", ok: 1, failed: 0, skipped: 0, waiting: 0 });

        expect(hook.result.current.stopped).toBeNull();
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
    async function aRunLeavingTheGpuStep(runsGpu: (outputs: any[], hooks: any) => void, extra: any[] = []) {
        const box: { outputs: any[] } = { outputs: [] };
        const playNodes = jest.fn((_nodeIds: string[], hooks: any) => {
            runsGpu(box.outputs, hooks);
            return true;
        });
        const setup = setUp({ playNodes, extra });
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
        // What a tile left with nothing says, in place of a node to run or open.
        expect(hook.result.current.stopped).toBe('"gpu" could not run in this browser.');
    });

    test("the step that could not run is named as its header names it", async () => {
        const gpu = {
            id: "gpu",
            data: { nodeId: "gpu", nodeType: "curio.builtin/autk-grammar@1", packageTemplateLabel: "Cast sun rays on the GPU" },
        };
        const { hook, run, outcomes } = await aRunLeavingTheGpuStep((_outputs, hooks) => {
            hooks.onNodeDone("gpu", { failed: true, message: "WebGPU is not available in this browser." });
            hooks.onFinish();
        }, [gpu]);

        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(hook.result.current.stopped).not.toBeNull());

        expect(hook.result.current.stopped).toBe('"Cast sun rays on the GPU" could not run in this browser.');
        expect(outcomes.showSkipped).toHaveBeenCalledWith(
            "after", 'No data yet: "Cast sun rays on the GPU" could not run in this browser.',
        );
    });

    test("the next start clears why the last run stopped", async () => {
        const { hook, run } = await aRunLeavingTheGpuStep((_outputs, hooks) => {
            hooks.onNodeDone("gpu", { failed: true, message: "WebGPU is not available in this browser." });
            hooks.onFinish();
        });
        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(hook.result.current.stopped).not.toBeNull());

        mockStart.mockResolvedValueOnce({ runId: "r2", token: "t2", joined: false, nodeIds: ["grid"] });
        await act(async () => { await hook.result.current.start(); });

        expect(hook.result.current.stopped).toBeNull();
        expect(hook.result.current.active).toBe(true);
    });

    test("a run that cannot go on from the page's step leaves the tiles saying why, not computing", async () => {
        const { hook, run, showToast } = await aRunLeavingTheGpuStep((outputs, hooks) => {
            outputs.push({ nodeId: "gpu", output: { path: "page-1", dataType: "dict" } });
            hooks.onNodeDone("gpu", { failed: false });
            hooks.onFinish();
        });
        mockStart.mockRejectedValueOnce(new Error("This run's token has expired."));

        await act(async () => { run.emit(finished("needs_canvas")); });
        await waitFor(() => expect(hook.result.current.active).toBe(false));

        expect(showToast).toHaveBeenCalledWith("This run's token has expired.", "error");
        expect(hook.result.current.stopped).toBe("This run's token has expired.");
    });
});

describe("four steps only a browser runs, two to a scenario", () => {
    // As two scenarios of two GPU steps leave them, none below another; each
    // scenario's step below them waits for its own two.
    const GPU_STEPS = ["gpu-a1", "gpu-a2", "gpu-b1", "gpu-b2"];
    const BELOW = ["after-a", "after-b"];
    const LAYERS = { dataType: "outputs", data: [{ type: "FeatureCollection", features: [] }] };

    /**
     * A change whose run leaves the four GPU steps to the page, with the steps
     * below them waiting. The page plays them, and the test finishes each one
     * when it likes: *sends* as an Autark node a run asked the page for does,
     * handing its layers to the run (toPoolOutput), and *cannotRun* as one in
     * a browser without WebGPU does.
     */
    async function aRunLeavingFourGpuSteps() {
        let hooks: any = null;
        const playNodes = jest.fn((_nodeIds: string[], given: any) => {
            hooks = given;
            return true;
        });
        mockKeepStep.mockImplementation(async (_projectId: string, _runId: string, _token: string, nodeId: string) => ({
            output: { path: `page-${nodeId}`, dataType: "dict" }, artifactIds: [`page-${nodeId}`],
        }));
        const setup = setUp({ playNodes });
        mockStart.mockResolvedValueOnce({ runId: "r1", token: "t1", joined: false, nodeIds: ["grid", ...GPU_STEPS, ...BELOW] });
        await act(async () => { setup.hook.result.current.opened("dash-1"); });
        setup.nodes[0].data.widgets = [{ ...period, value: "Month" }] as any;
        await act(async () => { await setup.hook.result.current.start(); });
        const run = followed();
        run.emit({ kind: "step_finished", nodeId: "grid", status: "ok", output: { path: "art-grid", dataType: "str" } });
        for (const nodeId of GPU_STEPS) run.emit({ kind: "step_finished", nodeId, status: "browser" });
        for (const nodeId of BELOW) {
            run.emit({ kind: "step_finished", nodeId, status: "waiting", skipReason: "Waits for the canvas" });
        }
        await act(async () => {
            run.emit({ kind: "run_finished", status: "needs_canvas", ok: 1, failed: 0, skipped: 0, waiting: BELOW.length });
        });
        // The page plays them a tick after the run hands them over.
        await waitFor(() => expect(playNodes).toHaveBeenCalledTimes(1));

        const sends = async (nodeId: string) => {
            const kept = await keepPageResult(nodeId, LAYERS);
            setup.outputsRef.current.push({ nodeId, output: kept });
            hooks.onNodeDone(nodeId, { failed: false });
        };
        const cannotRun = (nodeId: string) => {
            hooks.onNodeDone(nodeId, { failed: true, message: "WebGPU is not available in this browser." });
        };
        const finishPlaying = () => hooks.onFinish();
        return { ...setup, run, sends, cannotRun, finishPlaying };
    }

    test("the page plays all four, sends each one's result, and starts the run again once, after the last", async () => {
        const { hook, playNodes, outcomes, sends, finishPlaying } = await aRunLeavingFourGpuSteps();
        mockStart.mockResolvedValueOnce({ runId: "r2", token: "t1", joined: false, nodeIds: BELOW });

        expect(playNodes).toHaveBeenCalledWith(GPU_STEPS, expect.anything());
        expect(GPU_STEPS.every((nodeId) => askedOfPage(nodeId))).toBe(true);
        // They finish in any order: the run waits for the last, and the tiles below with it.
        for (const nodeId of ["gpu-b2", "gpu-a1", "gpu-b1"]) {
            await act(async () => { await sends(nodeId); });
            expect(mockStart).toHaveBeenCalledTimes(1);
            expect(hook.result.current.active).toBe(true);
            expect(hook.result.current.stopped).toBeNull();
        }
        await act(async () => {
            await sends("gpu-a2");
            finishPlaying();
        });
        await waitFor(() => expect(mockFollow).toHaveBeenCalledTimes(2));

        expect(mockKeepStep.mock.calls).toEqual(
            ["gpu-b2", "gpu-a1", "gpu-b1", "gpu-a2"].map((nodeId) => ["dash-1", "r1", "t1", nodeId, LAYERS]),
        );
        expect(mockStart).toHaveBeenCalledTimes(2);
        expect(mockStart).toHaveBeenLastCalledWith("dash-1", { param: { period: "Month" } }, {
            token: "t1",
            browserOutputs: {
                "gpu-a1": "page-gpu-a1", "gpu-a2": "page-gpu-a2", "gpu-b1": "page-gpu-b1", "gpu-b2": "page-gpu-b2",
            },
        });
        expect(GPU_STEPS.some((nodeId) => askedOfPage(nodeId))).toBe(false);
        // Nothing reached the steps below: they wait for the next run's steps.
        expect(outcomes.showSkipped).not.toHaveBeenCalled();
        expect(outcomes.showResult.mock.calls.filter((call) => BELOW.includes(call[0]))).toEqual([]);
        const next = followed();
        expect(next).toMatchObject({ projectId: "dash-1", runId: "r2", token: "t1" });
        expect(hook.result.current.active).toBe(true);

        for (const nodeId of BELOW) {
            next.emit({ kind: "step_finished", nodeId, status: "ok", output: { path: `art-${nodeId}`, dataType: "str" } });
        }
        next.emit({ kind: "run_finished", status: "succeeded", ok: BELOW.length, failed: 0, skipped: 0, waiting: 0 });
        for (const nodeId of BELOW) {
            expect(outcomes.showResult).toHaveBeenCalledWith(nodeId, expect.objectContaining({ kind: "result" }), { live: false });
        }
        expect(hook.result.current.active).toBe(false);
        expect(mockStart).toHaveBeenCalledTimes(2);
        expect(playNodes).toHaveBeenCalledTimes(1);
    });

    test.each<[string, string[]]>([
        ["one of the four", ["gpu-b1"]],
        ["all four, as in a browser without WebGPU", GPU_STEPS],
    ])("a GPU step that cannot run here (%s) leaves the nodes below naming it, and nothing runs again", async (_case, cannot) => {
        const { hook, outcomes, showToast, sends, cannotRun, finishPlaying } = await aRunLeavingFourGpuSteps();

        await act(async () => {
            for (const nodeId of GPU_STEPS) {
                if (cannot.includes(nodeId)) cannotRun(nodeId);
                else await sends(nodeId);
            }
            finishPlaying();
        });
        await waitFor(() => expect(hook.result.current.active).toBe(false));

        // The first step that reported it could not run, by name.
        const why = `"${cannot[0]}" could not run in this browser.`;
        expect(hook.result.current.stopped).toBe(why);
        for (const nodeId of BELOW) expect(outcomes.showSkipped).toHaveBeenCalledWith(nodeId, `No data yet: ${why}`);
        expect(mockStart).toHaveBeenCalledTimes(1);
        expect(mockFollow).toHaveBeenCalledTimes(1);
        expect(showToast).not.toHaveBeenCalled();
        expect(GPU_STEPS.some((nodeId) => askedOfPage(nodeId))).toBe(false);
    });
});
