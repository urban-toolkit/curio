/**
 * A Data Export's file is read by its output's artifact id at `/output-file`
 * (backend `api/routes.py`), with the signed-in user's token. One a dashboard
 * viewer's run wrote is read on its dashboard's route, with the run's token
 * (`runs/dashboardRunFiles.ts`). A refusal hands back its reason, which the
 * node shows under its Download button.
 */
import { fetchOutputFile } from "../../services/outputFiles";
import { forgetDashboardRunFiles, rememberDashboardRunFiles } from "../../services/runs/dashboardRunFiles";
import { backendUrl } from "../../utils/backendUrl";

let mockToken: string | null = "alice-token";
jest.mock("../../utils/authApi", () => ({
  ...jest.requireActual("../../utils/authApi"),
  getToken: () => mockToken,
}));

const originalFetch = global.fetch;
const FILE = new Blob(["tree,height\noak,10\n"], { type: "text/csv" });
let asked: { url: string; headers: Record<string, string> }[] = [];
let reply: { ok: boolean; status: number; body?: unknown };

beforeEach(() => {
  forgetDashboardRunFiles();
  mockToken = "alice-token";
  asked = [];
  reply = { ok: true, status: 200 };
  global.fetch = jest.fn(async (url: string, init?: { headers?: Record<string, string> }) => {
    asked.push({ url: String(url), headers: { ...(init?.headers ?? {}) } });
    return {
      ok: reply.ok,
      status: reply.status,
      blob: async () => FILE,
      json: async () => {
        if (reply.body === undefined) throw new SyntaxError("Unexpected token < in JSON");
        return reply.body;
      },
    };
  }) as unknown as typeof fetch;
});

afterEach(() => {
  global.fetch = originalFetch;
  forgetDashboardRunFiles();
});

test("a file is asked for by its output's id, with the signed-in user's token", async () => {
  const fetched = await fetchOutputFile("1792169042468_bd44c99d");

  expect(fetched).toEqual({ ok: true, blob: FILE });
  expect(asked).toEqual([{
    url: `${backendUrl()}/output-file?fileName=1792169042468_bd44c99d`,
    headers: { Authorization: "Bearer alice-token" },
  }]);
});

test("one a dashboard viewer's run wrote is read on its dashboard's route, with the run's token", async () => {
  mockToken = null;
  rememberDashboardRunFiles("dash-1", "t1", ["1792169042468_bd44c99d"]);

  const fetched = await fetchOutputFile("1792169042468_bd44c99d");

  expect(fetched).toEqual({ ok: true, blob: FILE });
  expect(asked).toEqual([{
    url: `${backendUrl()}/api/projects/dash-1/dashboard/outputs/output-file?fileName=1792169042468_bd44c99d`,
    headers: { "X-Curio-Run-Token": "t1" },
  }]);
});

test("a refusal hands back its reason, or its status when it gives none", async () => {
  const outside = "This node's output names a file outside the folder of the run that made it.";
  reply = { ok: false, status: 403, body: { error: "outside", message: outside } };
  await expect(fetchOutputFile("1792169042468_bd44c99d")).resolves.toEqual({ ok: false, status: 403, message: outside });

  reply = { ok: false, status: 502 };
  await expect(fetchOutputFile("1792169042468_bd44c99d")).resolves.toEqual({ ok: false, status: 502, message: "HTTP 502" });
});
