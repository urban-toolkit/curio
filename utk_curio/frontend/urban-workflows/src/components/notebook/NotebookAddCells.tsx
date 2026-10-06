// The notebook view's (+): one in the gap below every cell, the last one's
// included. It opens the canvas's left rail as one row under it, the notebook
// view having no rail of its own: a click on a node tile adds that node as a
// cell reading the output of the cell above the (+), and the catalogs and Run
// All work as in the rail.
import React, { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useReactFlow, type Node } from "reactflow";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faPlus } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../providers/FlowProvider";
import { useCode } from "../../hook/useCode";
import { usePosition } from "../../hook/usePosition";
import { tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import { ConnectionValidator } from "../../ConnectionValidator";
import { NodeType } from "../../constants";
import { getUnversionedFlowNodeType, unversionedNodeType } from "../../utils/flowNodeCanonicalType";
import { addedCellConnection, type CellEnd } from "../../utils/notebookAddCell";
import ToolsMenu from "../menus/nodes/ToolsMenu";
import styles from "./NotebookAddCells.module.css";

const ADD_SIZE = 22;
/** Below this share of the window, the page scrolls the (+) up before its menu opens, so the menu and its catalog panels have room. */
const MENU_ROOM = 0.45;
/** Where the (+) goes when the page scrolls it up: under the top bar and title. */
const MENU_ANCHOR_TOP = 150;
/** React Flow has the new node a frame or two after it is added; the wiring waits this many frames for it. */
const WIRE_FRAMES = 30;

function cellEnd(node: Node): CellEnd {
    const nodeType = String(node.data?.nodeType ?? "");
    return {
        id: node.id,
        nodeType: getUnversionedFlowNodeType(node),
        handles: tryGetNodeDescriptor(nodeType)?.adapter?.handles ?? [],
    };
}

const compatible = (outType: string, inType: string) =>
    ConnectionValidator.checkBoxCompatibility(unversionedNodeType(outType) as NodeType, unversionedNodeType(inType) as NodeType);

export function NotebookAddCells({ scrollerRef }: { scrollerRef: React.RefObject<HTMLElement | null> }) {
    const { notebookAddPoints, notebookColumn, onConnect, revealNodes, markDirty } = useFlowContext();
    const { createCodeNode } = useCode();
    const { getPosition } = usePosition();
    const reactFlow = useReactFlow();
    const [open, setOpen] = useState<{ after: string; top: number; left: number } | null>(null);

    const close = useCallback(() => setOpen(null), []);

    // Escape, or a press anywhere but the menu (its catalog panels included)
    // and the (+) buttons, closes it.
    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") close();
        };
        const onPress = (event: PointerEvent) => {
            const target = event.target as Element | null;
            if (!target) return;
            if (target.closest("#tools-palette-dock") || target.closest("[data-curio-add-after]")) return;
            close();
        };
        window.addEventListener("keydown", onKey);
        window.addEventListener("pointerdown", onPress, true);
        return () => {
            window.removeEventListener("keydown", onKey);
            window.removeEventListener("pointerdown", onPress, true);
        };
    }, [open, close]);

    const openBelow = (after: string, button: HTMLElement) => {
        if (open?.after === after) {
            close();
            return;
        }
        const scroller = scrollerRef.current;
        let rect = button.getBoundingClientRect();
        if (scroller && rect.top > window.innerHeight * MENU_ROOM) {
            const shift = rect.top - MENU_ANCHOR_TOP;
            scroller.scrollTop += shift;
            rect = button.getBoundingClientRect();
        }
        const columnLeft = scroller ? scroller.getBoundingClientRect().left + notebookColumn.x : rect.left;
        setOpen({ after, top: Math.round(rect.bottom + 6), left: Math.round(Math.max(16, columnLeft)) });
    };

    // The new node is wired from the cell above once React Flow has it, then
    // its cell is scrolled into view where the order puts it.
    const wireBelow = useCallback((aboveId: string, added: Node, frame = 0) => {
        const placed = reactFlow.getNode(added.id);
        if (!placed && frame < WIRE_FRAMES) {
            window.requestAnimationFrame(() => wireBelow(aboveId, added, frame + 1));
            return;
        }
        const above = reactFlow.getNode(aboveId);
        const connection = placed && above ? addedCellConnection(cellEnd(above), cellEnd(placed), compatible) : null;
        if (connection) onConnect(connection);
        revealNodes([added.id]);
    }, [reactFlow, onConnect, revealNodes]);

    const addBelow = useCallback((nodeType: string) => {
        if (!open) return;
        // `createCodeNode` hands back the node it added (typed as void).
        const added = createCodeNode(nodeType, { position: getPosition() }) as unknown as Node | undefined;
        markDirty();
        close();
        if (added) wireBelow(open.after, added);
    }, [open, createCodeNode, getPosition, markDirty, close, wireBelow]);

    return (
        <>
            {notebookAddPoints.map((point) => (
                <button
                    key={point.after}
                    type="button"
                    className={`${styles.add} nodrag nopan${open?.after === point.after ? ` ${styles.addOpen}` : ""}`}
                    style={{
                        top: point.y - ADD_SIZE / 2,
                        left: notebookColumn.x + notebookColumn.width / 2 - ADD_SIZE / 2,
                        width: ADD_SIZE,
                        height: ADD_SIZE,
                    }}
                    data-curio-add-after={point.after}
                    title="Add a cell"
                    aria-label="Add a cell"
                    aria-expanded={open?.after === point.after}
                    onClick={(event) => openBelow(point.after, event.currentTarget)}
                >
                    <FontAwesomeIcon icon={faPlus} />
                </button>
            ))}
            {open
                ? createPortal(
                    <div className={styles.menu}>
                        <ToolsMenu layout="row" onPickTile={addBelow} style={{ top: open.top, left: open.left }} />
                    </div>,
                    document.body,
                )
                : null}
        </>
    );
}
