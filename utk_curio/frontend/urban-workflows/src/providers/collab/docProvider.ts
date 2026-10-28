/**
 * Curio's Yjs provider: one tab's doc of one dataflow, synced with the
 * server's over the socket.io connection the room already uses.
 *
 * The protocol is the server's (`collaboration/dataflow_docs.py`): y-protocols'
 * frames (sync 0, with step 1, step 2 and update 0 to 2; awareness 1) as bytes,
 * in the `message` of a `yjs` event, `{projectId, message}`.
 *
 * - Once the room has joined the tab, the tab sends sync step 1, naming the
 *   doc it holds. The server answers with step 2, with its own step 1 when the
 *   tab edits, and with everyone's awareness; the ack is `{ok, docId, role}`.
 *   A tab holding another doc than the server's is told `reload`, and starts
 *   again with an empty doc (`onReload`).
 * - The tab's own changes are sent once that ack is in, each as an update
 *   whose ack, `{ok, kept}`, says the server has it: `whenKept` waits for every
 *   one sent. Changes made before it are held and sent after it.
 * - A watcher's tab never sends a change: the server would drop it anyway.
 * - Awareness is the tab's presence (`y-protocols/awareness`): its own state is
 *   sent at every change and every renewal, everyone else's comes from the
 *   server, and a disconnect clears them.
 */
import * as Y from "yjs";
import * as decoding from "lib0/decoding";
import * as encoding from "lib0/encoding";
import * as syncProtocol from "y-protocols/sync";
import * as awarenessProtocol from "y-protocols/awareness";

import { DOC_EVENT } from "./docMapping";

/** The slice of a socket.io client socket the provider drives. */
export interface DocSocket {
    connected: boolean;
    emit(event: string, payload: unknown, ack?: (answer: any) => void): unknown;
    on(event: string, handler: (payload: any) => void): unknown;
    off(event: string, handler: (payload: any) => void): unknown;
}

/** What a sync's start was answered with. */
export interface SyncAck {
    ok: boolean;
    error?: string;
    docId?: string;
    role?: string;
}

export interface DocProviderOptions {
    /** Whether this tab's changes are sent: an owner's and an editor's are. */
    canWrite: boolean;
    /** The doc's id the tab last held, when it starts again on one. */
    docId?: string | null;
    /** The server holds another doc: start again with an empty one. */
    onReload?: (docId: string | null) => void;
    /** The server took this tab's changes no more (its role became a watcher's). */
    onReadOnly?: () => void;
    /** The first sync is done: the doc holds the server's. */
    onSynced?: () => void;
}

/** How long a wait for the server to keep this tab's changes may take. */
export const KEPT_WAIT_MS = 10000;
/** How long after a start that failed the tab asks again. */
const RETRY_MS = 1000;

const MESSAGE_SYNC = 0;
const MESSAGE_AWARENESS = 1;

function bytesOf(message: unknown): Uint8Array | null {
    if (message instanceof Uint8Array) return message;
    if (message instanceof ArrayBuffer) return new Uint8Array(message);
    if (ArrayBuffer.isView(message)) {
        const view = message as ArrayBufferView;
        return new Uint8Array(view.buffer, view.byteOffset, view.byteLength);
    }
    return null;
}

export class DataflowDocProvider {
    readonly doc: Y.Doc;
    readonly awareness: awarenessProtocol.Awareness;
    readonly projectId: string;
    readonly canWrite: boolean;
    /** The id of the doc the server holds, once a sync named it. */
    docId: string | null;
    /** True once the first sync's ack is in. */
    synced = false;

    private socket: DocSocket | null = null;
    private joined = false;
    private started = false;
    private destroyed = false;
    private held: Uint8Array[] = [];
    private inFlight = 0;
    private keptWaiters: Array<(kept: boolean) => void> = [];
    private retryTimer: ReturnType<typeof setTimeout> | null = null;
    private readonly options: DocProviderOptions;

