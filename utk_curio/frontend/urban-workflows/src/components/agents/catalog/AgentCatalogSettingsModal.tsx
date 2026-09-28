import React, { useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import {
  agentsApi,
  type CatalogSetting,
  type CatalogSettingReader,
  type CatalogSettingsResponse,
} from "../../../api/agentsApi";
import styles from "./AgentCatalogSettingsModal.module.css";

/**
 * Catalog settings: values the user owns, such as the types a keyword can take,
 * which agents read when they run. Account-level, so one edit reaches every
 * project. The server defines each setting and validates every save; this
 * modal edits a list of entries whose fields the setting's schema names.
 */

type Row = Record<string, string>;

interface ItemSchema {
  required: string[];
  fields: { name: string; list: boolean }[];
}

/** The fields of a setting whose value is a list of entries, from its schema:
 * a string field is one input, a list of strings one comma-separated input. */
export function itemSchema(schema: Record<string, unknown>): ItemSchema | null {
  const items = schema.items as Record<string, unknown> | undefined;
  const properties = items?.properties as Record<string, { type?: string }> | undefined;
  if (schema.type !== "array" || !properties) return null;
  return {
    required: (items?.required as string[] | undefined) ?? [],
    fields: Object.entries(properties).map(([name, field]) => ({
      name,
      list: field.type === "array",
    })),
  };
}

function toRows(value: unknown, item: ItemSchema): Row[] {
  if (!Array.isArray(value)) return [];
  return value.map((entry: Record<string, unknown>) =>
    Object.fromEntries(
      item.fields.map(({ name, list }) => {
        const field = entry?.[name];
        return [name, list && Array.isArray(field) ? field.join(", ") : String(field ?? "")];
      })
    )
  );
}

/** Rows back to the value the server validates. Empty optional fields are left
 * out rather than sent as empty strings or lists. */
export function fromRows(rows: Row[], item: ItemSchema): Record<string, unknown>[] {
  return rows.map((row) => {
    const entry: Record<string, unknown> = {};
    for (const { name, list } of item.fields) {
      const text = (row[name] ?? "").trim();
      if (list) {
        const values = text
          .split(",")
          .map((part) => part.trim())
          .filter(Boolean);
        if (values.length > 0 || item.required.includes(name)) entry[name] = values;
      } else if (text || item.required.includes(name)) {
        entry[name] = text;
      }
    }
    return entry;
  });
}

function readerText(readers: CatalogSettingReader[]): string {
  const byAgent = new Map<string, string[]>();
  for (const reader of readers) {
    const capabilities = byAgent.get(reader.agentName) ?? [];
    capabilities.push(reader.capability ?? "every run");
    byAgent.set(reader.agentName, capabilities);
  }
  return Array.from(
    byAgent,
    ([agent, capabilities]) => `${agent} (${capabilities.join(", ")})`
  ).join("; ");
}

function fieldLabel(name: string): string {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

const SettingEditor: React.FC<{
  setting: CatalogSetting;
  editable: boolean;
  onSaved: (response: CatalogSettingsResponse) => void;
}> = ({ setting, editable, onSaved }) => {
  const item = itemSchema(setting.schema);
  const [rows, setRows] = useState<Row[]>(() => (item ? toRows(setting.value, item) : []));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  // A save or a restore answers with the server's value: show that one.
  useEffect(() => {
    const fields = itemSchema(setting.schema);
    if (fields) setRows(toRows(setting.value, fields));
  }, [setting.value, setting.schema]);

  if (!item) return null;

  const save = async (value: unknown | null) => {
    setError(null);
    setSaved(false);
    setBusy(true);
    try {
      onSaved(await agentsApi.updateCatalogSettings({ [setting.key]: value }));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Saving failed");
    } finally {
      setBusy(false);
    }
  };

  const update = (index: number, name: string, text: string) => {
    setSaved(false);
    setRows((prev) => prev.map((row, i) => (i === index ? { ...row, [name]: text } : row)));
  };

  return (
    <section className={styles.setting} aria-labelledby={`setting-${setting.key}`}>
      <h3 id={`setting-${setting.key}`} className={styles.settingTitle}>
        {setting.label}
        {setting.isDefault ? <span className={styles.badge}>Default</span> : null}
      </h3>
      <p className={styles.hint}>{setting.description}</p>
      {setting.readBy.length > 0 ? (
        <p className={styles.readers}>Read by {readerText(setting.readBy)}.</p>
      ) : null}

      <table className={styles.table}>
        <thead>
          <tr>
            {item.fields.map(({ name, list }) => (
              <th key={name} scope="col">
                {fieldLabel(name)}
                {list ? <span className={styles.fieldNote}> (comma-separated)</span> : null}
              </th>
            ))}
            {editable ? <th scope="col" aria-label="Remove" /> : null}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {item.fields.map(({ name }) => (
                <td key={name}>
                  <input
                    className={styles.input}
                    aria-label={`${fieldLabel(name)} ${index + 1}`}
                    value={row[name] ?? ""}
                    readOnly={!editable}
                    onChange={(e) => update(index, name, e.target.value)}
                  />
                </td>
              ))}
              {editable ? (
                <td>
                  <button
                    type="button"
                    className={styles.remove}
                    aria-label={`Remove ${row[item.fields[0].name] || `row ${index + 1}`}`}
                    onClick={() => {
                      setSaved(false);
                      setRows((prev) => prev.filter((_, i) => i !== index));
                    }}
                  >
                    ×
                  </button>
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>

      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : null}

      {editable ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={styles.secondary}
            onClick={() => {
              setSaved(false);
              setRows((prev) => [
                ...prev,
                Object.fromEntries(item.fields.map((f) => [f.name, ""])),
              ]);
            }}
          >
            Add row
          </button>
          <button
            type="button"
            className={styles.secondary}
            disabled={busy || setting.isDefault}
            onClick={() => void save(null)}
          >
            Restore default
          </button>
          <span className={styles.spacer} />
          {saved ? <span className={styles.saved}>Saved</span> : null}
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() => void save(fromRows(rows, item))}
          >
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      ) : null}
    </section>
  );
};

export const AgentCatalogSettingsModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [data, setData] = useState<CatalogSettingsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    agentsApi
      .catalogSettings()
      .then((response) => live && setData(response))
      .catch((e) => live && setError(e instanceof Error ? e.message : "Loading failed"));
    return () => {
      live = false;
    };
  }, []);

  return (
    <ModalShell onClose={onClose} layer="overlay" size="large" titleId="catalog-settings-title">
      <div className={styles.body}>
        <h2 id="catalog-settings-title" className={styles.title}>
          Catalog settings
        </h2>
        <p className={styles.hint}>
          Values your agents read when they run. They belong to your account and apply in every
          project.
        </p>
        {data && !data.editable && data.reason ? (
          <p className={styles.notice}>{data.reason}</p>
        ) : null}
        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
        {!data && !error ? <p className={styles.hint}>Loading settings…</p> : null}
        {data?.settings.map((setting) => (
          <SettingEditor
            key={setting.key}
            setting={setting}
            editable={data.editable}
            onSaved={setData}
          />
        ))}
        <div className={styles.footer}>
          <button type="button" className={styles.secondary} onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </ModalShell>
  );
};
