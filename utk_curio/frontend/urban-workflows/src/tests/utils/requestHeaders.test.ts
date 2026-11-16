/**
 * Every request a page sends the backend names the dataflow the page shows,
 * in the `X-Curio-Dataflow` header (`utils/requestHeaders.ts`). With several
 * backend processes (`curio.py start --backend-processes N`), the router
 * sends each request to the process that owns that dataflow
 * (`cli/backend_group.py`), a request whose path names no dataflow too: a
 * run's `/api/runs/<run>`, `/processPythonCode`, `/storeOutput`,
 * `/nodeRuntime` and the outputs' reads.
 *
 * The dataflow is the one the page's route names: the canvas's
 * (`/dataflow/<id>`) or the dashboard's (`/dashboard/<id>`), under the app's
 * base path too, and the route's even while the canvas still holds the
 * dataflow before it. On `/dataflow/new` it is the id a new dataflow gets on
 * its first save, the one its reads are on (`services/dataflowReads.ts`). Any
 * other page, the projects, a catalog or the monitor, names none. A request
 * that names its dataflow itself, in its body or its query, names that one. A
 * hosted guest's page names the dataflow it shows, never its own copy's:
 * `providers/collabSocketNamesDataflow.test.tsx`.
 *
 * The helper is loaded in each test, so a checkout without it fails each test
 * on its own.
 */
import fs from "fs";
import path from "path";

