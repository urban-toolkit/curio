// The notebook view: the same nodes and edges, shown as one column of cells in
// dataflow order, with the connections drawn in a bar on the right.
//
// Cells are the canvas's own nodes, moved. React Flow has to stay mounted for
// Run All, output propagation and saves (they read its store), so this works
// the way the dashboard page does: each node's canvas spot is stamped into
// `data.workflowPosition`, which a save writes instead of `position`
// (utils/canvasPosition), and `position` holds the cell's slot.
//
// The canvas spots live in a map this hook owns. Stamps are written from it
// on every change of the node list, so an update that rebuilt a node's data
// without the stamp is repaired before anything can save it; a collaborator's
// drag lands in the map; leaving the view puts every node back on its spot
// and deletes every stamp.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Edge, Node, ReactFlowInstance, Viewport } from "reactflow";
import { useUpdateNodeInternals } from "reactflow";
import { canvasPositionOf } from "../../utils/canvasPosition";
import { dataflowOrder } from "../../utils/dataflowOrder";
import { fitViewWithMenuOffset } from "../../utils/fitViewWithMenuOffset";
import {
    assignNotebookLanes,
    layoutNotebook,
    NOTEBOOK_MARGIN,
    notebookLaneX,
    type NotebookLayout,
    type NotebookPane,
    type XY,
} from "../../utils/notebookLayout";
import { directedEdgesOf } from "./runLevels";
import type { NotebookViewValue } from "./notebookViewContext";

export type CanvasView = "canvas" | "notebook";

const VIEW_PARAM = "view";

/** The view the address asks for: `?view=notebook`, or the canvas. */
export function readCanvasViewParam(): CanvasView {
    try {
        return new URLSearchParams(window.location.search).get(VIEW_PARAM) === "notebook" ? "notebook" : "canvas";
    } catch {
        return "canvas";
    }
}

/**
 * Keep the view in the address, so a reload or a copied link opens it again.
 * Written straight to `history` rather than through the router: FlowProvider
 * also renders without one (its tests, the standalone dashboard), and only
 * this one parameter changes.
 */
export function writeCanvasViewParam(view: CanvasView): void {
    try {
        const url = new URL(window.location.href);
        if (view === "notebook") url.searchParams.set(VIEW_PARAM, "notebook");
        else url.searchParams.delete(VIEW_PARAM);
        if (url.href !== window.location.href) {
            window.history.replaceState(window.history.state, "", url.href);
        }
    } catch {
        /* no address to keep it in */
    }
}

function samePoint(a: XY | undefined | null, b: XY | undefined | null): boolean {
    return !!a && !!b && a.x === b.x && a.y === b.y;
}

/**
 * Stamp every node with its canvas spot from *canvas* and move it to its slot.
 *
 * The stamp is written onto the node's existing `data` object: React Flow's
 * store shares that object, so a save reads the stamp at once, and a stamp
 * nobody sees needs no re-render. A node the map has not seen joins it with
 * the spot it has now, which for a node just added is where it was put on the
 * canvas. Returns *nodes* itself when no node has to move.
 */
export function placeNotebookNodes<N extends Node>(
    nodes: N[],
    slots: ReadonlyMap<string, XY>,
    canvas: Map<string, XY>,
): N[] {
    let moved = false;
    const next = nodes.map((node) => {
        if (!canvas.has(node.id)) canvas.set(node.id, { ...canvasPositionOf(node) });
        const spot = canvas.get(node.id)!;
        if (node.data && !samePoint(node.data.workflowPosition, spot)) {
            node.data.workflowPosition = { ...spot };
        }
        const slot = slots.get(node.id);
        if (!slot || samePoint(node.position, slot)) return node;
        moved = true;
        return { ...node, position: { ...slot } };
    });
    return moved ? next : nodes;
}

/** Put every node back on its canvas spot and delete every stamp. */
export function restoreCanvasNodes<N extends Node>(nodes: N[], canvas: ReadonlyMap<string, XY>): N[] {
    return nodes.map((node) => {
        const spot = canvas.get(node.id) ?? node.data?.workflowPosition;
        if (node.data && "workflowPosition" in node.data) delete node.data.workflowPosition;
        return spot ? { ...node, position: { ...spot } } : node;
    });
}

const NO_PANE: NotebookPane = { width: 0, top: 0, left: 0 };
const NO_LAYOUT: NotebookLayout = layoutNotebook([], NO_PANE);
const NO_LANES: ReadonlyMap<string, number> = new Map();

