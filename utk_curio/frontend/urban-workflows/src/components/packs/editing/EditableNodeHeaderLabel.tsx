import React, { useCallback, useEffect, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear } from "@fortawesome/free-solid-svg-icons";
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

  return (
    <div className={styles.labelWrap}>
      {executed ? (
        <span className={styles.execMark} title="Executed">
          &#10003;
        </span>
      ) : null}
      {editing ? (
        <input
          className={`${styles.labelInput} ${keywordHighlighted ? styles.labelInputHighlighted : ""}`}
          value={draft}
          aria-label="Node title"
          autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={onKeyDown}
        />
      ) : (
        <button
          type="button"
          className={`${styles.labelText} ${editable ? styles.labelTextEditable : ""} ${
            keywordHighlighted ? styles.labelTextHighlighted : ""
          }`}
          title={editable ? "Click to edit node title" : displayLabel}
          disabled={!editable}
          onClick={() => {
            if (!editable) return;
            setDraft(displayLabel);
            setEditing(true);
          }}
        >
          {displayLabel}
        </button>
      )}
      {showConfig ? (
        <button
          type="button"
          className={`${styles.configBtn} ${keywordHighlighted ? styles.configBtnHighlighted : ""}`}
          title="Configure node kind"
          aria-label={`Configure ${displayLabel}`}
          onClick={onConfigure}
        >
          <FontAwesomeIcon icon={faGear} aria-hidden />
        </button>
      ) : null}
      {showSaveAs ? (
        <button
          type="button"
          className={`${styles.saveAsBtn} ${keywordHighlighted ? styles.saveAsBtnHighlighted : ""}`}
          title="Save this node into a pack"
          aria-label={`Save as pack node for ${displayLabel}`}
          onClick={onSaveAs}
        >
          Save As
        </button>
      ) : null}
    </div>
  );
}

