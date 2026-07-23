import React, { useCallback, useEffect, useMemo, useState } from "react";
import ModalShell from "../../ModalShell";
import {
  agentsApi,
  type AgentPolicySettings,
  type EffectivePolicy,
} from "../../../api/agentsApi";
import styles from "./AgentSettingsModal.module.css";

/**
 * The shared settings shell (memo dev/24) with the three v1 policy screens —
 * Cost, Quotas, Resource policies — at the **Account policy** or **Project
 * agent default** scope. One record per scope: drafts PATCH the whole
 * settings object with an optimistic revision (409 → reload + reapply
 * message). Every field shows its effective value + source; bounds are
 * enforced server-side (tighten-only) and surfaced as field errors. The
 * project scope adds `Reset to agent default`. No Publish/Release/Share
 * exists in any scope.
 */

type Scope = "account" | "project";
type Tab = "cost" | "quotas" | "resources";

interface Loaded {
  revision: number;
  settings: AgentPolicySettings & Record<string, unknown>;
  effective: EffectivePolicy;
  usedToday: number;
  ceilings?: { quotas: { runsPerDay: number }; resources: { maxOutputTokens: number } };
  name?: string;
}

/** Draft field values as strings; "" = inherit (no override). */
type Drafts = {
  runsPerDay: string;
  dailyBudgetUsd: string;
  estimatedCostPerRunUsd: string;
  maxOutputTokens: string;
};

const num = (v: unknown): string => (typeof v === "number" ? String(v) : "");

function draftsFrom(settings: AgentPolicySettings): Drafts {
  return {
    runsPerDay: num(settings.quotas?.runsPerDay),
    dailyBudgetUsd: num(settings.cost?.dailyBudgetUsd),
    estimatedCostPerRunUsd: num(settings.cost?.estimatedCostPerRunUsd),
    maxOutputTokens: num(settings.resources?.maxOutputTokens),
  };
}

function settingsFrom(drafts: Drafts, scope: Scope): AgentPolicySettings {
  const out: AgentPolicySettings = {};
  const put = (section: "quotas" | "cost" | "resources", key: string, raw: string) => {
    if (!raw.trim()) return;
    const value = Number(raw);
    if (!Number.isFinite(value)) return;
    (out[section] as Record<string, number>) = {
      ...(out[section] as Record<string, number> | undefined),
      [key]: value,
    };
  };
  put("quotas", "runsPerDay", drafts.runsPerDay);
  put("cost", "dailyBudgetUsd", drafts.dailyBudgetUsd);
  if (scope === "account") put("cost", "estimatedCostPerRunUsd", drafts.estimatedCostPerRunUsd);
  put("resources", "maxOutputTokens", drafts.maxOutputTokens);
  return out;
}

