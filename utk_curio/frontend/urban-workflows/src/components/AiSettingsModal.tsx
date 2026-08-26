import React, { useState, useEffect } from "react";
import ModalShell from "./ModalShell";
import modal from "./modal-content.module.css";
import styles from "./AiSettingsModal.module.css";
import { useUserContext } from "../providers/UserProvider";
import { agentsApi, ProviderDefault } from "../api/agentsApi";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

type UiMode = "openai" | "anthropic" | "gemini" | "custom";

interface ProviderInfo {
  model: string;
  keyLink: string;
  keyLinkLabel: string;
  showBaseUrl: boolean;
  baseUrlPlaceholder?: string;
}

const PROVIDER_INFO: Record<UiMode, ProviderInfo> = {
  openai: {
    model: "gpt-4o-mini",
    keyLink: "https://platform.openai.com/api-keys",
    keyLinkLabel: "Get your OpenAI key",
    showBaseUrl: false,
  },
  anthropic: {
    model: "claude-haiku-4-5-20251001",
    keyLink: "https://console.anthropic.com/keys",
    keyLinkLabel: "Get your Anthropic key",
    showBaseUrl: false,
  },
  gemini: {
    model: "gemini-2.0-flash",
    keyLink: "https://aistudio.google.com/apikey",
    keyLinkLabel: "Get your Gemini key",
    showBaseUrl: false,
  },
  custom: {
    model: "",
    keyLink: "",
    keyLinkLabel: "",
    showBaseUrl: true,
    baseUrlPlaceholder: "http://localhost:11434/v1  (Ollama, LM Studio, vLLM, …)",
  },
};

function uiModeFromSaved(apiType: string | null, baseUrl: string | null): UiMode {
  if (apiType === "anthropic") return "anthropic";
  if (apiType === "gemini") return "gemini";
  if (baseUrl) return "custom";
  return "openai";
}

