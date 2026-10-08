/**
 * Who is looking at a dashboard page that was served with its data.
 *
 * The page has no session of its own and names no account. A visitor with no
 * session is the viewer it is, and the page asks nothing of a server. A
 * browser that holds a session asks one thing, whether it may edit this
 * dashboard's layout (`GET /api/projects/<id>/dashboard/can-edit`). On a no,
 * or no answer in time, the page stays its viewer's. On a yes it learns who is
 * signed in the way any page does, and ProjectLoader loads the dataflow as
 * its owner's. A page the server refused to build asks nothing at all.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";

const mockApiFetch = jest.fn();
const mockGetMe = jest.fn();
const mockGetPublicConfig = jest.fn();
let mockToken: string | undefined;

jest.mock("../../utils/authApi", () => ({
  apiFetch: (...a: unknown[]) => mockApiFetch(...a),
  authApi: {
    getMe: (...a: unknown[]) => mockGetMe(...a),
    getPublicConfig: (...a: unknown[]) => mockGetPublicConfig(...a),
    signinAutoGuest: jest.fn(),
    signinGuest: jest.fn(),
  },
  getToken: () => mockToken,
  setToken: jest.fn(),
  clearToken: jest.fn(),
  isUnauthorized: (e: { status?: number } | null) => e?.status === 401,
}));
jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn().mockResolvedValue(undefined),
}));
jest.mock("../../components/login/Loading", () => ({
  Loading: () => <div data-testid="loading" />,
}));

import UserProvider, { useUserContext } from "../../providers/UserProvider";
import { resetEmbeddedDashboardForTests } from "../../standalone/dashboardPayload";

const PROJECT_ID = "11111111-2222-3333-4444-555555555555";
const OWNER = {
  id: 7,
  username: "owner",
  name: "Owner",
  email: null,
  profile_image: null,
  type: null,
  is_guest: false,
};

function serve(payload: unknown) {
  const el = document.createElement("script");
  el.id = "curio-dashboard-payload";
  el.type = "application/json";
  el.textContent = JSON.stringify(payload);
  document.body.appendChild(el);
  resetEmbeddedDashboardForTests();
}

const DASHBOARD = {
  meta: { projectId: PROJECT_ID, name: "Trips" },
  spec: { dataflow: { nodes: [], edges: [] } },
  outputs: {},
};

const REFUSED = {
  meta: { projectId: PROJECT_ID, name: "Trips" },
  refused: { status: 413, message: "over the 25.0 MB limit" },
};

/** Who the page thinks is looking, and whether it runs with sign-in on. */
const Probe: React.FC = () => {
  const { user, enableUserAuth } = useUserContext();
  return <span data-testid="who">{user ? `${user.name}|${enableUserAuth}` : "none"}</span>;
};

function renderProvider() {
  return render(
    <UserProvider>
      <Probe />
    </UserProvider>,
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  mockToken = undefined;
  mockApiFetch.mockResolvedValue({ canEdit: false });
  mockGetPublicConfig.mockResolvedValue({ allow_guest_login: false });
  mockGetMe.mockResolvedValue(OWNER);
});

afterEach(() => {
  document.getElementById("curio-dashboard-payload")?.remove();
  resetEmbeddedDashboardForTests();
  jest.useRealTimers();
});

test("a session asks whether it may edit this dashboard, and nothing more on a no", async () => {
  serve(DASHBOARD);
  mockToken = "viewer-token";

  const { getByTestId } = renderProvider();

  await waitFor(() => expect(mockApiFetch).toHaveBeenCalledTimes(1));
  expect(mockApiFetch.mock.calls[0][0]).toBe(`/api/projects/${PROJECT_ID}/dashboard/can-edit`);
  await waitFor(() => expect(getByTestId("who").textContent).toBe("Viewer|false"));
  expect(mockGetMe).not.toHaveBeenCalled();
  expect(mockGetPublicConfig).not.toHaveBeenCalled();
});

test("on a yes, the page learns who is signed in as any page does", async () => {
  serve(DASHBOARD);
  mockToken = "owner-token";
  mockApiFetch.mockResolvedValue({ canEdit: true });

  const { getByTestId } = renderProvider();

  await waitFor(() => expect(getByTestId("who").textContent).toBe("Owner|true"));
  expect(mockGetMe).toHaveBeenCalledTimes(1);
});

test("with no session it asks nothing, and the viewer is who it is", async () => {
  serve(DASHBOARD);

  const { getByTestId } = renderProvider();

  await waitFor(() => expect(getByTestId("who").textContent).toBe("Viewer|false"));
  expect(mockApiFetch).not.toHaveBeenCalled();
  expect(mockGetMe).not.toHaveBeenCalled();
  expect(mockGetPublicConfig).not.toHaveBeenCalled();
});

test("a page the server refused asks nothing, even with a session", async () => {
  serve(REFUSED);
  mockToken = "owner-token";

  const { getByTestId } = renderProvider();

  await waitFor(() => expect(getByTestId("who").textContent).toBe("Viewer|false"));
  expect(mockApiFetch).not.toHaveBeenCalled();
  expect(mockGetMe).not.toHaveBeenCalled();
});

test("an answer that does not come in time leaves the viewer", async () => {
  // The page must open where its server cannot be reached.
  jest.useFakeTimers();
  serve(DASHBOARD);
  mockToken = "owner-token";
  mockApiFetch.mockReturnValue(new Promise(() => {}));

  const { getByTestId } = renderProvider();
  await act(async () => {
    jest.advanceTimersByTime(10_000);
  });

  await waitFor(() => expect(getByTestId("who").textContent).toBe("Viewer|false"));
  expect(mockGetMe).not.toHaveBeenCalled();
});
