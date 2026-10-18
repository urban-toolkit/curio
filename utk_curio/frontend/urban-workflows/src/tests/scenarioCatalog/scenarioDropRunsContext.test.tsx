/**
 * A scenario dropped from the Scenario Catalog whose fixed context has no
 * saved output in its own project (#662): the drop runs that context first,
 * on the server and in the scenario's project, then asks what it copies again
 * and copies it.
 *
 * - the run is of the source project, on the nodes the plan lists to run;
 * - a run that fails, or the two-runs limit, says why and adds nothing;
 * - a run already going in the source is followed;
 * - a run that ends with the output still unsaved adds nothing.
 */
import { act, renderHook } from "@testing-library/react";

const mockShowToast = jest.fn();
const mockFlow = {
  scenarios: [],
  nodes: [],
  setScenarios: jest.fn(),
  setOutputs: jest.fn(),
  hydrateRestoredOutputs: jest.fn(),
  markDirty: jest.fn(),
  ensureProjectId: jest.fn(),
  workflowNameRef: { current: "Elsewhere" },
  workflowGoal: "",
};
const mockReactFlow = { getNodes: () => [], getEdges: () => [] };
const mockLoadTrill = jest.fn(() => ({ nodes: [], edges: [] }));

jest.mock("reactflow", () => ({ useReactFlow: () => mockReactFlow }));
jest.mock("../../providers/FlowProvider", () => ({ useFlowContext: () => mockFlow }));
jest.mock("../../providers/ToastProvider", () => ({ useToastContext: () => ({ showToast: mockShowToast }) }));
jest.mock("../../hook/useCode", () => ({ useCode: () => ({ loadTrill: mockLoadTrill }) }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({ refreshPackageRegistry: jest.fn() }));
jest.mock("../../registry/projectPackagesStore", () => ({ setCurrentProjectPackages: jest.fn() }));
jest.mock("../../services/datasetCatalog", () => ({ buildDatasetLoaderNodeOptions: jest.fn() }));
jest.mock("../../TrillGenerator", () => ({
  TrillGenerator: { generateTrill: () => ({ dataflow: { nodes: [], edges: [] } }) },
}));
jest.mock("../../utils/scenarios/scenarioParts", () => ({ liveScenarios: (saved: unknown) => saved }));
jest.mock("../../utils/scenarios/scenarioDrop", () => ({
  planScenarioDrop: () => ({
    outputs: [{ source: "buildings", node: "loader-1" }],
    loaders: [],
    scenario: { id: "dropped", name: "Existing", color: "#2a9d8f", nodes: [] },
  }),
  dropGraph: () => ({ nodes: [{ id: "loader-1" }], edges: [] }),
  loaderNodes: () => [],
}));
jest.mock("../../services/scenarioCatalog", () => ({
  scenarioCatalogApi: { getCopyPlan: jest.fn(), copyInto: jest.fn() },
}));
jest.mock("../../services/runs/runsApi", () => {
  const actual = jest.requireActual("../../services/runs/runsApi");
  return { ...actual, runsApi: { start: jest.fn(), follow: jest.fn(), get: jest.fn() } };
});

import { useScenarioDrop } from "../../components/scenarios/useScenarioDrop";
import { scenarioCatalogApi } from "../../services/scenarioCatalog";
import { runsApi } from "../../services/runs/runsApi";
import type { RunEvent } from "../../services/runs/runsApi";

const catalog = scenarioCatalogApi as unknown as { getCopyPlan: jest.Mock; copyInto: jest.Mock };
const runs = runsApi as unknown as { start: jest.Mock; follow: jest.Mock; get: jest.Mock };

const PAYLOAD = { projectId: "src", scenarioId: "existing" } as any;

/** What the server says a drop of "Existing" from chicago-loop-shadow-towers copies; *toRun* lists the context to run first. */
function plan(toRun: { nodeId: string; label: string }[]): any {
  return {
    scenario: { id: "existing", name: "Existing", color: "#2a9d8f", description: "" },
    project: { id: "src", name: "Chicago Loop shadow with towers removed or edited" },
    levers: ["shadow"],
    context: [{ nodeId: "buildings", label: "Buildings", source: { nodeId: "buildings", copiedFrom: [] } }],
    outcomes: [{ nodeId: "shadow", label: "Accumulated Shadow", sources: [] }],
    dataflow: { nodes: [], edges: [] },
    packages: [],
    problems: [],
    toRun,
  };
}

const TO_RUN = plan([{ nodeId: "buildings", label: "Buildings" }]);
const READY = plan([]);
const COPIED = { packages: [], added: [], datasets: {}, outputs: [] };

function run(id: string): any {
  return { id, projectId: "src", status: "queued", targetNodeIds: ["buildings"] };
}

/** Follow streams these events for the run, then ends. */
function streams(events: RunEvent[]) {
  runs.follow.mockImplementation(async (_runId: string, onEvent: (e: RunEvent) => void) => {
    for (const event of events) onEvent(event);
  });
}

const FINISHED_OK: RunEvent[] = [
  { kind: "step_finished", nodeId: "buildings", status: "ok" },
  { kind: "run_finished", status: "succeeded", ok: 1, failed: 0, skipped: 0, waiting: 0 },
];

function refused(status: number, message: string, body: Record<string, unknown> = {}) {
  return Object.assign(new Error(message), { status, body: { error: message, ...body } });
}

async function drop() {
  const { result } = renderHook(() => useScenarioDrop());
  let dropped: unknown;
  await act(async () => {
    dropped = await result.current(PAYLOAD, { x: 10, y: 20 });
  });
  return dropped;
}

const errors = () => mockShowToast.mock.calls.filter(([, variant]) => variant === "error").map(([message]) => message);

beforeEach(() => {
  jest.clearAllMocks();
  mockFlow.ensureProjectId.mockResolvedValue("target");
  catalog.copyInto.mockResolvedValue(COPIED);
});

it("runs the context on the server in the scenario's project, plans again, then copies", async () => {
  catalog.getCopyPlan.mockResolvedValueOnce(TO_RUN).mockResolvedValueOnce(READY);
  runs.start.mockResolvedValue(run("r1"));
  streams(FINISHED_OK);

  const dropped = await drop();

  expect(runs.start).toHaveBeenCalledTimes(1);
  expect(runs.start).toHaveBeenCalledWith("src", { targets: ["buildings"] });
  expect(mockShowToast).toHaveBeenCalledWith(
    "Running Buildings in Chicago Loop shadow with towers removed or edited for Existing", "info");
  expect(runs.follow.mock.calls.map(([runId]) => runId)).toEqual(["r1"]);
  expect(catalog.getCopyPlan).toHaveBeenCalledTimes(2);
  expect(catalog.getCopyPlan).toHaveBeenLastCalledWith("src", "existing", "target");
  expect(catalog.copyInto).toHaveBeenCalledTimes(1);
  // In that order: the run, its end, the second plan, the copy.
  const [started] = runs.start.mock.invocationCallOrder;
  const [followed] = runs.follow.mock.invocationCallOrder;
  const [, replanned] = catalog.getCopyPlan.mock.invocationCallOrder;
  const [copied] = catalog.copyInto.mock.invocationCallOrder;
  expect(started < followed && followed < replanned && replanned < copied).toBe(true);
  expect(dropped).toEqual({ nodes: ["loader-1"], scenario: "dropped" });
  expect(errors()).toEqual([]);
});

it("names every node it runs", async () => {
  catalog.getCopyPlan
    .mockResolvedValueOnce(plan([{ nodeId: "buildings", label: "Buildings" }, { nodeId: "trees", label: "Trees" }]))
    .mockResolvedValueOnce(READY);
  runs.start.mockResolvedValue(run("r1"));
  streams(FINISHED_OK);

  await drop();

  expect(runs.start).toHaveBeenCalledWith("src", { targets: ["buildings", "trees"] });
  expect(mockShowToast).toHaveBeenCalledWith(
    "Running Buildings and Trees in Chicago Loop shadow with towers removed or edited for Existing", "info");
});

it("a run that fails says why and copies nothing", async () => {
  catalog.getCopyPlan.mockResolvedValue(TO_RUN);
  runs.start.mockResolvedValue(run("r1"));
  streams([
    { kind: "step_finished", nodeId: "buildings", status: "error", stderrTail: "FileNotFoundError: buildings.geojson" },
    { kind: "run_finished", status: "failed", ok: 0, failed: 1, skipped: 0, waiting: 0 },
  ]);

  const dropped = await drop();

  expect(dropped).toBeNull();
  expect(catalog.copyInto).not.toHaveBeenCalled();
  const [message] = errors();
  expect(message).toContain("Buildings");
  expect(message).toContain("Chicago Loop shadow with towers removed or edited");
  expect(message).toContain("FileNotFoundError: buildings.geojson");
});

it("the two-runs limit says so and copies nothing", async () => {
  catalog.getCopyPlan.mockResolvedValue(TO_RUN);
  runs.start.mockRejectedValue(refused(429, "You already have two dataflows running. Wait for one to finish."));

  const dropped = await drop();

  expect(dropped).toBeNull();
  expect(runs.follow).not.toHaveBeenCalled();
  expect(catalog.copyInto).not.toHaveBeenCalled();
  expect(errors()).toEqual([expect.stringContaining("You already have two dataflows running.")]);
});

it("follows a run already going in the scenario's project, then copies", async () => {
  catalog.getCopyPlan.mockResolvedValueOnce(TO_RUN).mockResolvedValueOnce(READY);
  runs.start.mockRejectedValue(refused(409, "This dataflow is already running.", { runId: "r9" }));
  streams(FINISHED_OK);

  const dropped = await drop();

  expect(runs.start).toHaveBeenCalledTimes(1);
  expect(runs.follow.mock.calls.map(([runId]) => runId)).toEqual(["r9"]);
  expect(catalog.copyInto).toHaveBeenCalledTimes(1);
  expect(dropped).toEqual({ nodes: ["loader-1"], scenario: "dropped" });
});

it("a run that ends with the context still unsaved adds nothing", async () => {
  catalog.getCopyPlan.mockResolvedValue(TO_RUN);
  runs.start.mockResolvedValue(run("r1"));
  streams(FINISHED_OK);

  const dropped = await drop();

  expect(dropped).toBeNull();
  expect(runs.start).toHaveBeenCalledTimes(1);
  expect(catalog.copyInto).not.toHaveBeenCalled();
  expect(errors()).toEqual([expect.stringContaining("Buildings")]);
});

it("a plan with nothing to run copies at once, as before", async () => {
  catalog.getCopyPlan.mockResolvedValue(READY);

  const dropped = await drop();

  expect(runs.start).not.toHaveBeenCalled();
  expect(catalog.getCopyPlan).toHaveBeenCalledTimes(1);
  expect(catalog.copyInto).toHaveBeenCalledTimes(1);
  expect(dropped).toEqual({ nodes: ["loader-1"], scenario: "dropped" });
});
