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
import { providerLabel } from "../llmConfigs/llmProviderInfo";
import { CURIO_DEFAULT_BADGE, CURIO_DEFAULT_LABEL, CURIO_ROW_NAME, providedBy } from "../llmConfigs/curioModels";
import { NodeKeyForm, deliveryText, formatUsed } from "./NodeKeyForm";
import { SourceKeyForm, usedByText } from "./SourceKeyForm";
import type { ApiSettingsFocus } from "./apiSettingsRequest";
import type { LlmListingState } from "./useLlmListing";
import { HOSTED_GUEST_KEYS_NOTE } from "./useHostedGuest";

/** "A", "A and B", "A, B and C". */
export function listNames(names: string[]): string {
  if (names.length <= 1) return names.join("");
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
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

const PLUS_ICON = (
  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" aria-hidden="true" focusable="false">
    <path d="M8 3v10M3 8h10" />
  </svg>
);

const REMOVE_ICON = (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8"
    strokeLinecap="round" aria-hidden="true" focusable="false">
    <path d="M4 4l8 8M12 4l-8 8" />
  </svg>
);

const EDIT_ICON = (
  <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinejoin="round" aria-hidden="true" focusable="false">
    <path d="M10.5 2.5l3 3L6 13H3v-3z" />
    <path d="M9 4l3 3" />
  </svg>
);

/**
 * API Settings, API keys: every key this account uses, in one list. The "+"
 * at the end of the list's header adds one of any kind.
 *
 * - Language model: one read-only row per endpoint of this Curio's own (the
 *   operator's endpoint file), named Curio and provided by that endpoint,
 *   listing its models; then each LLM configuration of the user's own, an
 *   endpoint and a model. Curio's models are picked on Agent configuration.
 * - Data source: the key a Discovery Catalog source sends, listed once one is
 *   saved or this Curio supplies one. The kinds are the keys the sources'
 *   manifests declare (`GET /api/discovery/keys`), so a key a new source needs
 *   appears without a change here, and is saved by its secret id.
 * - Node code: a key node code reads as `curio_secret("<name>")`, sent only to
 *   its host.
 *
 * A row the user owns ends with Remove and Edit. Every key is write-only: the
 * list says whether one is saved, never what it is. A guest on a hosted Curio
 * sees this Curio's rows and can add nothing.
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
      await updateTokens({ source_keys: { [row.slot]: "" } });
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
    await updateTokens({ source_keys: { [row.slot]: value } });
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
  // This Curio's own endpoints, which every account sees, a hosted guest's too.
  const curioEndpoints = deployment?.endpoints ?? [];
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
  const loaded = sourceRows !== null && nodeKeys !== null;
  const canAdd = firstKind !== null && loaded;

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
          ? ` It is your default, so runs will use ${CURIO_DEFAULT_LABEL} (${deployment.model}).`
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

  const iconButton = (
    icon: React.ReactNode, tooltip: string, ariaLabel: string, onClick: () => void,
  ) => (
    <button
      type="button"
      className={llmStyles.iconBtn}
      disabled={anyBusy}
      aria-label={ariaLabel}
      data-tooltip={tooltip}
      onClick={onClick}
    >
      {icon}
    </button>
  );

  /** The last cell of a row the user owns: Remove, then Edit, or the removal's question. */
  const ownedActions = (
    id: string,
    label: string,
    question: string,
    remove: () => void,
    open: () => void,
  ) => (
    <td className={`${llmStyles.actions} ${confirming === id ? llmStyles.confirming : ""}`}>
      {confirming === id ? (
        confirmCell(id, label, question, remove)
      ) : (
        <span className={llmStyles.rowIcons}>
          {iconButton(REMOVE_ICON, "Remove", `Remove ${label}`, () => setConfirming(id))}
          {iconButton(EDIT_ICON, "Edit", `Edit ${label}`, open)}
        </span>
      )}
    </td>
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
      const initial = editing.mode === "llm" ? editing.config : null;
      return (
        <LlmConfigEditor
          key={formSeq}
          initial={initial}
          defaultChecked={editing.mode === "add" && configs.length === 0}
          kindPicker={kindPicker}
          onDuplicate={initial ? () => {
            edit(null);
            void act(`duplicate:${initial.id}`, async () => {
              const copy = await llmConfigsApi.duplicate(initial.id);
              setStatus(`Added ${copy.config.label}.`);
            });
          } : undefined}
          duplicateDisabled={full || anyBusy}
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
    const title = editing.mode === "add" ? "Add a configuration" : `Replace ${row.label}`;
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

  const nodeKeyList = nodeKeys ?? [];
  const anyRows =
    curioEndpoints.length + configs.length + listedSources.length + nodeKeyList.length > 0;

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
                Guests use <strong>{listing.active.model}</strong> on this Curio&apos;s endpoint.
              </>
            ) : (
              listing.active.error
            )}
          </p>
        </>
      ) : null}
      {hostedGuest ? (
        <p className={styles.guestNotice}>{HOSTED_GUEST_KEYS_NOTE}</p>
      ) : null}
      {sourceError ? <p className={modal.error} role="alert">{sourceError}</p> : null}
      {nodeError ? <p className={modal.error} role="alert">{nodeError}</p> : null}

      {!loaded ? (
        <div className={llmStyles.skeleton} aria-busy="true">Loading your keys…</div>
      ) : !anyRows && !canAdd ? (
        llmEditable || !hostedGuest ? <p className={llmStyles.empty}>No keys yet.</p> : null
      ) : (
        <table className={llmStyles.table}>
          <caption>Your keys. Keys are never shown.</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Kind</th>
              <th scope="col">Details</th>
              <th scope="col" className={llmStyles.actionsHead}>
                <span className={llmStyles.srOnly}>Actions</span>
                {canAdd && !editing ? (
                  <button
                    type="button"
                    className={llmStyles.iconBtn}
                    disabled={anyBusy}
                    aria-label="Add configuration"
                    data-tooltip="Add configuration"
                    onClick={() => edit({ mode: "add", kind: firstKind! })}
                  >
                    {PLUS_ICON}
                  </button>
                ) : null}
              </th>
            </tr>
          </thead>
          <tbody>
            {curioEndpoints.map((endpoint, index) => {
              const [first, ...rest] = endpoint.models;
              return (
                <tr key={`curio:${endpoint.name}`} data-testid="llm-curio-row" data-endpoint={endpoint.name}>
                  <td className={llmStyles.name}>
                    {CURIO_ROW_NAME}
                    <span className={llmStyles.status}>{providedBy(endpoint.name)}</span>
                  </td>
                  <td>Language model</td>
                  <td>
                    {first}
                    {index === 0 ? <span className={llmStyles.badge}>{CURIO_DEFAULT_BADGE}</span> : null}
                    {rest.length ? <span className={llmStyles.host}>{rest.join(", ")}</span> : null}
                  </td>
                  <td />
                </tr>
              );
            })}
            {configs.map((config) => {
              const id = `llm:${config.id}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>
                    {config.label}
                    <span className={llmStyles.status}>{config.hasApiKey ? "Key saved" : "No key"}</span>
                  </td>
                  <td>Language model</td>
                  <td>
                    {providerLabel(config)} · {config.model}
                    {listing!.default === config.id ? <span className={llmStyles.badge}>My default</span> : null}
                    {config.baseUrlHost ? <span className={llmStyles.host}>{config.baseUrlHost}</span> : null}
                    {chosenLine(chosenFor(config.id))}
                  </td>
                  {ownedActions(
                    id,
                    config.label,
                    `Remove ${config.label}?${removeNote(config)}`,
                    () => {
                      void act(id, () => llmConfigsApi.remove(config.id)).finally(() => setConfirming(null));
                    },
                    () => edit({ mode: "llm", config }),
                  )}
                </tr>
              );
            })}
            {listedSources.map((row) => {
              const id = `source:${row.slot}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>
                    {row.label}
                    <span className={llmStyles.status}>{row.present ? "Key saved" : "Set by this Curio"}</span>
                  </td>
                  <td>Data source</td>
                  <td>{usedByText(row)}</td>
                  {row.present ? (
                    ownedActions(
                      id,
                      row.label,
                      `Remove the saved ${row.label}?`,
                      () => void removeSource(row),
                      () => edit({ mode: "source", slot: row.slot }),
                    )
                  ) : (
                    <td />
                  )}
                </tr>
              );
            })}
            {nodeKeyList.map((k) => {
              const id = `node:${k.name}`;
              return (
                <tr key={id} data-key-row={id}>
                  <td className={llmStyles.name}>
                    {k.name}
                    <span className={llmStyles.status}>Key saved</span>
                  </td>
                  <td>Node code</td>
                  <td>
                    {k.host} · {deliveryText(k.delivery)}
                    <span className={llmStyles.host}>{formatUsed(k.lastUsedAt)}</span>
                  </td>
                  {ownedActions(
                    id,
                    k.name,
                    `Nodes that call curio_secret("${k.name}") will fail until a key with this name is saved again.`,
                    () => void removeNodeKey(k.name),
                    () => edit({ mode: "node", key: k }),
                  )}
                </tr>
              );
            })}
            {!anyRows ? (
              <tr>
                <td colSpan={4} className={llmStyles.empty}>No keys yet.</td>
              </tr>
            ) : null}
          </tbody>
        </table>
      )}

      {error ? <p className={modal.error} role="alert">{error}</p> : null}
      {keyError ? <p className={modal.error} role="alert">{keyError}</p> : null}
      {status ? <p className={modal.success} role="status">{status}</p> : null}

      {editing ? editor() : null}
    </div>
  );
};
