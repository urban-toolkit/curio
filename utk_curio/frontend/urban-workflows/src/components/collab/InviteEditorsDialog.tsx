import React, { useEffect, useId, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faXmark } from "@fortawesome/free-solid-svg-icons";

import ModalShell from "../ModalShell";
import shared from "../ConfirmDialog.module.css";
import styles from "./InviteEditorsDialog.module.css";
import { projectEditorsApi, type ProjectEditor } from "../../api/projectEditorsApi";

export const INVITE_EDITORS_INTRO =
  "Editors change this dataflow with you while it is open. Anyone else with its link watches.";

function messageOf(err: unknown): string {
  return err instanceof Error && err.message ? err.message : "Something went wrong. Try again.";
}

/**
 * The owner's list of a dataflow's editors, opened from Share > Invite editors:
 * a username field with Add, then each editor with Remove. Built from the
 * ConfirmDialog parts, as PromptDialog is. The server says why an invite is
 * refused (an unknown account, a guest, the owner), and the dialog shows its
 * sentence as it is.
 */
export default function InviteEditorsDialog({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const titleId = useId();
  const fieldId = useId();
  const [editors, setEditors] = useState<ProjectEditor[] | null>(null);
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    projectEditorsApi
      .list(projectId)
      .then((list) => {
        if (!cancelled) setEditors(list);
      })
      .catch((err) => {
        if (cancelled) return;
        setEditors([]);
        setError(messageOf(err));
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const change = async (request: () => Promise<ProjectEditor[]>, after?: () => void) => {
    setBusy(true);
    setError(null);
    try {
      setEditors(await request());
      after?.();
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  };

  const trimmed = username.trim();

  return (
    <ModalShell onClose={busy ? () => {} : onClose} titleId={titleId}>
      <form
        className={`${shared.dialog} ${styles.dialog}`}
        data-testid="invite-editors-dialog"
        onSubmit={(event) => {
          event.preventDefault();
          if (!trimmed || busy) return;
          void change(() => projectEditorsApi.add(projectId, trimmed), () => setUsername(""));
        }}
      >
        <h2 id={titleId} className={shared.title}>
          Invite editors
        </h2>
        <p className={styles.intro}>{INVITE_EDITORS_INTRO}</p>
        <div className={shared.field}>
          <label className={shared.fieldLabel} htmlFor={fieldId}>
            Username
          </label>
          <div className={styles.addRow}>
            <input
              id={fieldId}
              className={shared.input}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              disabled={busy}
              autoComplete="off"
              autoFocus
            />
            <button type="submit" className={shared.actionButton} disabled={busy || !trimmed}>
              Add
            </button>
          </div>
        </div>
        {error && (
          <p role="alert" className={styles.error}>
            {error}
          </p>
        )}
        <h3 className={`${shared.fieldLabel} ${styles.listTitle}`}>Editors</h3>
        {editors === null ? (
          <p className={styles.empty}>Loading…</p>
        ) : editors.length === 0 ? (
          <p className={styles.empty}>No editors yet.</p>
        ) : (
          <ul className={styles.list}>
            {editors.map((editor) => (
              <li key={editor.user_id} className={styles.row} data-editor={editor.username}>
                <span className={styles.name}>{editor.name || editor.username}</span>
                <span className={styles.username}>{editor.username}</span>
                <button
                  type="button"
                  className={styles.remove}
                  onClick={() => void change(() => projectEditorsApi.remove(projectId, editor.user_id))}
                  disabled={busy}
                  aria-label={`Remove ${editor.username}`}
                  data-tooltip="Remove editor"
                >
                  <FontAwesomeIcon icon={faXmark} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className={shared.footer}>
          <button type="button" className={shared.ghostButton} onClick={onClose} disabled={busy}>
            Done
          </button>
        </div>
      </form>
    </ModalShell>
  );
}
