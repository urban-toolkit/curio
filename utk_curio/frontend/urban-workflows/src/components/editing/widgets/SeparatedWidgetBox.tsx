/**
 * One widget's box in a dashboard tile whose widgets are separated
 * (nodeControlsOnly, "Separate widgets"): placed from the tile's corner, and,
 * while the layout is edited, moved by its grip and resized by its corner.
 * Only an owner edits a dashboard's layout, so the box needs no read-only
 * check of its own (NodeResizeHandle's).
 */
import React, { useEffect, useRef, useState } from "react";
import { useStore } from "reactflow";
import type { WidgetBoxLayout } from "../nodeControlsOnly";
import styles from "./WidgetTags.module.css";

const MIN_BOX_WIDTH = 120;
const MIN_BOX_HEIGHT = 40;

export function SeparatedWidgetBox({
    nodeId,
    name,
    box,
    defaultWidth,
    editable,
    onChange,
    header,
    boxRef,
    children,
}: {
    nodeId: string;
    name: string;
    box: WidgetBoxLayout;
    defaultWidth: number;
    editable: boolean;
    onChange: (box: WidgetBoxLayout) => void;
    header?: React.ReactNode;
    /** The box's element, which the tile measures to stack boxes not yet placed. */
    boxRef?: (el: HTMLDivElement | null) => void;
    children: React.ReactNode;
}) {
    // The box as it moves; the saved one once the drag ends.
    const [live, setLive] = useState<WidgetBoxLayout>(box);
    const boxKey = JSON.stringify(box);
    useEffect(() => setLive(box), [boxKey]);
    const liveRef = useRef(live);
    liveRef.current = live;
    const element = useRef<HTMLDivElement | null>(null);
    // A drag in screen pixels moves the box by that much over the zoom.
    const zoom = useStore((s) => s.transform[2]) || 1;

    /** A drag from the grip moves the box; from the corner, sizes it. */
    const startDrag = (mode: "move" | "resize") => (event: React.MouseEvent) => {
        if (!editable || event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        const el = element.current;
        const start = {
            x: event.clientX,
            y: event.clientY,
            box: liveRef.current,
            // Its size as saved, else as drawn.
            width: liveRef.current.width ?? (el?.offsetWidth || defaultWidth),
            height: liveRef.current.height ?? (el?.offsetHeight || MIN_BOX_HEIGHT),
        };
        const move = (e: MouseEvent) => {
            const dx = (e.clientX - start.x) / zoom;
            const dy = (e.clientY - start.y) / zoom;
            setLive(mode === "move"
                ? { ...start.box, x: start.box.x + dx, y: start.box.y + dy }
                : {
                    ...start.box,
                    width: Math.max(MIN_BOX_WIDTH, start.width + dx),
                    height: Math.max(MIN_BOX_HEIGHT, start.height + dy),
                });
        };
        const stop = () => {
            window.removeEventListener("mousemove", move);
            window.removeEventListener("mouseup", stop);
            onChange(liveRef.current);
        };
        window.addEventListener("mousemove", move);
        window.addEventListener("mouseup", stop);
    };

    return (
        <div
            ref={(el) => {
                element.current = el;
                boxRef?.(el);
            }}
            className={`nowheel nodrag ${styles.separatedBox}`}
            data-separated-widget={name}
            style={{
                left: `${live.x}px`,
                top: `${live.y}px`,
                width: `${live.width ?? defaultWidth}px`,
                height: live.height !== undefined ? `${live.height}px` : undefined,
            }}
        >
            {editable ? (
                <div
                    className={styles.separatedGrip}
                    title="Drag to move this widget"
                    aria-label={`Move widget ${name}`}
                    onMouseDown={startDrag("move")}
                >
                    {header}
                </div>
            ) : null}
            <div className={styles.separatedBody}>{children}</div>
            {editable ? (
                <div
                    id={`${nodeId}-widget-${name}-resizer`}
                    className="resizer nowheel nodrag"
                    aria-label={`Resize widget ${name}`}
                    onMouseDown={startDrag("resize")}
                />
            ) : null}
        </div>
    );
}
