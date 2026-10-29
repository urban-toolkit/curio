/**
 * Each tab's pointer on the canvas, as its awareness carries it, `pointer`
 * (`providers/collab/cursors.ts`): read in flow coordinates, sent about 20
 * times a second at most and only when it moved on the dataflow, its last
 * place always sent, cleared at once when it leaves; and everyone else's,
 * drawn in their color with their name, faded once it rests.
 */
import * as Y from "yjs";
import { Awareness } from "y-protocols/awareness";

import {
    CURSOR_EVERY_MS,
    CURSOR_IDLE_MS,
    CursorSender,
    CursorTracker,
    flowPointOf,
    pointerOf,
    type Point,
} from "../../../providers/collab/cursors";
import { participantColor, personColor, type PresenceState } from "../../../providers/collab/presence";

const NOW = 1_700_000_000_000;

let awareness: Awareness;

beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    awareness = new Awareness(new Y.Doc());
});

afterEach(() => {
    awareness.destroy();
    jest.useRealTimers();
});

/** What the sender put into the awareness as `pointer`, in order. */
function watchPointer(): unknown[] {
    const sent: unknown[] = [];
    const set = awareness.setLocalStateField.bind(awareness);
    jest.spyOn(awareness, "setLocalStateField").mockImplementation((field: string, value: unknown) => {
        if (field === "pointer") sent.push(value);
        set(field, value);
    });
    return sent;
}

const sentPointer = () => (awareness.getLocalState() as PresenceState).pointer;

describe("where a pointer is on the dataflow", () => {
    test("is the point React Flow's view draws under it, however the view is panned or zoomed", () => {
        const box = { x: 60, y: 48 };
        // Zoom 2, the plane moved by (100, 50): the flow point (100, 100) is
        // drawn at the canvas's corner plus (100 + 200, 50 + 200).
        expect(flowPointOf({ x: 360, y: 298 }, box, [100, 50, 2])).toEqual({ x: 100, y: 100 });
        // Panned and zoomed out, the same point of the dataflow is drawn
        // elsewhere, and read as the same point.
        const view = [-40, 30, 0.5] as const;
        const drawn = { x: box.x + view[0] + 100 * view[2], y: box.y + view[1] + 100 * view[2] };
        expect(flowPointOf(drawn, box, view)).toEqual({ x: 100, y: 100 });
    });
});

describe("a tab's pointer", () => {
    test("goes at once, then at most once every 50 ms while it moves: about 20 a second, the last place included", () => {
        const sent = watchPointer() as Array<{ x: number; y: number; t: number }>;
        let at: Point = { x: 0, y: 0 };
        const sender = new CursorSender(awareness, () => at);
        // A second of moves from a 250 Hz mouse.
        for (let i = 1; i <= 250; i += 1) {
            at = { x: i, y: 2 * i };
            sender.moved();
            jest.advanceTimersByTime(4);
        }
        jest.advanceTimersByTime(CURSOR_EVERY_MS);

        expect(sent.length).toBeGreaterThanOrEqual(20);
        expect(sent.length).toBeLessThanOrEqual(21);
        expect(sent[0]).toEqual({ x: 1, y: 2, t: NOW });
        for (let i = 1; i < sent.length; i += 1) {
            expect(sent[i].t - sent[i - 1].t).toBeGreaterThanOrEqual(CURSOR_EVERY_MS);
        }
        expect(sent[sent.length - 1]).toMatchObject({ x: 250, y: 500 });
        expect(sentPointer()).toMatchObject({ x: 250, y: 500 });
    });

    test("sends nothing while it rests on one point of the dataflow", () => {
        const sent = watchPointer();
        let at: Point = { x: 12, y: 34 };
        const sender = new CursorSender(awareness, () => at);
        sender.moved();
        expect(sent).toHaveLength(1);
        // Moves that leave it on the same point, to a tenth of a flow unit (a
        // pan drags the view along with the pointer), then nothing for a while.
        for (let i = 0; i < 20; i += 1) {
            at = { x: 12 + (i % 2) * 0.01, y: 34 - (i % 2) * 0.02 };
            sender.moved();
            jest.advanceTimersByTime(CURSOR_EVERY_MS);
        }
        jest.advanceTimersByTime(10_000);
        expect(sent).toHaveLength(1);
    });

    test("is sent to a tenth of a flow unit, with the time it went", () => {
        const sent = watchPointer();
        const sender = new CursorSender(awareness, () => ({ x: 10.04, y: -3.06 }));
        sender.moved();
        expect(sent).toEqual([{ x: 10, y: -3.1, t: NOW }]);
    });

    test("leaving the canvas clears it at once, and a place still on its way never lands", () => {
        const sent = watchPointer();
        let at: Point = { x: 1, y: 1 };
        const sender = new CursorSender(awareness, () => at);
        sender.moved();
        jest.advanceTimersByTime(10);
        at = { x: 2, y: 2 };
        sender.moved(); // held for the rest of the 50 ms
        sender.left();
        expect(sentPointer()).toBeNull();
        jest.advanceTimersByTime(CURSOR_EVERY_MS * 4);
        expect(sentPointer()).toBeNull();
        // One message to clear it, and none for a pointer already off.
        sender.left();
        expect(sent).toEqual([{ x: 1, y: 1, t: NOW }, null]);
    });

    test("a pointer that comes back after leaving is sent again, even on the point it left from", () => {
        const sent = watchPointer();
        const sender = new CursorSender(awareness, () => ({ x: 5, y: 5 }));
        sender.moved();
        sender.left();
        jest.advanceTimersByTime(CURSOR_EVERY_MS);
        sender.moved();
        expect(sent).toEqual([
            { x: 5, y: 5, t: NOW },
            null,
            { x: 5, y: 5, t: NOW + CURSOR_EVERY_MS },
        ]);
    });

    test("a stopped sender clears the pointer and sends no more", () => {
        const sent = watchPointer();
        let at: Point = { x: 1, y: 1 };
        const sender = new CursorSender(awareness, () => at);
        sender.moved();
        sender.stop();
        at = { x: 9, y: 9 };
        sender.moved();
        jest.advanceTimersByTime(CURSOR_EVERY_MS * 4);
        expect(sent).toEqual([{ x: 1, y: 1, t: NOW }, null]);
    });
});

