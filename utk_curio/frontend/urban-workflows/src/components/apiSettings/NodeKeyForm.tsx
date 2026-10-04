import React, { useEffect, useMemo, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import llmStyles from "../llmConfigs/LlmConfigs.module.css";
import styles from "./ApiSettings.module.css";
import { connectionKeysApi, type ConnectionKeyRef } from "../../api/connectionKeysApi";
import { suggestName } from "./apiSettingsRequest";

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

/** How a key's row says where it goes. */
export function deliveryText(delivery: string): string {
  const { kind, target } = splitDelivery(delivery);
  if (kind === "query") return `query parameter "${target}"`;
  if (kind === "header") return `header "${target}"`;
  return "in the code";
}

export function formatUsed(ts: number | null): string {
  if (!ts) return "never used";
  try {
    return `used ${new Date(ts * 1000).toLocaleString()}`;
  } catch {
    return "used";
  }
}

/**
 * The form for a key node code reads by name, as `curio_secret("<name>")`,
 * sent only to its host. The key is entered once through a masked, write-only
 * field and never read back. Opened from API keys' "Add configuration", from a
 * saved key's Replace, or from a card's "Add key for <host>" with the host
 * filled in.
 */
export const NodeKeyForm: React.FC<{
  /** A saved key to replace, or what a card asked for. */
  initial?: { name?: string; host?: string; delivery?: string } | null;
  replacing?: boolean;
  /** The "Kind" select, when this form was opened by "Add configuration". */
  kindPicker?: React.ReactNode;
  onSaved: (key: ConnectionKeyRef) => void;
  onCancel: () => void;
}> = ({ initial = null, replacing = false, kindPicker, onSaved, onCancel }) => {
  const start = splitDelivery(initial?.delivery ?? "code");
  const [name, setName] = useState(initial?.name ?? (initial?.host ? suggestName(initial.host) : ""));
  const [host, setHost] = useState(initial?.host ?? "");
  const [deliveryKind, setDeliveryKind] = useState<DeliveryKind>(start.kind);
  const [deliveryTarget, setDeliveryTarget] = useState(start.target);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [needsReplace, setNeedsReplace] = useState(false);
  const firstRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    // Focus moves to the form when a card or a row sent the user here.
    const id = window.setTimeout(() => firstRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, []);

  const delivery = useMemo(() => {
    if (deliveryKind === "code") return "code";
    return `${deliveryKind}:${deliveryTarget.trim()}`;
  }, [deliveryKind, deliveryTarget]);

  const save = async (replace = false) => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await connectionKeysApi.put(name.trim(), {
        host: host.trim(),
        value,
        delivery,
        ...(replace ? { replace: true } : {}),
      });
      setValue(""); // write-only: the field never holds a saved value
      setNeedsReplace(false);
      onSaved(res.key);
    } catch (e) {
      const err = e as Error & { status?: number };
      setNeedsReplace(err.status === 409);
      setSaveError(err.message || "Could not save the key");
    } finally {
      setSaving(false);
    }
  };

  const canSave = !saving && name.trim() && host.trim() && value.trim() && (deliveryKind === "code" || deliveryTarget.trim());

  return (
    <div className={llmStyles.editor} data-testid="node-key-editor">
      <h4 className={llmStyles.editorTitle}>{replacing ? `Replace ${initial?.name}` : "Add a configuration"}</h4>
      {kindPicker}
      <p className={llmStyles.intro} id="node-key-intro">
        A key your node code reads by name: use <code>api_key = curio_secret("&lt;name&gt;")</code> in the
        node&apos;s code. The key never appears in your dataflow, proposals or chat, and it is never read back here.
      </p>
      <div className={styles.row}>
        <div className={modal.field}>
          <label className={modal.label} htmlFor="connection-key-name">Name</label>
          <input
            id="connection-key-name"
            ref={replacing ? undefined : firstRef}
            className={modal.input}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="census"
            autoComplete="off"
            readOnly={replacing}
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
          <span className={modal.hint}>The hostname only. A pasted URL is trimmed to it.</span>
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
          ref={replacing ? firstRef : undefined}
          className={modal.input}
          type="password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          autoComplete="new-password"
          aria-describedby="node-key-intro"
          disabled={saving}
        />
      </div>
      {saveError ? <p className={modal.error} role="alert">{saveError}</p> : null}
      <div className={modal.buttonRow}>
        <button type="button" className={modal.ghostBtn} onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        {needsReplace ? (
          <button type="button" className={modal.ghostBtn} disabled={!canSave} onClick={() => void save(true)}>
            Replace the host binding
          </button>
        ) : null}
        <button type="button" className={modal.primaryBtn} disabled={!canSave} onClick={() => void save(false)}>
          {saving ? "Saving…" : "Save key"}
        </button>
      </div>
    </div>
  );
};
