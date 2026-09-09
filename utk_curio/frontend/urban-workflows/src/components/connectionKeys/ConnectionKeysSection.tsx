import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "./ConnectionKeysSection.module.css";
import { connectionKeysApi, type ConnectionKeyRef } from "../../api/connectionKeysApi";
import type { ConnectionKeysFocus } from "./connectionKeysRequest";

type DeliveryKind = "code" | "query" | "header";

const DELIVERY_LABEL: Record<DeliveryKind, string> = {
  code: "in the code (default)",
  query: "as a query parameter",
  header: "as an HTTP header",
};

function splitDelivery(delivery: string): { kind: DeliveryKind; target: string } {
  if (delivery.startsWith("query:")) return { kind: "query", target: delivery.slice(6) };
  if (delivery.startsWith("header:")) return { kind: "header", target: delivery.slice(7) };
  return { kind: "code", target: "" };
}

function deliveryText(delivery: string): string {
  const { kind, target } = splitDelivery(delivery);
  if (kind === "query") return `query parameter "${target}"`;
  if (kind === "header") return `header "${target}"`;
  return "in the code";
}

function suggestName(host: string): string {
  const bare = host
    .trim()
    .toLowerCase()
    .replace(/^[a-z]+:\/\//, "")
    .split(/[/?#:@]/)
    .filter(Boolean)
    .pop() ?? "";
  const labels = bare.split(".").filter(Boolean);
  const label = labels.length >= 2 ? labels[labels.length - 2] : labels[0] ?? "";
  return label.replace(/[^a-z0-9_-]/g, "-").replace(/^-+|-+$/g, "").slice(0, 40);
}

function formatUsed(ts: number | null): string {
  if (!ts) return "never used";
  try {
    return `used ${new Date(ts * 1000).toLocaleString()}`;
  } catch {
    return "used";
  }
}

/**
 * dev/116 (DEC-074): Settings → Connection keys. A key is entered once through
 * a masked, write-only field and never read back; node code reaches it as
 * `curio_secret("<name>")`. The table lists refs (name, host, delivery, last
 * used) — never values.
 */
export const ConnectionKeysSection: React.FC<{
  focus?: ConnectionKeysFocus | null;
  /** The shared guest account: keys are shared by everyone on this instance. */
  sharedGuest?: boolean;
}> = ({ focus = null, sharedGuest = false }) => {
  const [keys, setKeys] = useState<ConnectionKeyRef[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [open, setOpen] = useState<boolean>(Boolean(focus));

  const [name, setName] = useState(focus?.suggestedName ?? (focus?.host ? suggestName(focus.host) : ""));
  const [host, setHost] = useState(focus?.host ?? "");
  const [deliveryKind, setDeliveryKind] = useState<DeliveryKind>("code");
  const [deliveryTarget, setDeliveryTarget] = useState("");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [needsReplace, setNeedsReplace] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setListError(null);
    try {
      const res = await connectionKeysApi.list();
      setKeys(res.keys);
    } catch (e) {
      setKeys([]);
      setListError(e instanceof Error ? e.message : "Could not load the connection keys");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (focus) {
      setOpen(true);
      if (focus.host) setHost(focus.host);
      setName(focus.suggestedName ?? (focus.host ? suggestName(focus.host) : ""));
      // Focus moves to the form when a card sent the user here.
      const id = window.setTimeout(() => nameRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
    return undefined;
  }, [focus]);

  const delivery = useMemo(() => {
    if (deliveryKind === "code") return "code";
    return `${deliveryKind}:${deliveryTarget.trim()}`;
  }, [deliveryKind, deliveryTarget]);

  const save = async (replace = false) => {
    setSaving(true);
    setSaveError(null);
    setStatus(null);
    try {
      const res = await connectionKeysApi.put(name.trim(), {
        host: host.trim(),
        value,
        delivery,
        ...(replace ? { replace: true } : {}),
      });
      setValue(""); // write-only: the field never holds a saved value
      setNeedsReplace(false);
      setStatus(`Saved "${res.key.name}" for ${res.key.host}. Use it in node code as ${res.key.use}`);
      setKeys((prev) => {
        const rest = (prev ?? []).filter((k) => k.name !== res.key.name);
        return [...rest, res.key].sort((a, b) => a.name.localeCompare(b.name));
      });
    } catch (e) {
      const err = e as Error & { status?: number };
      setNeedsReplace(err.status === 409);
      setSaveError(err.message || "Could not save the key");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (keyName: string) => {
    setRemoving(keyName);
    setSaveError(null);
    const before = keys;
    setKeys((prev) => (prev ?? []).filter((k) => k.name !== keyName));
    try {
      await connectionKeysApi.remove(keyName);
      setStatus(`Removed "${keyName}".`);
    } catch (e) {
      setKeys(before);
      setSaveError(e instanceof Error ? e.message : "Could not remove the key");
    } finally {
      setRemoving(null);
      setConfirmRemove(null);
    }
  };

  const count = keys?.length ?? 0;
  const canSave = !saving && name.trim() && host.trim() && value.trim() && (deliveryKind === "code" || deliveryTarget.trim());

  const body = (
    <>
      <p className={styles.intro} id="connection-keys-intro">
        API keys a data-loading node reaches by name: use <code>api_key = curio_secret("&lt;name&gt;")</code> in the
        node's code. The key never appears in your dataflow, proposals or chat, and it is never read back here.
      </p>
      {sharedGuest ? (
        <p className={styles.shared} role="note">
          Keys saved here are shared by everyone using this local instance.
        </p>
      ) : null}

      {keys === null && !listError ? (
        <div className={styles.skeleton} aria-busy="true">Loading your keys…</div>
      ) : listError ? (
        <p className={modal.error} role="alert">{listError}</p>
      ) : count === 0 ? (
        <p className={styles.empty}>No connection keys yet.</p>
      ) : (
        <table className={styles.table}>
          <caption>Saved keys — values are never shown</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Host</th>
              <th scope="col">Sent as</th>
              <th scope="col">Last used</th>
              <th scope="col"><span className={modal.hint}>Remove</span></th>
            </tr>
          </thead>
          <tbody>
            {(keys ?? []).map((k) => (
              <tr key={k.name}>
                <td className={styles.name}>{k.name}</td>
                <td>{k.host}</td>
                <td>{deliveryText(k.delivery)}</td>
                <td>{formatUsed(k.lastUsedAt)}</td>
                <td>
                  {confirmRemove === k.name ? (
                    <span className={styles.confirm} role="alert">
                      Nodes that call curio_secret("{k.name}") will fail until a key with this name is saved again.
                      <button
                        type="button"
                        className={modal.ghostBtn}
                        disabled={removing !== null}
                        onClick={() => void remove(k.name)}
                        aria-label={`Confirm removing ${k.name}`}
                      >
                        {removing === k.name ? "Removing…" : "Remove"}
                      </button>
                      <button type="button" className={modal.ghostBtn} onClick={() => setConfirmRemove(null)}>
                        Keep
                      </button>
                    </span>
                  ) : (
                    <button
                      type="button"
                      className={styles.removeBtn}
                      onClick={() => setConfirmRemove(k.name)}
                      aria-label={`Remove ${k.name}`}
                    >
                      Remove
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      <div className={styles.row}>
        <div className={modal.field}>
          <label className={modal.label} htmlFor="connection-key-name">Name</label>
          <input
            id="connection-key-name"
            ref={nameRef}
            className={modal.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="census"
            autoComplete="off"
            disabled={saving}
          />
        </div>
        <div className={modal.field}>
          <label className={modal.label} htmlFor="connection-key-host">Host</label>
          <input
            id="connection-key-host"
            className={modal.input}
            value={host}
            onChange={(e) => {
              setHost(e.target.value);
              if (!name) setName(suggestName(e.target.value));
            }}
            placeholder="api.census.gov"
            autoComplete="off"
            disabled={saving}
          />
          <span className={modal.hint}>The hostname only — a pasted URL is trimmed to it.</span>
        </div>
      </div>
      <div className={styles.row}>
        <div className={modal.field}>
          <label className={modal.label} htmlFor="connection-key-delivery">Sent as</label>
          <select
            id="connection-key-delivery"
            className={modal.select}
            value={deliveryKind}
            onChange={(e) => setDeliveryKind(e.target.value as DeliveryKind)}
            disabled={saving}
          >
            {(Object.keys(DELIVERY_LABEL) as DeliveryKind[]).map((k) => (
              <option key={k} value={k}>{DELIVERY_LABEL[k]}</option>
            ))}
          </select>
        </div>
        {deliveryKind !== "code" ? (
          <div className={modal.field}>
            <label className={modal.label} htmlFor="connection-key-delivery-target">
              {deliveryKind === "query" ? "Parameter name" : "Header name"}
            </label>
            <input
              id="connection-key-delivery-target"
              className={modal.input}
              value={deliveryTarget}
              onChange={(e) => setDeliveryTarget(e.target.value)}
              placeholder={deliveryKind === "query" ? "key" : "X-Api-Key"}
              autoComplete="off"
              disabled={saving}
            />
          </div>
        ) : null}
      </div>
      <div className={modal.field}>
        <label className={modal.label} htmlFor="connection-key-value">Key</label>
        <input
          id="connection-key-value"
          className={modal.input}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="new-password"
          aria-describedby="connection-keys-intro"
          disabled={saving}
        />
      </div>
      {saveError ? <p className={modal.error} role="alert">{saveError}</p> : null}
      {status ? <p className={modal.success} role="status">{status}</p> : null}
      <div className={modal.buttonRow}>
        {needsReplace ? (
          <button type="button" className={modal.ghostBtn} disabled={!canSave} onClick={() => void save(true)}>
            Replace the host binding
          </button>
        ) : null}
        <button type="button" className={modal.primaryBtn} disabled={!canSave} onClick={() => void save(false)}>
          {saving ? "Saving…" : "Save key"}
        </button>
      </div>
    </>
  );

  return (
    <details
      className={styles.section}
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      data-testid="connection-keys-section"
    >
      <summary className={styles.summary}>
        Connection keys{keys === null ? "" : ` (${count})`}
      </summary>
      {/* The body mounts only while open: a closed section adds no fields,
          buttons or comboboxes to the modal's accessibility tree. */}
      {open ? body : null}
    </details>
  );
};

