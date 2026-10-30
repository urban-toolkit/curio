/**
 * Every other peer's drag on the canvas (`providers/collab/agentDrags.ts`): an
 * agent's cursor, in its category's tint with its name, carrying a ghost of what
 * it drags from this tab's own start to the drop point, the drop at its point of
 * the dataflow through every pan and zoom.
 *
 * The drags are drawn on the pan-and-zoom plane the pointers are drawn on, in a
 * layer of their own over the tool rail and the catalog drawers, since a drag
 * starts in them. Mounted by `CanvasCursors`, a child of React Flow, which it
 * reads the view and the nodes from. On a canvas no doc binds, the drags are
 * those a run's change events play (`changeDragStates`).
 */
import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useStore, useStoreApi, type ReactFlowState } from "reactflow";
import type { Awareness } from "y-protocols/awareness";

import {
    AGENT_DRAGS_ATTR,
    DragTracker,
    changeDragStates,
    dragPoint,
    dragStart,
    motionEndsAt,
    sameDrags,
    subscribeChangeDrags,
    type DragGhost,
    type PlayedDrag,
    type StartPage,
} from "../../providers/collab/agentDrags";
import { othersOf } from "../../providers/collab/presence";
import { CanvasCursor, CursorPlane } from "../scenarios/ScenarioLayers";
import styles from "./AgentDrags.module.css";

const NONE: PlayedDrag[] = [];
const canvasOf = (s: ReactFlowState) => s.domNode;

function prefersReducedMotion(): boolean {
    return typeof window !== "undefined" && typeof window.matchMedia === "function"
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The drags others in *awareness* are playing, and those runs' change events
 *  play on a canvas no doc binds, each with its start in this tab, read from
 *  the page when it arrives. */
function usePlayedDrags(awareness: Awareness | null): PlayedDrag[] {
    const store = useStoreApi();
    const [drags, setDrags] = useState<PlayedDrag[]>(NONE);
    useEffect(() => {
        const page: StartPage = {
            document,
            nodeBox: (id) => {
                const node = store.getState().nodeInternals.get(id);
                if (!node) return null;
                const at = node.positionAbsolute ?? node.position;
                return { x: at.x, y: at.y, width: node.width ?? 0, height: node.height ?? 0 };
            },
        };
        const tracker = new DragTracker((carrying) => dragStart(carrying, page), prefersReducedMotion);
        const read = () => {
            const next = tracker.read([...othersOf(awareness), ...changeDragStates()], Date.now());
            setDrags((prev) => (sameDrags(prev, next) ? prev : next.length ? next : NONE));
        };
        read();
        awareness?.on("change", read);
        const unsubscribe = subscribeChangeDrags(read);
        return () => {
            awareness?.off("change", read);
            unsubscribe();
        };
    }, [awareness, store]);
    return drags;
}

/** This tab's clock, read on every frame until the last of *drags* reaches its
 *  drop point. */
function useMotionClock(drags: readonly PlayedDrag[]): number {
    const [now, setNow] = useState(Date.now);
    const endsAt = drags.reduce((last, drag) => Math.max(last, motionEndsAt(drag) ?? 0), 0);
    useEffect(() => {
        setNow(Date.now());
        if (endsAt <= Date.now()) return;
        let frame = 0;
        const tick = () => {
            const at = Date.now();
            setNow(at);
            if (at < endsAt) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frame);
    }, [endsAt]);
    return now;
}

/** The copy of a tile, row or card, the size it has on the page. */
function GhostCopy({ ghost, zoom }: { ghost: Extract<DragGhost, { kind: "copy" }>; zoom: number }) {
    const hold = useCallback(
        (holder: HTMLDivElement | null) => {
            if (holder && holder.firstChild !== ghost.element) holder.replaceChildren(ghost.element);
        },
        [ghost.element],
    );
    return (
        <div
            ref={hold}
            className={styles.copy}
            data-agent-ghost="copy"
            style={{ width: ghost.width, height: ghost.height, transform: `scale(${1 / zoom})` }}
        />
    );
}

function Ghost({ ghost, color, zoom }: { ghost: DragGhost; color: string; zoom: number }) {
    if (ghost.kind === "copy") return <GhostCopy ghost={ghost} zoom={zoom} />;
    return (
        <div
            className={styles.outline}
            data-agent-ghost="outline"
            style={{ width: ghost.width, height: ghost.height, borderColor: color, color }}
        >
            {ghost.label ? (
                <span className={styles.outlineLabel} style={{ backgroundColor: color }}>
                    {ghost.label}
                </span>
            ) : null}
        </div>
    );
}

export const AgentDrags = React.memo(function AgentDrags({ awareness }: { awareness: Awareness | null }) {
    const drags = usePlayedDrags(awareness);
    const now = useMotionClock(drags);
    const canvas = useStore(canvasOf);
    if (drags.length === 0 || !canvas) return null;
    const box = canvas.getBoundingClientRect();
    const origin = { x: box.left, y: box.top };
    return createPortal(
        <CursorPlane className={styles.layer} origin={origin} markers={{ [AGENT_DRAGS_ATTR]: "true" }}>
            {(view) =>
                drags.map((drag) => {
                    const at = dragPoint(drag, now, origin, view);
                    return (
                        <div
                            key={drag.key}
                            className={styles.drag}
                            data-agent-drag={drag.clientId}
                            data-drag-kind={drag.carrying.kind}
                            data-drag-start={drag.start.from}
                            style={{ left: at.x, top: at.y }}
                        >
                            <Ghost ghost={drag.start.ghost} color={drag.color} zoom={view[2]} />
                            <CanvasCursor
                                x={0}
                                y={0}
                                name={drag.name}
                                color={drag.color}
                                zoom={view[2]}
                                markers={{ "data-agent-cursor": drag.clientId }}
                            />
                        </div>
                    );
                })
            }
        </CursorPlane>,
        document.body,
    );
});
