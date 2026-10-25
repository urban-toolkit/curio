/**
 * While a dataflow is open on the canvas, every reader of an artifact reads it
 * on that dataflow's output routes (`projects/routes.py`): `fetchData` (charts,
 * maps), `fetchPreviewData` (a Data Pool tile) and `fetchRaster` (an Autark
 * map over a raster). There an output the dataflow saved is read from its
 * owner's Data Catalog in place, so a reopened dataflow needs no copy of it.
 *
 * The dashboard page keeps its own order: what the page carries, then what a
 * viewer's run made, and only then the open dataflow's route.
 */
import { fetchData, fetchPreviewData, fetchRaster } from "../../services/api";
import { setOpenDataflow } from "../../services/dataflowReads";
import { forgetDashboardRunFiles, rememberDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

const originalFetch = global.fetch;
let asked: { url: string; headers: Record<string, string> }[] = [];

function answer(body: unknown, headers: Record<string, string> = { "Content-Type": "application/json" }) {
    return {
        ok: true,
        status: 200,
        headers: { get: (name: string) => headers[name] ?? null, forEach: () => {} },
        json: async () => body,
        arrayBuffer: async () => new ArrayBuffer(4),
    };
}

function serve(payload: unknown) {
    const el = document.createElement("script");
    el.id = "curio-dashboard-payload";
    el.type = "application/json";
    el.textContent = JSON.stringify(payload);
    document.body.appendChild(el);
    resetEmbeddedDashboardForTests();
}

beforeEach(() => {
    document.body.innerHTML = "";
    resetEmbeddedDashboardForTests();
    forgetDashboardRunFiles();
    setOpenDataflow(null);
    asked = [];
    global.fetch = jest.fn(async (url: string, init?: { headers?: Record<string, string> }) => {
        asked.push({ url: String(url), headers: { ...(init?.headers ?? {}) } });
        if (String(url).includes("/raster")) {
            return answer(null, { "X-Curio-Raster": JSON.stringify({ width: 1, height: 1 }) });
        }
        return answer({ dataType: "str", data: "Month" });
    }) as unknown as typeof fetch;
});

afterEach(() => {
    global.fetch = originalFetch;
    forgetDashboardRunFiles();
    setOpenDataflow(null);
    document.body.innerHTML = "";
    resetEmbeddedDashboardForTests();
});

describe("while a dataflow is open", () => {
    beforeEach(() => setOpenDataflow("df-1"));

    test("fetchData reads on the dataflow's route, Arrow first, with no run token", async () => {
        await fetchData("art-1");
        // Arrow, then JSON, both on the dataflow's route.
        expect(asked).toHaveLength(2);
        for (const { url, headers } of asked) {
            expect(url).toContain("/api/projects/df-1/outputs/get?fileName=art-1");
            expect(headers["X-Curio-Run-Token"]).toBeUndefined();
        }
    });

    test("fetchPreviewData reads its preview on the dataflow's route", async () => {
        await fetchPreviewData("art-1");
        expect(asked).toHaveLength(1);
        expect(asked[0].url).toContain("/api/projects/df-1/outputs/get-preview?fileName=art-1");
    });

    test("fetchRaster reads the raster on the dataflow's route, with its bounds and part", async () => {
        await fetchRaster("art-1", { part: 2, maxCells: 10, maxSide: 5 });
        expect(asked).toHaveLength(1);
        expect(asked[0].url).toContain("/api/projects/df-1/outputs/raster?");
        expect(asked[0].url).toContain("fileName=art-1");
        expect(asked[0].url).toContain("maxCells=10");
        expect(asked[0].url).toContain("maxSide=5");
        expect(asked[0].url).toContain("part=2");
    });

    test("the dataflow's id and the name are sent encoded", async () => {
        setOpenDataflow("a/b");
        await fetchPreviewData("x&y");
        expect(asked[0].url).toContain("/api/projects/a%2Fb/outputs/get-preview?fileName=x%26y");
    });
});

describe("the order of the readers", () => {
    test("what the page carries answers first, with no request", async () => {
        setOpenDataflow("df-1");
        serve({ meta: {}, spec: {}, outputs: { "art-1": { dataType: "str", data: "carried" } } });

        const data = await fetchData("art-1");
        const preview = await fetchPreviewData("art-1");

        expect(data.data).toBe("carried");
        expect(preview.data).toBe("carried");
        expect(asked).toHaveLength(0);
    });

    test("what a viewer's run made is read on the dashboard's route, before the dataflow's", async () => {
        setOpenDataflow("df-1");
        rememberDashboardRunFiles("dash-1", "t1", ["art-1"]);

        await fetchPreviewData("art-1");
        await fetchRaster("art-1", { maxCells: 10, maxSide: 5 });
        await fetchPreviewData("art-2");

        expect(asked).toHaveLength(3);
        expect(asked[0].url).toContain("/api/projects/dash-1/dashboard/outputs/get-preview?fileName=art-1");
        expect(asked[1].url).toContain("/api/projects/dash-1/dashboard/outputs/raster?");
        expect(asked[2].url).toContain("/api/projects/df-1/outputs/get-preview?fileName=art-2");
        expect(asked[2].headers["X-Curio-Run-Token"]).toBeUndefined();
    });

    test("with no dataflow open, every read goes where it always did", async () => {
        await fetchData("art-1");
        await fetchPreviewData("art-1");
        await fetchRaster("art-1", { maxCells: 10, maxSide: 5 });

        expect(asked.length).toBeGreaterThan(0);
        for (const { url } of asked) {
            expect(url).not.toContain("/api/projects/");
        }
        expect(asked[0].url).toContain("/get?fileName=art-1");
        expect(asked[asked.length - 2].url).toContain("/get-preview?fileName=art-1");
        expect(asked[asked.length - 1].url).toContain("/raster?");
    });

    test("closing the dataflow sends reads where they always went", async () => {
        setOpenDataflow("df-1");
        setOpenDataflow(null);

        await fetchPreviewData("art-1");

        expect(asked[0].url).not.toContain("/api/projects/");
    });
});
