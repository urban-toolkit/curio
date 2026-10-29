/**
 * An agent's drag on the canvas, as every tab plays it
 * (`components/collab/AgentDrags.tsx`, mounted by `CanvasCursors`), with real
 * awareness states, React Flow's own store, and the real Built-in palette and
 * drawer cards. An agent peer's state is the one the step 14 plan names: `user`
 * with its `agent` and category, and during a drag `pointer` at the drop point
 * and `carrying`, `{id, kind, from, onto, node: {type, label}, ms}`.
 *
 * - The agent's cursor, in its category's tint with its name, carries a ghost
 *   of what it drags from this tab's own start to the drop point in `ms`.
 * - The start is the item's tile in an open palette, its card in an open
 *   drawer (before the palette's row), the rail's edge at its palette's button
 *   when that palette is closed, or the node's place for a move.
 * - The drop stays at its point of the dataflow through pans and zooms, and
 *   under reduced motion the drag waits there.
 * - The agent has one cursor, the drag's, and two agents' drags play at once.
 */
import fs from "fs";
import path from "path";
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
import { faUpload } from "@fortawesome/free-solid-svg-icons";

// It pulls in FlowProvider and, through it, vega; the card's badge is not
// what these tests are about.
jest.mock("../../../components/datasets/catalog/DatasetConnectionBadge", () => ({
    DatasetConnectionBadge: () => null,
}));

import { CanvasCursors } from "../../../components/collab/CanvasCursors";
import { BuiltinPaletteDropdown } from "../../../components/menus/nodes/builtinPalette/BuiltinPaletteDropdown";
import { DatasetCard } from "../../../components/datasets/catalog/DatasetCard";
import { PackageCard } from "../../../components/packages/publishing/PackageCard";
import { DataflowDocContext, type DocBinding } from "../../../providers/collab/docContext";
import type { PresenceState } from "../../../providers/collab/presence";
import type { NodeDescriptor } from "../../../registry/types";
import type { DatasetCatalogItem } from "../../../services/datasetCatalog";
import type { PackagePayload } from "../../../services/packages";
import { declaredValue } from "../../_support/cssRules";

const NOW = 1_700_000_000_000;
/** Where the canvas's box starts in the window. */
const BOX = { left: 60, top: 48 };
/** The view this tab has: translated by (100, 50), at zoom 2. */
const VIEW: View = [100, 50, 2];
/** How long the server says a drag takes. */
const MS = 500;
/** Past the drag's length by more than a frame. */
const PAST_MS = MS + 50;
/** Where the Built-in palette's root, as tall as its button, sits in the rail. */
const RAIL = { left: 50, top: 150, width: 112, height: 50 };
/** The rail's edge at that button, on the page. */
const RAIL_EDGE = { x: RAIL.left + RAIL.width, y: RAIL.top + RAIL.height / 2 };
const DROP = { x: 400, y: 260 };

type View = [number, number, number];
type Store = ReturnType<typeof useStoreApi>;
type Drag = { carrying: Record<string, unknown>; drop: { x: number; y: number } };

let mine: Awareness;
let builder: Awareness;
let nodeBuilder: Awareness;
let ana: Awareness;
let canvas: HTMLDivElement;

beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(NOW);
    mine = new Awareness(new Y.Doc());
    builder = new Awareness(new Y.Doc());
    nodeBuilder = new Awareness(new Y.Doc());
    ana = new Awareness(new Y.Doc());
    canvas = document.createElement("div");
    boxed(canvas, BOX.left, BOX.top, 1200, 700);
    document.body.appendChild(canvas);
});

afterEach(() => {
    for (const awareness of [mine, builder, nodeBuilder, ana]) awareness.destroy();
    canvas.remove();
    jest.useRealTimers();
});

/** Gives *element* the box it would have on the page. */
function boxed(element: Element | null, left: number, top: number, width: number, height: number) {
    (element as HTMLElement).getBoundingClientRect = () =>
        ({ x: left, y: top, left, top, right: left + width, bottom: top + height, width, height, toJSON: () => ({}) }) as DOMRect;
}

