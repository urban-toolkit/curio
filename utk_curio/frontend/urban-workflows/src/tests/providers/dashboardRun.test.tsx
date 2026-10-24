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
 * - Save layout gets the widgets as the page opened with them, never a tried value.
 */
import { act, renderHook } from "@testing-library/react";

import { dashboardRunRead, forgetDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { useDashboardRun } from "../../providers/flow/useDashboardRun";
import { dashboardValues } from "../../utils/widgets/dashboardControls";

const mockStart = jest.fn();
const mockFollow = jest.fn();

jest.mock("../../services/runs/dashboardRunsApi", () => ({
    ...jest.requireActual("../../services/runs/dashboardRunsApi"),
    dashboardRunsApi: {
        start: (...args: unknown[]) => mockStart(...args),
        follow: (...args: unknown[]) => mockFollow(...args),
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

function setUp({ saved = [SAVED_GRID] }: { saved?: any[] } = {}) {
    const nodes = makeNodes();
    const outcomes = { showOnNode: jest.fn(), showResult: jest.fn(), showSkipped: jest.fn() };
    const showToast = jest.fn();
    const reactFlow: any = { getNodes: () => nodes, getEdges: () => EDGES };
    const outputsRef = { current: [...saved] };
    const hook = renderHook(() => useDashboardRun({
        enabled: true, reactFlow, outcomes, outputsRef, showToast,
    }));
    return { nodes, outcomes, showToast, hook };
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

        // Restored as a load restores an output: passed on, nothing saved.
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
