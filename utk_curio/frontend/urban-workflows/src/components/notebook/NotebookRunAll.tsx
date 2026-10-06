// The notebook view's Run all: the rail's button, at the top right of the page,
// since the notebook view has no rail to hold it.
import React from "react";
import { RunAllButton } from "../menus/nodes/RunAllButton";
import styles from "./NotebookRunAll.module.css";

export function NotebookRunAll() {
    return (
        <div id="notebook-run-all" className={styles.dock}>
            <RunAllButton />
        </div>
    );
}