/** React Flow's store as a drawn canvas holds it: its element, its view, its nodes. */
function Canvas({ into, view, nodes }: { into: { store?: Store }; view: View; nodes?: Map<string, unknown> }) {
    const store = useStoreApi();
    React.useLayoutEffect(() => {
        into.store = store;
        store.setState({ domNode: canvas, transform: view, ...(nodes ? { nodeInternals: nodes as never } : {}) });
    }, [store]);
    return null;
}

/** This tab's canvas, with *page* (the rail's palettes, a drawer's cards) beside it. */
function renderCanvas(page: React.ReactNode = null, view: View = VIEW, nodes?: Map<string, unknown>) {
    const into: { store?: Store } = {};
    const binding = { provider: { awareness: mine }, synced: true } as unknown as DocBinding;
    const rendered = render(
        <DataflowDocContext.Provider value={binding}>
            <ReactFlowProvider>
                <Canvas into={into} view={view} nodes={nodes} />
                <CanvasCursors />
            </ReactFlowProvider>
            {page}
        </DataflowDocContext.Provider>,
    );
    return { ...rendered, view: (next: View) => act(() => into.store!.setState({ transform: next })) };
}

/** What the server relays of *peer*: its state, as this tab's awareness takes it. */
function peerIs(peer: Awareness, state: Record<string, unknown> | null) {
    act(() => {
        if (state) peer.setLocalState(state);
        else removeAwarenessStates(peer, [peer.clientID], "test");
        applyAwarenessUpdate(mine, encodeAwarenessUpdate(peer, [peer.clientID]), "server");
    });
}

/** An agent at work: its `user` as the server writes it, and during *drag* its
 *  `pointer` at the drop point and its `carrying`. */
function agentAt(name: string, category: string, drag: Drag | null): Record<string, unknown> {
    return {
        user: {
            participant_id: `agent-${category}`,
            user_id: null,
            name,
            agent: {
                attachmentId: `attachment-${category}`,
                coord: `agent.curio.${category}@1`,
                category,
                askedBy: { account: "ana", name: "Ana" },
            },
        },
        skills: ["catalogs"],
        editing: null,
        pointer: drag ? { ...drag.drop, t: Date.now() } : null,
        carrying: drag ? drag.carrying : null,
    };
}

const builderIs = (drag: Drag | null) => peerIs(builder, agentAt("Dataflow Builder", "canvas", drag));
const nodeBuilderIs = (drag: Drag | null) => peerIs(nodeBuilder, agentAt("Node Builder", "node", drag));

const DATA_LOADING = { type: "curio.builtin/data-loading@1", label: "Data Loading" };

/** Adding a node from *from*, a palette's item, dropped at *drop*. */
const adding = (from: Record<string, unknown>, id = "drag-1", drop = DROP, node = DATA_LOADING): Drag => ({
    carrying: { id, kind: "add", from, onto: null, node, ms: MS },
    drop,
});

const BUILTIN_DATA_LOADING = { palette: "builtin", item: "curio.builtin/data-loading@1" };

const dataLoading = {
    id: "curio.builtin/data-loading@1",
    label: "Data Loading",
    category: "data",
    icon: faUpload,
    package: { packageId: "curio.builtin" },
} as unknown as NodeDescriptor;

/** The rail's Built-in palette, open or closed, its root and tile where the page has them. */
function builtinPalette(open: boolean) {
    return <BuiltinPaletteDropdown nodeTypes={[dataLoading]} open={open} setOpen={jest.fn()} />;
}

function placeBuiltinPalette() {
    boxed(document.getElementById("builtin-palette"), RAIL.left, RAIL.top, RAIL.width, RAIL.height);
    const tile = document.getElementById("tile-data-loading");
    if (tile) boxed(tile, 172, 220, 45, 45);
}

