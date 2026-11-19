/**
 * The room's socket names its dataflow in its handshake
 * (`CollaborationProvider`): the `dataflow` query argument of its connection.
 * A start of several backend processes sends the socket by it to the process
 * that keeps the dataflow's room (`cli/backend_group.py`); `join_session`
 * names the dataflow again once the socket is there. Each dataflow's socket is
 * a connection of its own, so the page's next dataflow opens one that names
 * the new one, never a connection made for the one before.
 *
 * A hosted guest's canvas of an example works on the guest's own copy of it,
 * which the server keeps on the backend process the copy's own id names. The
 * canvas's load of the example answers with that id (`copy_id`,
 * `utils/requestHeaders.ts`), and the room's socket waits for it: its
 * handshake, a reconnect of it, and the page's requests name the copy, while
 * the join still names the example, and answers with the copy's id, whose
 * room the tab joins.
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
  // What a load named, which a page that starts knows nothing of.
  require("../../utils/requestHeaders").resetDataflowNames?.();
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

/** Let the provider read its namespace and run what follows from it: a
 *  socket it would open opens by now. */
async function settled() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

test("a hosted guest's socket waits for the load's answer, then it and the page's requests name its own copy", async () => {
  const names = require("../../utils/requestHeaders");
  // ProjectLoader starts the canvas's load of the example: no socket yet.
  names.awaitDataflowName(PAGE);
  render(
    <CollaborationProvider>
      <div />
    </CollaborationProvider>,
  );
  await settled();
  expect(sockets).toHaveLength(0);
  expect(names.requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", "X-Curio-Dataflow": PAGE });

  // The load answers with the guest's own copy: the socket opens, naming it.
  act(() => names.nameDataflow(PAGE, COPY));
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  fire(socket, "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: COPY }]);
  // The join names the example, and answers with the copy's room.
  expect(joins(socket)).toEqual([PAGE]);
  const join = socket.emits.find((e) => e.event === "join_session");
  act(() => join!.ack!({
    ok: true, participant_id: "p-5", role: "owner", projectId: COPY,
    snapshot: { users: [{ user_id: 3, username: "guest_shared", participant_id: "p-5", role: "owner" }], locks: {}, activity: [] },
  }));

  // The tab is in its copy's room: the doc it syncs names the copy.
  const syncs = socket.emits.filter((e) => e.event === "yjs");
  expect(syncs.length).toBeGreaterThan(0);
  expect(new Set(syncs.map((e) => e.payload.projectId))).toEqual(new Set([COPY]));
  // Its requests name the copy.
  expect(names.requestHeaders("tok")).toEqual({ Authorization: "Bearer tok", "X-Curio-Dataflow": COPY });

  // A reconnect is the same connection, its handshake unchanged, and it
  // joins by the page's dataflow again.
  fire(socket, "disconnect");
  fire(socket, "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: COPY }]);
  expect(joins(socket)).toEqual([PAGE, PAGE]);
  expect(names.requestHeaders("tok")["X-Curio-Dataflow"]).toBe(COPY);
});

test("a hosted guest's socket whose load names no copy opens naming the dataflow", async () => {
  // Another account's dataflow, opened from its link: the guest watches it.
  const names = require("../../utils/requestHeaders");
  names.awaitDataflowName(PAGE);
  render(
    <CollaborationProvider>
      <div />
    </CollaborationProvider>,
  );
  await settled();
  expect(sockets).toHaveLength(0);

  act(() => names.nameDataflow(PAGE, null));

  await waitFor(() => expect(sockets).toHaveLength(1));
  fire(sockets[0], "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: PAGE }]);
  expect(joins(sockets[0])).toEqual([PAGE]);
});

test("a socket the room refused under the dataflow's id opens again by the copy's once the load names it", async () => {
  const names = require("../../utils/requestHeaders");
  // A socket that opened before the page knew of a copy, which the process
  // the dataflow's id names refuses: the guest's room is its copy's.
  const first = await connected();
  const join = first.emits.find((e) => e.event === "join_session");
  act(() => join!.ack!({ ok: false, error: "not_the_owner", message: "belongs to backend process 1" }));
  expect(first.disconnect).toHaveBeenCalled();
  // The same dataflow by the same id stays refused.
  act(() => mockStoreListeners.forEach((listener) => listener()));
  await settled();
  expect(sockets).toHaveLength(1);

  act(() => names.nameDataflow(PAGE, COPY));

  await waitFor(() => expect(sockets).toHaveLength(2));
  fire(sockets[1], "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: PAGE }, { dataflow: COPY }]);
  expect(joins(sockets[1])).toEqual([PAGE]);
});

test("the next dataflow's socket waits for its load, and the socket before it closes meanwhile", async () => {
  const names = require("../../utils/requestHeaders");
  const first = await connected();

  // The page opens another dataflow, whose load has not answered yet.
  names.awaitDataflowName(OTHER);
  mockProjectId = OTHER;
  window.history.replaceState(null, "", `/dataflow/${OTHER}`);
  act(() => mockStoreListeners.forEach((listener) => listener()));
  await settled();
  expect(first.disconnect).toHaveBeenCalled();
  expect(sockets).toHaveLength(1);

  // Its answer names a hosted guest's copy of it: the socket opens by that.
  act(() => names.nameDataflow(OTHER, COPY));
  await waitFor(() => expect(sockets).toHaveLength(2));
  fire(sockets[1], "connect");
  expect(handshakes().map((options) => options.query)).toEqual([{ dataflow: PAGE }, { dataflow: COPY }]);
  expect(joins(sockets[1])).toEqual([OTHER]);
});
