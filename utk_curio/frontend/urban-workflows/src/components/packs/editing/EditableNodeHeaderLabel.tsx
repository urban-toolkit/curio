import React, { useCallback, useEffect, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear } from "@fortawesome/free-solid-svg-icons";
import { useHeaderIconDragClick } from "../../../utils/headerIconDragClick";
import styles from "./EditableNodeHeaderLabel.module.css";

export function EditableNodeHeaderLabel({
  displayLabel,
  editable,
  showSaveAs,
  showConfig,
  executed,
  keywordHighlighted,
  onLabelCommit,
  onSaveAs,
  onConfigure,
}: {
  displayLabel: string;
  editable: boolean;
  showSaveAs: boolean;
  showConfig: boolean;
  executed: boolean;
  keywordHighlighted: boolean;
  onLabelCommit: (label: string) => void;
  onSaveAs: () => void;
  onConfigure: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(displayLabel);

  useEffect(() => {
    if (!editing) setDraft(displayLabel);
  }, [displayLabel, editing]);

  const commit = useCallback(() => {
    const next = draft.trim();
    if (next && next !== displayLabel) onLabelCommit(next);
    setEditing(false);
  }, [draft, displayLabel, onLabelCommit]);

  const onKeyDown = useCallback(
    (ev: React.KeyboardEvent<HTMLInputElement>) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        commit();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        setDraft(displayLabel);
        setEditing(false);
      }
    },
    [commit, displayLabel],
  );

  const startEdit = useCallback(() => {
    setDraft(displayLabel);
    setEditing(true);
  }, [displayLabel]);

  const labelEditClick = useHeaderIconDragClick(startEdit);
  const configClick = useHeaderIconDragClick(onConfigure);
  const saveAsClick = useHeaderIconDragClick(onSaveAs);

  return (
    <div className={styles.labelWrap}>
      {executed ? (
        <span className={styles.execMark} title="Executed">
          &#10003;
        </span>
      ) : null}
      {editing ? (
        <input
          className={`nodrag nowheel ${styles.labelInput} ${keywordHighlighted ? styles.labelInputHighlighted : ""}`}
          data-curio-pack-palette-node-action="true"
          value={draft}
          aria-label="Node title"
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={onKeyDown}
        />
      ) : editable ? (
        <button
          type="button"
          className={`${styles.labelText} ${styles.labelTextEditable} ${
            keywordHighlighted ? styles.labelTextHighlighted : ""
          }`}
          data-curio-pack-palette-node-action="true"
          title="Click to edit node title"
          aria-label={`Edit node title: ${displayLabel}`}
          {...labelEditClick}
        >
          {displayLabel}
        </button>
      ) : (
        <span
          className={`${styles.labelText} ${keywordHighlighted ? styles.labelTextHighlighted : ""}`}
          title={displayLabel}
        >
          {displayLabel}
        </span>
      )}
      {showConfig ? (
        <button
          type="button"
          className={`${styles.configBtn} ${keywordHighlighted ? styles.configBtnHighlighted : ""}`}
          data-curio-pack-palette-node-action="true"
          title="Configure node kind"
          aria-label={`Configure ${displayLabel}`}
          {...configClick}
        >
          <FontAwesomeIcon icon={faGear} aria-hidden />
        </button>
      ) : null}
      {showSaveAs ? (
        <button
          type="button"
          className={`${styles.saveAsBtn} ${keywordHighlighted ? styles.saveAsBtnHighlighted : ""}`}
          data-curio-pack-palette-node-action="true"
          title="Save this node into a pack"
          aria-label={`Save as pack node for ${displayLabel}`}
          {...saveAsClick}
        >
          Save As
        </button>
      ) : null}
    </div>
  );
}

