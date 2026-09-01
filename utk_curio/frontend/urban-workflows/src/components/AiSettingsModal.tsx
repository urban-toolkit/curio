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

const PROVIDER_LABEL: Record<UiMode, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
  custom: "a custom endpoint",
};

// Named on the API Key input's aria-describedby, so the one-key-per-account
// rule reaches a screen reader too and not only a sighted user.
const OTHER_KEY_NOTE_ID = "ai-settings-api-key-other-provider";

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
  // A second credential, for a different provider: HuggingFace gates some
  // models behind a licence you accept with your own account, so the token is
  // per user rather than one the operator holds for everybody.
  const [hfToken, setHfToken] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);
  // What the configured endpoint says it serves. Empty means "we have not
  // asked, or it could not tell us", and the Model field stays free text -
  // an endpoint that cannot list must not become an endpoint you cannot use.
  const [models, setModels] = useState<string[]>([]);
  // The subset of `models` that came from the curated table rather than from
  // the endpoint (#241). Held separately so the dropdown can group the two and
  // the user can see which is which; a curated id is a suggestion, and reading
  // it as "what this endpoint serves" is how a wrong model gets saved.
  const [curatedModels, setCuratedModels] = useState<string[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [modelsNote, setModelsNote] = useState<string | null>(null);
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
      setHfToken("");
      setError(null);
      setSuccess(false);
      setModels([]);
      setCuratedModels([]);
      setModelsError(null);
      setModelsNote(null);
    }
  }, [isOpen, user]);

  // Curio stores ONE provider credential per account (`user.llm_api_key` with
  // `user.llm_api_type`), but this panel has a tab per provider, so every tab
  // read the same has_llm_api_key and every tab claimed a saved key (#242).
  // The key belongs to the provider it was saved under, and nowhere else.
  const savedMode = uiModeFromSaved(user?.llm_api_type ?? null, user?.llm_base_url ?? null);
  const keyBelongsHere = !!user?.has_llm_api_key && uiMode === savedMode;
  const otherProviderHasKey = !!user?.has_llm_api_key && !keyBelongsHere;

  const loadModels = async () => {
    setLoadingModels(true);
    setModelsError(null);
    // Cleared alongside the error: Refresh after adding a key would otherwise
    // leave "Showing known models" standing over a list that is now live.
    setModelsNote(null);
    try {
      const apiType =
        uiMode === "anthropic" ? "anthropic"
        : uiMode === "gemini" ? "gemini"
        : "openai_compatible";
      // Send what is on screen, not what is saved: the whole point is to pick a
      // model for the endpoint being configured right now. A blank key means
      // "use the saved one", which the server resolves.
      const res = await agentsApi.providerModels({
        apiType,
        baseUrl: uiMode === "custom" ? baseUrl : "",
        apiKey,
      });
      const listed = res.models || [];
      setModels(listed);
      setCuratedModels(res.curated || []);
      if (!listed.length) {
        setModelsError("The endpoint returned no models.");
      } else if (!res.listable) {
        // It used to say "This provider does not publish a model list", which
        // was both wrong (nobody had asked Anthropic or Gemini) and a dead end.
        // Now there is always something to pick, and the reason sits next to it.
        setModelsNote(
          res.warning
            ? `${res.warning} Showing known models for this provider instead.`
            : "Showing known models for this provider.",
        );
      } else if (res.source === "live+curated") {
        setModelsNote("Known models are listed after the ones this endpoint reported.");
      }
    } catch (e: any) {
      setModels([]);
      setCuratedModels([]);
      setModelsError(e?.message || "Could not reach the endpoint.");
    } finally {
      setLoadingModels(false);
    }
  };

  const handleModeChange = (newMode: UiMode) => {
    setUiMode(newMode);
    // Clear rather than stamp a suggestion in: an empty box means "use the
    // inherited model", which the placeholder names. Writing the suggestion
    // into the value would save it as an explicit override the user never
    // chose, and quietly detach them from the deployment default.
    setModel("");
    // A list fetched from one provider must not be offered for another.
    setModels([]);
    setCuratedModels([]);
    setModelsError(null);
    setModelsNote(null);
    if (newMode !== "custom") {
      setBaseUrl("");
    }
  };

  // Revoking a stored secret. The backend clears on an empty string, and a
  // test already pinned that, but nothing in the UI could send one: the field
  // treats blank as "keep", so "saved" was a state with no exit.
  const [removing, setRemoving] = useState<null | "apiKey" | "hfToken">(null);

  const handleRemoveSecret = async (which: "apiKey" | "hfToken") => {
    setRemoving(which);
    setError(null);
    try {
      await updateLlmConfig(
        which === "apiKey" ? { apiKey: "" } : { huggingfaceToken: "" },
      );
      if (which === "apiKey") setApiKey("");
      else setHfToken("");
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
      const apiType =
        uiMode === "anthropic" ? "anthropic"
        : uiMode === "gemini" ? "gemini"
        : "openai_compatible";

      await updateLlmConfig({
        apiType,
        baseUrl: uiMode === "custom" ? baseUrl : "",
        // Sent verbatim, so clearing the box clears the override. It used to
        // be `model || undefined`, which JSON.stringify drops, so a blank
        // field was omitted from the PATCH and the backend kept the old value:
        // the copy said "leave blank to use the deployment default" and there
        // was no way to get back to it.
        model,
        // "Blank means keep" holds only while you are on the provider the
        // stored key belongs to - that is what its label promises, and
        // re-typing a key to save an unrelated field would be hostile. On any
        // other tab, blank has to mean *clear* (#242): the account holds one
        // key, and leaving it in place while writing a new llm_api_type
        // silently re-attributed a Gemini key to Anthropic and sent it there.
        apiKey: keyBelongsHere ? (apiKey || undefined) : apiKey,
        huggingfaceToken: hfToken || undefined,
      });
      setSuccess(true);
      setApiKey("");
      setHfToken("");
      // 2000, not 800: this line is the only feedback that a credential was
      // stored, and it shared its budget with the panel's own dismissal, so it
      // was gone in roughly a third of a comfortable read.
      setTimeout(onClose, 2000);
    } catch (e: any) {
      setError(e.message || "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  };

  if (!isOpen) return null;

  const info = PROVIDER_INFO[uiMode];
  // `models` is the merged list the server returned, live entries first. Split
  // it back apart for the dropdown's two groups rather than asking the server
  // for it twice.
  const curatedSet = new Set(curatedModels);
  const liveModels = models.filter((m) => !curatedSet.has(m));
  const offeredCurated = models.filter((m) => curatedSet.has(m));

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
                <label className={modal.label} htmlFor="ai-settings-base-url">
                  Base URL
                </label>
                <input
                  id="ai-settings-base-url"
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
              <label className={modal.label} htmlFor="ai-settings-api-key">
                API Key{" "}
                <span className={styles.optional}>
                  {keyBelongsHere
                    ? "(saved - leave blank to keep)"
                    : deployed?.hasApiKey
                      ? "(optional - this deployment provides one)"
                      : uiMode === "custom"
                        ? "(optional for keyless servers)"
                        : "(required)"}
                </span>
              </label>
              <input
                id="ai-settings-api-key"
                className={modal.input}
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={keyBelongsHere ? "••••••••  (unchanged)" : "Enter your API key"}
                autoComplete="new-password"
                aria-describedby={otherProviderHasKey ? OTHER_KEY_NOTE_ID : undefined}
              />
              {/* One credential per account, so switching tabs and saving
                  replaces the stored key rather than adding a second one. The
                  panel used to imply otherwise by showing "saved" on every tab
                  (#242), and saving from one of them quietly kept the other
                  provider's key and relabelled it. */}
              {otherProviderHasKey && (
                <span id={OTHER_KEY_NOTE_ID} className={modal.hint}>
                  Curio stores one provider key per account, and the saved one
                  belongs to {PROVIDER_LABEL[savedMode]}. Saving here replaces
                  it.
                </span>
              )}
              {info.keyLink && (
                <a href={info.keyLink} target="_blank" rel="noreferrer" className={styles.keyLink}>
                  {info.keyLinkLabel} →
                </a>
              )}
              {keyBelongsHere && (
                <button
                  type="button"
                  className={styles.removeSecretBtn}
                  onClick={() => void handleRemoveSecret("apiKey")}
                  disabled={removing !== null}
                >
                  {removing === "apiKey" ? "Removing…" : "Remove saved key"}
                </button>
              )}
            </div>

            <div className={modal.field}>
              <label className={modal.label} htmlFor="ai-settings-model">
                Model
              </label>
              {models.length > 0 ? (
                <select
                  id="ai-settings-model"
                  className={modal.input}
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                >
                  {/* Blank stays reachable: it is what "inherit the
                      deployment's model" means, and losing it would strand a
                      user who had chosen inheritance. */}
                  <option value="">
                    {deployed?.model
                      ? `${deployed.model} (from this deployment)`
                      : "Select a model…"}
                  </option>
                  {/* Grouped so a curated suggestion is never mistaken for
                      something the endpoint said it had (#241). When only one
                      group has entries the label still reads correctly, so
                      there is no special case for that. */}
                  {liveModels.length > 0 && (
                    <optgroup label="From this endpoint">
                      {liveModels.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </optgroup>
                  )}
                  {offeredCurated.length > 0 && (
                    <optgroup label="Known models for this provider">
                      {offeredCurated.map((m) => (
                        <option key={m} value={m}>{m}</option>
                      ))}
                    </optgroup>
                  )}
                  {/* A model saved earlier that the endpoint no longer lists
                      would otherwise vanish from the box that claims to show
                      it. */}
                  {model && !models.includes(model) && (
                    <option value={model}>{model} (not listed)</option>
                  )}
                </select>
              ) : (
                <input
                  id="ai-settings-model"
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
              )}
              <div className={styles.modelFetchRow}>
                <button
                  type="button"
                  className={styles.fetchModelsBtn}
                  onClick={() => void loadModels()}
                  disabled={loadingModels}
                >
                  {loadingModels
                    ? "Fetching models…"
                    : models.length > 0
                      ? "Refresh models"
                      : "Fetch models"}
                </button>
                {modelsError && (
                  <span className={styles.modelsError}>{modelsError}</span>
                )}
                {!modelsError && modelsNote && (
                  <span className={styles.modelsNote}>{modelsNote}</span>
                )}
              </div>
              <span className={modal.hint}>
                Asks the endpoint above what it serves. Leave blank to inherit
                the deployment's model.
              </span>
            </div>

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
