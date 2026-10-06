// A node's run controls: Play, the Save output toggle and the run status, each
// drawn alone in the node's header, on the canvas and in a notebook cell alike:
// Play first, the status at the header's right, and the toggle among the node's
// tools. One component for all three, so every place runs the same code.
import React from "react";
import { Spinner } from "react-bootstrap";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCirclePlay } from "@fortawesome/free-solid-svg-icons";
import { ICodeData } from "../../types";
import { RUN_NODE_SHORTCUT_LABEL } from "../canvasKeyBindings";
import { SaveOutputToggle } from "./SaveOutputToggle";

export interface NodeRunControlsProps {
    nodeId: string;
    /** Which control. */
    part: "play" | "status" | "save";
    disablePlay: boolean;
    isLoading: boolean;
    output?: ICodeData;
    showSaveToggle: boolean;
    saveOutput: boolean;
    onSaveOutputChange: (next: boolean) => void;
    onPlay: () => void;
}

/** Play's size in the header. */
const HEADER_PLAY_PX = 22;

export function NodeRunControls({
    nodeId,
    part,
    disablePlay,
    isLoading,
    output,
    showSaveToggle,
    saveOutput,
    onSaveOutputChange,
    onPlay,
}: NodeRunControlsProps) {
    if (part === "play") {
        return disablePlay ? null : isLoading ? (
            <Spinner
                animation="border"
                size="sm"
                style={{
                    color: "rgb(251, 170, 105)",
                    width: `${HEADER_PLAY_PX - 4}px`,
                    height: `${HEADER_PLAY_PX - 4}px`,
                    marginTop: 0,
                    flexShrink: 0,
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
                    fontSize: `${HEADER_PLAY_PX}px`,
                    color: "rgb(251, 170, 105)",
                    flexShrink: 0,
                }}
                onClick={onPlay}
            />
        );
    }

    if (part === "save") {
        return showSaveToggle ? (
            <SaveOutputToggle
                variant="node"
                id={`save-output-${nodeId}`}
                checked={saveOutput}
                disabled={isLoading}
                onChange={onSaveOutputChange}
            />
        ) : null;
    }

    return output != undefined ? (
        <p
            style={{
                fontSize: "10px",
                textAlign: "center",
                marginBottom: 0,
                whiteSpace: "nowrap",
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
}