describe("a person's color", () => {
    test("comes from their account: the same in two of their tabs, and after a reload or a reconnect", () => {
        // Each tab, and each reconnect, is a new participant with a new id.
        const before = personColor({ username: "ana", user_id: 3, participant_id: "0f1e2d3c" });
        const after = personColor({ username: "ana", user_id: 3, participant_id: "9a8b7c6d" });
        expect(after).toBe(before);
        expect(before).toBe(participantColor("ana"));
        // The room's list of people names accounts the same way: chips and cursors agree.
        expect(personColor({ username: "ana", user_id: 3, name: "Ana", role: "editor" })).toBe(before);
    });

    test("what names no account takes its participant's color, then its client's", () => {
        expect(personColor({ participant_id: "0f1e2d3c" }, "7")).toBe(participantColor("0f1e2d3c"));
        expect(personColor(null, "7")).toBe(participantColor("7"));
        expect(personColor({ user_id: 3 })).toBe(participantColor("user 3"));
    });
});

describe("everyone else's cursors", () => {
    const ana = (pointer: unknown): PresenceState => ({
        user: { participant_id: "p-ana", username: "ana", name: "Ana" },
        pointer: pointer as PresenceState["pointer"],
    });

    test("are drawn in their person's color with their name; a state with no point is not", () => {
        const tracker = new CursorTracker();
        const drawn = tracker.read([
            [7, ana({ x: 10, y: 20, t: NOW })],
            [8, { user: { participant_id: "p-bea", username: "bea" }, pointer: null }],
            [9, { user: { participant_id: "p-cy", name: "Cy" }, pointer: { x: "10", y: 20 } as any }],
            [10, { user: { participant_id: "p-di", name: "Di" }, pointer: { x: Number.NaN, y: 1, t: NOW } }],
            [11, { user: { participant_id: "p-ed", name: "Ed" } }],
        ], NOW);
        expect(drawn).toEqual([
            { clientId: 7, x: 10, y: 20, name: "Ana", color: participantColor("ana"), idle: false },
        ]);
        expect(pointerOf({ pointer: { x: 1, y: 2 } as any })).toEqual({ x: 1, y: 2, t: 0 });
    });

    test("two tabs of one person are drawn in one color", () => {
        const tracker = new CursorTracker();
        const [first, second] = tracker.read([
            [7, ana({ x: 10, y: 20, t: NOW })],
            [8, { ...ana({ x: 30, y: 40, t: NOW }), user: { participant_id: "p-ana-2", username: "ana", name: "Ana" } }],
        ], NOW);
        expect(second.color).toBe(first.color);
    });

    test("a watcher's pointer is drawn as anyone's is", () => {
        const tracker = new CursorTracker();
        const watcher: PresenceState = {
            user: { participant_id: "p-wes", username: "wes", name: "Wes", role: "watcher" },
            pointer: { x: -5, y: 7.5, t: NOW },
        };
        expect(tracker.read([[12, watcher]], NOW)).toEqual([
            { clientId: 12, x: -5, y: 7.5, name: "Wes", color: participantColor("wes"), idle: false },
        ]);
    });

    test("fade once they rest for CURSOR_IDLE_MS, and are drawn whole again when they move", () => {
        const tracker = new CursorTracker();
        const resting = ana({ x: 10, y: 20, t: NOW });
        expect(tracker.read([[7, resting]], NOW)[0].idle).toBe(false);
        expect(tracker.nextFadeAt(NOW)).toBe(NOW + CURSOR_IDLE_MS);
        expect(tracker.read([[7, resting]], NOW + CURSOR_IDLE_MS - 1)[0].idle).toBe(false);
        expect(tracker.read([[7, resting]], NOW + CURSOR_IDLE_MS)[0].idle).toBe(true);
        expect(tracker.nextFadeAt(NOW + CURSOR_IDLE_MS)).toBeNull();

        const later = NOW + CURSOR_IDLE_MS + 10;
        expect(tracker.read([[7, ana({ x: 11, y: 20, t: later })]], later)[0].idle).toBe(false);
        expect(tracker.nextFadeAt(later)).toBe(later + CURSOR_IDLE_MS);
    });

    test("rest by this tab's clock: a pointer sent by a clock an hour behind is not faded when it arrives", () => {
        const tracker = new CursorTracker();
        const sentAnHourAgo = ana({ x: 10, y: 20, t: NOW - 3_600_000 });
        expect(tracker.read([[7, sentAnHourAgo]], NOW)[0].idle).toBe(false);
        expect(tracker.read([[7, sentAnHourAgo]], NOW + CURSOR_IDLE_MS)[0].idle).toBe(true);
    });

    test("one that left is forgotten: when it comes back it is drawn whole", () => {
        const tracker = new CursorTracker();
        const resting = ana({ x: 10, y: 20, t: NOW });
        tracker.read([[7, resting]], NOW);
        expect(tracker.read([[7, ana(null)]], NOW + 1)).toEqual([]);
        expect(tracker.nextFadeAt(NOW + 1)).toBeNull();
        expect(tracker.read([[7, resting]], NOW + CURSOR_IDLE_MS * 3)[0].idle).toBe(false);
    });
});
