import React, { useMemo, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "./LlmConfigs.module.css";
import {
  llmConfigsApi,
  type LlmConfig,
  type LlmConfigInput,
  type LlmDeployment,
} from "../../api/llmConfigsApi";
import {
  DEPLOYMENT_TAB_LABEL,
  PROVIDER_INFO,
  endpointFields,
  formatSeenAt,
  uiModeOf,
  type UiMode,
} from "./llmProviderInfo";

/**
 * Adds or edits one LLM configuration: a label, a provider, its endpoint, a
 * write-only key and a model. A key typed here is sent once and never shown
 * again; editing leaves it in place unless a new one is typed or it is
 * removed. The server refuses a key that would follow its configuration to a
 * different endpoint, and its message is shown as is.
 */
export const LlmConfigEditor: React.FC<{
  initial: LlmConfig | null;
  deployment: LlmDeployment;
  /** For a new configuration: whether "Make this my default" starts checked. */
  defaultChecked?: boolean;
  /** API keys' "Kind" select, when "Add configuration" opened this editor. */
  kindPicker?: React.ReactNode;
  onSaved: (config: LlmConfig, makeDefault: boolean) => void;
  onCancel: () => void;
}> = ({ initial, deployment, defaultChecked = false, kindPicker, onSaved, onCancel }) => {
  const [label, setLabel] = useState(initial?.label ?? "");
  const [mode, setMode] = useState<UiMode>(initial ? uiModeOf(initial) : "openai");
  const [baseUrl, setBaseUrl] = useState(
    initial && uiModeOf(initial) === "custom" ? initial.baseUrl : "",
  );
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [model, setModel] = useState(initial?.model ?? "");
  const [makeDefault, setMakeDefault] = useState(defaultChecked);
  const [models, setModels] = useState<string[]>([]);
  const [replay, setReplay] = useState<{ at: string | null } | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsNote, setModelsNote] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const tabs: UiMode[] = useMemo(
    () => [
      "openai",
      "anthropic",
      "gemini",
      "custom",
      ...(deployment.endpointOffered || initial?.endpoint === "deployment" ? (["deployment"] as UiMode[]) : []),
    ],
    [deployment.endpointOffered, initial?.endpoint],
  );
  const info = mode === "deployment" ? null : PROVIDER_INFO[mode];
  const sameEndpoint = initial !== null && uiModeOf(initial) === mode
    && (mode !== "custom" || baseUrl.trim().replace(/\/+$/, "") === initial.baseUrl);
  const keySaved = Boolean(initial?.hasApiKey) && sameEndpoint && !clearKey;
  const idBase = initial ? `llm-config-${initial.id}` : "llm-config-new";

  const selectMode = (next: UiMode) => {
    setMode(next);
    setModels([]);
    setReplay(null);
    setModelsNote(null);
    setClearKey(false);
    if (next !== "custom") setBaseUrl("");
  };

  const fetchModels = async () => {
    setLoadingModels(true);
    setModelsNote(null);
    try {
      const fields = endpointFields(mode, baseUrl, initial);
      const res = await llmConfigsApi.models(
        mode === "deployment"
          ? { endpoint: "deployment" }
          : {
              apiType: fields.apiType,
              baseUrl: fields.baseUrl,
              apiKey: apiKey || undefined,
              // Lets the server use the key saved on this configuration, and
              // only while the endpoint is still its own.
              configId: initial?.id,
            },
      );
      setModels(res.models);
      setReplay(res.source === "remembered" ? { at: res.rememberedAt ?? null } : null);
      if (res.source === "remembered") {
        setModelsNote(
          (res.warning ? res.warning + " " : "") +
            "Showing what this endpoint last reported" + formatSeenAt(res.rememberedAt) + " instead.",
        );
      } else if (res.models.length === 0) {
        setModelsNote("The endpoint returned no models.");
      }
    } catch (e: any) {
      setModels([]);
      setReplay(null);
      setModelsNote(e?.message || "Could not list models.");
    } finally {
      setLoadingModels(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    const body: LlmConfigInput = {
      label: label.trim(),
      model: model.trim(),
      ...endpointFields(mode, baseUrl, initial),
    };
    if (mode !== "deployment") {
      if (apiKey) body.apiKey = apiKey;
      // A saved key stays with its endpoint: moving without typing one saves
      // the configuration keyless, or the server says this provider needs one.
      else if (clearKey || (initial?.hasApiKey && !sameEndpoint)) body.clearApiKey = true;
    }
    try {
      const res = initial ? await llmConfigsApi.update(initial.id, body) : await llmConfigsApi.create(body);
      setApiKey("");
      onSaved(res.config, makeDefault);
    } catch (e: any) {
      setError(e?.message || "Could not save the configuration.");
    } finally {
      setSaving(false);
    }
  };

  const canSave = !saving && label.trim() && model.trim() && (mode !== "custom" || baseUrl.trim());

  return (
    <div className={styles.editor} data-testid="llm-config-editor">
      <h4 className={styles.editorTitle}>{initial ? `Edit ${initial.label}` : "Add a configuration"}</h4>
      {kindPicker}

      <div className={modal.field}>
        <label className={modal.label} htmlFor={`${idBase}-label`}>Label</label>
        <input
          id={`${idBase}-label`}
          className={modal.input}
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Work OpenAI, Local Ollama…"
          autoComplete="off"
          disabled={saving}
        />
      </div>

      <div className={modal.field}>
        <span className={modal.label} id={`${idBase}-provider`}>Provider</span>
        <div className={styles.modeTabs} role="group" aria-labelledby={`${idBase}-provider`}>
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              className={`${styles.modeTab} ${mode === tab ? styles.modeTabActive : ""}`}
              aria-pressed={mode === tab}
              onClick={() => selectMode(tab)}
              disabled={saving}
            >
              {tab === "deployment" ? DEPLOYMENT_TAB_LABEL : PROVIDER_INFO[tab].label}
            </button>
          ))}
        </div>
      </div>

      {mode === "deployment" ? (
        <p className={styles.note}>
          Runs on this Curio install&apos;s own endpoint
          {deployment.baseUrlHost ? ` (${deployment.baseUrlHost})` : ""} with its key. You choose the model.
        </p>
      ) : null}

      {info?.showBaseUrl ? (
        <div className={modal.field}>
          <label className={modal.label} htmlFor={`${idBase}-base-url`}>Base URL</label>
          <input
            id={`${idBase}-base-url`}
            className={modal.input}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder={info.baseUrlPlaceholder}
            autoComplete="off"
            disabled={saving}
          />
        </div>
      ) : null}

      {mode !== "deployment" && info ? (
        <div className={modal.field}>
          <label className={modal.label} htmlFor={`${idBase}-api-key`}>
            API key{" "}
            <span className={styles.optional}>
              {keySaved
                ? "(saved - leave blank to keep)"
                : info.keyRequired || mode === "openai"
                  ? "(required)"
                  : "(optional for keyless servers)"}
            </span>
          </label>
          <input
            id={`${idBase}-api-key`}
            className={modal.input}
            type="password"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder={keySaved ? "••••••••  (unchanged)" : ""}
            autoComplete="new-password"
            disabled={saving}
          />
          <span className={modal.hint}>
            Kept on this Curio for this configuration only and never shown again.
            {initial?.hasApiKey && !sameEndpoint
              ? " A key never follows a configuration to another endpoint, so enter it again."
              : ""}
          </span>
          {info.keyLink ? (
            <a href={info.keyLink} target="_blank" rel="noreferrer" className={styles.keyLink}>
              {info.keyLinkLabel} ↗
            </a>
          ) : null}
          {keySaved && !info.keyRequired ? (
            <button
              type="button"
              className={styles.quietBtn}
              onClick={() => setClearKey(true)}
              disabled={saving}
            >
              Remove the saved key
            </button>
          ) : null}
        </div>
      ) : null}

      <div className={modal.field}>
        <label className={modal.label} htmlFor={`${idBase}-model`}>Model</label>
        <input
          id={`${idBase}-model`}
          className={modal.input}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder={info?.model || (mode === "deployment" ? deployment.model ?? "" : "")}
          list={models.length ? `${idBase}-models` : undefined}
          autoComplete="off"
          disabled={saving}
        />
        {models.length ? (
          <datalist id={`${idBase}-models`}>
            {models.map((m) => (
              <option key={m} value={m} />
            ))}
          </datalist>
        ) : null}
        <div className={styles.modelFetchRow}>
          <button
            type="button"
            className={styles.fetchModelsBtn}
            onClick={() => void fetchModels()}
            disabled={loadingModels || saving}
          >
            {loadingModels ? "Fetching models…" : models.length ? "Refresh models" : "Fetch models"}
          </button>
          {models.length ? (
            <span className={modal.hint}>
              {replay ? "Last reported by this endpoint" + formatSeenAt(replay.at) : "From this endpoint"}:{" "}
              {models.length} model{models.length === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>
        {modelsNote ? <span className={modal.hint} role="status">{modelsNote}</span> : null}
      </div>

      {!initial ? (
        <label className={styles.checkRow}>
          <input
            type="checkbox"
            checked={makeDefault}
            onChange={(e) => setMakeDefault(e.target.checked)}
            disabled={saving}
          />
          Make this my default
        </label>
      ) : null}

      {error ? <p className={modal.error} role="alert">{error}</p> : null}
      <div className={modal.buttonRow}>
        <button type="button" className={modal.ghostBtn} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className={modal.primaryBtn} onClick={() => void save()} disabled={!canSave}>
          {saving ? "Saving…" : initial ? "Save configuration" : "Add configuration"}
        </button>
      </div>
    </div>
  );
};
