import React from "react";

import "bootstrap/dist/css/bootstrap.min.css";

import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";
import { AccessLevelType, BoxType } from "../constants";
import { ConnectionValidator } from "../ConnectionValidator";
import { getNodeDescriptor } from "../registry";
import "./Box.css"

type DescriptionModalProps = {
    nodeId: string;
    boxType: BoxType;
    name?: string;
    description?: any;
    accessLevel?: AccessLevelType;
    show: boolean;
    handleClose: any;
    custom?: boolean;
};

function DescriptionModal({
    nodeId,
    boxType,
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

    const getTypeDescription = (boxType: BoxType) => {
        const descriptor = getNodeDescriptor(boxType);
        let linesText: string[] = [];

        const inputCardinality = descriptor.inputPorts.length > 0
            ? descriptor.inputPorts[0].cardinality ?? '1'
            : 'N/A';
        linesText.push("Input number: " + inputCardinality);

        if (ConnectionValidator._inputTypesSupported[boxType]?.length > 0)
            linesText.push(
                "Supported input types: " +
                    ConnectionValidator._inputTypesSupported[boxType].join(", ")
            );

        const outputCardinality = descriptor.outputPorts.length > 0
            ? descriptor.outputPorts[0].cardinality ?? '1'
            : 'N/A';
        linesText.push("Output number: " + outputCardinality);

        if (ConnectionValidator._outputTypesSupported[boxType]?.length > 0)
            linesText.push(
                "Supported output types: " +
                    ConnectionValidator._outputTypesSupported[boxType].join(", ")
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

    const boxLabel = (() => {
        try { return getNodeDescriptor(boxType).label; }
        catch { return boxType; }
    })();

    return (
        <>
            <Modal show={show} onHide={closeModal}>
                <Modal.Header closeButton>
                    <Modal.Title>Description</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>Box Type: {boxLabel}</p>
                    {custom != undefined && custom ? (
                        <p>Custom template: {name}</p>
                    ) : custom != undefined && !custom ? (
                        <p>Default template: {name}</p>
                    ) : null}
                    {description != undefined ? <p>{description}</p> : null}
                    {accessLevel != undefined ? (
                        <p>Access Level: {accessLevel}</p>
                    ) : null}
                    {getTypeDescription(boxType).map(
                        (line: string, index: number) => {
                            return (
                                <p
                                    key={
                                        "description_modal_" +
                                        nodeId +
                                        "_" +
                                        index
                                    }
                                >
                                    {line}
                                </p>
                            );
                        }
                    )}
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
