/**
 * Curio's Yjs provider on the room's socket (`providers/collab/docProvider.ts`),
 * against a server that speaks as `collaboration/dataflow_docs.py` does: the
 * same `yjs` event and y-protocols frames, its answers played here.
 */
import * as Y from "yjs";
import * as decoding from "lib0/decoding";
import * as encoding from "lib0/encoding";
import * as syncProtocol from "y-protocols/sync";
import * as awarenessProtocol from "y-protocols/awareness";

import { DataflowDocProvider } from "../../../providers/collab/docProvider";
import { dataflowToDoc, docToDataflow } from "../../../providers/collab/docMapping";

const PROJECT = "3fd026a7-ef31-4fb6-ac24-2d1b099ff7cf";

interface Sent {
    event: string;
    payload: any;
    ack?: (answer: any) => void;
}

class FakeSocket {
    connected = true;
    sent: Sent[] = [];
    private handlers: Record<string, Array<(payload: any) => void>> = {};

    on(event: string, handler: (payload: any) => void) {
        (this.handlers[event] ??= []).push(handler);
    }

    off(event: string, handler: (payload: any) => void) {
        this.handlers[event] = (this.handlers[event] ?? []).filter((h) => h !== handler);
    }

    emit(event: string, payload: any, ack?: (answer: any) => void) {
        this.sent.push({ event, payload, ack });
    }

    /** A message the server sends this socket. */
    receive(message: Uint8Array) {
        // socket.io-client hands a binary attachment over as an ArrayBuffer.
        for (const handler of this.handlers.yjs ?? []) handler({ projectId: PROJECT, message: message.slice().buffer });
    }

    /** What this socket sent of the doc's protocol. */
    messages(): Sent[] {
        return this.sent.filter((sent) => sent.event === "yjs");
    }
}

/** What kind of y-protocols frame *sent* carries: "step1", "step2", "update"
 *  or "awareness". */
function kindOf(sent: Sent): string {
    const bytes: Uint8Array = sent.payload.message;
    if (bytes[0] === 1) return "awareness";
    return ["step1", "step2", "update"][bytes[1]];
}

/** The server's side of a doc, as `dataflow_docs.py` answers a tab. */
class FakeServer {
    doc = new Y.Doc();

    constructor(dataflow: any) {
        dataflowToDoc(dataflow, this.doc, "doc-1");
    }

    /** Answer the tab's step 1: step 2, the server's own step 1, then the ack. */
    start(socket: FakeSocket, sent: Sent, { asEditor = true, ack = { ok: true, docId: "doc-1" } } = {}) {
        const decoder = decoding.createDecoder(sent.payload.message);
        decoding.readVarUint(decoder);
        const reply = encoding.createEncoder();
        encoding.writeVarUint(reply, 0);
        syncProtocol.readSyncMessage(decoder, reply, this.doc, "tab");
        socket.receive(encoding.toUint8Array(reply));
        if (asEditor) {
            const step1 = encoding.createEncoder();
            encoding.writeVarUint(step1, 0);
            syncProtocol.writeSyncStep1(step1, this.doc);
            socket.receive(encoding.toUint8Array(step1));
        }
        sent.ack?.(ack);
    }

    /** Apply a tab's step 2 or update, as an owner's or an editor's is. */
    take(sent: Sent, ack: any = { ok: true, kept: {} }) {
        const decoder = decoding.createDecoder(sent.payload.message);
        decoding.readVarUint(decoder);
        syncProtocol.readSyncMessage(decoder, encoding.createEncoder(), this.doc, "tab");
        sent.ack?.(ack);
    }

    /** Relay a change someone else made to the server's doc. */
    relay(socket: FakeSocket, change: (doc: Y.Doc) => void) {
        const updates: Uint8Array[] = [];
        const keep = (update: Uint8Array) => updates.push(update);
        this.doc.on("update", keep);
        this.doc.transact(() => change(this.doc));
        this.doc.off("update", keep);
        for (const update of updates) {
            const encoder = encoding.createEncoder();
            encoding.writeVarUint(encoder, 0);
            syncProtocol.writeUpdate(encoder, update);
            socket.receive(encoding.toUint8Array(encoder));
        }
    }
}

