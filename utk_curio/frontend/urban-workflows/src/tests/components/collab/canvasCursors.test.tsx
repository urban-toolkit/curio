/**
 * Everyone's pointer on the canvas (`components/collab/CanvasCursors.tsx`),
 * with real awareness states and React Flow's own store:
 *
 * - this tab's pointer goes into its awareness at its point of the dataflow
 *   while it is over the canvas, again when the view moves under it, and
 *   becomes null when it leaves the canvas or the tab is hidden;
 * - everyone else's is drawn at its point of the dataflow on the plane that
 *   follows the view's pan and zoom, at one size, in their color with their
 *   name, and faded once it rests; this tab's own is never drawn.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi } from "reactflow";
import * as Y from "yjs";
import {
    Awareness,
    applyAwarenessUpdate,
    encodeAwarenessUpdate,
    removeAwarenessStates,
} from "y-protocols/awareness";

import { CanvasCursors } from "../../../components/collab/CanvasCursors";
import { DataflowDocContext, type DocBinding } from "../../../providers/collab/docContext";
import { CURSOR_EVERY_MS, CURSOR_IDLE_MS } from "../../../providers/collab/cursors";
import { participantColor, type PresenceState } from "../../../providers/collab/presence";

const NOW = 1_700_000_000_000;
/** Where the canvas's box starts in the window. */
const BOX = { left: 60, top: 48 };

type Store = ReturnType<typeof useStoreApi>;

let mine: Awareness;
let ana: Awareness;
let canvas: HTMLDivElement;

beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    mine = new Awareness(new Y.Doc());
    ana = new Awareness(new Y.Doc());
    canvas = document.createElement("div");
    canvas.getBoundingClientRect = () =>
        ({ x: BOX.left, y: BOX.top, left: BOX.left, top: BOX.top, right: BOX.left + 1200, bottom: BOX.top + 700, width: 1200, height: 700, toJSON: () => ({}) }) as DOMRect;
    document.body.appendChild(canvas);
});

afterEach(() => {
    mine.destroy();
    ana.destroy();
    canvas.remove();
    jest.useRealTimers();
});

/** React Flow's store as a drawn canvas holds it: its element and its view. */
function Canvas({ into, view }: { into: { store?: Store }; view: [number, number, number] }) {
    const store = useStoreApi();
    React.useLayoutEffect(() => {
        into.store = store;
        store.setState({ domNode: canvas, transform: view });
    }, [store]);
    return null;
}

function renderCanvas(view: [number, number, number] = [100, 50, 2]) {
    const into: { store?: Store } = {};
    const binding = { provider: { awareness: mine }, synced: true } as unknown as DocBinding;
    const rendered = render(
        <DataflowDocContext.Provider value={binding}>
            <ReactFlowProvider>
                <Canvas into={into} view={view} />
                <CanvasCursors />
            </ReactFlowProvider>
        </DataflowDocContext.Provider>,
    );
    return { ...rendered, view: (next: [number, number, number]) => act(() => into.store!.setState({ transform: next })) };
}

/** What the server relays of Ana's tab: her state, as this tab's awareness takes it. */
function anaIs(state: PresenceState | null) {
    act(() => {
        if (state) ana.setLocalState(state as { [key: string]: unknown });
        else removeAwarenessStates(ana, [ana.clientID], "test");
        applyAwarenessUpdate(mine, encodeAwarenessUpdate(ana, [ana.clientID]), "server");
    });
}

/** Ana watches: the server keeps a watcher's `pointer`. */
const anaAt = (x: number, y: number): PresenceState => ({
    user: { participant_id: "p-ana", username: "ana", name: "Ana", role: "watcher" },
    pointer: { x, y, t: Date.now() },
});

function pointer(type: "pointermove" | "pointerleave", x = 0, y = 0) {
    act(() => {
        canvas.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: type === "pointermove" }));
    });
}

const drawn = () => Array.from(document.querySelectorAll<HTMLElement>("[data-canvas-cursor]"));
const myCursor = () => (mine.getLocalState() as PresenceState | null)?.pointer;

function cssColor(color: string): string {
    const probe = document.createElement("div");
    probe.style.color = color;
    return probe.style.color;
}

