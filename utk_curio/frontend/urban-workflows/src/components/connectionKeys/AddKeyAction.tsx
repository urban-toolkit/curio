import React from "react";
import type { AgentRemedy } from "../../api/agentsApi";
import { remedyFocus, requestConnectionKeys } from "./connectionKeysRequest";
import styles from "./AddKeyAction.module.css";

/**
 * dev/116: the ONE rendering of a `source-missing` remedy. A missing key is a
 * button that opens Settings → Connection keys with the host prefilled; a key
 * that exists but was not used is a sentence (Solve again is the action).
 */
export const AddKeyAction: React.FC<{ remedy?: AgentRemedy | null; className?: string }> = ({
  remedy,
  className,
}) => {
  if (!remedy || !remedy.host) return null;
  if (remedy.kind === "use-connection-key") {
    return (
      <span className={`${styles.note}${className ? ` ${className}` : ""}`}>
        A connection key{remedy.name ? ` "${remedy.name}"` : ""} is saved for {remedy.host} — Solve again so the
        builder uses it.
      </span>
    );
  }
  const focus = remedyFocus(remedy);
  if (!focus) return null;
  return (
    <button
      type="button"
      className={`${styles.button}${className ? ` ${className}` : ""}`}
      title="Opens Settings → Connection keys with this host filled in. The key never appears in your dataflow, proposals or chat."
      onClick={() => requestConnectionKeys(focus)}
    >
      Add key for {remedy.host}
    </button>
  );
};
