/**
 * What a dashboard viewer's run made (#1117) is read on the dashboard's own
 * output routes (`runs/viewer_routes.py`), with the run's token, by every
 * reader of an artifact: `fetchData` (charts, maps), `fetchPreviewData` (a
 * Data Pool tile) and `fetchRaster` (an Autark map over a raster). The plain
 * `/get` reads the caller's own session, and a viewer has none. Any other
 * artifact is read where it always was.
 */
import { fetchData, fetchPreviewData, fetchRaster } from "../../services/api";
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

beforeEach(() => {
    document.body.innerHTML = "";
    resetEmbeddedDashboardForTests();
    forgetDashboardRunFiles();
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
});

describe("an artifact a viewer's run made", () => {
    beforeEach(() => rememberDashboardRunFiles("dash-1", "t1", ["art-1"]));

    test("fetchData reads it on the dashboard's route, Arrow first, with the run's token", async () => {
        await fetchData("art-1");
        expect(asked.length).toBeGreaterThan(0);
        for (const { url, headers } of asked) {
            expect(url).toContain("/api/projects/dash-1/dashboard/outputs/get?fileName=art-1");
            expect(headers["X-Curio-Run-Token"]).toBe("t1");
        }
    });

    test("fetchPreviewData reads its preview on the dashboard's route", async () => {
        await fetchPreviewData("art-1");
        expect(asked).toHaveLength(1);
        expect(asked[0].url).toContain("/api/projects/dash-1/dashboard/outputs/get-preview?fileName=art-1");
        expect(asked[0].headers["X-Curio-Run-Token"]).toBe("t1");
    });

    test("fetchRaster reads the raster on the dashboard's route, with its bounds", async () => {
        await fetchRaster("art-1", { maxCells: 10, maxSide: 5 });
        expect(asked).toHaveLength(1);
        expect(asked[0].url).toContain("/api/projects/dash-1/dashboard/outputs/raster?");
        expect(asked[0].url).toContain("fileName=art-1");
        expect(asked[0].url).toContain("maxCells=10");
        expect(asked[0].headers["X-Curio-Run-Token"]).toBe("t1");
    });
});

describe("any other artifact", () => {
    test("is read where it always was, with no run token", async () => {
        rememberDashboardRunFiles("dash-1", "t1", ["art-1"]);
        await fetchData("saved-grid");
        await fetchPreviewData("saved-grid");
        expect(asked.length).toBeGreaterThan(0);
        for (const { url, headers } of asked) {
            expect(url).not.toContain("/dashboard/outputs/");
            expect(headers["X-Curio-Run-Token"]).toBeUndefined();
        }
    });

    test("forgetting the runs' files sends every read where it always was", async () => {
        rememberDashboardRunFiles("dash-1", "t1", ["art-1"]);
        forgetDashboardRunFiles();
        await fetchPreviewData("art-1");
        expect(asked[0].url).not.toContain("/dashboard/outputs/");
    });
});
