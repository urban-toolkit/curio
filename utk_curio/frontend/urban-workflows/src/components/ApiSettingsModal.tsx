import React from "react";
import ModalShell from "./ModalShell";
import modal from "./modal-content.module.css";
import styles from "./ApiSettingsModal.module.css";
import { useUserContext } from "../providers/UserProvider";
import { ConnectionKeysSection } from "./connectionKeys/ConnectionKeysSection";
import { EvaluationModeSection } from "./evaluation/EvaluationModeSection";
import { LlmConfigsSection } from "./llmConfigs/LlmConfigsSection";
import { ModelTrainingSection } from "./training/ModelTrainingSection";
import { SourceKeysSection } from "./apiSettings/SourceKeysSection";
import type { ConnectionKeysFocus } from "./connectionKeys/connectionKeysRequest";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  /** Open on one section: Connection keys (dev/116, host prefilled), an agent's
   * row in Agent models, one LLM configuration, or one source key. */
  focus?: ConnectionKeysFocus | null;
}

/**
 * The account's keys, grouped by the catalog that uses them.
 *
 * Agent Catalog: the LLM configurations and the one each agent runs on, the
 * connection keys a node reaches by name, and the evaluation and training
 * panels that run on the Dataflow Builder's configuration.
 *
 * Discovery Catalog: the key each source sends, one row per key the server
 * knows (`SourceKeysSection`).
 */
const ApiSettingsModal: React.FC<Props> = ({ isOpen, onClose, focus = null }) => {
  const { user, isSharedGuest, enableUserAuth } = useUserContext();
  // A guest under --deploy shares one account with every visitor, so it saves
  // nothing personal. Without --deploy the shared guest is the one local user.
  const hostedGuest = Boolean(user?.is_guest) && enableUserAuth;
  const keyFocus = focus?.section === "connection-keys" ? focus : null;
  const llmFocus = focus?.section === "agent-models" || focus?.section === "llm-configs" ? focus : null;
  const sourceSlot = focus?.section === "source-key" ? focus.slot ?? null : null;

  if (!isOpen) return null;

  return (
    // `layer="overlay"` because the Agent Catalog drawer's header cog opens
    // this, and the drawer sits at --curio-z-agent-drawer (10048) behind a
    // full-viewport scrim. At the default --curio-z-modal-base (500) the panel
    // painted underneath it and the scrim swallowed every click, which left the
    // canvas with no way to reach API Settings at all. Correct from the
    // /projects and /catalog headers too, so it is unconditional.
    <ModalShell onClose={onClose} layer="overlay" titleId="api-settings-title">
      <div className={modal.content}>
        <h2 id="api-settings-title" className={modal.title}>API Settings</h2>

        <section className={styles.section} aria-labelledby="api-settings-agents-title">
          <h3 id="api-settings-agents-title" className={styles.sectionTitle}>Agent Catalog</h3>
          <LlmConfigsSection focus={llmFocus} />
          {hostedGuest ? null : (
            <>
              {/* dev/116 (DEC-074): API keys a data-loading node reaches by name. */}
              <ConnectionKeysSection focus={keyFocus} sharedGuest={isSharedGuest} />
              {/* dev/123 (DEC-079): run one of Curio's own examples through
                  the real lifecycle on the Dataflow Builder's configuration,
                  and score what it built. */}
              <EvaluationModeSection />
              {/* dev/122 (DEC-078): fine-tune a model on Curio's own
                  approved examples, on a configuration holding your own key. */}
              <ModelTrainingSection />
            </>
          )}
        </section>

        {hostedGuest ? (
          <p className={styles.guestNotice}>
            Personal keys cannot be saved on a shared guest account.
          </p>
        ) : (
          <>
            {isSharedGuest ? (
              <p className={styles.sharedNote} role="note">
                Everyone using this Curio shares this account, so keys saved here are shared too.
              </p>
            ) : null}
            <SourceKeysSection focusSlot={sourceSlot} />
          </>
        )}

        <div className={modal.buttonRow}>
          <button className={modal.ghostBtn} onClick={onClose}>Close</button>
        </div>
      </div>
    </ModalShell>
  );
};

export default ApiSettingsModal;
