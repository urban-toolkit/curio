/**
 * An agent's change on a canvas no doc binds (a hosted guest's example), as a
 * run's `change` events bring it (`services/agents/agentEvents.ts`,
 * `bridgeLandedChangeEvent`): no awareness tells this tab what the agent does,
 * so the change plays as the room's tabs saw it, one step at a time, each
 * step's drag first, drawn by the drag layer every tab draws peers' drags
 * with (`components/collab/AgentDrags.tsx`), then the step's canvas mutation.
 *
 * - A plan's steps land in order, each new node only once its drop ended, and
 *   the whole plan's mutation, which a bound canvas takes, never lands here.
 * - A change that comes while another plays waits for it.
 * - A canvas a doc's awareness feeds takes the whole change at once and plays
 *   nothing: it saw the drags as they happened.
 * - A drag names a node type as the dataflow does, without its major, and
 *   still starts at its tile, which names it with its major.
 */
import React from "react";
import { act, render } from "@testing-library/react";
import { ReactFlowProvider, useStoreApi } from "reactflow";
import * as Y from "yjs";
import { Awareness, applyAwarenessUpdate, encodeAwarenessUpdate } from "y-protocols/awareness";
import { faUpload } from "@fortawesome/free-solid-svg-icons";

import { CanvasCursors } from "../../../components/collab/CanvasCursors";
import { BuiltinPaletteDropdown } from "../../../components/menus/nodes/builtinPalette/BuiltinPaletteDropdown";
import { useAgentsWriting } from "../../../providers/collab/agentHolds";
import { DataflowDocContext, type DocBinding } from "../../../providers/collab/docContext";
import type { NodeDescriptor } from "../../../registry/types";
import {
    bridgeLandedChangeEvent,
    subscribeAgentCanvasMutations,
    type AgentCanvasMutation,
} from "../../../services/agents/agentEvents";

const NOW = 1_700_000_000_000;
const BOX = { left: 60, top: 48 };
const MS = 500;
const TYPE = "curio.builtin/computation-analysis";

type Store = ReturnType<typeof useStoreApi>;

let canvas: HTMLDivElement;
let landed: AgentCanvasMutation[];
let unsubscribe: () => void;
let matchMedia: typeof window.matchMedia;

beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    canvas = document.createElement("div");
    boxed(canvas, BOX.left, BOX.top, 1200, 700);
    document.body.appendChild(canvas);
    landed = [];
    unsubscribe = subscribeAgentCanvasMutations((mutation) => landed.push(mutation));
    // Under reduced motion each drag waits at its drop point for its length.
    matchMedia = window.matchMedia;
    window.matchMedia = ((query: string) => ({
        matches: query.includes("prefers-reduced-motion: reduce"),
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
    })) as unknown as typeof window.matchMedia;
});

afterEach(() => {
    // Every change still playing ends, so none waits into the next test.
    act(() => {
        jest.runAllTimers();
    });
    unsubscribe();
    window.matchMedia = matchMedia;
    canvas.remove();
    jest.useRealTimers();
});

function boxed(element: Element | null, left: number, top: number, width: number, height: number) {
    (element as HTMLElement).getBoundingClientRect = () =>
        ({ x: left, y: top, left, top, right: left + width, bottom: top + height, width, height, toJSON: () => ({}) }) as DOMRect;
}

/** React Flow's store as a drawn canvas holds it: its element and its view. */
function Canvas() {
    const store: Store = useStoreApi();
    React.useLayoutEffect(() => {
        store.setState({ domNode: canvas, transform: [0, 0, 1] });
    }, [store]);
    return null;
}

/** A canvas no doc binds, with the rail's Built-in palette beside it. */
function renderUnbound(page: React.ReactNode = null) {
    return render(
        <>
            <ReactFlowProvider>
                <Canvas />
                <CanvasCursors />
            </ReactFlowProvider>
            {page}
        </>,
    );
}

function advance(ms: number) {
    act(() => {
        jest.advanceTimersByTime(ms);
    });
}

const AGENT = {
    participant_id: "agent-builder",
    user_id: null,
    name: "Dataflow Builder",
    agent: { attachmentId: "att-1", coord: "agent.curio.dataflow-builder@1", category: "canvas", askedBy: { account: "1", name: "Ana" } },
};

/** The drag the agent's state carried before a node landed at *x*, *y*. */
function dragged(id: string, label: string, x: number, y: number) {
    return {
        user: AGENT,
        pointer: { x, y, t: NOW },
        carrying: { id, kind: "add", from: { palette: "builtin", item: TYPE }, onto: null, node: { type: TYPE, label }, ms: MS },
    };
}

const node = (id: string, x: number, y: number) => ({ id, type: TYPE, content: "", goal: id, x, y });

/** A plan of a removal, two new nodes and their connection, as its change event says it landed. */
function planChange() {
    const step = (n: number, body: Record<string, unknown>) => ({ kind: "graph-created", planId: "plan-1", step: n, nodes: [], edges: [], ...body });
    return {
        changeId: "change-1",
        attachmentId: "att-1",
        tool: "dataflow.plan.write",
        canvas: {
            kind: "graph-created", planId: "plan-1", nodes: [node("fetch", 700, 80), node("clean", 1345, 80)],
            edges: [{ id: "e2", source: "fetch", target: "clean" }], removedNodeIds: ["load"], removedEdgeIds: ["e1"],
        },
        steps: [
            { canvas: step(0, { removedNodeIds: ["load"], removedEdgeIds: ["e1"] }) },
            { canvas: step(1, { nodes: [node("fetch", 700, 80)] }), dragged: dragged("drag-fetch", "Fetch", 700, 80) },
            { canvas: step(2, { nodes: [node("clean", 1345, 80)] }), dragged: dragged("drag-clean", "Clean", 1345, 80) },
            { canvas: step(3, { edges: [{ id: "e2", source: "fetch", target: "clean" }] }) },
        ],
    };
}

