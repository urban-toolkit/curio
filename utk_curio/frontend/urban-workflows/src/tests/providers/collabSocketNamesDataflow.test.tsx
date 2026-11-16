/**
 * The room's socket names its dataflow in its handshake
 * (`CollaborationProvider`): the `dataflow` query argument of its connection.
 * A start of several backend processes sends the socket by it to the process
 * that keeps the dataflow's room (`cli/backend_group.py`); `join_session`
 * names the dataflow again once the socket is there. Each dataflow's socket is
 * a connection of its own, so the page's next dataflow opens one that names
 * the new one, never a connection made for the one before.
 *
 * A hosted guest's join to an example answers with its own copy's id, whose
 * room the tab joins: the socket, a reconnect of it, and the page's requests
 * (`utils/requestHeaders.ts`) still name the dataflow the page shows, with
 * which the server keeps the copy.
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
    getMe: () => Promise.resolve({ id: 3, username: "guest_shared" }),
  },
}));

/** The dataflow the page shows, another one, and a hosted guest's own copy of the first. */
const PAGE = "11111111-2222-4333-8444-555555555555";
const OTHER = "66666666-7777-4888-9999-000000000000";
const COPY = "99999999-8888-5777-a666-555555555555";

let mockProjectId = PAGE;
const mockStoreListeners = new Set<() => void>();
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => mockProjectId,
  subscribe: (listener: () => void) => {
    mockStoreListeners.add(listener);
    return () => mockStoreListeners.delete(listener);
  },
}));

import { CollaborationProvider } from "../../providers/CollaborationProvider";

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

/** What each socket's handshake asked: the options `io` was given. */
const handshakes = () => mockIo.mock.calls.map(([, options]) => options);
const joins = (socket: FakeSocket) =>
  socket.emits.filter((e) => e.event === "join_session").map((e) => e.payload.projectId);

beforeEach(() => {
  sockets = [];
  mockProjectId = PAGE;
  mockStoreListeners.clear();
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
  window.history.replaceState(null, "", `/dataflow/${PAGE}`);
});

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

async function connected() {
  render(
    <CollaborationProvider>
      <div />
    </CollaborationProvider>,
  );
  await waitFor(() => expect(sockets).toHaveLength(1));
  fire(sockets[0], "connect");
  return sockets[0];
}

test("the handshake names the dataflow the socket joins, on a connection of its own", async () => {
  const socket = await connected();

  expect(handshakes()).toHaveLength(1);
  expect(handshakes()[0].query).toEqual({ dataflow: PAGE });
  // A connection socket.io-client kept for another dataflow's socket would
  // send that one's handshake: each dataflow's socket asks for its own.
  expect(handshakes()[0].forceNew).toBe(true);
  expect(handshakes()[0].auth).toEqual({ token: "tok" });
  expect(joins(socket)).toEqual([PAGE]);
});

test("the page's next dataflow opens a socket that names the new one", async () => {
  const first = await connected();

  mockProjectId = OTHER;
  window.history.replaceState(null, "", `/dataflow/${OTHER}`);
  act(() => mockStoreListeners.forEach((listener) => listener()));
  await waitFor(() => expect(sockets).toHaveLength(2));
  fire(sockets[1], "connect");

  expect(first.disconnect).toHaveBeenCalled();
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: PAGE }, { dataflow: OTHER }]);
  expect(joins(sockets[1])).toEqual([OTHER]);
});

test("a hosted guest's socket and requests name the dataflow its page shows, never its own copy's", async () => {
  const { requestHeaders } = require("../../utils/requestHeaders");
  const socket = await connected();
  const join = socket.emits.find((e) => e.event === "join_session");
  act(() => join!.ack!({
    ok: true, participant_id: "p-5", role: "owner", projectId: COPY,
    snapshot: { users: [{ user_id: 3, username: "guest_shared", participant_id: "p-5", role: "owner" }], locks: {}, activity: [] },
  }));

  // The tab is in its copy's room: the doc it syncs names the copy.
  const syncs = socket.emits.filter((e) => e.event === "yjs");
  expect(syncs.length).toBeGreaterThan(0);
  expect(new Set(syncs.map((e) => e.payload.projectId))).toEqual(new Set([COPY]));
  // Its requests name the dataflow the page shows.
  expect(requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", "X-Curio-Dataflow": PAGE });

  // A reconnect is the same connection, its handshake unchanged, and it
  // joins by the page's dataflow again.
  fire(socket, "disconnect");
  fire(socket, "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: PAGE }]);
  expect(joins(socket)).toEqual([PAGE, PAGE]);
  expect(requestHeaders("tok")["X-Curio-Dataflow"]).toBe(PAGE);
});
