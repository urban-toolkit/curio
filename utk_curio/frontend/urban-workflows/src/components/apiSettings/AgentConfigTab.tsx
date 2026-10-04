import React from "react";
import modal from "../modal-content.module.css";
import llmStyles from "../llmConfigs/LlmConfigs.module.css";
import styles from "./ApiSettings.module.css";
import { llmConfigsApi } from "../../api/llmConfigsApi";
import { AgentModelsSection } from "../llmConfigs/AgentModelsSection";
import type { ApiSettingsFocus } from "./apiSettingsRequest";
import type { LlmListingState } from "./useLlmListing";

/**
 * API Settings, Agent configuration: which language model the agents run on.
 * The default answers every agent with no choice of its own; the table below
 * gives an agent a configuration of its own. The configurations themselves
 * are added and edited on the API keys tab.
 *
 * A guest on a hosted Curio sees the guest configuration and nothing to choose.
 */
export const AgentConfigTab: React.FC<{
  llm: LlmListingState;
  focus?: ApiSettingsFocus | null;
  /** Switch to the API keys tab, to add a configuration. */
  onShowKeys: () => void;
}> = ({ llm, focus = null, onShowKeys }) => {
  const { listing, loadError, busy, error, act } = llm;

  if (loadError) {
    return (
      <div className={styles.tabBody}data-testid="agent-config-tab">
        <p className={modal.error} role="alert">{loadError}</p>
      </div>
    );
  }
  if (!listing) {
    return (
      <div className={styles.tabBody}data-testid="agent-config-tab">
        <div className={llmStyles.skeleton} aria-busy="true">Loading your LLM configurations…</div>
      </div>
    );
  }

  const { deployment, active } = listing;

  if (!listing.editable) {
    return (
      <div className={styles.tabBody}data-testid="agent-config-tab">
        <p className={llmStyles.note} role="note">{listing.reason}</p>
        <p className={llmStyles.active}>
          {active.source ? (
            <>
              Guests use <strong>{active.model}</strong>
              {active.baseUrlHost ? <> at <code>{active.baseUrlHost}</code></> : null}.
            </>
          ) : (
            active.error
          )}
        </p>
      </div>
    );
  }

  const nothingToChoose = listing.configs.length === 0 && !deployment.model;

  return (
    <div className={styles.tabBody}data-testid="agent-config-tab">
      <section className={llmStyles.section} aria-labelledby="agent-default-heading">
        <h3 className={llmStyles.heading} id="agent-default-heading">Default</h3>
        <p className={llmStyles.active} data-testid="llm-active">
          {active.source ? (
            <>
              Answering now: <strong>{active.label}</strong> · {active.model}
              {active.baseUrlHost ? <> at <code>{active.baseUrlHost}</code></> : null}
            </>
          ) : (
            active.error
          )}
        </p>
        {nothingToChoose ? (
          <p className={llmStyles.note}>
            No language model is set up yet.{" "}
            <button type="button" className={llmStyles.actionBtn} onClick={onShowKeys}>
              Add one on the API keys tab
            </button>
          </p>
        ) : (
          <div className={modal.field}>
            <label className={modal.label} htmlFor="agent-default-config">Default for agents</label>
            <select
              id="agent-default-config"
              className={modal.select}
              value={listing.default ?? ""}
              disabled={busy !== null}
              onChange={(e) => {
                const next = e.target.value || null;
                void act("default", () => llmConfigsApi.setDefault(next));
              }}
            >
              {deployment.model ? (
                <option value="">
                  {deployment.label} · {deployment.model}
                </option>
              ) : (
                <option value="" disabled>
                  None chosen
                </option>
              )}
              {listing.configs.map((config) => (
                <option key={config.id} value={config.id}>
                  {config.label} · {config.model}
                </option>
              ))}
            </select>
            <span className={modal.hint}>Every agent with no configuration of its own below runs on this one.</span>
          </div>
        )}
      </section>
      {error ? <p className={modal.error} role="alert">{error}</p> : null}
      <AgentModelsSection
        listing={listing}
        busy={busy !== null}
        focusAgentId={focus?.section === "agent-models" ? focus.agentId : null}
        onChoose={(agentId, choice) =>
          void act(`choose:${agentId}`, () => llmConfigsApi.setAssignments({ [agentId]: choice }))
        }
      />
    </div>
  );
};
