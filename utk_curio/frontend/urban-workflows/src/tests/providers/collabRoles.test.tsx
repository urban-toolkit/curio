/**
 * The room says who this tab is (`CollaborationProvider`): its join answers
 * with the tab's participant id, and the tab's role is its own entry's in the
 * room's list, so a change the owner makes to the editors reaches it with the
 * list. A join the room refuses (a hosted guest's to an example) closes the
 * socket, and none opens again for that dataflow.
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
jest.mock("../../utils/authApi", () => ({
  getToken: () => "tok",
  authApi: {
    getPublicConfig: () => Promise.resolve({ enable_collab: true, collab_namespace: "/collab" }),
    // The account behind the token: ana, user 7, with two tabs in the room.
    getMe: () => Promise.resolve({ id: 7, username: "ana" }),
  },
}));
let mockProjectId = "project-1";
const mockStoreListeners = new Set<() => void>();
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => mockProjectId,
  subscribe: (listener: () => void) => {
    mockStoreListeners.add(listener);
    return () => mockStoreListeners.delete(listener);
  },
}));

import { CollaborationProvider, useCollab } from "../../providers/CollaborationProvider";

type Handler = (payload?: any) => void;
interface FakeSocket {
  handlers: Record<string, Handler[]>;
  emits: Array<{ event: string; payload: any; ack?: (answer: any) => void }>;
  disconnect: jest.Mock;
}
let sockets: FakeSocket[] = [];

function fakeSocket(): FakeSocket & Record<string, unknown> {
  const fake: any = {
    handlers: {},
    emits: [],
    connected: true,
    on(event: string, handler: Handler) {
      fake.handlers[event] = fake.handlers[event] || [];
      fake.handlers[event].push(handler);
    },
    // The dataflow's doc, which starts once the room joins the tab, takes
    // its handler off the socket when it goes.
    off(event: string, handler: Handler) {
      fake.handlers[event] = (fake.handlers[event] || []).filter((h: Handler) => h !== handler);
    },
    emit(event: string, payload: any, ack?: (answer: any) => void) {
      fake.emits.push({ event, payload, ack });
    },
    removeAllListeners: jest.fn(),
    disconnect: jest.fn(),
  };
  return fake;
}

function fire(socket: FakeSocket, event: string, payload?: any) {
  act(() => {
    for (const handler of socket.handlers[event] ?? []) handler(payload);
  });
}

function joinAnswer(socket: FakeSocket, answer: any) {
  const join = socket.emits.find((e) => e.event === "join_session");
  expect(join).toBeDefined();
  act(() => join!.ack!(answer));
}

let seen: ReturnType<typeof useCollab>;
const Probe = () => {
  seen = useCollab();
  return null;
};

// Two tabs of ana's (user 7): the room names this one p-2.
const USERS = [
  { user_id: 7, username: "ana", participant_id: "p-1", role: "owner" },
  { user_id: 7, username: "ana", participant_id: "p-2", role: "editor" },
];
const SNAPSHOT = { users: USERS, locks: {}, proposals: [], activity: [] };

beforeEach(() => {
  sockets = [];
  mockProjectId = "project-1";
  mockStoreListeners.clear();
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
});

async function joined() {
  render(
    <CollaborationProvider>
      <Probe />
    </CollaborationProvider>,
  );
  await waitFor(() => expect(sockets).toHaveLength(1));
  fire(sockets[0], "connect");
  return sockets[0];
}

test("a tab's role is its own entry's in the room, not its account's", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: true, participant_id: "p-2", role: "editor", snapshot: SNAPSHOT });

  expect(seen.participantId).toBe("p-2");
  expect(seen.role).toBe("editor");
});

test("a change of editors reaches the tab's role with the room's list", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: true, participant_id: "p-2", role: "editor", snapshot: SNAPSHOT });

  fire(socket, "roles_changed", { users: [USERS[0], { ...USERS[1], role: "watcher" }] });

  expect(seen.role).toBe("watcher");
});

test("a disconnected tab has no role until it joins again", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: true, participant_id: "p-2", role: "editor", snapshot: SNAPSHOT });

  fire(socket, "disconnect");

  expect(seen.participantId).toBeNull();
  expect(seen.role).toBeNull();
});

test("a refused join closes the socket, and no other opens for that dataflow", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: false, error: "guest_owned" });

  expect(socket.disconnect).toHaveBeenCalled();
  expect(seen.role).toBeNull();
  act(() => mockStoreListeners.forEach((listener) => listener()));
  expect(mockIo).toHaveBeenCalledTimes(1);

  mockProjectId = "project-2";
  act(() => mockStoreListeners.forEach((listener) => listener()));
  expect(mockIo).toHaveBeenCalledTimes(2);
});
