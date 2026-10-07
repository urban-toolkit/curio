import React from "react";
import styles from "./CredentialHint.module.css";
import type { CredentialFinding } from "../../services/connectionKeys/credentialLiterals";
import { requestConnectionKeys, suggestName } from "../apiSettings/apiSettingsRequest";
import { HOSTED_GUEST_KEYS_NOTE, useHostedGuest } from "../apiSettings/useHostedGuest";

/**
 * dev/117: the quiet bar above a node's code editor when the code holds a
 * credential-shaped literal. A hint, never a block: Play, save and collab are
 * untouched, the code is never rewritten, and the value never leaves the tab
 * (the finding is a name and a line). Save as API key opens API Settings on
 * the node code key form through the dev/116 request bus. A hosted guest, who
 * cannot save a key and so has none for `curio_secret` to read, gets no such
 * button: its text says so, as API Settings does, and points it to an account
 * of its own. A read-only editor shows the text alone.
 */
export const CredentialHint: React.FC<{
  findings: CredentialFinding[];
  readOnly?: boolean;
  /** The bare hostname of the code's first URL, for the settings form. */
  host?: string | null;
  onDismiss?: () => void;
}> = ({ findings, readOnly = false, host = null, onDismiss }) => {
  const hostedGuest = useHostedGuest();
  if (!findings.length) return null;
  const lines = Array.from(new Set(findings.map((f) => f.line))).sort((a, b) => a - b);
  const lead =
    lines.length === 1
      ? `Line ${lines[0]} looks like an API key.`
      : `Lines ${lines.slice(0, -1).join(", ")} and ${lines[lines.length - 1]} look like API keys.`;
  return (
    <div className={styles.bar} role="status" aria-live="polite" data-testid="credential-hint">
      <span className={styles.text}>
        <span className={styles.lead}>{lead}</span> Keys in node code are saved with the dataflow and shared with
        it.{" "}
        {hostedGuest ? (
          <>{HOSTED_GUEST_KEYS_NOTE} Sign in with your own account to save it in API Settings.</>
        ) : (
          <>
            Save it in API Settings and write <code>api_key = curio_secret("&lt;name&gt;")</code> instead.
          </>
        )}
      </span>
      {!readOnly ? (
        <>
          {!hostedGuest ? (
            <button
              type="button"
              className={styles.button}
              aria-label="Save this key in API Settings"
              title="Opens API Settings. Paste the key there; it never appears in your dataflow, proposals or chat."
              onClick={() =>
                requestConnectionKeys(host ? { host, suggestedName: suggestName(host) } : {})
              }
            >
              Save as API key
            </button>
          ) : null}
          {onDismiss ? (
            <button type="button" className={styles.dismiss} aria-label="Dismiss this hint" onClick={onDismiss}>
              Dismiss
            </button>
          ) : null}
        </>
      ) : null}
    </div>
  );
};
