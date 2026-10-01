import React from "react";
import type { AgentRemedy } from "../../services/agents";
import { requestAgentModel } from "../connectionKeys/connectionKeysRequest";
import styles from "../connectionKeys/AddKeyAction.module.css";

/** The remedy a refused request carries (`apiFetch` keeps the body), or null. */
export function remedyOf(error: unknown): AgentRemedy | null {
  const remedy = (error as { body?: { remedy?: AgentRemedy } } | null)?.body?.remedy;
  return remedy && typeof remedy === "object" ? remedy : null;
}

/**
 * The one rendering of an `llm-config` remedy: no LLM configuration answers
 * this agent, so the button opens AI Settings on its row in Agent models.
 */
export const LlmConfigAction: React.FC<{ remedy?: AgentRemedy | null; className?: string }> = ({
  remedy,
  className,
}) => {
  if (!remedy || remedy.kind !== "llm-config") return null;
  return (
    <button
      type="button"
      className={`${styles.button}${className ? ` ${className}` : ""}`}
      onClick={() => requestAgentModel(remedy.agentId ?? undefined)}
    >
      Open AI Settings
    </button>
  );
};
