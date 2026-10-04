import React, { useCallback, useEffect, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import llmStyles from "../llmConfigs/LlmConfigs.module.css";
import styles from "./ApiSettings.module.css";
import { llmConfigsApi, type LlmConfig } from "../../api/llmConfigsApi";
import { connectionKeysApi, type ConnectionKeyRef } from "../../api/connectionKeysApi";
import { useUserContext } from "../../providers/UserProvider";
import {
  discoveryCatalogApi,
  notifyDiscoveryCatalogRefresh,
  type DiscoveryKeyRow,
} from "../../services/discoveryCatalog";
import { LlmConfigEditor } from "../llmConfigs/LlmConfigEditor";
import { PROVIDER_INFO, providerLabel } from "../llmConfigs/llmProviderInfo";
import { NodeKeyForm, deliveryText, formatUsed } from "./NodeKeyForm";
import { SourceKeyForm, usedByText } from "./SourceKeyForm";
import type { ApiSettingsFocus } from "./apiSettingsRequest";
import type { LlmListingState } from "./useLlmListing";

/** "A", "A and B", "A, B and C". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}

function deploymentProviderLabel(apiType: string | null): string {
  if (apiType === "anthropic") return PROVIDER_INFO.anthropic.label;
  if (apiType === "gemini") return PROVIDER_INFO.gemini.label;
  return "OpenAI-compatible";
}

/** What "Add configuration" adds: a language model, one data source's key,
 *  or a key node code reads. */
type AddKind = "llm" | "node" | `source:${string}`;

type Editing =
  | { mode: "add"; kind: AddKind; node?: { name?: string; host?: string } }
  | { mode: "llm"; config: LlmConfig }
  | { mode: "source"; slot: string }
  | { mode: "node"; key: ConnectionKeyRef };

const SOURCE_PREFIX = "source:";

/**
 * API Settings, API keys: every key this account uses, in one list, and one
 * "Add configuration" for each kind.
 *
 * - Language model: the Deployment default (this Curio's own, read only) and
 *   each LLM configuration, an endpoint and a model.
 * - Data source: the key a Discovery Catalog source sends, listed once one is
 *   saved or this Curio supplies one. The kinds come from the server's slot
 *   registry (`GET /api/discovery/keys`), so a key a new source needs appears
 *   without a change here.
 * - Node code: a key node code reads as `curio_secret("<name>")`, sent only to
 *   its host.
 *
 * Every key is write-only: the list says whether one is saved, never what it
 * is. A guest on a hosted Curio sees the guest configuration and can add
 * nothing.
 */
export const ApiKeysTab: React.FC<{
  llm: LlmListingState;
  hostedGuest: boolean;
  focus?: ApiSettingsFocus | null;
}> = ({ llm, hostedGuest, focus = null }) => {
  const { updateTokens } = useUserContext();
  const { listing, loadError, busy, error, act } = llm;
  const [sourceRows, setSourceRows] = useState<DiscoveryKeyRow[] | null>(hostedGuest ? [] : null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [nodeKeys, setNodeKeys] = useState<ConnectionKeyRef[] | null>(hostedGuest ? [] : null);
  const [nodeError, setNodeError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  // Bumped on every new form, so a form opened again starts from its initial state.
  const [formSeq, setFormSeq] = useState(0);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [keyBusy, setKeyBusy] = useState<string | null>(null);
  const [keyError, setKeyError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  const edit = useCallback((next: Editing | null) => {
    setEditing(next);
    setFormSeq((n) => n + 1);
    if (next) setStatus(null);
  }, []);

  const loadSources = useCallback(async () => {
    try {
      const res = await discoveryCatalogApi.listKeys();
      setSourceRows(res.keys);
      setSourceError(null);
    } catch (e) {
      // A list we could not read is reported, not guessed at: no row claims a
      // key is saved, or inherited, on no evidence.
      setSourceRows([]);
      setSourceError(e instanceof Error ? e.message : "Could not load the data source keys");
    }
  }, []);

  const loadNodeKeys = useCallback(async () => {
    try {
      const res = await connectionKeysApi.list();
      setNodeKeys(res.keys);
      setNodeError(null);
    } catch (e) {
      setNodeKeys([]);
      setNodeError(e instanceof Error ? e.message : "Could not load the keys for node code");
    }
  }, []);

  useEffect(() => {
    if (hostedGuest) return;
    void loadSources();
    void loadNodeKeys();
  }, [hostedGuest, loadSources, loadNodeKeys]);

  // A card asked for one place: open its form once what it names is listed.
  const appliedFocus = useRef<ApiSettingsFocus | null>(null);
  useEffect(() => {
    if (!focus || appliedFocus.current === focus) return;
    if (focus.section === "connection-keys") {
      if (hostedGuest) return;
      appliedFocus.current = focus;
      edit({ mode: "add", kind: "node", node: { name: focus.suggestedName, host: focus.host } });
    } else if (focus.section === "llm-configs") {
      if (!listing) return;
      appliedFocus.current = focus;
      const config = listing.configs.find((c) => c.id === focus.configId);
      if (config) edit({ mode: "llm", config });
    } else if (focus.section === "source-key") {
      if (!sourceRows) return;
      appliedFocus.current = focus;
      const row = sourceRows.find((r) => r.slot === focus.slot);
      if (row) edit(row.present ? { mode: "source", slot: row.slot } : { mode: "add", kind: `${SOURCE_PREFIX}${row.slot}` });
    }
  }, [edit, focus, hostedGuest, listing, sourceRows]);

  const removeSource = async (row: DiscoveryKeyRow) => {
    setKeyBusy(`source:${row.slot}`);
    setKeyError(null);
    try {
      await updateTokens({ [row.field]: "" });
      // A saved or removed key changes what its sources' cards and pages offer.
      notifyDiscoveryCatalogRefresh();
      setStatus(`Removed the saved ${row.label}.`);
      await loadSources();
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Failed to remove.");
    } finally {
      setKeyBusy(null);
      setConfirming(null);
    }
  };

  const removeNodeKey = async (keyName: string) => {
    setKeyBusy(`node:${keyName}`);
    setKeyError(null);
    const before = nodeKeys;
    setNodeKeys((prev) => (prev ?? []).filter((k) => k.name !== keyName));
    try {
      await connectionKeysApi.remove(keyName);
      setStatus(`Removed "${keyName}".`);
    } catch (e) {
      setNodeKeys(before);
      setKeyError(e instanceof Error ? e.message : "Could not remove the key");
    } finally {
      setKeyBusy(null);
      setConfirming(null);
    }
  };

  const saveSource = (row: DiscoveryKeyRow) => async (value: string) => {
    await updateTokens({ [row.field]: value });
    notifyDiscoveryCatalogRefresh();
    await loadSources();
    edit(null);
    setStatus(`Saved the ${row.label}.`);
  };

  if (!listing && !loadError) {
    return (
      <div className={styles.tabBody}data-testid="api-keys-tab">
        <div className={llmStyles.skeleton} aria-busy="true">Loading your keys…</div>
      </div>
    );
  }

  const llmEditable = Boolean(listing?.editable);
  const configs = llmEditable ? listing!.configs : [];
  const deployment = listing?.deployment ?? null;
  const full = listing ? configs.length >= listing.maxConfigs : true;
  const listedSources = (sourceRows ?? []).filter((r) => r.present || r.inherited);
  const addableSources = (sourceRows ?? []).filter((r) => !r.present);
  const anyBusy = busy !== null || keyBusy !== null;
  const llmKind: "on" | "full" | "off" = !llmEditable ? "off" : full ? "full" : "on";
  const firstKind: AddKind | null =
    llmKind === "on"
      ? "llm"
      : !hostedGuest && addableSources.length
        ? `${SOURCE_PREFIX}${addableSources[0].slot}`
        : !hostedGuest
          ? "node"
          : null;

  const chosenFor = (choice: string) =>
    (listing?.agents ?? []).filter((row) => row.choice === choice).map((row) => row.name);
  const chosenLine = (names: string[]) =>
    names.length ? <span className={llmStyles.host}>Chosen for {listNames(names)}</span> : null;
  const removeNote = (config: LlmConfig) => {
    const moved = chosenFor(config.id);
    const movedNote = moved.length
      ? ` ${listNames(moved)} ${moved.length === 1 ? "goes" : "go"} back to the default.`
      : "";
    const defaultNote =
      listing?.default === config.id
        ? deployment?.model
          ? ` It is your default, so runs will use the Deployment default (${deployment.model}).`
          : " It is your default, and nothing will answer a run until you choose another."
        : "";
    return movedNote + defaultNote;
  };

  const confirmCell = (id: string, label: string, text: string, run: () => void) => (
    <span className={llmStyles.confirm} role="alert">
      {text}
      <button
        type="button"
        className={modal.ghostBtn}
        disabled={anyBusy}
        aria-label={`Confirm removing ${label}`}
        onClick={run}
      >
        {busy === id || keyBusy === id ? "Removing…" : "Remove"}
      </button>
      <button type="button" className={modal.ghostBtn} onClick={() => setConfirming(null)}>
        Keep
      </button>
    </span>
  );

  const action = (label: string, ariaLabel: string, onClick: () => void, disabled = false) => (
    <button
      type="button"
      className={llmStyles.actionBtn}
      disabled={anyBusy || disabled}
      aria-label={ariaLabel}
      onClick={onClick}
    >
      {label}
    </button>
  );

  const kindPicker =
    editing?.mode === "add" ? (
      <div className={modal.field}>
        <label className={modal.label} htmlFor="api-key-kind">Kind</label>
        <select
          id="api-key-kind"
          className={modal.select}
          value={editing.kind}
          onChange={(e) => edit({ mode: "add", kind: e.target.value as AddKind })}
        >
          {llmKind !== "off" ? (
            <option value="llm" disabled={llmKind === "full"}>
              {llmKind === "full" ? "Language model (the most configurations are saved)" : "Language model"}
            </option>
          ) : null}
          {!hostedGuest && addableSources.length ? (
            <optgroup label="Data source">
              {addableSources.map((row) => (
                <option key={row.slot} value={`${SOURCE_PREFIX}${row.slot}`}>
                  {row.label}
                </option>
              ))}
            </optgroup>
          ) : null}
          {!hostedGuest ? <option value="node">Another API, for node code</option> : null}
        </select>
      </div>
    ) : undefined;

  const editor = () => {
    if (!editing) return null;
    const close = () => edit(null);
    if (editing.mode === "llm" || (editing.mode === "add" && editing.kind === "llm")) {
      if (!listing) return null;
      return (
        <LlmConfigEditor
          key={formSeq}
          initial={editing.mode === "llm" ? editing.config : null}
          deployment={listing.deployment}
          defaultChecked={editing.mode === "add" && configs.length === 0}
          kindPicker={kindPicker}
          onCancel={close}
          onSaved={(saved, makeDefault) => {
            edit(null);
            setStatus(`Saved ${saved.label}.`);
            void act(`saved:${saved.id}`, async () => {
              if (makeDefault) await llmConfigsApi.setDefault(saved.id);
            });
          }}
        />
      );
    }
    if (editing.mode === "node" || (editing.mode === "add" && editing.kind === "node")) {
      return (
        <NodeKeyForm
          key={formSeq}
          initial={editing.mode === "node" ? editing.key : editing.node ?? null}
          replacing={editing.mode === "node"}
          kindPicker={kindPicker}
          onCancel={close}
          onSaved={(key) => {
            setNodeKeys((prev) => {
              const rest = (prev ?? []).filter((k) => k.name !== key.name);
              return [...rest, key].sort((a, b) => a.name.localeCompare(b.name));
            });
            edit(null);
            setStatus(`Saved "${key.name}" for ${key.host}. Use it in node code as ${key.use}`);
          }}
        />
      );
    }
    const slot = editing.mode === "source" ? editing.slot : editing.kind.slice(SOURCE_PREFIX.length);
    const row = (sourceRows ?? []).find((r) => r.slot === slot);
    if (!row) return null;
    const title = editing.mode === "add" ? "Add a configuration" : `${row.present ? "Replace" : "Override"} ${row.label}`;
    return (
      <SourceKeyForm
        key={formSeq}
        row={row}
        title={title}
        kindPicker={kindPicker}
        onCancel={close}
        onSave={saveSource(row)}
      />
    );
  };

  const empty =
    !(llmEditable && deployment?.model) && configs.length === 0 && listedSources.length === 0 && !(nodeKeys ?? []).length;

  return (
    <div className={styles.tabBody}data-testid="api-keys-tab">
      <p className={llmStyles.intro}>
        Every key this account uses: the language models agents run on, the keys the Discovery Catalog sends to
        data sources, and keys your node code reads by name. Keys are write-only: once saved they are never shown
        again.
      </p>
      {loadError ? <p className={modal.error} role="alert">{loadError}</p> : null}
      {listing && !listing.editable ? (
        <>
          <p className={llmStyles.note} role="note">{listing.reason}</p>
          <p className={llmStyles.active}>
            {listing.active.source ? (
              <>
                Guests use <strong>{listing.active.model}</strong>
                {listing.active.baseUrlHost ? <> at <code>{listing.active.baseUrlHost}</code></> : null}.
              </>
            ) : (
              listing.active.error
            )}
          </p>
        </>
      ) : null}
      {hostedGuest ? (
        <p className={styles.guestNotice}>Personal keys cannot be saved on a shared guest account.</p>
      ) : null}
      {sourceError ? <p className={modal.error} role="alert">{sourceError}</p> : null}
      {nodeError ? <p className={modal.error} role="alert">{nodeError}</p> : null}

      {sourceRows === null || nodeKeys === null ? (
        <div className={llmStyles.skeleton} aria-busy="true">Loading your keys…</div>
      ) : empty ? (
        llmEditable || !hostedGuest ? <p className={llmStyles.empty}>No keys yet.</p> : null
      ) : (
        <table className={llmStyles.table}>
          <caption>Your keys. Keys are never shown.</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Kind</th>
              <th scope="col">Details</th>
              <th scope="col">Key</th>
              <th scope="col"><span className={modal.hint}>Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {llmEditable && deployment?.model ? (
              <tr data-testid="llm-deployment-row">
                <td className={llmStyles.name}>
                  {deployment.label}
                  {listing!.default === null ? <span className={llmStyles.badge}>Default</span> : null}
                </td>
                <td>Language model</td>
                <td>
                  {deploymentProviderLabel(deployment.apiType)} · {deployment.model}
                  {deployment.baseUrlHost ? <span className={llmStyles.host}>{deployment.baseUrlHost}</span> : null}
                  {chosenLine(chosenFor("deployment"))}
                </td>
                <td>set by this Curio</td>
                <td />
              </tr>
            ) : null}
            {configs.map((config) => {
              const id = `llm:${config.id}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>
                    {config.label}
                    {listing!.default === config.id ? <span className={llmStyles.badge}>Default</span> : null}
                    {config.origin === "trained" ? <span className={llmStyles.badge}>Trained</span> : null}
                  </td>
                  <td>Language model</td>
                  <td>
                    {providerLabel(config)} · {config.model}
                    {config.baseUrlHost ? <span className={llmStyles.host}>{config.baseUrlHost}</span> : null}
                    {chosenLine(chosenFor(config.id))}
                  </td>
                  <td>{config.endpoint === "deployment" ? "this Curio's" : config.hasApiKey ? "saved" : "none"}</td>
                  <td className={llmStyles.actions}>
                    {confirming === id
                      ? confirmCell(id, config.label, `Remove ${config.label}?${removeNote(config)}`, () => {
                          void act(id, () => llmConfigsApi.remove(config.id)).finally(() => setConfirming(null));
                        })
                      : (
                        <>
                          {action("Edit", `Edit ${config.label}`, () => edit({ mode: "llm", config }))}
                          {action("Duplicate", `Duplicate ${config.label}`, () => {
                            void act(`duplicate:${config.id}`, () => llmConfigsApi.duplicate(config.id));
                          }, full)}
                          {action("Remove", `Remove ${config.label}`, () => setConfirming(id))}
                        </>
                      )}
                  </td>
                </tr>
              );
            })}
            {listedSources.map((row) => {
              const id = `source:${row.slot}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>{row.label}</td>
                  <td>Data source</td>
                  <td>{usedByText(row)}</td>
                  <td>{row.present ? "saved" : "set by this Curio"}</td>
                  <td className={llmStyles.actions}>
                    {confirming === id
                      ? confirmCell(id, row.label, `Remove the saved ${row.label}?`, () => void removeSource(row))
                      : (
                        <>
                          {row.present
                            ? action("Replace", `Replace ${row.label}`, () => edit({ mode: "source", slot: row.slot }))
                            : action("Override", `Override ${row.label}`, () => edit({ mode: "source", slot: row.slot }))}
                          {row.present ? action("Remove", `Remove ${row.label}`, () => setConfirming(id)) : null}
                        </>
                      )}
                  </td>
                </tr>
              );
            })}
            {(nodeKeys ?? []).map((k) => {
              const id = `node:${k.name}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>{k.name}</td>
                  <td>Node code</td>
                  <td>
                    {k.host} · {deliveryText(k.delivery)}
                    <span className={llmStyles.host}>{formatUsed(k.lastUsedAt)}</span>
                  </td>
                  <td>saved</td>
                  <td className={llmStyles.actions}>
                    {confirming === id
                      ? confirmCell(
                          id,
                          k.name,
                          `Nodes that call curio_secret("${k.name}") will fail until a key with this name is saved again.`,
                          () => void removeNodeKey(k.name),
                        )
                      : (
                        <>
                          {action("Replace", `Replace ${k.name}`, () => edit({ mode: "node", key: k }))}
                          {action("Remove", `Remove ${k.name}`, () => setConfirming(id))}
                        </>
                      )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {error ? <p className={modal.error} role="alert">{error}</p> : null}
      {keyError ? <p className={modal.error} role="alert">{keyError}</p> : null}
      {status ? <p className={modal.success} role="status">{status}</p> : null}

      {editing ? (
        editor()
      ) : firstKind && sourceRows !== null && nodeKeys !== null ? (
        <div className={modal.buttonRow}>
          <button
            type="button"
            className={modal.ghostBtn}
            disabled={anyBusy}
            onClick={() => edit({ mode: "add", kind: firstKind })}
          >
            Add configuration
          </button>
        </div>
      ) : null}
    </div>
  );
};
