import React, { useState } from "react";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";

import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";
import { AccessLevelType, BoxType } from "../constants";
import { ConnectionValidator } from "../ConnectionValidator";
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

    const boxNameTranslation = (boxType: BoxType) => {
        if (boxType == BoxType.COMPUTATION_ANALYSIS) {
            return "Computation Analysis";
        } else if (boxType == BoxType.CONSTANTS) {
            return "Constants";
        } else if (boxType == BoxType.DATA_CLEANING) {
            return "Data Cleaning";
        } else if (boxType == BoxType.DATA_EXPORT) {
            return "Data Export";
        } else if (boxType == BoxType.DATA_LOADING) {
            return "Data Loading";
        } else if (boxType == BoxType.DATA_POOL) {
            return "Data Pool";
        } else if (boxType == BoxType.DATA_TRANSFORMATION) {
            return "Data Transformation";
        } else if (boxType == BoxType.FLOW_SWITCH) {
            return "Flow Switch";
        } else if (boxType == BoxType.MERGE_FLOW) {
            return "Merge Flow";
        } else if (boxType == BoxType.VIS_IMAGE) {
            return "Image";
        } else if (boxType == BoxType.VIS_TABLE) {
            return "Table";
        } else if (boxType == BoxType.VIS_TEXT) {
            return "Text";
        } else if (boxType == BoxType.VIS_UTK) {
            return "UTK";
        } else if (boxType == BoxType.VIS_VEGA) {
            return "Vega-Lite";
        }
    };

    const getTypeDescription = (boxType: BoxType) => {
        let linesText = [];

        let inputNumber: any = {
            [BoxType.DATA_LOADING]: "N/A",
            [BoxType.DATA_EXPORT]: "1",
            [BoxType.DATA_CLEANING]: "1",
            [BoxType.DATA_TRANSFORMATION]: "[1,2]",
            [BoxType.COMPUTATION_ANALYSIS]: "[1,n]",
            [BoxType.FLOW_SWITCH]: "2",
            [BoxType.VIS_UTK]: "[1,n]",
            [BoxType.VIS_VEGA]: "1",
            [BoxType.VIS_TABLE]: "1",
            [BoxType.VIS_TEXT]: "1",
            [BoxType.VIS_IMAGE]: "1",
            [BoxType.CONSTANTS]: "N/A",
            [BoxType.DATA_POOL]: "1",
        };

        linesText.push("Input number: " + inputNumber[boxType]);

        if (ConnectionValidator._inputTypesSupported[boxType].length > 0)
            linesText.push(
                "Supported input types: " +
                    ConnectionValidator._inputTypesSupported[boxType].join(", ")
            );

        let outputNumber: any = {
            [BoxType.DATA_LOADING]: "[1,n]",
            [BoxType.DATA_EXPORT]: "N/A",
            [BoxType.DATA_CLEANING]: "1",
            [BoxType.DATA_TRANSFORMATION]: "[1,2]",
            [BoxType.COMPUTATION_ANALYSIS]: "[1,n]",
            [BoxType.FLOW_SWITCH]: "1",
            [BoxType.VIS_UTK]: "[1,n]",
            [BoxType.VIS_VEGA]: "1",
            [BoxType.VIS_TABLE]: "1",
            [BoxType.VIS_TEXT]: "1",
            [BoxType.VIS_IMAGE]: "1",
            [BoxType.CONSTANTS]: "1",
            [BoxType.DATA_POOL]: "1",
        };

        let codeMap: any = {
            [BoxType.DATA_LOADING]: 1,
            [BoxType.DATA_EXPORT]: 1,
            [BoxType.DATA_CLEANING]: 1,
            [BoxType.DATA_TRANSFORMATION]: 1,
            [BoxType.COMPUTATION_ANALYSIS]: 1,
            [BoxType.FLOW_SWITCH]: -1,
            [BoxType.VIS_UTK]: 0,
            [BoxType.VIS_VEGA]: 0,
            [BoxType.VIS_TABLE]: -1,
            [BoxType.VIS_TEXT]: -1,
            [BoxType.VIS_IMAGE]: -1,
            [BoxType.CONSTANTS]: -1,
            [BoxType.DATA_POOL]: -1,
        };

        let widgetsMap: any = {
            [BoxType.DATA_LOADING]: true,
            [BoxType.DATA_EXPORT]: true,
            [BoxType.DATA_CLEANING]: true,
            [BoxType.DATA_TRANSFORMATION]: true,
            [BoxType.COMPUTATION_ANALYSIS]: true,
            [BoxType.FLOW_SWITCH]: true,
            [BoxType.VIS_UTK]: true,
            [BoxType.VIS_VEGA]: true,
            [BoxType.VIS_TABLE]: false,
            [BoxType.VIS_TEXT]: true,
            [BoxType.VIS_IMAGE]: false,
            [BoxType.CONSTANTS]: true,
            [BoxType.DATA_POOL]: false,
        };

        let purposeMap: any = {
            [BoxType.DATA_LOADING]:
                "The Data Loading box is responsible for getting data from the outside world into the workflow.",
            [BoxType.DATA_EXPORT]:
                "The Export box is responsible for getting data from the workflow to the outside world.",
            [BoxType.DATA_CLEANING]:
                "The Data Cleaning box is reponsible for performing cleaning operations on the data.",
            [BoxType.DATA_TRANSFORMATION]:
                "The Data Transformation box is responsible for performing any kinds of transformations to the data.",
            [BoxType.COMPUTATION_ANALYSIS]:
                "The Computation Analysis box is the box generic box responsible for performing any kinds of computations.",
            [BoxType.FLOW_SWITCH]:
                "The Flow Switch box is responsible for choosing which incoming data flow will be passed forward to the next box",
            [BoxType.VIS_UTK]:
                "The Urban Toolkit box is responsible for visualizing geolocated data.",
            [BoxType.VIS_VEGA]:
                "The Vega box is responsible for visualizing 2D plots.",
            [BoxType.VIS_TABLE]:
                "The Table box is responsible for displaying DataFrames and GeoDataFrames in a tabular format.",
            [BoxType.VIS_TEXT]:
                "The Text box is responsible for displaying text.",
            [BoxType.VIS_IMAGE]:
                "The Image box is responsible for displaying images.",
            [BoxType.CONSTANTS]: "The Constant box stores a constant.",
            [BoxType.DATA_POOL]:
                "The Data Pool is reponsible for storing data that can be interacted by all connected visualizations. Interactions can also be propagated to other Data Pools.",
        };

        linesText.push("Output number: " + outputNumber[boxType]);

        if (ConnectionValidator._outputTypesSupported[boxType].length > 0)
            linesText.push(
                "Supported output types: " +
                    ConnectionValidator._outputTypesSupported[boxType].join(
                        ", "
                    )
            );

        if (codeMap[boxType] == 1) {
            linesText.push("Coding: Python");
        } else if (codeMap[boxType] == 0) {
            linesText.push("Coding: Grammar");
        } else {
            linesText.push("Coding: N/A");
        }

        if (widgetsMap[boxType]) {
            linesText.push("Widgets: Yes");
        } else if (codeMap[boxType] == 0) {
            linesText.push("Widgets: No");
        }

        linesText.push(purposeMap[boxType]);

        return linesText;
    };

    return (
        <>
            <Modal show={show} onHide={closeModal}>
                <Modal.Header closeButton>
                    <Modal.Title>Description</Modal.Title>
                </Modal.Header>
                <Modal.Body>
                    <p>Box Type: {boxNameTranslation(boxType)}</p>
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