export function useNotebookView({
    nodes, edges, setNodes, reactFlow, dashboardOn,
}: {
    nodes: Node[];
    edges: Edge[];
    setNodes: React.Dispatch<React.SetStateAction<Node[]>>;
    reactFlow: ReactFlowInstance;
    dashboardOn: boolean;
}) {
    const [canvasView, setCanvasViewState] = useState<CanvasView>(
        () => (dashboardOn ? "canvas" : readCanvasViewParam()),
    );
    const notebookOn = canvasView === "notebook" && !dashboardOn;
    const notebookOnRef = useRef(notebookOn);
    notebookOnRef.current = notebookOn;

    const [pane, setPane] = useState<NotebookPane>(NO_PANE);
    const paneRef = useRef(pane);
    paneRef.current = pane;
    const scrollerRef = useRef<HTMLElement | null>(null);
    const canvasSpotsRef = useRef(new Map<string, XY>());
    const savedViewportRef = useRef<Viewport | null>(null);
    const entryIdsRef = useRef<Set<string>>(new Set());
    const pendingRevealRef = useRef<string[] | null>(null);
    const revealFromRef = useRef<number | null>(null);
    const [revealTick, setRevealTick] = useState(0);
    const updateNodeInternals = useUpdateNodeInternals();

    // What the layout depends on, as one string: recomputed only when a node
    // comes or goes or changes height, a connection changes, or the pane does -
    // not on every output, which also changes `nodes`. A cell is as tall as its
    // content: React Flow measures each node and writes its `height` onto it
    // (a `dimensions` change), and measures again whenever it resizes.
    const directed = directedEdgesOf(edges);
    const layoutKey = notebookOn
        ? [
            nodes.map((n) => `${n.id}:${n.height ?? ""}`).join(","),
            directed.map((e) => `${e.source}>${e.target}`).join(","),
            `${pane.width}|${pane.top}|${pane.left}`,
        ].join("#")
        : "";
    const layoutFor = useCallback(
        (list: Node[], links: Edge[], at: NotebookPane): NotebookLayout => {
            const order = dataflowOrder(list, directedEdgesOf(links));
            return layoutNotebook(order.map((n) => ({ id: n.id, height: n.height })), at);
        },
        [],
    );
    const layout = useMemo(
        () => (notebookOn ? layoutFor(nodes, edges, pane) : NO_LAYOUT),
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [layoutKey],
    );
    const layoutRef = useRef(layout);
    layoutRef.current = layout;

    // The lanes follow the rows and the bar, not the heights: a cell that grows
    // (a typed line, an output) moves the cells below it, but hands no node or
    // edge a new context, which would re-render them all.
    const rowsKey = notebookOn
        ? `${layout.barX}#${Array.from(layout.rows, ([id, row]) => `${id}:${row}`).join(",")}`
        : "";
    const lanesKey = notebookOn
        ? edges.map((e) => `${e.id}:${e.source}.${e.sourceHandle}>${e.target}.${e.targetHandle}`).join(",")
        : "";
    const laneX = useMemo(() => {
        if (!notebookOn) return NO_LANES;
        const { lanes, count } = assignNotebookLanes(edges, layout.rows);
        const xs = new Map<string, number>();
        lanes.forEach((lane, id) => xs.set(id, notebookLaneX(layout.barX, lane, count)));
        return xs;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [rowsKey, lanesKey]);

    // Every change of the node list: keep the map to the live nodes, repair
    // stamps, and move anything not in its slot (a new node, a load, a cell
    // the order moved). Idempotent, so it settles after one pass.
    useEffect(() => {
        if (!notebookOn) return;
        const spots = canvasSpotsRef.current;
        const live = new Set(nodes.map((n) => n.id));
        for (const id of Array.from(spots.keys())) {
            if (!live.has(id)) spots.delete(id);
        }
        const placed = placeNotebookNodes(nodes, layout.positions, spots);
        if (placed !== nodes) setNodes((prev) => placeNotebookNodes(prev, layout.positions, spots));
    }, [notebookOn, nodes, layout, setNodes]);

    // After a switch, in either direction: the handles moved to the other
    // edge, so React Flow measures them again. Leaving the view brings back
    // the canvas viewport it was entered from, once the canvas props are live
    // (they are by the time effects run); MainCanvas holds the notebook's own
    // view at the origin.
    const firstRunRef = useRef(true);
    useEffect(() => {
        const ids = reactFlow.getNodes().map((n) => n.id);
        const frame = window.requestAnimationFrame(() => {
            if (ids.length > 0) updateNodeInternals(ids);
        });
        if (!notebookOn && !firstRunRef.current) {
            const saved = savedViewportRef.current;
            const sameDataflow = reactFlow.getNodes().some((n) => entryIdsRef.current.has(n.id));
            savedViewportRef.current = null;
            if (saved && sameDataflow) reactFlow.setViewport(saved);
            else fitViewWithMenuOffset(reactFlow, { padding: 0.2 });
        }
        firstRunRef.current = false;
        if (!dashboardOn) writeCanvasViewParam(canvasView);
        return () => window.cancelAnimationFrame(frame);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [notebookOn]);

    const setCanvasView = useCallback((view: CanvasView) => {
        if (dashboardOn) return;
        if (view === "notebook" && !notebookOnRef.current) {
            const current = reactFlow.getNodes();
            savedViewportRef.current = reactFlow.getViewport();
            entryIdsRef.current = new Set(current.map((n) => n.id));
            const spots = canvasSpotsRef.current;
            spots.clear();
            const slots = layoutFor(current, reactFlow.getEdges(), paneRef.current).positions;
            // Placed in the same update as the switch, so no frame shows the
            // canvas layout under the notebook's settings. React Flow's view
            // follows a frame or two later (see MainCanvas).
            setNodes((prev) => placeNotebookNodes(prev, slots, spots));
            const selected = current.find((n) => n.selected);
            if (selected) {
                pendingRevealRef.current = [selected.id];
                setRevealTick((t) => t + 1);
            } else {
                scrollerRef.current?.scrollTo({ top: 0 });
            }
        } else if (view === "canvas" && notebookOnRef.current) {
            const spots = new Map(canvasSpotsRef.current);
            canvasSpotsRef.current.clear();
            setNodes((prev) => restoreCanvasNodes(prev, spots));
        }
        setCanvasViewState(view);
    }, [dashboardOn, reactFlow, setNodes, layoutFor]);

    /**
     * A collaborator moved a node on their canvas. In the notebook view the
     * move belongs to the node's canvas spot, not its cell: true when it was
     * taken here, so the caller leaves `position` alone.
     */
    const takeCanvasPosition = useCallback((nodeId: string, position: XY): boolean => {
        if (!notebookOnRef.current) return false;
        canvasSpotsRef.current.set(nodeId, { x: position.x, y: position.y });
        return true;
    }, []);

    /**
     * Scroll a cell into view where the canvas would center on its node. False
     * on the canvas, so callers keep their own framing there. A node added in
     * the same moment is revealed once the layout has a slot for it; with
     * `ifMoved`, only when the change being made moves the cell (a new
     * connection can push its target further down the column).
     */
    const revealNodes = useCallback((ids: string[], options?: { ifMoved?: boolean }): boolean => {
        if (!notebookOnRef.current || ids.length === 0) return false;
        pendingRevealRef.current = ids;
        revealFromRef.current = options?.ifMoved ? layoutRef.current.positions.get(ids[0])?.y ?? null : null;
        setRevealTick((t) => t + 1);
        return true;
    }, []);

    useEffect(() => {
        const ids = pendingRevealRef.current;
        if (!notebookOn || !ids) return;
        const id = ids.find((candidate) => layout.positions.has(candidate));
        if (!id) return;
        const slot = layout.positions.get(id)!;
        const from = revealFromRef.current;
        pendingRevealRef.current = null;
        revealFromRef.current = null;
        if (from !== null && from === slot.y) return;
        scrollerRef.current?.scrollTo({
            top: Math.max(0, slot.y - pane.top - NOTEBOOK_MARGIN),
            behavior: "smooth",
        });
    }, [revealTick, layout, notebookOn, pane.top]);

    /** MainCanvas reports the scrolling pane and its overlays as they change. */
    const setNotebookPane = useCallback((next: NotebookPane) => {
        setPane((prev) =>
            Math.abs(prev.width - next.width) < 1 && Math.abs(prev.top - next.top) < 1 && Math.abs(prev.left - next.left) < 1
                ? prev
                : next);
    }, []);

    const registerNotebookScroller = useCallback((element: HTMLElement | null) => {
        scrollerRef.current = element;
    }, []);

    const notebookViewValue = useMemo<NotebookViewValue>(
        () => ({ on: notebookOn, laneX, cellWidth: layout.cellWidth, reveal: revealNodes }),
        [notebookOn, laneX, layout.cellWidth, revealNodes],
    );

    return {
        canvasView: notebookOn ? "notebook" as const : "canvas" as const,
        setCanvasView,
        notebookOn,
        notebookContentHeight: layout.contentHeight,
        notebookColumn: { x: layout.columnX, width: layout.cellWidth },
        notebookAddPoints: layout.addPoints,
        notebookViewValue,
        setNotebookPane,
        registerNotebookScroller,
        revealNodes,
        takeCanvasPosition,
    };
}