const dragOf = (peer: Awareness) => document.querySelector<HTMLElement>(`[data-agent-drag="${peer.clientID}"]`);
const at = (element: HTMLElement | null) => [parseFloat(element!.style.left), parseFloat(element!.style.top)];
const ghostOf = (drag: HTMLElement | null) => drag!.querySelector<HTMLElement>("[data-agent-ghost]")!;
const cursorOf = (drag: HTMLElement | null) => drag!.querySelector<HTMLElement>("[data-agent-cursor]")!;
const planeOf = (drag: HTMLElement | null) => (drag!.parentElement as HTMLElement).style.transform;
const plainCursorOf = (peer: Awareness) => document.querySelector(`[data-canvas-cursor="${peer.clientID}"]`);

/** The point of the dataflow a point of the page is on, for this canvas's box and *view*. */
function flowOf(x: number, y: number, [tx, ty, zoom]: View = VIEW): number[] {
    return [(x - BOX.left - tx) / zoom, (y - BOX.top - ty) / zoom];
}

function advance(ms: number) {
    act(() => {
        jest.advanceTimersByTime(ms);
    });
}

describe("an agent's drag starts from this tab's own page", () => {
    test("at its tile in an open palette, carrying a copy of the tile that names nothing", () => {
        renderCanvas(builtinPalette(true));
        placeBuiltinPalette();
        builderIs(adding(BUILTIN_DATA_LOADING));

        const drag = dragOf(builder);
        expect(drag).not.toBeNull();
        expect(drag!.getAttribute("data-drag-start")).toBe("tile");
        expect(drag!.getAttribute("data-drag-kind")).toBe("add");
        // The tile's top-left, (172, 220) on the page, is (6, 61) on the dataflow.
        expect(at(drag)).toEqual(flowOf(172, 220));
        expect(at(drag)).toEqual([6, 61]);

        const ghost = ghostOf(drag);
        expect(ghost.getAttribute("data-agent-ghost")).toBe("copy");
        // The tile as it looks, its size on the page at any zoom.
        expect([ghost.style.width, ghost.style.height, ghost.style.transform]).toEqual(["45px", "45px", "scale(0.5)"]);
        const copy = ghost.firstElementChild as HTMLElement;
        expect(copy.querySelector("svg")).not.toBeNull();
        expect(copy.hasAttribute("inert")).toBe(true);
        // It names nothing a selector, an id lookup or the tooltip finds.
        for (const named of ["[id]", "[data-palette]", "[data-palette-item]", "[data-tooltip]", "[draggable]", "[aria-label]"]) {
            expect([copy, ...Array.from(copy.querySelectorAll("*"))].filter((el) => el.matches(named))).toEqual([]);
        }
        expect(document.querySelectorAll("#tile-data-loading")).toHaveLength(1);
        expect(document.querySelectorAll('[data-palette-item="curio.builtin/data-loading@1"]')).toHaveLength(1);

        // Its cursor carries it: the agent's name, in its category's tint.
        const cursor = cursorOf(drag);
        expect(cursor.parentElement).toBe(drag);
        expect(cursor.textContent).toBe("Dataflow Builder");
        expect(cursor.style.color).toBe("var(--curio-category-agent-canvas-fg)");
        expect((cursor.querySelector("span") as HTMLElement).style.backgroundColor).toBe(
            "var(--curio-category-agent-canvas-fg)",
        );

        advance(PAST_MS);
        expect(at(dragOf(builder))).toEqual([DROP.x, DROP.y]);
    });

    test("at its card in an open drawer before the open palette's row, then the row, then the rail's edge", () => {
        const bikes = {
            id: "imported.bikes",
            title: "Bike Routes",
            origin: "imported",
            format: "csv",
            uri: "curio://datasets/imported.bikes",
            consumerNodeIds: [],
            updatedAt: "2026-07-14T00:00:00Z",
            tags: [],
            installed: true,
        } as unknown as DatasetCatalogItem;
        const { getByTestId } = renderCanvas(
            <>
                {/* The rail's Datasets palette, open, with the dataset's row. */}
                <div id="datasets-palette" data-curio-tools-palette-dropdown="true">
                    <div data-testid="row" data-palette="datasets" data-palette-item="imported.bikes" />
                </div>
                <div data-testid="drawer">
                    <DatasetCard dataset={bikes} isInstalled busy={false} onInstall={jest.fn()} />
                </div>
            </>,
        );
        boxed(document.getElementById("datasets-palette"), 50, 260, 112, 50);
        boxed(getByTestId("row"), 180, 300, 40, 40);
        const card = document.querySelector('article[data-palette-item="imported.bikes"]');
        expect(card).not.toBeNull();
        boxed(card, 900, 120, 320, 96);
        const bikesFrom = { palette: "datasets", item: "imported.bikes" };

        builderIs(adding(bikesFrom, "drag-1"));
        let drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("card");
        expect(at(drag)).toEqual(flowOf(900, 120));
        const ghost = ghostOf(drag);
        expect(ghost.getAttribute("data-agent-ghost")).toBe("copy");
        expect([ghost.style.width, ghost.style.height]).toEqual(["320px", "96px"]);
        expect(ghost.textContent).toContain("Bike Routes");
        expect(ghost.querySelector("[data-dataset-id]")).toBeNull();
        expect(document.querySelectorAll('[data-dataset-id="imported.bikes"]')).toHaveLength(1);
        builderIs(null);

        // The drawer closes: its card is hidden as it goes, and the row is next.
        getByTestId("drawer").setAttribute("aria-hidden", "true");
        builderIs(adding(bikesFrom, "drag-2"));
        drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("tile");
        expect(at(drag)).toEqual(flowOf(180, 300));
        builderIs(null);

        // The palette closes too: the rail's edge at its button.
        boxed(getByTestId("row"), 0, 0, 0, 0);
        builderIs(adding(bikesFrom, "drag-3"));
        drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("rail");
        expect(at(drag)).toEqual(flowOf(50 + 112, 260 + 25));
        expect(ghostOf(drag).getAttribute("data-agent-ghost")).toBe("outline");
    });

    test("at the card of a package that has the node, among its nodes", () => {
        const shapes = {
            dirName: "acme.shapes@1",
            packageId: "acme.shapes",
            name: "Shapes",
            version: "1.0.0",
            publisher: "Acme",
            description: "",
            templates: [
                { id: "acme.shapes/hexbin@1", label: "Hexbin" },
                { id: "acme.shapes/heatmap@1", label: "Heatmap" },
            ],
            lineage: null,
            familyKey: "acme.shapes@1",
        } as unknown as PackagePayload;
        renderCanvas(
            <PackageCard
                pkg={shapes}
                isInstalled={false}
                hasUpdate={false}
                catalogRow={undefined}
                busy={false}
                onInstall={jest.fn()}
                onUpdate={jest.fn()}
            />,
        );
        const card = document.querySelector('article[data-pkg-dir="acme.shapes@1"]');
        boxed(card, 880, 400, 300, 90);
        builderIs(
            adding({ palette: "packages", item: "acme.shapes/heatmap@1" }, "drag-1", DROP, {
                type: "acme.shapes/heatmap@1",
                label: "Heatmap",
            }),
        );
        const drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("card");
        expect(at(drag)).toEqual(flowOf(880, 400));
        expect(ghostOf(drag).textContent).toContain("Shapes");
    });

    test("at the rail's edge at its palette's button when the palette is closed, carrying the node's outline", () => {
        renderCanvas(builtinPalette(false));
        placeBuiltinPalette();
        expect(document.getElementById("tile-data-loading")).toBeNull();
        builderIs(adding(BUILTIN_DATA_LOADING));

        const drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("rail");
        expect(at(drag)).toEqual(flowOf(RAIL_EDGE.x, RAIL_EDGE.y));
        expect(at(drag)).toEqual([1, 38.5]);
        // The outline of the node it adds, the size the node lands at, on the
        // dataflow: it scales with the view, as the node does.
        const ghost = ghostOf(drag);
        expect(ghost.getAttribute("data-agent-ghost")).toBe("outline");
        expect([ghost.style.width, ghost.style.height, ghost.style.transform]).toEqual(["525px", "350px", ""]);
        expect(ghost.textContent).toBe("Data Loading");
        expect(ghost.style.borderColor).toBe("var(--curio-category-agent-canvas-fg)");

        advance(PAST_MS);
        expect(at(dragOf(builder))).toEqual([DROP.x, DROP.y]);
    });

    test("at the node's place, where this tab's canvas has it, for a move, carrying the node's outline", () => {
        const nodes = new Map([
            ["n1", { id: "n1", position: { x: 40, y: 30 }, positionAbsolute: { x: 40, y: 30 }, width: 300, height: 200, data: {} }],
        ]);
        renderCanvas(null, VIEW, nodes);
        const drop = { x: 520, y: 300 };
        nodeBuilderIs({
            carrying: {
                id: "drag-1",
                kind: "move",
                from: { node: "n1", x: 36, y: 24 },
                onto: null,
                node: { type: "curio.builtin/vis-vega@1", label: "Vega-Lite" },
                ms: MS,
            },
            drop,
        });

        let drag = dragOf(nodeBuilder);
        expect(drag!.getAttribute("data-drag-start")).toBe("node");
        expect(drag!.getAttribute("data-drag-kind")).toBe("move");
        // A point of the dataflow: the node's own top-left.
        expect(at(drag)).toEqual([40, 30]);
        const ghost = ghostOf(drag);
        expect(ghost.getAttribute("data-agent-ghost")).toBe("outline");
        expect([ghost.style.width, ghost.style.height]).toEqual(["300px", "200px"]);
        expect(ghost.textContent).toBe("Vega-Lite");
        expect(cursorOf(drag).style.color).toBe("var(--curio-category-agent-node-fg)");

        advance(PAST_MS);
        expect(at(dragOf(nodeBuilder))).toEqual([drop.x, drop.y]);
        nodeBuilderIs(null);

        // A node this tab's canvas does not have starts at the place its state names.
        nodeBuilderIs({
            carrying: {
                id: "drag-2",
                kind: "move",
                from: { node: "n9", x: 200, y: 120 },
                onto: null,
                node: { type: "curio.builtin/vis-vega@1", label: "Vega-Lite" },
                ms: MS,
            },
            drop,
        });
        drag = dragOf(nodeBuilder);
        expect(drag!.getAttribute("data-drag-start")).toBe("node");
        expect(at(drag)).toEqual([200, 120]);
    });

    test("at its drop point, where it waits, when this tab shows nothing to start from", () => {
        renderCanvas();
        builderIs(adding({ palette: "datasets", item: "imported.elsewhere" }));
        const drag = dragOf(builder);
        expect(drag!.getAttribute("data-drag-start")).toBe("drop");
        expect(at(drag)).toEqual([DROP.x, DROP.y]);
        advance(MS / 2);
        expect(at(dragOf(builder))).toEqual([DROP.x, DROP.y]);
    });
});

