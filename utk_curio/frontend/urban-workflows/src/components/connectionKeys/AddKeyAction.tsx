import React from "react";
import type { AgentRemedy } from "../../services/agents";
import { remedyFocus, requestConnectionKeys } from "../apiSettings/apiSettingsRequest";
import { useHostedGuest } from "../apiSettings/useHostedGuest";
import styles from "./AddKeyAction.module.css";

/**
 * dev/116: the ONE rendering of a `source-missing` remedy. A missing key is a
 * button that opens API Settings' node code key form with the host prefilled; a key
 * that exists but was not used is a sentence (Solve again is the action). A
 * hosted guest has no keys for node code and cannot save one, so it gets neither.
 */
export const AddKeyAction: React.FC<{ remedy?: AgentRemedy | null; className?: string }> = ({
  remedy,
  className,
}) => {
  const hostedGuest = useHostedGuest();
  if (hostedGuest || !remedy || !remedy.host) return null;
  if (remedy.kind === "use-connection-key") {
    return (
      <span className={`${styles.note}${className ? ` ${className}` : ""}`}>
        A connection key{remedy.name ? ` "${remedy.name}"` : ""} is saved for {remedy.host}. Solve again so the
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
      title="Opens API Settings with this host filled in. The key never appears in your dataflow, proposals or chat."
      onClick={() => requestConnectionKeys(focus)}
    >
      Add key for {remedy.host}
    </button>
  );
};