import { apiFetch } from "../../utils/authApi";
import { postSseStream } from "../../utils/sseStream";
import { runNodeOnBackend } from "../../utils/nodeRunRequest";
import { fetchData, fetchPreviewData, fetchRaster, storeOutput } from "../../services/api";
import { setOpenDataflow } from "../../services/dataflowReads";
import { fetchOutputFile } from "../../services/outputFiles";
import { reportNodeRuntime, resetNodeRuntimeReports } from "../../services/nodeRuntimeReport";
import { datasetCatalogApi } from "../../services/datasetCatalog/datasetCatalogApi";
import { forgetDashboardRunFiles, rememberDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import useStarters from "../../providers/starters";

const HEADER = "X-Curio-Dataflow";
const A = "11111111-2222-4333-8444-555555555555";
const B = "66666666-7777-4888-9999-000000000000";
const NEW = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";

/** The helper, loaded when a test asks for it. */
const helper = (): any => require("../../utils/requestHeaders");

/** The file the frontend and the router share the header's name in. */
const route = (): { header: string; query: string } =>
  JSON.parse(fs.readFileSync(path.resolve(__dirname, "../../contracts/dataflowRoute.json"), "utf8"));

/** Put the page at *where*, as the router's navigation does. */
const at = (where: string) => window.history.replaceState(null, "", where);

function servedUnder(base: string) {
  const element = document.createElement("base");
  element.setAttribute("href", base);
  document.head.appendChild(element);
}

afterEach(() => {
  at("/");
  setOpenDataflow(null);
  document.querySelectorAll("base").forEach((element) => element.remove());
});

describe("the dataflow a page names", () => {
  test("the header is the file's, which the router reads, and so is the socket's query", () => {
    expect(helper().DATAFLOW_HEADER).toBe(route().header);
    expect(helper().DATAFLOW_QUERY).toBe(route().query);
    expect(route().header).toBe(HEADER);
  });

  test("the canvas names the dataflow its route opens", () => {
    at(`/dataflow/${A}`);

    expect(helper().pageDataflow()).toBe(A);
    expect(helper().requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", [HEADER]: A });
  });

  test("the dashboard names its dataflow", () => {
    at(`/dashboard/${A}`);

    expect(helper().requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", [HEADER]: A });
  });

  test("a page served under a base path names the dataflow its route opens", () => {
    servedUnder("/app-dev/");
    at(`/app-dev/dataflow/${A}`);
    expect(helper().pageDataflow()).toBe(A);

    at(`/app-dev/dashboard/${B}`);
    expect(helper().pageDataflow()).toBe(B);
  });

  test("the canvas names the route's dataflow while it still holds the one before it", () => {
    setOpenDataflow(B);
    at(`/dataflow/${A}`);

    expect(helper().pageDataflow()).toBe(A);
  });

  test("a new dataflow names none until its first save, then the id it got", () => {
    at("/dataflow/new");
    expect(helper().pageDataflow()).toBeNull();
    expect(helper().requestHeaders("tok")).toEqual({ Authorization: "Bearer tok" });

    // What the first save's answer sets, as ProjectLoader does on a reload.
    setOpenDataflow(NEW);
    expect(helper().requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", [HEADER]: NEW });

    // The canvas with no id in its route is the same new dataflow.
    at("/dataflow");
    expect(helper().pageDataflow()).toBe(NEW);
  });

  test.each([
    "/projects",
    "/catalog/data",
    `/catalog/scenarios/${A}/s1`,
    "/monitor",
    "/settings/keys",
    "/auth/signin",
    "/",
  ])("%s names no dataflow, even right after a canvas closed", (where) => {
    // The canvas that closed last opened A; nothing on this page is about it.
    setOpenDataflow(A);
    at(where);

    expect(helper().pageDataflow()).toBeNull();
    expect(helper().requestHeaders("tok")).toEqual({ Authorization: "Bearer tok" });
  });

  test("a request that names its dataflow names that one, on any page", () => {
    at("/projects");
    expect(helper().requestHeaders("tok", {}, A)).toEqual({ Authorization: "Bearer tok", [HEADER]: A });

    at(`/dataflow/${B}`);
    expect(helper().requestHeaders("tok", {}, A)[HEADER]).toBe(A);
    // A request that names none names the page's.
    expect(helper().requestHeaders("tok", {}, null)[HEADER]).toBe(B);
  });

  test("with no sign-in a request names the dataflow alone, and on a page with none, nothing", () => {
    at(`/dashboard/${A}`);
    expect(helper().requestHeaders(undefined)).toEqual({ [HEADER]: A });

    at("/projects");
    expect(helper().requestHeaders(null)).toEqual({});
  });

  test("a request keeps the headers of its own", () => {
    at(`/dataflow/${A}`);

    expect(helper().requestHeaders("tok", { "Content-Type": "application/json", "X-Curio-Run-Token": "t1" })).toEqual({
      "Content-Type": "application/json",
      "X-Curio-Run-Token": "t1",
      Authorization: "Bearer tok",
      [HEADER]: A,
    });
  });
});

describe("what each client sends", () => {
  const originalFetch = global.fetch;
  let asked: { url: string; headers: Record<string, string> }[] = [];

  function answer(url: string) {
    const body = url.includes("/storeOutput")
      ? { output: { path: "art-2", dataType: "dataframe" } }
      : url.includes("/starters") ? [] : { dataType: "str", data: "Month" };
    return {
      ok: true,
      status: 200,
      headers: { get: () => null, forEach: () => {} },
      json: async () => body,
      text: async () => "",
      blob: async () => new Blob(["x"]),
      arrayBuffer: async () => new ArrayBuffer(4),
      body: { getReader: () => ({ read: async () => ({ done: true, value: undefined }) }) },
    };
  }

  beforeEach(() => {
    asked = [];
    resetNodeRuntimeReports();
    forgetDashboardRunFiles();
    document.cookie = "session_token=tok; path=/";
    global.fetch = jest.fn(async (url: string, init?: { headers?: Record<string, string> }) => {
      asked.push({ url: String(url), headers: { ...(init?.headers ?? {}) } });
      return answer(String(url));
    }) as unknown as typeof fetch;
    // The canvas of A, which ProjectLoader opened.
    at(`/dataflow/${A}`);
    setOpenDataflow(A);
  });

  afterEach(() => {
    global.fetch = originalFetch;
    forgetDashboardRunFiles();
    document.cookie = "session_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT";
  });

  const clients: Array<[string, () => Promise<unknown>]> = [
    ["a run's state (apiFetch)", () => apiFetch("/api/runs/r1")],
    ["a run's stream (postSseStream)", () => postSseStream("/api/runs/r1/stream", null, () => {}, undefined, "GET")],
    ["a node's run (runNodeOnBackend)", () => new Promise((settle) =>
      runNodeOnBackend("/processPythonCode", { code: "return 1" }, "n1", settle, settle))],
    ["rows kept as an output (storeOutput)", () => storeOutput("n1", { dataType: "dataframe", data: {} })],
    ["an output's read (fetchData)", () => fetchData("art-1")],
    ["an output's preview (fetchPreviewData)", () => fetchPreviewData("art-1")],
    ["a raster (fetchRaster)", () => fetchRaster("art-1", { maxCells: 10, maxSide: 5 })],
    ["an output's file (fetchOutputFile)", () => fetchOutputFile("art-1")],
    ["a node's outcome (reportNodeRuntime)", () => reportNodeRuntime({ dataflowId: A, nodeId: "n1", status: "ok" })],
    ["the starters (useStarters)", () => useStarters()],
    ["a dataset's import (importDataset)", () =>
      datasetCatalogApi.importDataset(new File(["a,b\n1,2\n"], "rows.csv"), { dataflowId: A })],
  ];

  test.each(clients)("%s names the page's dataflow, with the sign-in", async (_what, send) => {
    await send();

    expect(asked.length).toBeGreaterThan(0);
    for (const { url, headers } of asked) {
      expect({ url, named: headers[HEADER], signedIn: headers.Authorization }).toEqual({
        url, named: A, signedIn: "Bearer tok",
      });
    }
  });

  test("a dashboard viewer's read names the dashboard's dataflow beside its run's token", async () => {
    at(`/dashboard/${A}`);
    rememberDashboardRunFiles(A, "t1", ["art-1"]);

    await fetchPreviewData("art-1");

    expect(asked).toHaveLength(1);
    expect(asked[0].url).toContain(`/api/projects/${A}/dashboard/outputs/get-preview`);
    expect(asked[0].headers).toMatchObject({ "X-Curio-Run-Token": "t1", [HEADER]: A });
  });

  test("a node's outcome sent as its canvas closes names its own dataflow", async () => {
    at("/projects");
    setOpenDataflow(null);

    await reportNodeRuntime({ dataflowId: A, nodeId: "n2", status: "error", message: "boom" });

    expect(asked).toHaveLength(1);
    expect(asked[0].headers[HEADER]).toBe(A);
  });

  test("the same client on a page with no dataflow names none", async () => {
    await apiFetch("/api/runs/r1");
    at("/projects");
    setOpenDataflow(null);
    await apiFetch("/api/projects");

    expect(asked.map(({ headers }) => [headers.Authorization, headers[HEADER]])).toEqual([
      ["Bearer tok", A],
      ["Bearer tok", undefined],
    ]);
  });
});
