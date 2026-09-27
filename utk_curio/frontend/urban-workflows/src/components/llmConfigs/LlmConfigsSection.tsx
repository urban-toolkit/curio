import React, { useCallback, useEffect, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "./LlmConfigs.module.css";
import { llmConfigsApi, type LlmConfig, type LlmListing } from "../../api/llmConfigsApi";
import { LlmConfigEditor } from "./LlmConfigEditor";
import { PROVIDER_INFO, providerLabel } from "./llmProviderInfo";

function deploymentProviderLabel(apiType: string | null): string {
  if (apiType === "anthropic") return PROVIDER_INFO.anthropic.label;
  if (apiType === "gemini") return PROVIDER_INFO.gemini.label;
  return "OpenAI-compatible";
}

/**
 * AI Settings → LLM configurations. Each configuration is an endpoint and a
 * model; the default answers every agent. Keys are write-only: the table says
 * whether one is saved, never what it is. The Deployment default is this
 * Curio's own configuration, read-only here, and answers when no default is
 * chosen.
 *
 * A guest on a hosted Curio sees the guest configuration and nothing to edit.
 */
export const LlmConfigsSection: React.FC = () => {
  const [listing, setListing] = useState<LlmListing | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<LlmConfig | "new" | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setListing(await llmConfigsApi.listing());
      setLoadError(null);
    } catch (e: any) {
      setLoadError(e?.message || "Could not load your LLM configurations.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (key: string, run: () => Promise<unknown>) => {
    setBusy(key);
    setError(null);
    try {
      await run();
      await load();
    } catch (e: any) {
      setError(e?.message || "That did not work.");
    } finally {
      setBusy(null);
      setConfirmRemove(null);
    }
  };

  if (loadError) {
    return (
      <section className={styles.section} data-testid="llm-configs-section">
        <h3 className={styles.heading}>LLM configurations</h3>
        <p className={modal.error} role="alert">{loadError}</p>
      </section>
    );
  }
  if (!listing) {
    return (
      <section className={styles.section} data-testid="llm-configs-section">
        <h3 className={styles.heading}>LLM configurations</h3>
        <div className={styles.skeleton} aria-busy="true">Loading your LLM configurations…</div>
      </section>
    );
  }

  const { deployment, active } = listing;

  if (!listing.editable) {
    return (
      <section className={styles.section} data-testid="llm-configs-section">
        <h3 className={styles.heading}>LLM configurations</h3>
        <p className={styles.note} role="note">{listing.reason}</p>
        {active.source ? (
          <p className={styles.active}>
            Guests use <strong>{active.model}</strong>
            {active.baseUrlHost ? <> at <code>{active.baseUrlHost}</code></> : null}.
          </p>
        ) : (
          <p className={styles.active}>{active.error}</p>
        )}
      </section>
    );
  }

  const configs = listing.configs;
  const full = configs.length >= listing.maxConfigs;
  const removeNote = (config: LlmConfig) =>
    listing.default === config.id
      ? deployment.model
        ? ` It is your default, so runs will use the Deployment default (${deployment.model}).`
        : " It is your default, and nothing will answer a run until you choose another."
      : "";

  return (
    <section className={styles.section} data-testid="llm-configs-section">
      <h3 className={styles.heading}>LLM configurations</h3>
      <p className={styles.intro}>
        Each configuration is an endpoint and a model. Your default answers every agent. Keys are write-only:
        once saved they are never shown again.
      </p>
      {listing.shared ? (
        <p className={styles.shared} role="note">
          Everyone using this Curio shares this account, so configurations saved here are shared too.
        </p>
      ) : null}
      <p className={styles.active} data-testid="llm-active">
        {active.source ? (
          <>
            Answering now: <strong>{active.label}</strong> · {active.model}
            {active.baseUrlHost ? <> at <code>{active.baseUrlHost}</code></> : null}
          </>
        ) : (
          active.error
        )}
      </p>

      <table className={styles.table}>
        <caption>Your configurations. Keys are never shown.</caption>
        <thead>
          <tr>
            <th scope="col">Label</th>
            <th scope="col">Provider</th>
            <th scope="col">Model</th>
            <th scope="col">Key</th>
            <th scope="col"><span className={modal.hint}>Actions</span></th>
          </tr>
        </thead>
        <tbody>
          {deployment.model ? (
            <tr data-testid="llm-deployment-row">
              <td className={styles.name}>
                {deployment.label}
                {listing.default === null ? <span className={styles.badge}>Default</span> : null}
              </td>
              <td>
                {deploymentProviderLabel(deployment.apiType)}
                {deployment.baseUrlHost ? <span className={styles.host}>{deployment.baseUrlHost}</span> : null}
              </td>
              <td>{deployment.model}</td>
              <td>set by this Curio</td>
              <td className={styles.actions}>
                {listing.default !== null ? (
                  <button
                    type="button"
                    className={styles.actionBtn}
                    disabled={busy !== null}
                    onClick={() => void act("default:deployment", () => llmConfigsApi.setDefault(null))}
                  >
                    Make default
                  </button>
                ) : null}
              </td>
            </tr>
          ) : null}
          {configs.map((config) => (
            <tr key={config.id}>
              <td className={styles.name}>
                {config.label}
                {listing.default === config.id ? <span className={styles.badge}>Default</span> : null}
                {config.origin === "trained" ? <span className={styles.badge}>Trained</span> : null}
              </td>
              <td>
                {providerLabel(config)}
                {config.baseUrlHost ? <span className={styles.host}>{config.baseUrlHost}</span> : null}
              </td>
              <td>{config.model}</td>
              <td>{config.endpoint === "deployment" ? "this Curio's" : config.hasApiKey ? "saved" : "none"}</td>
              <td className={styles.actions}>
                {confirmRemove === config.id ? (
                  <span className={styles.confirm} role="alert">
                    Remove {config.label}?{removeNote(config)}
                    <button
                      type="button"
                      className={modal.ghostBtn}
                      disabled={busy !== null}
                      aria-label={`Confirm removing ${config.label}`}
                      onClick={() => void act(`remove:${config.id}`, () => llmConfigsApi.remove(config.id))}
                    >
                      {busy === `remove:${config.id}` ? "Removing…" : "Remove"}
                    </button>
                    <button type="button" className={modal.ghostBtn} onClick={() => setConfirmRemove(null)}>
                      Keep
                    </button>
                  </span>
                ) : (
                  <>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      disabled={busy !== null}
                      aria-label={`Edit ${config.label}`}
                      onClick={() => setEditing(config)}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className={styles.actionBtn}
                      disabled={busy !== null || full}
                      aria-label={`Duplicate ${config.label}`}
                      onClick={() => void act(`duplicate:${config.id}`, () => llmConfigsApi.duplicate(config.id))}
                    >
                      Duplicate
                    </button>
                    {listing.default !== config.id ? (
                      <button
                        type="button"
                        className={styles.actionBtn}
                        disabled={busy !== null}
                        aria-label={`Make ${config.label} the default`}
                        onClick={() => void act(`default:${config.id}`, () => llmConfigsApi.setDefault(config.id))}
                      >
                        Make default
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className={styles.actionBtn}
                      disabled={busy !== null}
                      aria-label={`Remove ${config.label}`}
                      onClick={() => setConfirmRemove(config.id)}
                    >
                      Remove
                    </button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {configs.length === 0 ? <p className={styles.empty}>No configurations of your own yet.</p> : null}
      {error ? <p className={modal.error} role="alert">{error}</p> : null}

      {editing ? (
        <LlmConfigEditor
          key={editing === "new" ? "new" : editing.id}
          initial={editing === "new" ? null : editing}
          deployment={deployment}
          defaultChecked={editing === "new" && configs.length === 0}
          onCancel={() => setEditing(null)}
          onSaved={(saved, makeDefault) => {
            setEditing(null);
            void act(`saved:${saved.id}`, async () => {
              if (makeDefault) await llmConfigsApi.setDefault(saved.id);
            });
          }}
        />
      ) : (
        <div className={modal.buttonRow}>
          <button
            type="button"
            className={modal.ghostBtn}
            disabled={busy !== null || full}
            onClick={() => setEditing("new")}
          >
            Add configuration
          </button>
        </div>
      )}
    </section>
  );
};
