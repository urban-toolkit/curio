import React from "react";
import ModalShell from "./ModalShell";
import content from "./modal-content.module.css";
import { AccessLevelType } from "../constants";
import { getNodeDescriptor } from "../registry";
import { NodeTemplateId } from "../registry/types";

type DescriptionModalProps = {
    nodeId: string;
    nodeType: NodeTemplateId;
    name?: string;
    description?: any;
    accessLevel?: AccessLevelType;
    show: boolean;
    handleClose: any;
    custom?: boolean;
};

/**
 * The modal's lines about one side's ports.
 *
 * A kind with one port reads as it always has: its cardinality, then the types
 * it takes. A kind with several says how many there are and lists each one's
 * types, so Spatial Join's two inputs do not read as "Input number: 1" and one
 * input taking GEODATAFRAME twice (#528).
 */
export function describePorts(
    ports: readonly { cardinality?: string; types: readonly string[] }[],
    side: "Input" | "Output",
): string[] {
    if (ports.length === 0) return [`${side} number: N/A`];
    if (ports.length === 1) {
        const [port] = ports;
        const lines = [`${side} number: ${port.cardinality ?? "1"}`];
        if (port.types.length > 0) {
            lines.push(`Supported ${side.toLowerCase()} types: ${port.types.join(", ")}`);
        }
        return lines;
    }
    return [
        `${side} number: ${ports.length}`,
        ...ports.map((port, index) => {
            const connections =
                port.cardinality && port.cardinality !== "1" ? ` (${port.cardinality})` : "";
            return `${side} ${index + 1}${connections}: ${port.types.join(", ")}`;
        }),
    ];
}

function DescriptionModal({
    nodeId,
    nodeType,
    name,
    description,
    accessLevel,
    show,
    handleClose,
    custom,
}: DescriptionModalProps) {
    if (!show) return null;

    const getTypeDescription = (nodeType: NodeTemplateId) => {
        const descriptor = getNodeDescriptor(nodeType);
        let linesText: string[] = [
            ...describePorts(descriptor.inputPorts, "Input"),
            ...describePorts(descriptor.outputPorts, "Output"),
        ];

        if (descriptor.hasCode) {
            linesText.push("Coding: Python");
        } else if (descriptor.hasGrammar) {
            linesText.push("Coding: Grammar");
        } else {
            linesText.push("Coding: N/A");
        }

        if (descriptor.hasWidgets) {
            linesText.push("Widgets: Yes");
        } else if (descriptor.hasGrammar) {
            linesText.push("Widgets: No");
        }

        linesText.push(descriptor.description);

        return linesText;
    };

    const nodeLabel = (() => {
        try { return getNodeDescriptor(nodeType).label; }
        catch { return nodeType; }
    })();

    return (
        <ModalShell onClose={handleClose} titleId="description-modal-title">
            <div className={content.content}>
                <h2 id="description-modal-title" className={content.title}>Description</h2>
                <div>
                    <p>Node Type: {nodeLabel}</p>
                    {custom != undefined && custom ? (
                        <p>Custom template: {name}</p>
                    ) : custom != undefined && !custom ? (
                        <p>Default template: {name}</p>
                    ) : null}
                    {description != undefined ? <p>{description}</p> : null}
                    {accessLevel != undefined ? <p>Access Level: {accessLevel}</p> : null}
                    {getTypeDescription(nodeType).map((line: string, index: number) => (
                        <p key={"description_modal_" + nodeId + "_" + index}>{line}</p>
                    ))}
                </div>
                <div className={content.buttonRow}>
                    <button className={content.primaryButton} onClick={handleClose}>
                        Close
                    </button>
                </div>
            </div>
        </ModalShell>
    );
}

export default DescriptionModal;
