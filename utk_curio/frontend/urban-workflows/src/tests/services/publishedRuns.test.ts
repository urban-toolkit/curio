/**
 * A visitor's published run: the values it sends, the calls `useServerRun`
 * makes through it, and the artifacts read with the run's key.
 */
import {
    clearPublishedRun,
    notePublishedArtifacts,
    publishedArtifactPath,
    setPublishedRun,
} from "../../services/published/publishedArtifacts";
import { publishLinkToken } from "../../services/published/publishedApi";

const mockApi = {
    describe: jest.fn(),
    startRun: jest.fn(),
    getRun: jest.fn(),
    cancel: jest.fn(),
    follow: jest.fn(),
};
jest.mock("../../services/published/publishedApi", () => ({
    ...jest.requireActual("../../services/published/publishedApi"),
    // Read when called: the factory runs before `mockApi` is assigned.
    get publishedApi() {
        return mockApi;
    },
}));

import { inputsFromNodes, publishedRunApi } from "../../services/published/publishedRunApi";

const node = (id: string, widgets: unknown[]) => ({ id, position: { x: 0, y: 0 }, data: { widgets } }) as any;

beforeEach(() => {
    jest.clearAllMocks();
    clearPublishedRun();
});

describe("the link in the address", () => {
    test("is the run parameter", () => {
        expect(publishLinkToken("?run=abc")).toBe("abc");
        expect(publishLinkToken("?other=1")).toBeNull();
        expect(publishLinkToken("?run=%20")).toBeNull();
    });
});

describe("inputsFromNodes", () => {
    const nodes = [
        node("p", [
            { name: "weight", type: "slider", default: 0.5, value: 0.9 },
            { name: "mode", type: "choice", default: "fast", options: { choices: ["fast", "safe"] } },
            { name: "secret", type: "text", default: "x" },
        ]),
        node("q", [{ name: "weight", type: "slider", default: 0.1 }]),
    ];

    test("sends the values the widgets show, for the inputs the link allows only", () => {
        const allowed = [{ nodeId: "p", name: "weight" }, { nodeId: "p", name: "mode" }];
        expect(inputsFromNodes(nodes, allowed)).toEqual({ p: { weight: 0.9, mode: "fast" } });
    });

    test("sends nothing when the link allows nothing", () => {
        expect(inputsFromNodes(nodes, [])).toEqual({});
    });
});

describe("the artifacts of a published run", () => {
    test("only the names the run produced are read with its key", () => {
        expect(publishedArtifactPath("get", "art-1")).toBeNull();
        setPublishedRun("run 1", "k/ey");
        notePublishedArtifacts({ output: { path: "art-1", dataType: "dataframe" } });
        expect(publishedArtifactPath("get", "art-1")).toBe(
            "/api/published/runs/run%201/get?key=k%2Fey&fileName=art-1",
        );
        expect(publishedArtifactPath("raster", "someone-elses")).toBeNull();
    });

    test("the parts a bundle lists may be read once the bundle was", () => {
        setPublishedRun("r", "k");
        notePublishedArtifacts({ dataType: "outputs", data: [{ path: "part-1" }, { dataset: "part-2" }] });
        expect(publishedArtifactPath("get-preview", "part-1")).not.toBeNull();
        expect(publishedArtifactPath("get", "part-2")).not.toBeNull();
    });

    test("another run starts with nothing, and clearing forgets the run", () => {
        setPublishedRun("r", "k");
        notePublishedArtifacts({ path: "a" });
        setPublishedRun("r2", "k2");
        expect(publishedArtifactPath("get", "a")).toBeNull();
        clearPublishedRun();
        notePublishedArtifacts({ path: "a" });
        expect(publishedArtifactPath("get", "a")).toBeNull();
    });
});

describe("publishedRunApi", () => {
    const nodes = [node("p", [{ name: "weight", type: "slider", default: 0.5, value: 0.7 }])];

    test("a start sends the allowed values, keeps the key, and reads the run", async () => {
        mockApi.describe.mockResolvedValue({ inputs: [{ nodeId: "p", name: "weight" }] });
        mockApi.startRun.mockResolvedValue({ runId: "r1", key: "secret", cached: false });
        mockApi.getRun.mockResolvedValue({ status: "running", steps: [{ nodeId: "p", role: "run", status: "pending" }] });
        const api = publishedRunApi("tok", () => nodes);

        const run = await api.start("ignored", {});
        expect(mockApi.startRun).toHaveBeenCalledWith("tok", { p: { weight: 0.7 } });
        expect(mockApi.getRun).toHaveBeenCalledWith("r1", "secret");
        expect(run.id).toBe("r1");
        expect(run.steps?.map((s) => [s.nodeId, s.role, s.status])).toEqual([["p", "run", "pending"]]);

        await api.cancel("r1");
        expect(mockApi.cancel).toHaveBeenCalledWith("r1", "secret");
    });

    test("following notes each step's artifacts before passing the event on", async () => {
        mockApi.describe.mockResolvedValue({ inputs: [] });
        mockApi.startRun.mockResolvedValue({ runId: "r1", key: "secret", cached: true });
        mockApi.getRun.mockResolvedValue({ status: "succeeded", steps: [] });
        mockApi.follow.mockImplementation(async (_id: string, _key: string, onEvent: (e: any) => void) => {
            onEvent({ kind: "step_finished", nodeId: "p", status: "ok", output: { path: "art-p" } });
        });
        const api = publishedRunApi("tok", () => []);
        await api.start("x", {});
        const seen: unknown[] = [];
        await api.follow("r1", (event) => {
            // By the time a node hears of its output, the output is readable.
            seen.push(publishedArtifactPath("get", "art-p"));
            seen.push(event.kind);
        });
        expect(mockApi.follow.mock.calls[0][1]).toBe("secret");
        expect(seen).toEqual(["/api/published/runs/r1/get?key=secret&fileName=art-p", "step_finished"]);
    });

    test("a visitor reports nothing and has no runs of their own", async () => {
        const api = publishedRunApi("tok", () => []);
        await expect(api.listForProject("p")).resolves.toEqual([]);
        await expect(api.reportStep("r", "n", { status: "ok" })).resolves.toMatchObject({ id: "r" });
    });
});
