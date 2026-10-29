/**
 * Leaving a dataflow keeps the change its tab made a moment before
 * (`CollaborationProvider`'s `retire`): the browser's Back, a link that asked
 * nothing, any way out of the canvas. The tab's socket stays open, listening
 * for nothing but the doc's answers, until the server has every change sent
 * on it, since the server refuses a queued change whose socket has gone. The
 * tab leaves everyone else's view at once all the same: its presence and its
 * locks go at the leave. A socket with nothing on its way closes at once.
 */
import React from "react";
import { act, render, waitFor } from "@testing-library/react";
import * as decoding from "lib0/decoding";

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
// The dataflow the route names, which a test moves away from.
let mockProjectId: string | undefined = "project-1";
const mockProjectListeners = new Set<() => void>();
jest.mock("../../registry/projectPackagesStore", () => ({
  getCurrentProjectId: () => mockProjectId,
  subscribe: (listener: () => void) => {
    mockProjectListeners.add(listener);
    return () => mockProjectListeners.delete(listener);
  },
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
  disconnect: jest.Mock;
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
    removeAllListeners: jest.fn(() => {
      for (const event of Object.keys(handlers)) delete handlers[event];
    }),
    disconnect: jest.fn(() => {
      fake.connected = false;
    }),
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
  mockProjectId = "project-1";
  mockProjectListeners.clear();
  mockIo.mockReset();
  mockIo.mockImplementation(() => {
    const socket = fakeSocket();
    sockets.push(socket);
    return socket;
  });
});

/** The owner's tab of project-1, its doc synced with the server's. */
async function ownersTab(): Promise<FakeSocket> {
  render(
    <CollaborationProvider>
      <Probe />
    </CollaborationProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  await waitFor(() => expect(sockets).toHaveLength(1));
  const socket = sockets[0];
  socket.fire("connect");
  const join = socket.sent.find((sent) => sent.event === "join_session");
  const users = [{ user_id: 7, username: "ana", participant_id: "p-1", role: "owner" }];
  act(() => join!.ack!({ ok: true, participant_id: "p-1", role: "owner", snapshot: { users, locks: {}, activity: [] } }));
  const start = socket.sent.find((sent) => sent.event === "yjs");
  act(() => start!.ack!({ ok: true, docId: "doc-1", role: "owner" }));
  await waitFor(() => expect(binding?.synced).toBe(true));
  return socket;
}

/** A change from this tab's canvas, which goes to the server at once. */
function renameOnCanvas() {
  const doc = binding!.provider.doc;
  act(() => {
    doc.transact(() => doc.getMap("dataflow").set("name", JSON.stringify("Renamed")), CANVAS_ORIGIN);
  });
}

/** The doc's updates *socket* carried: y-protocols sync updates, not presence. */
function updatesOn(socket: FakeSocket): Sent[] {
  return socket.sent.filter((sent) => {
    const bytes: Uint8Array | undefined = sent.payload?.message;
    return sent.event === "yjs" && !!bytes && bytes[0] === 0 && bytes[1] === 2;
  });
}

/** The presence messages *socket* carried. */
function presenceOn(socket: FakeSocket): Sent[] {
  return socket.sent.filter((sent) => {
    const bytes: Uint8Array | undefined = sent.payload?.message;
    return sent.event === "yjs" && !!bytes && bytes[0] === 1;
  });
}

/** Each client's state a presence message carries: null for one that left. */
function statesIn(sent: Sent): Map<number, unknown> {
  const decoder = decoding.createDecoder(sent.payload.message);
  decoding.readVarUint(decoder);
  const update = decoding.createDecoder(decoding.readVarUint8Array(decoder));
  const states = new Map<number, unknown>();
  for (let count = decoding.readVarUint(update); count > 0; count -= 1) {
    const client = decoding.readVarUint(update);
    decoding.readVarUint(update);
    states.set(client, JSON.parse(decoding.readVarString(update)));
  }
  return states;
}

/** The route leaves the dataflow, as the browser's Back does. */
function leaveTheDataflow() {
  act(() => {
    mockProjectId = undefined;
    for (const listener of mockProjectListeners) listener();
  });
}

test("a tab that leaves right after a change keeps its socket until the server has the change", async () => {
  const socket = await ownersTab();
  const client = binding!.provider.doc.clientID;
  renameOnCanvas();
  const [update] = updatesOn(socket);
  expect(update).toBeDefined();
  const presenceBefore = presenceOn(socket).length;

  leaveTheDataflow();

  // The canvas has left the doc, but the change is still on its way.
  expect(binding).toBeNull();
  expect(socket.disconnect).not.toHaveBeenCalled();
  // Everyone else sees the tab leave at once: its presence goes now.
  const gone = presenceOn(socket).slice(presenceBefore);
  expect(gone.length).toBeGreaterThan(0);
  expect(statesIn(gone[gone.length - 1]).get(client)).toBeNull();

  await act(async () => {
    update.ack!({ ok: true, kept: {} });
    await Promise.resolve();
  });
  await waitFor(() => expect(socket.disconnect).toHaveBeenCalledTimes(1));
});

test("a change the server queued is waited for until its kept message answers it", async () => {
  const socket = await ownersTab();
  renameOnCanvas();
  const [update] = updatesOn(socket);
  act(() => update.ack!({ ok: true, queued: true }));

  leaveTheDataflow();
  expect(socket.disconnect).not.toHaveBeenCalled();

  // The doc's answers are still heard on the socket the room has left.
  socket.fire("yjs_kept", { projectId: "project-1", answered: 1, kept: {} });
  await waitFor(() => expect(socket.disconnect).toHaveBeenCalledTimes(1));
});

test("the locks this tab holds go at the leave, though its socket waits for the doc's answers", async () => {
  const socket = await ownersTab();
  socket.fire("node_locked", { nodeId: "n1", lock: { user_id: 7, username: "ana", participant_id: "p-1", since: 1 } });
  socket.fire("node_locked", { nodeId: "n2", lock: { user_id: 8, username: "bo", participant_id: "p-2", since: 1 } });
  renameOnCanvas();

  leaveTheDataflow();

  expect(socket.disconnect).not.toHaveBeenCalled();
  const released = socket.sent.filter((sent) => sent.event === "node_unlock").map((sent) => sent.payload.nodeId);
  expect(released).toEqual(["n1"]);
});

test("a tab with nothing on its way closes its socket at once", async () => {
  const socket = await ownersTab();
  renameOnCanvas();
  const [update] = updatesOn(socket);
  act(() => update.ack!({ ok: true, kept: {} }));

  leaveTheDataflow();

  expect(socket.disconnect).toHaveBeenCalledTimes(1);
});