describe("this tab's pointer", () => {
    test("goes into its awareness at its point of the dataflow, and again when the view moves under it", () => {
        const { view } = renderCanvas([100, 50, 2]);
        // 60 + 100 + 2 * 100, 48 + 50 + 2 * 100: the flow point (100, 100).
        pointer("pointermove", 360, 298);
        expect(myCursor()).toEqual({ x: 100, y: 100, t: NOW });

        // A zoom button, with the pointer at rest: it is on another point now.
        act(() => jest.advanceTimersByTime(CURSOR_EVERY_MS));
        view([0, 0, 1]);
        act(() => jest.advanceTimersByTime(CURSOR_EVERY_MS));
        expect(myCursor()).toMatchObject({ x: 300, y: 250 });
    });

    test("becomes null when it leaves the canvas, and when the tab is hidden", () => {
        renderCanvas();
        pointer("pointermove", 360, 298);
        expect(myCursor()).not.toBeNull();
        pointer("pointerleave");
        expect(myCursor()).toBeNull();

        act(() => jest.advanceTimersByTime(CURSOR_EVERY_MS));
        pointer("pointermove", 400, 300);
        expect(myCursor()).not.toBeNull();
        Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
        try {
            act(() => {
                document.dispatchEvent(new Event("visibilitychange"));
            });
        } finally {
            delete (document as unknown as { visibilityState?: string }).visibilityState;
        }
        expect(myCursor()).toBeNull();
    });

    test("goes when the canvas does: the notebook view, another page", () => {
        const { unmount } = renderCanvas();
        pointer("pointermove", 360, 298);
        expect(myCursor()).not.toBeNull();
        unmount();
        expect(myCursor()).toBeNull();
    });

    test("is never drawn on this tab's own canvas", () => {
        renderCanvas();
        pointer("pointermove", 360, 298);
        expect(myCursor()).not.toBeNull();
        expect(drawn()).toHaveLength(0);
    });
});

describe("everyone else's pointer", () => {
    test("is drawn at its point of the dataflow on the view's plane, at one size, with their name in their color", () => {
        renderCanvas([100, 50, 2]);
        anaIs(anaAt(100, 100));

        const [cursor] = drawn();
        expect(drawn()).toHaveLength(1);
        expect(cursor.textContent).toBe("Ana");
        expect([cursor.style.left, cursor.style.top]).toEqual(["100px", "100px"]);
        // The plane is the view: the flow point (100, 100) lands at
        // (100 + 2 * 100, 50 + 2 * 100) on the canvas.
        expect((cursor.parentElement as HTMLElement).style.transform).toBe("translate(100px, 50px) scale(2)");
        expect(cursor.style.transform).toBe("scale(0.5)");
        // Her account's color, whatever participant id her tab has today.
        expect(cursor.style.color).toBe(cssColor(participantColor("ana")));
        expect((cursor.querySelector("span") as HTMLElement).style.backgroundColor).toBe(cssColor(participantColor("ana")));
    });

    test("stays at its point of the dataflow as this tab pans and zooms", () => {
        const { view } = renderCanvas([100, 50, 2]);
        anaIs(anaAt(100, 100));
        view([-40, 30, 0.5]);
        const [cursor] = drawn();
        expect((cursor.parentElement as HTMLElement).style.transform).toBe("translate(-40px, 30px) scale(0.5)");
        expect([cursor.style.left, cursor.style.top, cursor.style.transform]).toEqual(["100px", "100px", "scale(2)"]);
    });

    test("fades once it rests, and is drawn whole again when it moves", () => {
        renderCanvas();
        anaIs(anaAt(100, 100));
        expect(drawn()[0].getAttribute("data-idle")).toBeNull();

        act(() => jest.advanceTimersByTime(CURSOR_IDLE_MS - 1));
        expect(drawn()[0].getAttribute("data-idle")).toBeNull();
        act(() => jest.advanceTimersByTime(1));
        expect(drawn()[0].getAttribute("data-idle")).toBe("true");

        anaIs(anaAt(120, 100));
        expect(drawn()[0].getAttribute("data-idle")).toBeNull();
        expect(drawn()[0].style.left).toBe("120px");
    });

    test("goes when it leaves the canvas, and when its tab leaves the room", () => {
        renderCanvas();
        anaIs(anaAt(100, 100));
        expect(drawn()).toHaveLength(1);
        anaIs({ ...anaAt(0, 0), pointer: null });
        expect(drawn()).toHaveLength(0);

        anaIs(anaAt(100, 100));
        expect(drawn()).toHaveLength(1);
        anaIs(null);
        expect(drawn()).toHaveLength(0);
    });
});