const DATAFLOW = {
    nodes: [{ id: "loader", type: "curio.builtin/code", x: 0, y: 0, content: "x = 1\n" }],
    edges: [],
    name: "Shared",
};

function typeInto(doc: Y.Doc, text: string) {
    const node = doc.getMap("nodes").get("loader") as Y.Map<any>;
    (node.get("content") as Y.Text).insert(0, text);
}

test("a tab starts with sync step 1, naming the doc it held", () => {
    const socket = new FakeSocket();
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true, docId: "doc-0" });
    provider.attach(socket);

    const [first] = socket.messages();
    expect(kindOf(first)).toBe("step1");
    expect(first.payload.projectId).toBe(PROJECT);
    expect(first.payload.docId).toBe("doc-0");
});

test("it takes the server's doc, answers the server's step 1, and is synced once the start is answered", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const onSynced = jest.fn();
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true, onSynced });
    provider.attach(socket);

    server.start(socket, socket.messages()[0]);

    expect(docToDataflow(provider.doc).nodes[0].content).toBe("x = 1\n");
    expect(socket.messages().map(kindOf)).toContain("step2");
    expect(onSynced).toHaveBeenCalledTimes(1);
    expect(provider.synced).toBe(true);
    expect(provider.docId).toBe("doc-1");
});

test("a change made before the start is answered waits for it, then reaches the server", async () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    provider.attach(socket);
    // The server's doc comes first: the tab's change lands on it.
    const decoder = decoding.createDecoder(socket.messages()[0].payload.message);
    decoding.readVarUint(decoder);
    const reply = encoding.createEncoder();
    encoding.writeVarUint(reply, 0);
    syncProtocol.readSyncMessage(decoder, reply, server.doc, "tab");
    socket.receive(encoding.toUint8Array(reply));

    typeInto(provider.doc, "# early\n");
    expect(socket.messages().filter((m) => kindOf(m) === "update")).toEqual([]);

    socket.messages()[0].ack?.({ ok: true, docId: "doc-1" });
    const updates = socket.messages().filter((m) => kindOf(m) === "update");
    expect(updates).toHaveLength(1);
    const kept = provider.whenKept(1000);
    expect(provider.isKept()).toBe(false);
    server.take(updates[0]);
    await expect(kept).resolves.toBe(true);
    expect(docToDataflow(server.doc).nodes[0].content).toBe("# early\nx = 1\n");
});

test("each change after the sync goes as it is made, and the server's reach the tab", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    provider.attach(socket);
    server.start(socket, socket.messages()[0]);

    typeInto(provider.doc, "# mine\n");
    const updates = socket.messages().filter((m) => kindOf(m) === "update");
    expect(updates).toHaveLength(1);
    server.take(updates[0]);
    server.relay(socket, (doc) => typeInto(doc, "# theirs\n"));

    expect(docToDataflow(provider.doc).nodes[0].content).toBe(docToDataflow(server.doc).nodes[0].content);
    // The server's change came back through no update of the tab's own.
    expect(socket.messages().filter((m) => kindOf(m) === "update")).toHaveLength(1);
});

test("a watcher never sends a change, nor answers the server's step 1", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: false });
    provider.attach(socket);
    server.start(socket, socket.messages()[0], { asEditor: true, ack: { ok: true, docId: "doc-1", role: "watcher" } as any });

    typeInto(provider.doc, "# watched\n");

    expect(socket.messages().map(kindOf).filter((kind) => kind === "update" || kind === "step2")).toEqual([]);
    expect(docToDataflow(provider.doc).nodes[0].content).toBe("# watched\nx = 1\n");
    expect(docToDataflow(server.doc).nodes[0].content).toBe("x = 1\n");
});

