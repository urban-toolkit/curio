/**
 * #615: collaboration connects on the namespace the backend serves.
 *
 * `--collab-namespace` moves the backend's Socket.IO namespace off `/collab`,
 * and `/api/config/public` reports the one it serves. The page has to open its
 * socket there, or the handshake reaches a namespace nothing listens on.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockIo = jest.fn();

jest.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));
jest.mock("../../utils/backendUrl", () => ({
  backendUrl: () => "http://localhost:5002",
}));
jest.mock("../../utils/authApi", () => ({
  getToken: () => "tok",
  authApi: {
    getPublicConfig: () => Promise.resolve({ enable_collab: true, collab_namespace: "/team" }),
    getMe: () => Promise.resolve({ id: 1 }),
  },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => "project-1",
  subscribe: () => () => {},
}));

import { CollaborationProvider } from "../../providers/CollaborationProvider";

beforeEach(() => {
  mockIo.mockReset();
  mockIo.mockImplementation(() => ({
    on: jest.fn(),
    emit: jest.fn(),
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
    connected: false,
  }));
});

test("the socket opens on the namespace the backend reports", async () => {
  render(
    <CollaborationProvider>
      <div />
    </CollaborationProvider>,
  );
  await waitFor(() => expect(mockIo).toHaveBeenCalled());
  const [url, options] = mockIo.mock.calls[0];
  expect(url).toBe("http://localhost:5002/team");
  expect(options).toMatchObject({ path: "/socket.io", auth: { token: "tok" } });
});