export const AgentSettingsModal: React.FC<{
  scope: Scope;
  /** Required for the project scope. */
  projectId?: string;
  coord?: string;
  onClose: () => void;
}> = ({ scope, projectId, coord, onClose }) => {
  const [data, setData] = useState<Loaded | null>(null);
  const [drafts, setDrafts] = useState<Drafts>(draftsFrom({}));
  const [tab, setTab] = useState<Tab>("quotas");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let loaded: Loaded;
      if (scope === "account") {
        const r = await agentsApi.getAgentSettings();
        loaded = { ...r, usedToday: r.usedToday };
      } else {
        if (!projectId || !coord) throw new Error("no project");
        const r = await agentsApi.getProjectAgentDefaults(projectId, coord);
        loaded = {
          revision: r.revision,
          settings: r.settings,
          effective: r.effective,
          usedToday: r.effective.quotas.runsPerDay.usedToday ?? 0,
          name: r.name,
        };
      }
      setData(loaded);
      setDrafts(draftsFrom(loaded.settings));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, [scope, projectId, coord]);

  useEffect(() => {
    void load();
  }, [load]);

  const dirty = useMemo(
    () => data !== null && JSON.stringify(drafts) !== JSON.stringify(draftsFrom(data.settings)),
    [drafts, data],
  );

  const close = () => {
    if (dirty && !window.confirm("Discard unsaved settings changes?")) return;
    onClose();
  };

  const applyResponse = (r: {
    revision: number;
    settings: AgentPolicySettings & Record<string, unknown>;
    effective: EffectivePolicy;
    usedToday?: number;
    ceilings?: Loaded["ceilings"];
    name?: string;
  }) => {
    const loaded: Loaded = {
      revision: r.revision,
      settings: r.settings,
      effective: r.effective,
      usedToday: r.usedToday ?? r.effective.quotas.runsPerDay.usedToday ?? 0,
      ceilings: r.ceilings ?? data?.ceilings,
      name: r.name ?? data?.name,
    };
    setData(loaded);
    setDrafts(draftsFrom(loaded.settings));
  };

  const persist = async (settings: AgentPolicySettings) => {
    if (!data) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      if (scope === "account") {
        applyResponse(await agentsApi.updateAgentSettings(data.revision, settings));
      } else {
        applyResponse(
          await agentsApi.updateProjectAgentDefaults(
            projectId as string,
            coord as string,
            data.revision,
            settings,
          ),
        );
      }
      setNotice("Saved.");
    } catch (e) {
      const status = (e as { status?: number } | null)?.status;
      if (status === 409) {
        setNotice("These settings changed elsewhere — reloaded. Please reapply your edits.");
        await load();
      } else {
        setError(e instanceof Error ? e.message : "Failed to save settings");
      }
    } finally {
      setSaving(false);
    }
  };

  const save = () => void persist(settingsFrom(drafts, scope));

  const resetToDefault = () => {
    if (!window.confirm("Reset this agent's project defaults to inherit everything?")) return;
    void persist({});
  };

  const field = (label: string, key: keyof Drafts, eff: { value: number | null; source: string | null }, hint?: string) => (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <input
        className={styles.input}
        type="number"
        min={1}
        value={drafts[key]}
        placeholder={eff.value != null ? `${eff.value} (inherited)` : "inherit"}
        onChange={(e) => setDrafts((d) => ({ ...d, [key]: e.target.value }))}
      />
      <span className={styles.provenance}>
        {eff.source ? `effective ${eff.value} · from ${eff.source}` : "not set"}
        {hint ? ` · ${hint}` : ""}
      </span>
    </label>
  );

  const eff = data?.effective;

  return (
    <ModalShell onClose={close} layer="overlay">
      <div
        className={styles.body}
        role="dialog"
        aria-label={scope === "account" ? "Agent settings (account policy)" : `Project agent settings for ${data?.name ?? coord}`}
      >
        <p className={styles.scope}>
          {scope === "account" ? "Account policy" : "Project agent default"}
        </p>
        <h2 className={styles.title}>{scope === "account" ? "Agent settings" : data?.name ?? coord}</h2>
        {scope === "project" ? <p className={styles.coord}>{coord}</p> : null}

        <nav className={styles.tabs} aria-label="Settings screens">
          {(
            [
              ["cost", "Cost"],
              ["quotas", "Quotas"],
              ["resources", "Resource policies"],
            ] as [Tab, string][]
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              className={`${styles.tab} ${tab === key ? styles.tabActive : ""}`}
              aria-pressed={tab === key}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>

        {loading ? (
          <p className={styles.state}>Loading settings…</p>
        ) : !data || !eff ? (
          <p className={styles.state}>
            {error ?? "Failed to load settings"}
            <button type="button" className={styles.retry} onClick={() => void load()}>
              Retry
            </button>
          </p>
        ) : (
          <>
            {tab === "quotas" ? (
              <section className={styles.section}>
                {field(
                  "Runs per day",
                  "runsPerDay",
                  eff.quotas.runsPerDay,
                  data.ceilings ? `≤ ${data.ceilings.quotas.runsPerDay}` : undefined,
                )}
                <p className={styles.meta}>{data.usedToday} runs used today.</p>
              </section>
            ) : null}

            {tab === "cost" ? (
              <section className={styles.section}>
                {field("Daily budget (USD)", "dailyBudgetUsd", eff.cost.dailyBudgetUsd)}
                {scope === "account" ? (
                  field(
                    "Estimated cost per run (USD)",
                    "estimatedCostPerRunUsd",
                    eff.cost.estimatedCostPerRunUsd,
                  )
                ) : (
                  <p className={styles.meta}>
                    Estimated cost per run:{" "}
                    {eff.cost.estimatedCostPerRunUsd.value ?? "not set"} (account-scope setting).
                  </p>
                )}
                <p className={styles.meta}>
                  {eff.cost.configured
                    ? `Estimated spend today: ${data.usedToday} runs × $${eff.cost.estimatedCostPerRunUsd.value} ≈ $${(
                        eff.cost.estimatedSpendTodayUsd ??
                        data.usedToday * (eff.cost.estimatedCostPerRunUsd.value ?? 0)
                      ).toFixed(2)} · Actual: not available in v1`
                    : "The budget gate is inactive until both a budget and an estimate are set. Actual cost is not available in v1."}
                </p>
              </section>
            ) : null}

            {tab === "resources" ? (
              <section className={styles.section}>
                {field(
                  "Max output tokens",
                  "maxOutputTokens",
                  eff.resources.maxOutputTokens,
                  data.ceilings ? `≤ ${data.ceilings.resources.maxOutputTokens}` : undefined,
                )}
                <p className={styles.meta}>
                  Provider:{" "}
                  {eff.resources.provider
                    ? `${eff.resources.provider} · ${eff.resources.model ?? ""}`
                    : "account-configured"}{" "}
                  (read-only; provider profiles arrive in v2).
                </p>
              </section>
            ) : null}

            {error ? <p className={styles.error}>{error}</p> : null}
            {notice ? <p className={styles.notice}>{notice}</p> : null}

            <div className={styles.footer}>
              {scope === "project" ? (
                <button
                  type="button"
                  className={styles.resetBtn}
                  disabled={saving}
                  onClick={resetToDefault}
                >
                  Reset to agent default
                </button>
              ) : null}
              <span className={styles.footerSpacer} />
              <button
                type="button"
                className={styles.saveBtn}
                disabled={saving || !dirty}
                onClick={save}
              >
                {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </>
        )}
      </div>
    </ModalShell>
  );
};
