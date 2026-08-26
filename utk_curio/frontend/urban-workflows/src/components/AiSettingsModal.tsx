import React, { useState, useEffect } from "react";
import ModalShell from "./ModalShell";
import modal from "./modal-content.module.css";
import styles from "./AiSettingsModal.module.css";
import { AgentSettingsModal } from "./agents/settings/AgentSettingsModal";
import { useUserContext } from "../providers/UserProvider";

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
  // Two questions, one surface: which model, and how much it may spend.
  // They used to live in two modals reached from two places.
  const [tab, setTab] = useState<"provider" | "limits">("provider");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    if (isOpen && user) {
      const mode = uiModeFromSaved(user.llm_api_type, user.llm_base_url);
      setUiMode(mode);
      setBaseUrl(user.llm_base_url || "");
      setApiKey("");
      setModel(user.llm_model || PROVIDER_INFO[mode].model);
      setError(null);
      setSuccess(false);
    }
  }, [isOpen, user]);

  const handleModeChange = (newMode: UiMode) => {
    setUiMode(newMode);
    const defaultModel = PROVIDER_INFO[newMode].model;
    if (defaultModel) {
      setModel(defaultModel);
    }
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
            <nav className={styles.settingsTabs} aria-label="AI settings sections">
              <button
                type="button"
                className={`${styles.settingsTab}${tab === "provider" ? ` ${styles.settingsTabActive}` : ""}`}
                aria-pressed={tab === "provider"}
                onClick={() => setTab("provider")}
              >
                Provider
              </button>
              <button
                type="button"
                className={`${styles.settingsTab}${tab === "limits" ? ` ${styles.settingsTabActive}` : ""}`}
                aria-pressed={tab === "limits"}
                onClick={() => setTab("limits")}
              >
                Agent limits
              </button>
            </nav>

            {tab === "limits" ? (
              /* The account scope of the agent policy editor, rendered inline
                 rather than as a second modal. The drawer's per-agent cog
                 still opens the same component for a project override. */
              <AgentSettingsModal scope="account" embedded onClose={onClose} />
            ) : (
          <>
            <p className={styles.providerNote}>
              This provider answers every AI surface in Curio: the agents, the
              node-authoring assistants and chat. Leave it unset and those
              surfaces say so rather than calling anything.
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
                  placeholder={info.baseUrlPlaceholder}
                />
                <span className={modal.hint}>Any OpenAI-compatible endpoint (Ollama, LM Studio, vLLM, Groq, Azure, …)</span>
              </div>
            )}

            <div className={modal.field}>
              <label className={modal.label}>
                API Key{" "}
                <span className={styles.optional}>
                  {user?.has_llm_api_key ? "(saved - leave blank to keep)" : uiMode === "custom" ? "(optional for keyless servers)" : "(required)"}
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
                placeholder={info.model || "e.g. llama3.2"}
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
          </>
        )}
      </div>
    </ModalShell>
  );
};

export default AiSettingsModal;
