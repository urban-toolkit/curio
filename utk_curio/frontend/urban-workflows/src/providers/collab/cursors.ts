/**
 * Everyone's pointer on the canvas, through the doc's awareness
 * (`presence.ts`): each tab's state holds `cursor`, `{x, y, t}`, where `x` and
 * `y` are the point of the dataflow the pointer is on, in React Flow's flow
 * coordinates, and `t` is when it was sent, in milliseconds since the epoch.
 * It is `null` while the pointer is off the canvas.
 *
 * - **Sending** (`CursorSender`): at most once every `CURSOR_EVERY_MS`, about
 *   20 times a second, and only when the pointer's point of the dataflow
 *   changed: it moved, or the view moved under it. The point it ends on is
 *   always sent. Leaving the canvas clears it at once.
 * - **Drawing** (`CursorTracker`, then `ParticipantCursors`): everyone else's,
 *   each faded once it has not moved for `CURSOR_IDLE_MS`. The time is this
 *   tab's, from when the move arrived: another machine's clock can be off by
 *   minutes.
 */
import { colorOf, nameOf, type CursorPoint, type PresenceState } from "./presence";

export type { CursorPoint } from "./presence";

/** The awareness field. */
export const CURSOR_FIELD = "cursor";
/** The shortest time between two of a tab's cursor messages. */
export const CURSOR_EVERY_MS = 50;
/** How long a cursor rests before it fades. */
export const CURSOR_IDLE_MS = 5000;

export interface Point {
    x: number;
    y: number;
}

/** React Flow's view: its x and y translation and its zoom. */
export type ViewTransform = readonly [number, number, number];

/** The point of the dataflow under a pointer at *client* (window
 *  coordinates), on a canvas whose box starts at *box* and shows *view*: what
 *  React Flow's `screenToFlowPosition` gives. */
export function flowPointOf(client: Point, box: Point, view: ViewTransform): Point {
    const [x, y, zoom] = view;
    return { x: (client.x - box.x - x) / zoom, y: (client.y - box.y - y) / zoom };
}

function finite(value: unknown): value is number {
    return typeof value === "number" && Number.isFinite(value);
}

/** The cursor a state holds, or null when it holds none, or nothing a cursor
 *  can be: a state comes from another tab. */
export function cursorOf(state: PresenceState | null | undefined): CursorPoint | null {
    const cursor = state?.cursor as Partial<CursorPoint> | null | undefined;
    if (!cursor || typeof cursor !== "object" || !finite(cursor.x) || !finite(cursor.y)) return null;
    return { x: cursor.x, y: cursor.y, t: finite(cursor.t) ? cursor.t : 0 };
}

/** A tenth of a flow unit: a fifth of a pixel at React Flow's largest zoom. */
function rounded(value: number): number {
    return Math.round(value * 10) / 10;
}

/** The slice of an awareness the sender writes. */
export interface CursorAwareness {
    getLocalState(): { [field: string]: unknown } | null;
    setLocalStateField(field: string, value: unknown): void;
}

/**
 * Puts one tab's pointer into its awareness. *where* says where it is on the
 * dataflow now, or null when that cannot be told; it is asked only when a
 * message is about to go, so a burst of moves costs one reading.
 */
export class CursorSender {
    private timer: ReturnType<typeof setTimeout> | null = null;
    private sentAt = -Infinity;
    private sent: Point | null = null;
    private stopped = false;

    constructor(
        private readonly awareness: CursorAwareness,
        private readonly where: () => Point | null,
        private readonly everyMs: number = CURSOR_EVERY_MS,
    ) {}

    /** The pointer moved on the canvas, or the view moved under it. */
    moved(): void {
        if (this.stopped || this.timer) return;
        const wait = this.sentAt + this.everyMs - Date.now();
        if (wait <= 0) {
            this.send();
            return;
        }
        this.timer = setTimeout(() => {
            this.timer = null;
            this.send();
        }, wait);
    }

    /** The pointer left the canvas: the others stop drawing it now. */
    left(): void {
        this.cancel();
        this.sent = null;
        if ((this.awareness.getLocalState()?.[CURSOR_FIELD] ?? null) === null) return;
        this.sentAt = Date.now();
        this.awareness.setLocalStateField(CURSOR_FIELD, null);
    }

    /** Nothing more is sent, and the cursor goes. */
    stop(): void {
        this.left();
        this.stopped = true;
    }

    private cancel(): void {
        if (this.timer) clearTimeout(this.timer);
        this.timer = null;
    }

    private send(): void {
        if (this.stopped) return;
        const at = this.where();
        if (!at || !finite(at.x) || !finite(at.y)) return;
        const point = { x: rounded(at.x), y: rounded(at.y) };
        if (this.sent && this.sent.x === point.x && this.sent.y === point.y) return;
        this.sent = point;
        this.sentAt = Date.now();
        this.awareness.setLocalStateField(CURSOR_FIELD, { x: point.x, y: point.y, t: this.sentAt });
    }
}

/** A cursor as this tab draws it. */
export interface DrawnCursor {
    /** The awareness client whose cursor it is. */
    clientId: number;
    x: number;
    y: number;
    name: string;
    color: string;
    /** It has not moved for `CURSOR_IDLE_MS`: drawn faded. */
    idle: boolean;
}

/** Everyone else's cursors, from their awareness states, and when each last
 *  moved by this tab's clock. */
export class CursorTracker {
    private readonly seen = new Map<number, CursorPoint & { movedAt: number }>();

    /** The cursors *others* hold at *now*, in client order. */
    read(others: ReadonlyArray<readonly [number, PresenceState]>, now: number): DrawnCursor[] {
        const drawn: DrawnCursor[] = [];
        const held = new Set<number>();
        for (const [clientId, state] of others) {
            const cursor = cursorOf(state);
            if (!cursor) continue;
            held.add(clientId);
            const last = this.seen.get(clientId);
            const same = !!last && last.x === cursor.x && last.y === cursor.y && last.t === cursor.t;
            const movedAt = same ? last!.movedAt : now;
            this.seen.set(clientId, { ...cursor, movedAt });
            drawn.push({
                clientId,
                x: cursor.x,
                y: cursor.y,
                name: nameOf(state),
                color: colorOf(clientId, state),
                idle: now - movedAt >= CURSOR_IDLE_MS,
            });
        }
        for (const clientId of Array.from(this.seen.keys())) {
            if (!held.has(clientId)) this.seen.delete(clientId);
        }
        return drawn.sort((a, b) => a.clientId - b.clientId);
    }

    /** When the next cursor that still moves fades, or null if none will. */
    nextFadeAt(now: number): number | null {
        let next: number | null = null;
        for (const { movedAt } of this.seen.values()) {
            const at = movedAt + CURSOR_IDLE_MS;
            if (at > now && (next === null || at < next)) next = at;
        }
        return next;
    }
}

/** Whether two lists of drawn cursors draw the same. */
export function sameCursors(a: readonly DrawnCursor[], b: readonly DrawnCursor[]): boolean {
    if (a.length !== b.length) return false;
    return a.every((cursor, i) => {
        const other = b[i];
        return cursor.clientId === other.clientId && cursor.x === other.x && cursor.y === other.y
            && cursor.name === other.name && cursor.color === other.color && cursor.idle === other.idle;
    });
}
