import React, { RefObject, useEffect, useRef } from "react";
import { MIN_NODE_HEIGHT, MIN_NODE_WIDTH } from "../../constants";
import { useSharedView } from "../../hook/useSharedView";

/**
 * The handle at a node's bottom-right corner. A drag from it resizes the node's
 * box as the pointer moves, no smaller than the least node size, and the
 * release hands the box's final size to `onResizeEnd`.
 *
 * A read-only canvas (`useSharedView`) keeps every node at its size: there the
 * handle is not drawn and nothing listens for a drag. Only an owner resizes.
 */
export function NodeResizeHandle({
    nodeId,
    box,
    disabled = false,
    onResize,
    onResizeEnd,
}: {
    nodeId: string;
    /** The node's box, which the drag sizes. */
    box: RefObject<HTMLElement | null>;
    /** Drawn, but takes no press (a suggested node). */
    disabled?: boolean;
    onResize: (width: number, height: number) => void;
    onResizeEnd: (width: number, height: number) => void;
}) {
    const readOnly = useSharedView();
    const handleRef = useRef<HTMLDivElement>(null);
    // The latest callbacks, so a drag reports to the node's current state.
    const callbacks = useRef({ onResize, onResizeEnd });
    callbacks.current = { onResize, onResizeEnd };

    useEffect(() => {
        const handle = handleRef.current;
        if (readOnly || !handle) return;

        let startX = 0;
        let startY = 0;
        let startWidth = 0;
        let startHeight = 0;

        function resize(e: MouseEvent) {
            const el = box.current;
            if (!el) return;
            const width = Math.max(MIN_NODE_WIDTH, startWidth + (e.clientX - startX));
            const height = Math.max(MIN_NODE_HEIGHT, startHeight + (e.clientY - startY));
            el.style.width = width + "px";
            el.style.height = height + "px";
            callbacks.current.onResize(width, height);
        }

        function stopResize() {
            window.removeEventListener("mousemove", resize, false);
            window.removeEventListener("mouseup", stopResize, false);
            const el = box.current;
            if (!el) return;
            callbacks.current.onResizeEnd(el.offsetWidth, el.offsetHeight);
        }

        function initResize(e: MouseEvent) {
            const el = box.current;
            if (!el) return;
            startX = e.clientX;
            startY = e.clientY;
            startWidth = el.offsetWidth;
            startHeight = el.offsetHeight;
            window.addEventListener("mousemove", resize, false);
            window.addEventListener("mouseup", stopResize, false);
        }

        handle.addEventListener("mousedown", initResize, false);
        return () => {
            handle.removeEventListener("mousedown", initResize, false);
            window.removeEventListener("mousemove", resize, false);
            window.removeEventListener("mouseup", stopResize, false);
        };
    }, [readOnly, box]);

    if (readOnly) return null;
    return (
        <div
            ref={handleRef}
            id={nodeId + "resizer"}
            className="resizer nowheel nodrag"
            style={disabled ? { pointerEvents: "none" } : {}}
        />
    );
}
