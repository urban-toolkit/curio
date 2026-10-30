/**
 * An agent at work joins and leaves the dataflow's room as the server runs it
 * (`agent_peers.py`), and the room's Activity (`CollaborationProvider`) has
 * both as they happen: its join, which names it and who asked it, and its
 * leave, which also says what it did. Each is kept as the server keeps it for
 * a later join's snapshot, so the dock's Activity list says the same either
 * way (`agentsInTheDock.test.tsx` reads those entries).
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
    getMe: () => Promise.resolve({ id: 7, username: "ana" }),
  },
}));
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => "project-1",
  subscribe: () => () => undefined,
}));

import { CollaborationProvider, useCollab } from "../../providers/CollaborationProvider";

type Handler = (payload?: any) => void;
interface FakeSocket {
  handlers: Record<string, Handler[]>;
  emits: Array<{ event: string; payload: any; ack?: (answer: any) => void }>;
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

// Ana's tab, the dataflow's owner, and the agents she asks.
const USERS = [{ user_id: 7, username: "ana", name: "Ana", participant_id: "p-ana", role: "owner" }];

/** An agent at work as the server names it, in its state's `user` and in its
 *  join's Activity (`agent_peers.Peer.user`). */
const DATAFLOW_BUILDER = {
  participant_id: "agent-db",
  user_id: null,
  name: "Dataflow Builder",
  agent: {
    attachmentId: "att-db",
    coord: "agent.curio.dataflow-builder@1",
    category: "canvas",
    askedBy: { account: "7", name: "Ana" },
  },
};
const NODE_BUILDER = {
  ...DATAFLOW_BUILDER,
  participant_id: "agent-nb",
  name: "Node Builder",
  agent: { ...DATAFLOW_BUILDER.agent, attachmentId: "att-nb", coord: "agent.curio.node-builder@1", category: "node" },
};
/** Its leave: the same, with what it did, by verb and thing. */
const DATAFLOW_BUILDER_LEFT = { ...DATAFLOW_BUILDER, did: { added: { node: 3, connection: 2 } } };

beforeEach(() => {
  sockets = [];
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
});

test("an agent's join and leave reach the room's Activity as they happen, as the server keeps them", async () => {
  const socket = await joined();
  joinAnswer(socket, { ok: true, participant_id: "p-ana", role: "owner", snapshot: { users: USERS, locks: {}, activity: [] } });

  fire(socket, "agent_joined", DATAFLOW_BUILDER);
  fire(socket, "agent_left", DATAFLOW_BUILDER_LEFT);

  expect(seen.activity.map(({ kind, payload }) => [kind, payload])).toEqual([
    ["agent_joined", DATAFLOW_BUILDER],
    ["agent_left", DATAFLOW_BUILDER_LEFT],
  ]);
  // An agent is in no list of the room's people.
  expect(seen.users).toEqual(USERS);
});

test("after a join's snapshot, an agent's events come after what it brought, each as the snapshot keeps them", async () => {
  const socket = await joined();
  // The snapshot holds the Node Builder's earlier join and leave.
  const brought = [
    { kind: "agent_joined", ts: 1, payload: NODE_BUILDER },
    { kind: "agent_left", ts: 2, payload: { ...NODE_BUILDER, did: { changed: { node: 1 } } } },
  ];
  joinAnswer(socket, { ok: true, participant_id: "p-ana", role: "owner", snapshot: { users: USERS, locks: {}, activity: brought } });

  fire(socket, "agent_joined", NODE_BUILDER);
  fire(socket, "agent_left", { ...NODE_BUILDER, did: { changed: { node: 1 } } });

  const kept = seen.activity.map(({ kind, payload }) => [kind, payload]);
  expect(kept).toEqual([
    ["agent_joined", NODE_BUILDER],
    ["agent_left", { ...NODE_BUILDER, did: { changed: { node: 1 } } }],
    ["agent_joined", NODE_BUILDER],
    ["agent_left", { ...NODE_BUILDER, did: { changed: { node: 1 } } }],
  ]);
  // What came live reads as what the snapshot brought.
  expect(kept.slice(2)).toEqual(kept.slice(0, 2));
});
