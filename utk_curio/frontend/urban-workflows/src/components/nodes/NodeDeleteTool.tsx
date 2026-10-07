import React from "react";
import type CSS from "csstype";
import { faXmark } from "@fortawesome/free-solid-svg-icons";
import { HeaderIconButton } from "../HeaderIconButton";
import { useGraphEditGates } from "../../hook/useGraphEditGates";

/**
 * A node's Delete node tool, among its header's tools and on an icon-only
 * node's chip. Nodes are deleted where they are added and connected, on a
 * canvas the viewer edits (`graphEditGates`, the rule the Delete key follows):
 * a notebook cell has no such tool, nor does a node on a read-only canvas.
 */
export function NodeDeleteTool({ style, onDelete }: { style?: CSS.Properties; onDelete: () => void }) {
    const graphEdits = useGraphEditGates();
    if (!graphEdits.delete) return null;
    return <HeaderIconButton icon={faXmark} style={style} title="Delete node" onActivate={onDelete} />;
}
