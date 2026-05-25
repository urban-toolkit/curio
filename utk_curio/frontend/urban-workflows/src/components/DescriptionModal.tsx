import React from "react";
import ModalShell from "./ModalShell";
import content from "./modal-content.module.css";
import { AccessLevelType, NodeType } from "../constants";
import { ConnectionValidator } from "../ConnectionValidator";
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
        let linesText: string[] = [];

        const inputCardinality = descriptor.inputPorts.length > 0
            ? descriptor.inputPorts[0].cardinality ?? '1'
            : 'N/A';
        linesText.push("Input number: " + inputCardinality);

        if (ConnectionValidator._inputTypesSupported[nodeType]?.length > 0)
            linesText.push(
                "Supported input types: " +
                    ConnectionValidator._inputTypesSupported[nodeType].join(", ")
            );

        const outputCardinality = descriptor.outputPorts.length > 0
            ? descriptor.outputPorts[0].cardinality ?? '1'
            : 'N/A';
        linesText.push("Output number: " + outputCardinality);

        if (ConnectionValidator._outputTypesSupported[nodeType]?.length > 0)
            linesText.push(
                "Supported output types: " +
                    ConnectionValidator._outputTypesSupported[nodeType].join(", ")
            );

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
        <ModalShell onClose={handleClose}>
            <div className={content.content}>
                <h2 className={content.title}>Description</h2>
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