const AiSettingsModal: React.FC<Props> = ({ isOpen, onClose }) => {
  const { user, updateLlmConfig } = useUserContext();

  const [uiMode, setUiMode] = useState<UiMode>("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(PROVIDER_INFO.openai.model);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  // What this deployment configured with --llm-provider / --llm-base-url /
  // --llm-model. Those flags and this panel write the same account-wide
  // setting, so the flags' values belong here as the inherited value rather
  // than being invisible to the user they apply to.
  const [deployed, setDeployed] = useState<ProviderDefault | null>(null);

  useEffect(() => {
    if (!isOpen || user?.is_guest) return;
    let live = true;
    agentsApi
      .providerDefault()
      .then((d) => { if (live) setDeployed(d); })
      // A deployment default is a nicety, not a prerequisite: if the lookup
      // fails the panel still edits the user's own config.
      .catch(() => { if (live) setDeployed(null); });
    return () => { live = false; };
  }, [isOpen, user?.is_guest]);

  useEffect(() => {
    if (isOpen && user) {
      const mode = uiModeFromSaved(user.llm_api_type, user.llm_base_url);
      setUiMode(mode);
      setBaseUrl(user.llm_base_url || "");
      setApiKey("");
      setModel(user.llm_model || "");
      setError(null);
      setSuccess(false);
    }
  }, [isOpen, user]);

  const handleModeChange = (newMode: UiMode) => {
    setUiMode(newMode);
    // Clear rather than stamp a suggestion in: an empty box means "use the
    // inherited model", which the placeholder names. Writing the suggestion
    // into the value would save it as an explicit override the user never
    // chose, and quietly detach them from the deployment default.
    setModel("");
    if (newMode !== "custom") {
      setBaseUrl("");
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const apiType =
        uiMode === "anthropic" ? "anthropic"
        : uiMode === "gemini" ? "gemini"
        : "openai_compatible";

      await updateLlmConfig({
        apiType,
        baseUrl: uiMode === "custom" ? baseUrl : "",
        apiKey: apiKey || undefined,
        model: model || undefined,
      });
      setSuccess(true);
      setApiKey("");
      setTimeout(onClose, 800);
    } catch (e: any) {
      setError(e.message || "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const info = PROVIDER_INFO[uiMode];

  return (
    <ModalShell onClose={onClose}>
      <div className={modal.content}>
        <h2 className={modal.title}>AI Settings</h2>

        {user?.is_guest ? (
          <>
            <p className={styles.guestNotice}>
              AI features for guest accounts are configured by whoever runs this
              Curio. If they are unavailable, ask them to set a guest API key.
            </p>
            <div className={modal.buttonRow}>
              <button className={modal.ghostBtn} onClick={onClose}>Close</button>
            </div>
          </>
        ) : (
          <>
            <p className={styles.providerNote}>
              This provider answers every AI surface in Curio: the agents, the
              node-authoring assistants and chat.
              {deployed?.model ? (
                <>
                  {" "}Whoever runs this Curio set a default of{" "}
                  <strong>{deployed.model}</strong>
                  {deployed.baseUrl ? <> at <code>{deployed.baseUrl}</code></> : null}.
                  Leave a field blank to use it, or fill it in to override it
                  for your account.
                </>
              ) : (
                <>
                  {" "}No default is configured on this deployment, so those
                  surfaces say so rather than calling anything until you set one
                  here.
                </>
              )}
            </p>
            <div className={modal.field}>
              <label className={modal.label}>Provider</label>
              <div className={styles.modeTabs}>
                {(["openai", "anthropic", "gemini", "custom"] as UiMode[]).map((m) => (
                  <button
                    key={m}
                    className={`${styles.modeTab}${uiMode === m ? ` ${styles.modeTabActive}` : ""}`}
                    onClick={() => handleModeChange(m)}
                    type="button"
                  >
                    {m === "openai" ? "OpenAI"
                      : m === "anthropic" ? "Anthropic"
                      : m === "gemini" ? "Gemini"
                      : "Custom"}
                  </button>
                ))}
              </div>
            </div>

            {info.showBaseUrl && (
              <div className={modal.field}>
                <label className={modal.label}>Base URL</label>
                <input
                  className={modal.input}
                  type="text"
                  value={baseUrl}
                  onChange={(e) => setBaseUrl(e.target.value)}
                  placeholder={deployed?.baseUrl || info.baseUrlPlaceholder}
                />
                <span className={modal.hint}>Any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, Groq, Azure, …)</span>
              </div>
            )}

            <div className={modal.field}>
              <label className={modal.label}>
                API Key{" "}
                <span className={styles.optional}>
                  {user?.has_llm_api_key
                    ? "(saved - leave blank to keep)"
                    : deployed?.hasApiKey
                      ? "(optional - this deployment provides one)"
                      : uiMode === "custom"
                        ? "(optional for keyless servers)"
                        : "(required)"}
                </span>
              </label>
              <input
                className={modal.input}
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={user?.has_llm_api_key ? "••••••••  (unchanged)" : "Enter your API key"}
                autoComplete="new-password"
              />
              {info.keyLink && (
                <a href={info.keyLink} target="_blank" rel="noreferrer" className={styles.keyLink}>
                  {info.keyLinkLabel} →
                </a>
              )}
            </div>

            <div className={modal.field}>
              <label className={modal.label}>Model</label>
              <input
                className={modal.input}
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder={
                  deployed?.model
                    ? `${deployed.model} (from this deployment)`
                    : info.model || "e.g. llama3.2"
                }
              />
            </div>

            {error && <p className={modal.error}>{error}</p>}
            {success && <p className={modal.success}>Settings saved.</p>}

            <div className={modal.buttonRow}>
              <button className={modal.ghostBtn} onClick={onClose} disabled={saving}>
                Cancel
              </button>
              <button className={modal.primaryBtn} onClick={handleSave} disabled={saving}>
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
};

export default AiSettingsModal;
