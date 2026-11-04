import React from "react";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCircleCheck, faFloppyDisk } from "@fortawesome/free-solid-svg-icons";

import { useFlowContext } from "../../../providers/FlowProvider";
import { useCollab } from "../../../providers/CollaborationProvider";
import { useSaveState, type SaveState } from "../../../providers/flow/useSaveState";
import headerStyles from "../../layout/GlobalPageHeader.module.css";
import styles from "./UpMenu.module.css";

const LABEL: Record<SaveState, string> = {
    saved: "Saved",
    saving: "Saving...",
    offline: "Offline",
    unsaved: "Unsaved",
};

/**
 * The top bar's save status, always present on a dataflow you own, so its
 * absence never has to be interpreted.
 *
 * On a dataflow bound to its doc it reads Saved once the server has every
 * change, Saving... while some are on their way, and Offline while the tab
 * cannot reach the server. A dataflow not saved yet reads Unsaved, and so does
 * any canvas bound to no doc that holds changes no one keeps. The word says
 * it as well as the colour, so the state does not rest on telling two hues
 * apart. A click is File > Save.
 *
 * ``data-curio-changes-pending`` says whether changes wait for the server
 * right now, before the bar shows it.
 */
export function SaveStatus({ saving, onSave }: { saving: boolean; onSave: () => void }) {
    const { boundDoc, projectDirty, projectSavedAt } = useFlowContext();
    const collab = useCollab();
    const { state, savedAt, pending } = useSaveState({
        provider: boundDoc ?? null,
        connected: collab.connected !== false,
        projectDirty,
        projectSavedAt,
    });
    const shown: SaveState = saving ? "saving" : state;
    const tooltip =
        saving ? "Saving…"
        : state === "saving" ? "Saving your changes…"
        : state === "offline" ? "Offline: your changes are sent when Curio reaches the server - click to save"
        : state === "unsaved" ? (projectDirty ? "Unsaved changes - click to save" : "Not saved yet - click to save")
        : savedAt ? `Saved at ${savedAt.toLocaleTimeString()} - click to save`
        : "Saved - click to save";
    const done = shown === "saved";
    return (
        <button
            type="button"
            className={clsx(headerStyles.barButton, styles.saveStatus)}
            disabled={saving}
            onClick={onSave}
            data-tooltip={tooltip}
            data-curio-save-state={shown}
            data-curio-changes-pending={pending ? "true" : "false"}
        >
            <FontAwesomeIcon
                icon={done ? faCircleCheck : faFloppyDisk}
                className={clsx(done ? styles.savedIcon : styles.unsavedIcon, shown === "saving" && styles.savingPulse)}
            />
            <span>{LABEL[shown]}</span>
        </button>
    );
}

export default SaveStatus;