test("a doc the server built anew starts the tab again", () => {
    const socket = new FakeSocket();
    const onReload = jest.fn();
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true, docId: "doc-0", onReload });
    provider.attach(socket);

    socket.messages()[0].ack?.({ ok: false, error: "reload", docId: "doc-2" });

    expect(onReload).toHaveBeenCalledWith("doc-2");
    expect(provider.synced).toBe(false);
});

test("a change the server refuses as a watcher's turns the tab into a watcher", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const onReadOnly = jest.fn();
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true, onReadOnly });
    provider.attach(socket);
    server.start(socket, socket.messages()[0]);

    typeInto(provider.doc, "# refused\n");
    const [update] = socket.messages().filter((m) => kindOf(m) === "update");
    update.ack?.({ ok: false, error: "read_only" });

    expect(onReadOnly).toHaveBeenCalledTimes(1);
});

test("this tab's presence goes once synced, everyone else's arrives, and a disconnect clears it", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    provider.attach(socket);
    provider.awareness.setLocalStateField("editing", "loader");
    expect(socket.messages().map(kindOf)).not.toContain("awareness");

    server.start(socket, socket.messages()[0]);
    const sentPresence = socket.messages().filter((m) => kindOf(m) === "awareness");
    expect(sentPresence.length).toBeGreaterThan(0);

    const other = new awarenessProtocol.Awareness(new Y.Doc());
    other.setLocalState({ editing: "loader", user: { name: "Ana" } });
    const encoder = encoding.createEncoder();
    encoding.writeVarUint(encoder, 1);
    encoding.writeVarUint8Array(encoder, awarenessProtocol.encodeAwarenessUpdate(other, [other.clientID]));
    socket.receive(encoding.toUint8Array(encoder));
    expect((provider.awareness.getStates().get(other.clientID) as any)?.user?.name).toBe("Ana");

    provider.detach();
    expect(provider.awareness.getStates().has(other.clientID)).toBe(false);
    other.destroy();
    provider.destroy();
});

/** Hands the others what *socket* sent of its presence from the *from*-th
 *  message on, as the server relays it. */
function relayPresence(socket: FakeSocket, others: awarenessProtocol.Awareness, from = 0) {
    for (const sent of socket.messages().slice(from).filter((m) => kindOf(m) === "awareness")) {
        const decoder = decoding.createDecoder(sent.payload.message);
        decoding.readVarUint(decoder);
        awarenessProtocol.applyAwarenessUpdate(others, decoding.readVarUint8Array(decoder), "server");
    }
}

test("a provider that goes while its socket stays takes its presence, its cursor among it, from the others", () => {
    // A doc started again on the same socket (a reload, a new role) is a new
    // client: the old one's pointer would otherwise stay drawn, frozen.
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    provider.attach(socket);
    server.start(socket, socket.messages()[0]);
    provider.awareness.setLocalStateField("cursor", { x: 1, y: 2, t: 3 });
    const others = new awarenessProtocol.Awareness(new Y.Doc());
    relayPresence(socket, others);
    const clientId = provider.doc.clientID;
    expect((others.getStates().get(clientId) as any)?.cursor).toEqual({ x: 1, y: 2, t: 3 });

    const before = socket.messages().length;
    provider.destroy();
    relayPresence(socket, others, before);
    expect(others.getStates().has(clientId)).toBe(false);
    others.destroy();
});

test("a provider whose socket went sends nothing as it goes", () => {
    const socket = new FakeSocket();
    const server = new FakeServer(DATAFLOW);
    const provider = new DataflowDocProvider(PROJECT, { canWrite: true });
    provider.attach(socket);
    server.start(socket, socket.messages()[0]);
    socket.connected = false;
    const before = socket.messages().length;
    provider.destroy();
    expect(socket.messages().length).toBe(before);
});
