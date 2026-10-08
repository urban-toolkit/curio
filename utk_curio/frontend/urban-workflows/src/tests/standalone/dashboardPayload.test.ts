/**
 * Reading the payload a standalone dashboard page was served with.
 *
 * Everything that would otherwise fetch asks this module first, so the two
 * answers that matter are "here are the rows" and a clean null. Null is not a
 * failure: a backend that was down when the page was served, and the dev server
 * (which cannot inject), produce an ordinary page that fetches for itself. That
 * is the behaviour this replaces, so falling back to it is the safe outcome and
 * a thrown error is not. (A dashboard the backend refused to build is served
 * with its reason instead, and fetches nothing: refusedDashboard.test.tsx.)
 */
import {
  embeddedArtifact,
  getEmbeddedDashboard,
  isStandaloneDashboard,
  resetEmbeddedDashboardForTests,
} from "../../standalone/dashboardPayload";

const PAYLOAD = {
  meta: { projectId: "p1", name: "Trips" },
  spec: { dataflow: { nodes: [], edges: [] } },
  outputs: {
    "a.parquet": { dataType: "dataframe", data: { n: [1, 2] }, schema: { n: "int64" } },
  },
};

function serve(json: string | null) {
  document.body.innerHTML = "";
  if (json === null) return;
  const el = document.createElement("script");
  el.id = "curio-dashboard-payload";
  el.type = "application/json";
  el.textContent = json;
  document.body.appendChild(el);
}

beforeEach(() => {
  resetEmbeddedDashboardForTests();
  serve(null);
});

describe("a page served with a payload", () => {
  test("it reads the payload", () => {
    serve(JSON.stringify(PAYLOAD));

    expect(getEmbeddedDashboard()).toEqual(PAYLOAD);
    expect(isStandaloneDashboard()).toBe(true);
  });

  test("it hands back an artifact by the name a tile looks up", () => {
    serve(JSON.stringify(PAYLOAD));

    expect(embeddedArtifact("a.parquet")).toEqual(PAYLOAD.outputs["a.parquet"]);
  });

  test("an artifact it does not carry is a miss, not an error", () => {
    // That tile fetches and fails the way it does today, rather than taking the
    // whole page down with it.
    serve(JSON.stringify(PAYLOAD));

    expect(embeddedArtifact("missing.parquet")).toBeNull();
  });

  test("it parses once, however many tiles ask", () => {
    serve(JSON.stringify(PAYLOAD));
    const first = getEmbeddedDashboard();

    serve(JSON.stringify({ ...PAYLOAD, meta: { projectId: "changed" } }));

    // Re-reading megabytes of rows per tile would be the cost; the payload is a
    // document the page was served with, not state that changes under it.
    expect(getEmbeddedDashboard()).toBe(first);
  });

  test("a payload with no rows is still a payload", () => {
    // A dashboard whose tiles have nothing saved yet should render its empty
    // states offline rather than fall back to fetching nothing.
    serve(JSON.stringify({ meta: {}, spec: {} }));

    expect(isStandaloneDashboard()).toBe(true);
    expect(embeddedArtifact("a.parquet")).toBeNull();
  });
});

describe("a page served without one", () => {
  test("no tag means no payload", () => {
    expect(getEmbeddedDashboard()).toBeNull();
    expect(isStandaloneDashboard()).toBe(false);
    expect(embeddedArtifact("a.parquet")).toBeNull();
  });

  test("a truncated payload falls back rather than blanking the page", () => {
    // A serving fault is not something to show the viewer: an ordinary fetching
    // page is strictly better than an error.
    serve('{"meta": {}, "outputs": {"a.parquet"');

    expect(getEmbeddedDashboard()).toBeNull();
    expect(isStandaloneDashboard()).toBe(false);
  });

  test("an empty tag is not a payload", () => {
    serve("");

    expect(getEmbeddedDashboard()).toBeNull();
  });
});
