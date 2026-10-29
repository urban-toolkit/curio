/**
 * Which tabs send their changes to the dataflow's doc (`CollaborationProvider`,
 * `collab/participants.ts`'s `writesDoc`): the owner's and an invited
 * editor's, and a watcher's never. The doc's sync starts on the room's socket
 * once the room has joined the tab, and on a Curio with no sign-in (where the
 * shared guest is signed in for everyone) as on one with it.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";

const mockIo = jest.fn();
jest.mock("socket.io-client", () => ({
  io: (...args: unknown[]) => mockIo(...args),
}));
jest.mock("../../utils/backendUrl", () => ({
  backendUrl: () => "http://localhost:5002",
}));
/** What /api/config/public answers, as each test sets it. */
let mockConfig: Record<string, unknown> = {};
jest.mock("../../utils/authApi", () => ({
  getToken: () => "tok",
  authApi: {
    getPublicConfig: () => Promise.resolve({ collab_namespace: "/collab", ...mockConfig }),
    getMe: () => Promise.resolve({ id: 7, username: "ana" }),
  },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => "project-1",
  subscribe: () => () => undefined,
}));

import { CollaborationProvider } from "../../providers/CollaborationProvider";
import { CANVAS_ORIGIN, useDocBinding, type DocBinding } from "../../providers/collab/docContext";

type Handler = (payload?: any) => void;
interface Sent {
  event: string;
  payload: any;
  ack?: (answer: any) => void;
}
interface FakeSocket {
  connected: boolean;
  sent: Sent[];
  fire(event: string, payload?: any): void;
}
let sockets: FakeSocket[] = [];

function fakeSocket(): FakeSocket {
  const handlers: Record<string, Handler[]> = {};
  const fake: any = {
    connected: true,
    sent: [],
    on(event: string, handler: Handler) {
      (handlers[event] ??= []).push(handler);
    },
    off(event: string, handler: Handler) {
      handlers[event] = (handlers[event] ?? []).filter((h) => h !== handler);
    },
    emit(event: string, payload: any, ack?: (answer: any) => void) {
      fake.sent.push({ event, payload, ack });
    },
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
    fire(event: string, payload?: any) {
      act(() => {
        for (const handler of handlers[event] ?? []) handler(payload);
      });
    },
  };
  return fake;
}

let binding: DocBinding | null = null;
const Probe = () => {
  binding = useDocBinding();
  return null;
};

beforeEach(() => {
  sockets = [];
  binding = null;
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
});

/** The page, its public config read. */
async function opened(): Promise<void> {
  render(
    <CollaborationProvider>
      <Probe />
    </CollaborationProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

/** The room joins this tab as *role*. */
function joinAs(socket: FakeSocket, role: string) {
  socket.fire("connect");
  const join = socket.sent.find((sent) => sent.event === "join_session");
  expect(join).toBeDefined();
  const users = [{ user_id: 7, username: "ana", participant_id: "p-1", role }];
  act(() => join!.ack!({ ok: true, participant_id: "p-1", role, snapshot: { users, locks: {}, activity: [] } }));
}

/** A tab the room joins as *role*, its doc synced with the server's. */
async function joinedAs(role: string): Promise<FakeSocket> {
  await opened();
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  joinAs(socket, role);
  const start = socket.sent.find((sent) => sent.event === "yjs");
  expect(start).toBeDefined();
  act(() => start!.ack!({ ok: true, docId: "doc-1", role }));
  await waitFor(() => expect(binding?.synced).toBe(true));
  return socket;
}

/** The doc's changes *socket* carried: y-protocols sync updates, not presence. */
function updatesSent(socket: FakeSocket): number {
  return socket.sent.filter((sent) => {
    const bytes: Uint8Array | undefined = sent.payload?.message;
    return sent.event === "yjs" && !!bytes && bytes[0] === 0 && bytes[1] === 2;
  }).length;
}

/** A change from this tab's canvas: the dataflow renamed. */
function renameOnCanvas() {
  const doc = binding!.provider.doc;
  act(() => {
    doc.transact(() => doc.getMap("dataflow").set("name", JSON.stringify("Renamed")), CANVAS_ORIGIN);
  });
}

test.each([
  ["owner", true],
  ["editor", true],
  ["watcher", false],
])("a tab the room names %s sends its changes: %s", async (role, sends) => {
  mockConfig = {};
  const socket = await joinedAs(role);

  renameOnCanvas();

  expect(binding!.provider.canWrite).toBe(sends);
  expect(updatesSent(socket) > 0).toBe(sends);
});

test.each([
  ["curio_no_auth"],
  ["skip_project_page"],
  ["curio_no_project"],
])("on a Curio with no sign-in (%s), the owner's tab syncs its dataflow's doc and sends its changes", async (setting) => {
  // The shared guest is signed in for everyone there and owns every dataflow,
  // so its tab binds as a signed-in owner's does, and no tab saves.
  mockConfig = { [setting]: true };
  const socket = await joinedAs("owner");

  renameOnCanvas();

  expect(mockIo).toHaveBeenCalledTimes(1);
  expect(binding!.provider.canWrite).toBe(true);
  expect(updatesSent(socket)).toBeGreaterThan(0);
});
