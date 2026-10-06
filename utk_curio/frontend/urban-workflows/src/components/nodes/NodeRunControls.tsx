// A node's run controls: Play, the Save output toggle and the run status. The
// canvas draws all three in the node's bottom row; a notebook cell draws Play
// first in its header, the status at the header's right, and the toggle among
// the cell's tools. One component for both, so both run the same code.
import React from "react";
import { Spinner } from "react-bootstrap";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCirclePlay } from "@fortawesome/free-solid-svg-icons";
import { ICodeData } from "../../types";
import { RUN_NODE_SHORTCUT_LABEL } from "../canvasKeyBindings";
import { SaveOutputToggle } from "./SaveOutputToggle";

export interface NodeRunControlsProps {
    nodeId: string;
    /**
     * Which controls: all three in the canvas's bottom row (the default), or
     * one of them alone (a notebook cell's header).
     */
    part?: "row" | "play" | "status" | "save";
    disablePlay: boolean;
    isLoading: boolean;
    output?: ICodeData;
    showSaveToggle: boolean;
    saveOutput: boolean;
    onSaveOutputChange: (next: boolean) => void;
    onPlay: () => void;
}

/** In a cell's header, which is shorter than the canvas's bottom row. */
const HEADER_PLAY_PX = 22;

export function NodeRunControls({
    nodeId,
    part = "row",
    disablePlay,
    isLoading,
    output,
    showSaveToggle,
    saveOutput,
    onSaveOutputChange,
    onPlay,
}: NodeRunControlsProps) {
    const inHeader = part !== "row";
    const playSize = inHeader ? HEADER_PLAY_PX : 27;

    const play = disablePlay ? null : isLoading ? (
        <Spinner
            animation="border"
            size="sm"
            style={{
                color: "rgb(251, 170, 105)",
                width: inHeader ? `${HEADER_PLAY_PX - 4}px` : "24px",
                height: inHeader ? `${HEADER_PLAY_PX - 4}px` : "24px",
                marginTop: inHeader ? 0 : "2px",
                ...(inHeader ? { flexShrink: 0 } : {}),
            }}
        />
    ) : (
        <FontAwesomeIcon
            className={"nowheel nodrag"}
            icon={faCirclePlay}
            // The shortcut is only useful if it
            // is discoverable, and the play
            // button is where someone looks for
            // "how do I run this" (#223).
            title={`Run this node (${RUN_NODE_SHORTCUT_LABEL})`}
            style={{
                cursor: "pointer",
                fontSize: `${playSize}px`,
                color: "rgb(251, 170, 105)",
                ...(inHeader ? { flexShrink: 0 } : {}),
            }}
            onClick={onPlay}
        />
    );

    const toggle = showSaveToggle ? (
        <SaveOutputToggle
            variant="node"
            id={`save-output-${nodeId}`}
            checked={saveOutput}
            disabled={isLoading}
            onChange={onSaveOutputChange}
        />
    ) : null;

    const status = output != undefined ? (
        <p
            style={{
                fontSize: "10px",
                textAlign: "center",
                marginBottom: 0,
                ...(inHeader ? { whiteSpace: "nowrap" } : {}),
            }}
        >
            {output.code == "success" ? (
                <span style={{ color: "green" }}>
                    Done
                </span>
            ) : output.code == "exec" ? (
                <>
                    <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
                    {' '}
                </>
            ) : output.code == "error" ? (
                <span style={{ color: "red" }}>
                    Error
                </span>
            ) : (
                ""
            )}
        </p>
    ) : null;

    if (part === "play") return play;
    if (part === "status") return status;
    if (part === "save") return toggle;
    return (
        <Row style={{gap: "8px", paddingRight: 0}}>
            {play ?
                <Col md={3} style={{padding: 0}}>
                    {play}
                </Col> : null
            }
            {toggle ? (
                <Col md="auto" style={{ padding: 0, display: "flex", alignItems: "center" }}>
                    {toggle}
                </Col>
            ) : null}
            {status ? (
                <Col
                    md={2}
                    className="d-flex align-items-center"
                    style={{padding: 0}}
                >
                    {status}
                </Col>
            ) : null}
        </Row>
    );
}