describe("on its way to the drop", () => {
    test("goes from its start to its drop point in its ms, the drop at its point of the dataflow through a pan and a zoom", () => {
        const { view } = renderCanvas(builtinPalette(true));
        placeBuiltinPalette();
        builderIs(adding(BUILTIN_DATA_LOADING));
        let drag = dragOf(builder);
        expect(at(drag)).toEqual(flowOf(172, 220));
        expect(planeOf(drag)).toBe("translate(160px, 98px) scale(2)");

        // A pan and a zoom: the start stays on the tile, on the page, and the
        // plane takes the new view, the canvas's box included.
        const panned: View = [-40, 30, 0.5];
        view(panned);
        drag = dragOf(builder);
        expect(at(drag)).toEqual(flowOf(172, 220, panned));
        expect(at(drag)).toEqual([304, 284]);
        expect(planeOf(drag)).toBe("translate(20px, 78px) scale(0.5)");
        expect(ghostOf(drag).style.transform).toBe("scale(2)");
        expect(cursorOf(drag).style.transform).toBe("scale(2)");

        // On its way: between its start and its drop point.
        advance(MS / 2 - 10);
        const [x, y] = at(dragOf(builder));
        expect(x).toBeGreaterThan(304);
        expect(x).toBeLessThan(DROP.x);
        expect(y).toBeGreaterThan(DROP.y);
        expect(y).toBeLessThan(284);

        // Its ms over: the cursor and the ghost it holds are on the drop point.
        advance(PAST_MS);
        drag = dragOf(builder);
        expect(at(drag)).toEqual([DROP.x, DROP.y]);
        expect(cursorOf(drag).parentElement).toBe(drag);
        expect([cursorOf(drag).style.left, cursorOf(drag).style.top]).toEqual(["0px", "0px"]);
        expect(ghostOf(drag).parentElement).toBe(drag);

        // A zoom while it waits there keeps it on that point of the dataflow.
        view([10, -20, 1.25]);
        drag = dragOf(builder);
        expect(at(drag)).toEqual([DROP.x, DROP.y]);
        expect(planeOf(drag)).toBe("translate(70px, 28px) scale(1.25)");
        expect(cursorOf(drag).style.transform).toBe("scale(0.8)");

        // The drop ends: the drag goes, and the change lands.
        builderIs(null);
        expect(dragOf(builder)).toBeNull();
    });

    test("under reduced motion, waits at its drop point for the drag's length", () => {
        const matchMedia = window.matchMedia;
        window.matchMedia = ((query: string) => ({
            matches: query.includes("prefers-reduced-motion: reduce"),
            media: query,
            addEventListener: () => undefined,
            removeEventListener: () => undefined,
        })) as unknown as typeof window.matchMedia;
        try {
            renderCanvas(builtinPalette(false));
            placeBuiltinPalette();
            builderIs(adding(BUILTIN_DATA_LOADING));

            const drag = dragOf(builder);
            expect(drag).not.toBeNull();
            expect(at(drag)).toEqual([DROP.x, DROP.y]);
            expect(cursorOf(drag).textContent).toBe("Dataflow Builder");
            expect(ghostOf(drag).getAttribute("data-agent-ghost")).toBe("outline");
            advance(MS / 2);
            expect(at(dragOf(builder))).toEqual([DROP.x, DROP.y]);
            advance(MS / 2 - 1);
            expect(at(dragOf(builder))).toEqual([DROP.x, DROP.y]);

            builderIs(null);
            expect(dragOf(builder)).toBeNull();
        } finally {
            window.matchMedia = matchMedia;
        }
    });
});

