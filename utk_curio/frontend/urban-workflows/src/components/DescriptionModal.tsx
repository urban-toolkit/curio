import React from "react";

import "bootstrap/dist/css/bootstrap.min.css";

import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";
import { AccessLevelType, NodeType } from "../constants";
import { ConnectionValidator } from "../ConnectionValidator";
import { getNodeDescriptor } from "../registry";
import "./Node.css"

type DescriptionModalProps = {
    nodeId: string;
    nodeType: NodeType;
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
    const closeModal = () => {
        handleClose();
    };

    const getTypeDescription = (nodeType: NodeType) => {
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
      <>
        <Modal show={show} onHide={closeModal}>
          <Modal.Header closeButton>
            <Modal.Title>Description</Modal.Title>
          </Modal.Header>
          <Modal.Body>
            <p>Node Type: {nodeLabel}</p>
            {custom != undefined && custom ? (
              <p>Custom template: {name}</p>
            ) : custom != undefined && !custom ? (
              <p>Default template: {name}</p>
            ) : null}
            {description != undefined ? <p>{description}</p> : null}
            {accessLevel != undefined ? <p>Access Level: {accessLevel}</p> : null}
            {getTypeDescription(nodeType).map((line: string, index: number) => {
              return <p key={"description_modal_" + nodeId + "_" + index}>{line}</p>;
            })}
          </Modal.Body>
          <Modal.Footer>
            <Button variant="primary" onClick={closeModal}>
              Close
            </Button>
          </Modal.Footer>
        </Modal>
      </>
    );
}

export default DescriptionModal;
