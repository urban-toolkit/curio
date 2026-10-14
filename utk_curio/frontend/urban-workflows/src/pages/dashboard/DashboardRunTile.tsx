// The dashboard's Run button: Run All, as the canvas rail's button runs it,
// on a card of its own that the owner moves and resizes with Edit layout.
//
// It is no node of the dataflow, and deliberately no React Flow node either:
// Run All, a save and every graph helper read `reactFlow.getNodes()`, so a node
// there would be run, waited on and saved as part of the dataflow. It is drawn
// over the canvas instead, at its place and size in the page's coordinates
// (`dataflow.dashboard.runButton`, utils/dashboardSettings) carried through the
// viewport, so it pans and zooms with the tiles. While the layout is edited the
// whole card drags, and its corner resizes it; a click that did not move it
// still runs.
import React, { useRef } from "react";
import { useViewport } from "reactflow";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPlay, faStop } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../providers/FlowProvider";
import { RUN_BUTTON_MIN_SIZE, type RunButtonPlace } from "../../utils/dashboardSettings";
import styles from "./DashboardRunTile.module.css";

/** The least room kept between the card and the canvas's top-left edge. */
const EDGE = 8;

/** How far the pointer goes before a press on the card is a drag, not a click. */
const DRAG_THRESHOLD = 3;

export interface DashboardRunTileProps {
    /** Where the card stands and how big it is, in the page's coordinates. */
    place: Required<RunButtonPlace>;
    /** The layout is being edited: the card can be dragged and resized. */
    movable: boolean;
    /** While a drag or a resize goes, each place the card passes. */
    onPreview: (place: Required<RunButtonPlace>) => void;
    /** Where, and how big, the drag or the resize left it. */
    onCommit: (place: Required<RunButtonPlace>) => void;
}

type Gesture = {
    kind: "move" | "resize";
    pointerX: number;
    pointerY: number;
    from: Required<RunButtonPlace>;
    at: Required<RunButtonPlace>;
    moved: boolean;
};

export function DashboardRunTile({ place, movable, onPreview, onCommit }: DashboardRunTileProps) {
    const { x: panX, y: panY, zoom } = useViewport();
    const { playAllNodes, isRunActive, serverRunActive, cancelRun } = useFlowContext();
    const running = isRunActive || serverRunActive;
    const gestureRef = useRef<Gesture | null>(null);
    // A press that became a drag must not also run when it is released.
    const suppressClickRef = useRef(false);

    const scale = zoom || 1;
    // Kept on the canvas: a place panned or fitted out of view still shows.
    const left = Math.max(EDGE, place.x * scale + panX);
    const top = Math.max(EDGE, place.y * scale + panY);
    const width = place.width * scale;
    const height = place.height * scale;
    const iconSize = Math.max(10, Math.min(width, height) * 0.4);

    const begin = (kind: Gesture["kind"]) => (event: React.PointerEvent<HTMLElement>) => {
        if (!movable || event.button !== 0) return;
        event.stopPropagation();
        event.currentTarget.setPointerCapture?.(event.pointerId);
        gestureRef.current = { kind, pointerX: event.clientX, pointerY: event.clientY, from: place, at: place, moved: false };
    };
    const onPointerMove = (event: React.PointerEvent<HTMLElement>) => {
        const gesture = gestureRef.current;
        if (!gesture) return;
        const dx = event.clientX - gesture.pointerX;
        const dy = event.clientY - gesture.pointerY;
        if (!gesture.moved && Math.abs(dx) < DRAG_THRESHOLD && Math.abs(dy) < DRAG_THRESHOLD) return;
        gesture.moved = true;
        gesture.at = gesture.kind === "move"
            ? { ...gesture.from, x: gesture.from.x + dx / scale, y: gesture.from.y + dy / scale }
            : {
                ...gesture.from,
                width: Math.max(RUN_BUTTON_MIN_SIZE.width, gesture.from.width + dx / scale),
                height: Math.max(RUN_BUTTON_MIN_SIZE.height, gesture.from.height + dy / scale),
            };
        onPreview(gesture.at);
    };
    const end = (event: React.PointerEvent<HTMLElement>) => {
        const gesture = gestureRef.current;
        if (!gesture) return;
        gestureRef.current = null;
        event.currentTarget.releasePointerCapture?.(event.pointerId);
        if (!gesture.moved) return;
        suppressClickRef.current = true;
        onCommit(gesture.at);
    };

    const onClick = () => {
        if (suppressClickRef.current) {
            suppressClickRef.current = false;
            return;
        }
        if (running) cancelRun();
        else playAllNodes();
    };

    return (
        <div
            className={`${styles.tile} nodrag nowheel`}
            style={{ left, top, width, height }}
            data-editing={movable ? "true" : undefined}
            data-testid="dashboard-run-tile"
            onPointerDown={begin("move")}
            onPointerMove={onPointerMove}
            onPointerUp={end}
            onPointerCancel={end}
        >
            <button
                type="button"
                className={styles.button}
                style={{ fontSize: iconSize }}
                data-run-active={running ? "true" : undefined}
                onClick={onClick}
                title={running ? "Cancel the run in progress" : "Run the dataflow with the values shown"}
                aria-label={running ? "Cancel run" : "Run"}
                data-testid="dashboard-run-btn"
            >
                <FontAwesomeIcon icon={running ? faStop : faPlay} />
            </button>
            {movable ? (
                <span
                    className={styles.resize}
                    title="Drag to resize the Run button"
                    data-testid="dashboard-run-resize"
                    onPointerDown={begin("resize")}
                    onPointerMove={onPointerMove}
                    onPointerUp={end}
                    onPointerCancel={end}
                />
            ) : null}
        </div>
    );
}

export default DashboardRunTile;
