import React, { useState, useEffect } from "react";
import ModalShell from "./ModalShell";
import modal from "./modal-content.module.css";
import styles from "./AiSettingsModal.module.css";
import { useUserContext } from "../providers/UserProvider";
import { ConnectionKeysSection } from "./connectionKeys/ConnectionKeysSection";
import { EvaluationModeSection } from "./evaluation/EvaluationModeSection";
import { LlmConfigsSection } from "./llmConfigs/LlmConfigsSection";
import { ModelTrainingSection } from "./training/ModelTrainingSection";
import type { ConnectionKeysFocus } from "./connectionKeys/connectionKeysRequest";
import { authApi } from "../utils/authApi";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  /** Open on one section: Connection keys (dev/116, host prefilled), an agent's
   * row in Agent models, or one LLM configuration. */
  focus?: ConnectionKeysFocus | null;
}

/**
 * The account's credentials screen: its LLM configurations and the one each
 * agent runs on, the per-person HuggingFace and Socrata tokens, the connection
 * keys a node reaches by name, and the evaluation and training panels that
 * run on the Dataflow Builder's configuration.
 */
const AiSettingsModal: React.FC<Props> = ({ isOpen, onClose, focus = null }) => {
  const { user, updateTokens, isSharedGuest, enableUserAuth } = useUserContext();
  // A guest under --deploy shares one account with every visitor, so it saves
  // nothing personal. Without --deploy the shared guest is the one local user.
  const hostedGuest = Boolean(user?.is_guest) && enableUserAuth;
  const keyFocus = focus?.section === "connection-keys" ? focus : null;
  const llmFocus = focus?.section === "agent-models" || focus?.section === "llm-configs" ? focus : null;

  // HuggingFace gates some models behind a licence you accept with your own
  // account, so the token is per user rather than one the operator holds.
  const [hfToken, setHfToken] = useState("");
  // The Data Lake Catalog sends this one to Socrata portals.
  const [socrataToken, setSocrataToken] = useState("");
  // Whether this install supplies a Socrata token everyone inherits:
  // "(optional)" is misleading when leaving the box blank already
  // authenticates you.
  const [socrataInherited, setSocrataInherited] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  const [removing, setRemoving] = useState<null | "hfToken" | "socrataToken">(null);

  useEffect(() => {
    if (!isOpen) return;
    setHfToken("");
    setSocrataToken("");
    setError(null);
    setSuccess(false);
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    let cancelled = false;
    authApi
      .getPublicConfig()
      .then((cfg) => {
        if (!cancelled) setSocrataInherited(Boolean(cfg.has_default_socrata_app_token));
      })
      // A deployment fact we could not read is reported as "not set": saying
      // nothing is better than claiming an inheritance that may not exist.
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [isOpen]);

  const handleRemoveSecret = async (which: "hfToken" | "socrataToken") => {
    setRemoving(which);
    setError(null);
    try {
      await updateTokens(which === "hfToken" ? { huggingfaceToken: "" } : { socrataAppToken: "" });
      if (which === "hfToken") setHfToken("");
      else setSocrataToken("");
    } catch (e: any) {
      setError(e.message || "Failed to remove.");
    } finally {
      setRemoving(null);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      await updateTokens({
        huggingfaceToken: hfToken || undefined,
        socrataAppToken: socrataToken || undefined,
      });
      setSuccess(true);
      setHfToken("");
      setSocrataToken("");
    } catch (e: any) {
      setError(e.message || "Failed to save the tokens.");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  return (
    // `layer="overlay"` because the Agent Catalog drawer's header cog opens
    // this, and the drawer sits at --curio-z-agent-drawer (10048) behind a
    // full-viewport scrim. At the default --curio-z-modal-base (500) the panel
    // painted underneath it and the scrim swallowed every click, which left the
    // canvas with no way to reach AI Settings at all. Correct from the
    // /projects and /catalog headers too, so it is unconditional.
    <ModalShell onClose={onClose} layer="overlay" titleId="ai-settings-title">
      <div className={modal.content}>
        <h2 id="ai-settings-title" className={modal.title}>AI Settings</h2>

        <LlmConfigsSection focus={llmFocus} />

        {hostedGuest ? (
          <>
            <p className={styles.guestNotice}>
              Personal tokens cannot be saved on a shared guest account.
            </p>
            {/* dev/116: the shared guest (auth off) may still save connection
                keys, into the one store every guest shares; said plainly. */}
            {isSharedGuest ? <ConnectionKeysSection focus={keyFocus} sharedGuest /> : null}
            <div className={modal.buttonRow}>
              <button className={modal.ghostBtn} onClick={onClose}>Close</button>
            </div>
          </>
        ) : (
          <>
            {isSharedGuest ? (
              <p className={styles.sharedNote} role="note">
                Everyone using this Curio shares this account, so tokens saved here are shared too.
              </p>
            ) : null}
            <div className={modal.field}>
              <label className={modal.label} htmlFor="ai-settings-hf-token">
                HuggingFace token{" "}
                <span className={styles.optional}>
                  {user?.has_huggingface_token
                    ? "(saved - leave blank to keep)"
                    : "(optional)"}
                </span>
              </label>
              <input
                id="ai-settings-hf-token"
                className={modal.input}
                type="password"
                value={hfToken}
                onChange={(e) => setHfToken(e.target.value)}
                placeholder={
                  user?.has_huggingface_token
                    ? "••••••••  (unchanged)"
                    : "hf_..."
                }
                autoComplete="new-password"
              />
              <span className={modal.hint}>
                Only needed for <strong>gated</strong> models in the Street
                Vision node, which you unlock by accepting each model's licence
                on your own HuggingFace account. Public models need no token.
              </span>
              <a
                href="https://huggingface.co/settings/tokens"
                target="_blank"
                rel="noreferrer"
                className={styles.keyLink}
              >
                Get your HuggingFace token →
              </a>
              {user?.has_huggingface_token && (
                <button
                  type="button"
                  className={styles.removeSecretBtn}
                  onClick={() => void handleRemoveSecret("hfToken")}
                  disabled={removing !== null}
                >
                  {removing === "hfToken" ? "Removing…" : "Remove saved token"}
                </button>
              )}
            </div>

            <div className={modal.field}>
              <label className={modal.label} htmlFor="ai-settings-socrata-token">
                Socrata app token{" "}
                <span className={styles.optional}>
                  {user?.has_socrata_app_token
                    ? "(saved - leave blank to keep)"
                    : socrataInherited
                      ? "(inherited - leave blank to use it)"
                      : "(optional)"}
                </span>
              </label>
              <input
                id="ai-settings-socrata-token"
                className={modal.input}
                type="password"
                value={socrataToken}
                onChange={(e) => setSocrataToken(e.target.value)}
                placeholder={
                  user?.has_socrata_app_token ? "••••••••  (unchanged)" : "Your app token"
                }
                autoComplete="new-password"
              />
              <span className={modal.hint}>
                Used by the <strong>Data Lake Catalog</strong> for Socrata
                portals, such as Chicago&apos;s. They answer without one; a
                token raises the rate limit, and it is issued to you rather
                than to this install, so it lives on your account.
                {socrataInherited ? (
                  <>
                    {" "}Whoever runs this Curio set one for everyone. Leave
                    this blank to use it, or fill it in to override it for your
                    account.
                  </>
                ) : null}
              </span>
              <a
                href="https://evergreen.data.socrata.com/signup"
                target="_blank"
                rel="noreferrer"
                className={styles.keyLink}
              >
                Get a Socrata app token →
              </a>
              {user?.has_socrata_app_token && (
                <button
                  type="button"
                  className={styles.removeSecretBtn}
                  onClick={() => void handleRemoveSecret("socrataToken")}
                  disabled={removing !== null}
                >
                  {removing === "socrataToken" ? "Removing…" : "Remove saved token"}
                </button>
              )}
            </div>
            {error && <p className={modal.error}>{error}</p>}
            {success && <p className={modal.success}>Tokens saved.</p>}
            <div className={modal.buttonRow}>
              <button
                className={modal.primaryBtn}
                onClick={handleSave}
                disabled={saving || !(hfToken || socrataToken)}
              >
                {saving ? "Saving…" : "Save tokens"}
              </button>
            </div>

            {/* dev/116 (DEC-074): API keys a data-loading node reaches by name. */}
            <ConnectionKeysSection focus={keyFocus} sharedGuest={isSharedGuest} />
            {user?.is_guest ? null : (
              <>
                {/* dev/123 (DEC-079): run one of Curio's own examples through
                    the real lifecycle on the Dataflow Builder's configuration,
                    and score what it built. */}
                <EvaluationModeSection />
                {/* dev/122 (DEC-078): fine-tune a model on Curio's own
                    approved examples, on a configuration holding your own key. */}
                <ModelTrainingSection />
              </>
            )}

            <div className={modal.buttonRow}>
              <button className={modal.ghostBtn} onClick={onClose}>Close</button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
};

export default AiSettingsModal;