    constructor(projectId: string, options: DocProviderOptions) {
        this.projectId = projectId;
        this.options = options;
        this.canWrite = options.canWrite;
        this.docId = options.docId ?? null;
        this.doc = new Y.Doc();
        this.awareness = new awarenessProtocol.Awareness(this.doc);
        this.doc.on("update", this.onDocUpdate);
        this.awareness.on("update", this.onAwarenessUpdate);
    }

    /** Take *socket*, whose room has joined this tab: start the sync on it. */
    attach(socket: DocSocket): void {
        if (this.destroyed) return;
        if (this.socket !== socket) {
            this.socket?.off(DOC_EVENT, this.onMessage);
            this.socket = socket;
            socket.on(DOC_EVENT, this.onMessage);
        }
        this.joined = true;
        this.start();
    }

    /** The socket dropped: nothing is sent until the room joins this tab again,
     *  and everyone else's presence goes. */
    detach(): void {
        this.joined = false;
        this.started = false;
        this.settleInFlight();
        const others = Array.from(this.awareness.getStates().keys()).filter((id) => id !== this.doc.clientID);
        if (others.length) awarenessProtocol.removeAwarenessStates(this.awareness, others, this);
    }

    destroy(): void {
        if (this.destroyed) return;
        this.destroyed = true;
        if (this.retryTimer) clearTimeout(this.retryTimer);
        this.socket?.off(DOC_EVENT, this.onMessage);
        this.doc.off("update", this.onDocUpdate);
        this.awareness.off("update", this.onAwarenessUpdate);
        this.awareness.destroy();
        this.settleInFlight();
        this.doc.destroy();
    }

    /** Resolves once the server has kept every change this tab sent, or after
     *  `KEPT_WAIT_MS`. Whether it was kept. */
    whenKept(timeoutMs: number = KEPT_WAIT_MS): Promise<boolean> {
        if (!this.canWrite || this.destroyed) return Promise.resolve(true);
        if (this.isKept()) return Promise.resolve(true);
        return new Promise<boolean>((resolve) => {
            let done = false;
            const timer = setTimeout(() => {
                if (done) return;
                done = true;
                resolve(false);
            }, timeoutMs);
            this.keptWaiters.push((kept) => {
                if (done) return;
                done = true;
                clearTimeout(timer);
                resolve(kept);
            });
        });
    }

    /** Whether every change this tab made is with the server. */
    isKept(): boolean {
        return this.synced && this.inFlight === 0 && this.held.length === 0;
    }

    private start(): void {
        const socket = this.socket;
        if (!socket || !this.joined || this.started || this.destroyed) return;
        this.started = true;
        const encoder = encoding.createEncoder();
        encoding.writeVarUint(encoder, MESSAGE_SYNC);
        syncProtocol.writeSyncStep1(encoder, this.doc);
        const payload: Record<string, unknown> = {
            projectId: this.projectId,
            message: encoding.toUint8Array(encoder),
        };
        if (this.docId) payload.docId = this.docId;
        socket.emit(DOC_EVENT, payload, (ack: SyncAck) => this.onStarted(socket, ack));
    }

    private onStarted(socket: DocSocket, ack: SyncAck): void {
        if (this.destroyed || socket !== this.socket) return;
        if (ack && ack.ok) {
            const first = !this.synced;
            this.docId = ack.docId ?? this.docId;
            this.synced = true;
            this.sendHeld();
            this.sendAwareness();
            if (first) this.options.onSynced?.();
            this.notifyKept();
            return;
        }
        this.started = false;
        if (ack && ack.error === "reload") {
            this.options.onReload?.(ack.docId ?? null);
            return;
        }
        // The server could not open the doc now (a dataflow being written, a
        // join that has not landed): ask again in a moment.
        if (this.retryTimer) clearTimeout(this.retryTimer);
        this.retryTimer = setTimeout(() => {
            this.retryTimer = null;
            this.start();
        }, RETRY_MS);
    }