const drags = () => Array.from(document.querySelectorAll<HTMLElement>("[data-agent-drag]"));
const at = (element: HTMLElement) => [parseFloat(element.style.left), parseFloat(element.style.top)];
const steps = () => landed.map((mutation) => (mutation.kind === "graph-created" ? mutation.step : mutation.kind));

describe("a change on a canvas no doc binds plays its drags before it lands", () => {
    test("a plan's steps land in order, each new node once its drop ended, never the whole plan at once", () => {
        renderUnbound();

        act(() => {
            bridgeLandedChangeEvent("change", planChange());
        });

        // The removal lands at once, with no drag; then Fetch's drag plays,
        // its node not landed yet.
        expect(steps()).toEqual([0]);
        expect(drags()).toHaveLength(1);
        expect(drags()[0].querySelector("[data-agent-cursor]")!.textContent).toBe("Dataflow Builder");
        expect(at(drags()[0])).toEqual([700, 80]);
        advance(MS - 1);
        expect(steps()).toEqual([0]);

        // As its drop ends, Fetch lands, and Clean's drag plays.
        advance(1);
        expect(steps()).toEqual([0, 1]);
        expect(drags()).toHaveLength(1);
        expect(at(drags()[0])).toEqual([1345, 80]);

        // Then Clean, then the connection, with no drag.
        advance(MS);
        expect(steps()).toEqual([0, 1, 2, 3]);
        expect(drags()).toHaveLength(0);
        expect(landed.every((mutation) => mutation.landed === true)).toBe(true);
        expect(landed.some((mutation) => mutation.kind === "graph-created" && mutation.step === undefined)).toBe(false);
    });

    test("a change that comes while another plays waits for it", () => {
        renderUnbound();
        const created = {
            changeId: "change-2", attachmentId: "att-2", tool: "node.create",
            canvas: { kind: "node-created", node: node("note", 80, 600) },
            steps: [{ canvas: { kind: "node-created", node: node("note", 80, 600) }, dragged: dragged("drag-note", "Note", 80, 600) }],
        };

        act(() => {
            bridgeLandedChangeEvent("change", planChange());
            bridgeLandedChangeEvent("change", created);
        });
        advance(MS);
        expect(steps()).toEqual([0, 1]);
        advance(MS);
        // The plan's last steps land before the note's drag plays.
        expect(steps()).toEqual([0, 1, 2, 3]);
        expect(drags()).toHaveLength(1);
        expect(at(drags()[0])).toEqual([80, 600]);
        advance(MS);
        expect(steps()).toEqual([0, 1, 2, 3, "node-created"]);
    });

    test("a canvas a doc's awareness feeds takes the whole change at once and plays no drag", () => {
        const awareness = new Awareness(new Y.Doc());
        function Fed() {
            useAgentsWriting(awareness);
            return null;
        }
        render(<Fed />);
        renderUnbound();

        act(() => {
            bridgeLandedChangeEvent("change", planChange());
        });

        expect(landed).toHaveLength(1);
        expect(landed[0].kind === "graph-created" && landed[0].step).toBe(undefined);
        expect(drags()).toHaveLength(0);
        awareness.destroy();
    });
});

describe("a drag names a node type as the dataflow does", () => {
    test("without its major, and starts at its tile, which names it with its major", () => {
        const descriptor = {
            id: `${TYPE}@1`, label: "Computation Analysis", category: "computation", icon: faUpload,
            package: { packageId: "curio.builtin" },
        } as unknown as NodeDescriptor;
        const mine = new Awareness(new Y.Doc());
        const builder = new Awareness(new Y.Doc());
        const binding = { provider: { awareness: mine }, synced: true } as unknown as DocBinding;
        render(
            <DataflowDocContext.Provider value={binding}>
                <ReactFlowProvider>
                    <Canvas />
                    <CanvasCursors />
                </ReactFlowProvider>
                <BuiltinPaletteDropdown nodeTypes={[descriptor]} open setOpen={jest.fn()} />
            </DataflowDocContext.Provider>,
        );
        boxed(document.getElementById("builtin-palette"), 50, 150, 112, 50);
        boxed(document.getElementById("tile-computation-analysis"), 172, 220, 45, 45);
        expect(document.querySelectorAll(`[data-palette-item="${TYPE}@1"]`)).toHaveLength(1);

        // The agent's state, as the server relays it: the plan's node type, as
        // the dataflow names it.
        const { user, pointer, carrying } = dragged("drag-fetch", "Fetch", 700, 80);
        act(() => {
            builder.setLocalState({ user, skills: [], editing: null, pointer, carrying });
            applyAwarenessUpdate(mine, encodeAwarenessUpdate(builder, [builder.clientID]), "server");
        });

        expect(drags()).toHaveLength(1);
        expect(drags()[0].getAttribute("data-drag-start")).toBe("tile");
        mine.destroy();
        builder.destroy();
    });
});
