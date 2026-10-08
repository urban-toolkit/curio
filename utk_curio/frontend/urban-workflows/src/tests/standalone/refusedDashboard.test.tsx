/**
 * A dashboard the server refused asks it for nothing.
 *
 * When the backend will not build a dashboard as a page of its own (over the
 * size limit, or a tile that loads its own data), the page server carries the
 * backend's reason in the page instead of the data (`cli/static_server.py`).
 * That page holds no node descriptors and no starters either, and a page that
 * stands on its own must not go and ask the server for what it was not given:
 * that request is the fetch fallback the refusal exists to rule out.
 */
import React from "react";
import { act, render } from "@testing-library/react";

// vega and vega-lite ship ESM that Jest's default transform skips; nothing
// here reaches a Vega compile (same stubbing as behaviorScriptSingleFlight).
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

// No session: a standalone page never has one.
jest.mock("../../utils/authApi", () => ({ getToken: () => null }));

const mockListInstalled = jest.fn();
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { listInstalled: (...a: unknown[]) => mockListInstalled(...a) },
}));

const mockUseStarters = jest.fn();
jest.mock("../../providers/starters", () => ({
  __esModule: true,
  default: (...a: unknown[]) => mockUseStarters(...a),
}));

// Side-effect imports first, in the order packagesClient's own tests use.
import "../../registry/builtinBehaviors";
import "../../registry/iconRegistry";
import { loadInstalledPackages } from "../../registry/packagesClient";
import StarterProvider from "../../providers/StarterProvider";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

const REFUSED = {
  meta: { projectId: "11111111-2222-3333-4444-555555555555", name: "Trips" },
  refused: {
    status: 413,
    message:
      "This dashboard needs 31.0 MB of data embedded in the page, over the 25.0 MB limit.",
  },
};

function serve(payload: unknown) {
  const el = document.createElement("script");
  el.id = "curio-dashboard-payload";
  el.type = "application/json";
  el.textContent = JSON.stringify(payload);
  document.body.appendChild(el);
  resetEmbeddedDashboardForTests();
}

beforeEach(() => {
  jest.clearAllMocks();
  mockListInstalled.mockResolvedValue({ packages: [] });
  mockUseStarters.mockResolvedValue([]);
  serve(REFUSED);
});

afterEach(() => {
  document.getElementById("curio-dashboard-payload")?.remove();
  resetEmbeddedDashboardForTests();
});

test("it does not ask for the installed packages", async () => {
  await loadInstalledPackages();

  expect(mockListInstalled).not.toHaveBeenCalled();
});

test("it does not ask for the starters", async () => {
  await act(async () => {
    render(
      <StarterProvider>
        <span />
      </StarterProvider>,
    );
  });

  expect(mockUseStarters).not.toHaveBeenCalled();
});