    private onMessage = (payload: any): void => {
        if (this.destroyed || !payload || payload.projectId !== this.projectId) return;
        const bytes = bytesOf(payload.message);
        if (!bytes || bytes.length === 0) return;
        const decoder = decoding.createDecoder(bytes);
        const kind = decoding.readVarUint(decoder);
        if (kind === MESSAGE_SYNC) {
            const encoder = encoding.createEncoder();
            encoding.writeVarUint(encoder, MESSAGE_SYNC);
            const step = syncProtocol.readSyncMessage(decoder, encoder, this.doc, this);
            // The server's step 1: what it lacks of this tab's changes.
            if (step === syncProtocol.messageYjsSyncStep1 && this.canWrite && encoding.length(encoder) > 1) {
                this.send(encoding.toUint8Array(encoder));
            }
        } else if (kind === MESSAGE_AWARENESS) {
            awarenessProtocol.applyAwarenessUpdate(this.awareness, decoding.readVarUint8Array(decoder), this);
        }
    };

    private onDocUpdate = (update: Uint8Array, origin: unknown): void => {
        if (this.destroyed || origin === this || !this.canWrite) return;
        if (!this.synced || !this.joined || !this.socket?.connected) {
            this.held.push(update);
            return;
        }
        this.sendUpdate(update);
    };

    private onAwarenessUpdate = (
        { added, updated, removed }: { added: number[]; updated: number[]; removed: number[] },
        origin: unknown,
    ): void => {
        if (origin === this) return;
        const own = this.doc.clientID;
        if ([...added, ...updated, ...removed].includes(own)) this.sendAwareness();
    };

    private sendHeld(): void {
        if (!this.held.length) return;
        const held = this.held;
        this.held = [];
        this.sendUpdate(Y.mergeUpdates(held));
    }

    private sendUpdate(update: Uint8Array): void {
        const encoder = encoding.createEncoder();
        encoding.writeVarUint(encoder, MESSAGE_SYNC);
        syncProtocol.writeUpdate(encoder, update);
        this.send(encoding.toUint8Array(encoder));
    }

    private send(message: Uint8Array): void {
        const socket = this.socket;
        if (!socket) return;
        this.inFlight += 1;
        let answered = false;
        socket.emit(DOC_EVENT, { projectId: this.projectId, message }, (ack: SyncAck) => {
            if (answered) return;
            answered = true;
            this.inFlight = Math.max(0, this.inFlight - 1);
            if (this.destroyed) return;
            if (ack && !ack.ok) {
                if (ack.error === "read_only") {
                    this.options.onReadOnly?.();
                } else if (ack.error === "not_synced" && socket === this.socket) {
                    // The server lost this tab's sync (a backend that restarted):
                    // a new one carries what this change brought.
                    this.started = false;
                    this.start();
                }
            }
            this.notifyKept();
        });
    }

    private sendAwareness(): void {
        const socket = this.socket;
        if (!socket || !this.synced || !this.joined || this.destroyed) return;
        const update = awarenessProtocol.encodeAwarenessUpdate(this.awareness, [this.doc.clientID]);
        const encoder = encoding.createEncoder();
        encoding.writeVarUint(encoder, MESSAGE_AWARENESS);
        encoding.writeVarUint8Array(encoder, update);
        socket.emit(DOC_EVENT, { projectId: this.projectId, message: encoding.toUint8Array(encoder) });
    }

    /** A dropped socket answers none of what it carried: those waits end. */
    private settleInFlight(): void {
        this.inFlight = 0;
        this.notifyKept(false);
    }

    /** End the waits for the server to keep this tab's changes: with *kept*
     *  false, whatever the tab holds; else once it holds nothing unkept. */
    private notifyKept(kept = true): void {
        if (kept && !this.isKept()) return;
        const waiters = this.keptWaiters;
        this.keptWaiters = [];
        for (const waiter of waiters) waiter(kept);
    }
}
