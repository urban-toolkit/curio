// Run all: the canvas's rail draws it at its foot, and the notebook view, which
// has no rail, at the top right of its page. One button for both.
import React from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faForwardStep, faStop } from "@fortawesome/free-solid-svg-icons";
import { useFlowContext } from "../../../providers/FlowProvider";
import styles from "./ToolsMenu.module.css";

export function RunAllButton() {
    const { playAllNodes, isRunActive: browserRunActive, serverRunActive, cancelRun } = useFlowContext();
    const isRunActive = browserRunActive || serverRunActive;
    return (
        <div className={styles.playAllRow}>
            {/* One button, two states: while a run is in flight it cancels
                it. The guard used to be invisible, so the only sign a run
                was stuck was that clicks did nothing (#271). */}
            <button
                type="button"
                className={styles.playAllButton}
                data-run-active={isRunActive ? "true" : undefined}
                onClick={isRunActive ? cancelRun : playAllNodes}
                title={isRunActive ? "Cancel the run in progress" : "Run all nodes"}
                aria-label={isRunActive ? "Cancel run" : "Run all nodes"}
            >
                <FontAwesomeIcon icon={isRunActive ? faStop : faForwardStep} />
            </button>
        </div>
    );
}
