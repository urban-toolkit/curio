/**
 * The room says who this tab is (`CollaborationProvider`): its join answers
 * with the tab's participant id, and the tab's role is its own entry's in the
 * room's list, so a change the owner makes to the editors reaches it with the
 * list. A join the room refuses (a hosted guest's to an example) closes the
 * socket, and none opens again for that dataflow. The room's Activity is what
 * the join brought, then each join, leave and change of role as it comes.
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
    getPublicConfig: () => Promise.resolve({ collab_namespace: "/collab" }),
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

import { CollaborationProvider, roleChanges, useCollab } from "../../providers/CollaborationProvider";

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
const SNAPSHOT = { users: USERS, locks: {}, activity: [] };

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

// Someone else, who joins as a watcher with two tabs.
const BEN = { user_id: 9, username: "ben", name: "Ben", participant_id: "p-3", role: "watcher" };
const BENS_OTHER_TAB = { ...BEN, participant_id: "p-4" };

test("the room's Activity is what the join brought, then each join, leave and change of role as it comes", async () => {
  const socket = await joined();
  const brought = { kind: "user_joined", ts: 1, payload: { user_id: 7, username: "ana", role: "editor" } };
  joinAnswer(socket, { ok: true, participant_id: "p-2", role: "editor", snapshot: { ...SNAPSHOT, activity: [brought] } });
  expect(seen.activity).toEqual([brought]);

  fire(socket, "user_joined", { ...BEN, users: [...USERS, BEN] });
  fire(socket, "roles_changed", { users: [...USERS, { ...BEN, role: "editor" }] });
  fire(socket, "user_left", { user_id: 9, username: "ben", participant_id: "p-3", released_locks: [], users: USERS });

  expect(seen.activity.map(({ kind, payload }) => [kind, payload])).toEqual([
    ["user_joined", { user_id: 7, username: "ana", role: "editor" }],
    ["user_joined", { user_id: 9, username: "ben", name: "Ben", role: "watcher" }],
    ["role_changed", { user_id: 9, username: "ben", name: "Ben", role: "editor" }],
    ["user_left", { user_id: 9, username: "ben" }],
  ]);
});

// A tab of the shared guest account, which every guest signs in to: the room
// numbers it, and names it by its number in its join and its leave.
const GUEST_TAB = {
  user_id: 3, username: "guest_shared", name: "Shared Guest", participant_id: "p-5", role: "watcher", guest_number: 2,
};

test("a tab of the shared guest account keeps its name and its number in the Activity of its join and its leave", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: true, participant_id: "p-2", role: "editor", snapshot: SNAPSHOT });

  fire(socket, "user_joined", { ...GUEST_TAB, users: [...USERS, GUEST_TAB] });
  fire(socket, "user_left", {
    user_id: 3, username: "guest_shared", name: "Shared Guest", guest_number: 2,
    participant_id: "p-5", released_locks: [], users: USERS,
  });

  expect(seen.activity.map(({ kind, payload }) => [kind, payload])).toEqual([
    ["user_joined", { user_id: 3, username: "guest_shared", name: "Shared Guest", role: "watcher", guest_number: 2 }],
    ["user_left", { user_id: 3, username: "guest_shared", name: "Shared Guest", guest_number: 2 }],
  ]);
});

test("a change to the editors is one event for each account whose role changed, however many tabs it has", () => {
  const before = [...USERS, BEN, BENS_OTHER_TAB];
  const after = [...USERS, { ...BEN, role: "editor" }, { ...BENS_OTHER_TAB, role: "editor" }];
  expect(roleChanges(before as any, after as any)).toEqual([
    { user_id: 9, username: "ben", name: "Ben", role: "editor" },
  ]);
  expect(roleChanges(after as any, after as any)).toEqual([]);
  // A participant the list did not hold yet joined: that is not a change of role.
  expect(roleChanges(USERS as any, [...USERS, BEN] as any)).toEqual([]);
});
