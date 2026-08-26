import React, { useCallback, useEffect, useMemo, useState } from "react";
import ModalShell from "../../ModalShell";
import {
  agentsApi,
  type AgentPolicySettings,
  type AgentPricingSummary,
  type AgentUsage,
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

type Scope = "account" | "project" | "attachment";
type Tab = "cost" | "quotas" | "resources";

const SCOPE_BANNER: Record<Scope, string> = {
  account: "Account policy",
  project: "Project agent default",
  attachment: "Attached instance",
};

interface Loaded {
  revision: number;
  settings: AgentPolicySettings & Record<string, unknown>;
  effective: EffectivePolicy;
  usedToday: number;
  /** Actual tokens counted today (memo dev/37); zeros when the server has none. */
  usageToday: AgentUsage;
  /** Actual USD settled today (memo dev/40); null until anything real exists. */
  actualSpendTodayUsd: number | null;
  pricing: AgentPricingSummary | null;
  ceilings?: { quotas: { runsPerDay: number }; resources: { maxOutputTokens: number } };
  name?: string;
  coord?: string;
}

const NO_USAGE: AgentUsage = { inputTokens: 0, outputTokens: 0 };

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
  /** Required for the project and attachment scopes. */
  projectId?: string;
  /** Required for the project scope. */
  coord?: string;
  /** Required for the attachment scope (memo dev/42). */
  attachmentId?: string;
  onClose: () => void;
}> = ({ scope, projectId, coord, attachmentId, onClose }) => {
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
        loaded = {
          ...r,
          usedToday: r.usedToday,
          usageToday: r.usageToday ?? NO_USAGE,
          actualSpendTodayUsd: r.actualSpendTodayUsd ?? null,
          pricing: r.pricing ?? null,
        };
      } else {
        if (!projectId) throw new Error("no project");
        const r =
          scope === "attachment"
            ? await agentsApi.getAttachmentSettings(projectId, attachmentId as string)
            : await agentsApi.getProjectAgentDefaults(projectId, coord as string);
        loaded = {
          revision: r.revision,
          settings: r.settings,
          effective: r.effective,
          usedToday: r.effective.quotas.runsPerDay.usedToday ?? 0,
          usageToday: r.effective.quotas.usageToday ?? NO_USAGE,
          actualSpendTodayUsd: r.effective.cost.actualSpendTodayUsd ?? null,
          pricing: r.effective.cost.pricing ?? null,
          name: r.name,
          coord: r.coord,
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
    usageToday?: AgentUsage;
    actualSpendTodayUsd?: number | null;
    pricing?: AgentPricingSummary | null;
    ceilings?: Loaded["ceilings"];
    name?: string;
  }) => {
    const loaded: Loaded = {
      revision: r.revision,
      settings: r.settings,
      effective: r.effective,
      usedToday: r.usedToday ?? r.effective.quotas.runsPerDay.usedToday ?? 0,
      usageToday: r.usageToday ?? r.effective.quotas.usageToday ?? NO_USAGE,
      actualSpendTodayUsd:
        r.actualSpendTodayUsd ?? r.effective.cost.actualSpendTodayUsd ?? null,
      pricing: r.pricing ?? r.effective.cost.pricing ?? null,
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
      } else if (scope === "attachment") {
        applyResponse(
          await agentsApi.updateAttachmentSettings(
            projectId as string,
            attachmentId as string,
            data.revision,
            settings,
          ),
        );
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
    const question =
      scope === "attachment"
        ? "Clear this attachment's overrides and fall back to the project profile?"
        : "Reset this agent's project defaults to inherit everything?";
    if (!window.confirm(question)) return;
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
        aria-label={
          scope === "account"
            ? "Agent settings (account policy)"
            : scope === "attachment"
              ? `Attachment settings for ${data?.name ?? attachmentId}`
              : `Project agent settings for ${data?.name ?? coord}`
        }
      >
        <p className={styles.scope}>{SCOPE_BANNER[scope]}</p>
        <h2 className={styles.title}>{scope === "account" ? "Agent settings" : data?.name ?? coord}</h2>
        {scope !== "account" ? <p className={styles.coord}>{coord ?? data?.coord ?? ""}</p> : null}

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
                <p className={styles.meta}>
                  {data.usedToday} runs · {data.usageToday.inputTokens} in /{" "}
                  {data.usageToday.outputTokens} out tokens today (actual).
                </p>
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
                {/* Gate status (memo dev/40): estimate-gated, actual-gated,
                    fail-closed (a budget with neither estimate nor price
                    blocks runs — REQ-COST-001), or off. */}
                <p className={styles.meta}>
                  {eff.cost.configured
                    ? `Estimated spend today: ${data.usedToday} runs × $${eff.cost.estimatedCostPerRunUsd.value} ≈ $${(
                        eff.cost.estimatedSpendTodayUsd ??
                        data.usedToday * (eff.cost.estimatedCostPerRunUsd.value ?? 0)
                      ).toFixed(2)} (estimated)`
                    : eff.cost.dailyBudgetUsd.value != null && data.pricing?.priced
                      ? "The budget gate is active on actual provider-priced spend."
                      : eff.cost.dailyBudgetUsd.value != null
                        ? "A daily budget is set but no estimate or price is configured — runs are blocked until one is provided or the budget is cleared."
                        : "The budget gate is inactive until a daily budget is set."}
                </p>
                {/* The Actual line (memos dev/11/37/40): provider-grounded or
                    honestly absent — never an estimate, never a fake $0.00. */}
                <p className={styles.meta}>
                  {data.pricing?.priced && data.actualSpendTodayUsd != null
                    ? `Actual: $${data.actualSpendTodayUsd.toFixed(4)} today · ${data.usageToday.inputTokens} in / ${data.usageToday.outputTokens} out tokens (provider-reported)${
                        data.pricing.effectiveDate
                          ? ` · pricing effective ${data.pricing.effectiveDate}`
                          : ""
                      }`
                    : `Actual: ${data.usageToday.inputTokens} in / ${data.usageToday.outputTokens} out tokens today — no USD price configured${
                        data.pricing ? ` for ${data.pricing.provider} · ${data.pricing.model}` : ""
                      }.`}
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
              {scope !== "account" ? (
                <button
                  type="button"
                  className={styles.resetBtn}
                  disabled={saving}
                  onClick={resetToDefault}
                >
                  {scope === "attachment" ? "Clear overrides" : "Reset to agent default"}
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