describe("the agent's cursor", () => {
    test("is the drag's: no cursor of its own while it carries, and none once the drop ends", () => {
        renderCanvas(builtinPalette(false));
        placeBuiltinPalette();
        // Ana watches, her pointer on the canvas.
        peerIs(ana, {
            user: { participant_id: "p-ana", username: "ana", name: "Ana", role: "watcher" },
            pointer: { x: 100, y: 100, t: Date.now() },
        });
        expect(plainCursorOf(ana)).not.toBeNull();

        builderIs(adding(BUILTIN_DATA_LOADING));
        expect(plainCursorOf(builder)).toBeNull();
        const cursors = document.querySelectorAll(`[data-agent-cursor="${builder.clientID}"]`);
        expect(cursors).toHaveLength(1);
        expect(cursors[0].closest("[data-agent-drag]")).toBe(dragOf(builder));
        expect(cursors[0].textContent).toBe("Dataflow Builder");
        expect(plainCursorOf(ana)).not.toBeNull();

        advance(PAST_MS);
        expect(plainCursorOf(builder)).toBeNull();
        expect(document.querySelectorAll(`[data-agent-cursor="${builder.clientID}"]`)).toHaveLength(1);

        builderIs(null);
        expect(plainCursorOf(builder)).toBeNull();
        expect(document.querySelectorAll(`[data-agent-cursor="${builder.clientID}"]`)).toHaveLength(0);
        expect(plainCursorOf(ana)).not.toBeNull();
    });

    test("two agents' drags play at once, each with its own start, ghost, tint and drop", () => {
        const nodes = new Map([
            ["n1", { id: "n1", position: { x: 40, y: 30 }, positionAbsolute: { x: 40, y: 30 }, width: 300, height: 200, data: {} }],
        ]);
        renderCanvas(builtinPalette(false), VIEW, nodes);
        placeBuiltinPalette();
        const moveDrop = { x: 520, y: 300 };
        builderIs(adding(BUILTIN_DATA_LOADING));
        nodeBuilderIs({
            carrying: {
                id: "drag-1",
                kind: "move",
                from: { node: "n1", x: 40, y: 30 },
                onto: null,
                node: { type: "curio.builtin/vis-vega@1", label: "Vega-Lite" },
                ms: MS,
            },
            drop: moveDrop,
        });

        expect(document.querySelectorAll("[data-agent-drag]")).toHaveLength(2);
        const adds = dragOf(builder);
        const moves = dragOf(nodeBuilder);
        expect([adds!.getAttribute("data-drag-start"), moves!.getAttribute("data-drag-start")]).toEqual(["rail", "node"]);
        expect([cursorOf(adds).textContent, cursorOf(moves).textContent]).toEqual(["Dataflow Builder", "Node Builder"]);
        expect([cursorOf(adds).style.color, cursorOf(moves).style.color]).toEqual([
            "var(--curio-category-agent-canvas-fg)",
            "var(--curio-category-agent-node-fg)",
        ]);
        expect([ghostOf(adds).textContent, ghostOf(moves).textContent]).toEqual(["Data Loading", "Vega-Lite"]);
        expect([ghostOf(adds).style.width, ghostOf(moves).style.width]).toEqual(["525px", "300px"]);
        expect([at(adds), at(moves)]).toEqual([flowOf(RAIL_EDGE.x, RAIL_EDGE.y), [40, 30]]);

        advance(PAST_MS);
        expect([at(dragOf(builder)), at(dragOf(nodeBuilder))]).toEqual([
            [DROP.x, DROP.y],
            [moveDrop.x, moveDrop.y],
        ]);

        // One drop ends; the other drag stays where it is.
        builderIs(null);
        expect(dragOf(builder)).toBeNull();
        expect(at(dragOf(nodeBuilder))).toEqual([moveDrop.x, moveDrop.y]);

        // The first agent's next drag starts again from its own start.
        builderIs(adding(BUILTIN_DATA_LOADING, "drag-2", { x: 640, y: 420 }));
        expect(dragOf(builder)!.getAttribute("data-drag-start")).toBe("rail");
        expect(at(dragOf(builder))).toEqual(flowOf(RAIL_EDGE.x, RAIL_EDGE.y));
        expect(at(dragOf(nodeBuilder))).toEqual([moveDrop.x, moveDrop.y]);
        advance(PAST_MS);
        expect(at(dragOf(builder))).toEqual([640, 420]);
    });
});

describe("the layer it is drawn in", () => {
    test("is over the page, takes no pointer event and is hidden from assistive technology", () => {
        renderCanvas();
        builderIs(adding(BUILTIN_DATA_LOADING));
        const layer = dragOf(builder)!.closest("[data-agent-drags]") as HTMLElement;
        expect(layer).not.toBeNull();
        expect(layer.parentElement).toBe(document.body);
        expect(layer.getAttribute("aria-hidden")).toBe("true");
        builderIs(null);
        expect(document.querySelector("[data-agent-drags]")).toBeNull();

        // Its stylesheet: jest maps CSS modules to their class names, so the
        // rules are read from the source.
        const css = fs.readFileSync(path.resolve(__dirname, "../../../components/collab/AgentDrags.module.css"), "utf8");
        expect(declaredValue(css, ".layer", "position")).toBe("fixed");
        expect(declaredValue(css, ".layer", "pointer-events")).toBe("none");
        expect(declaredValue(css, ".layer", "z-index")).toBe("var(--curio-z-agent-drags)");
        // A drag moves on every frame: no transition lags it behind its point.
        expect(declaredValue(css, ".drag", "transition")).toBeUndefined();
    });
});
