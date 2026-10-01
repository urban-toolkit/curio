/**
 * #429: collaboration connects when the backend sits under a path.
 *
 * DEPLOYMENT.md puts the backend at `https://<host>/curio/api` behind a proxy
 * that strips the prefix. socket.io reads the path of the URL it is given as
 * the NAMESPACE, and sends the handshake to `path` (default `/socket.io`) at
 * the origin. `io("https://<host>/curio/api/collab")` therefore asked for
 * namespace `/curio/api/collab` at `https://<host>/socket.io/`, which the
 * proxy does not route to the backend. The prefix belongs in `path`.
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";

const mockIo = jest.fn();

jest.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));
jest.mock("../../utils/backendUrl", () => ({
  backendUrl: () => "https://lab.example.edu/curio/api",
}));
jest.mock("../../utils/authApi", () => ({
  getToken: () => "tok",
  authApi: {
    getPublicConfig: () => Promise.resolve({ enable_collab: true }),
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

test("the provider puts the backend's path prefix in socket.io's path", async () => {
  render(
    <CollaborationProvider>
      <div />
    </CollaborationProvider>,
  );
  await waitFor(() => expect(mockIo).toHaveBeenCalled());
  const [url, options] = mockIo.mock.calls[0];
  expect(url).toBe("https://lab.example.edu/collab");
  expect(options).toMatchObject({ path: "/curio/api/socket.io", auth: { token: "tok" } });
});
