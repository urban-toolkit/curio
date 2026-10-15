import React, { useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import { CatalogDetailHeader } from "../../catalog/CatalogDetailHeader";
import { agentsApi, type AgentCard } from "../../../services/agents";
import { llmConfigsApi } from "../../../api/llmConfigsApi";
import { requestAgentModel } from "../../apiSettings/apiSettingsRequest";
import { triggerBlobDownload } from "../../../services/packages";
import styles from "./AgentDetailModal.module.css";

export interface AgentDetailModalProps {
  agent: AgentCard;
  onClose: () => void;
}

/**
 * "View details" for one agent, the Agent Catalog's answer to
 * ``DatasetDetailModal``.
 *
 * A modal rather than a route, matching the Data Catalog and the constraint
 * ``catalog/agentDetailEntryPoints.test.ts`` pins: the browse page does not
 * navigate. It is also what makes the control work below 1100px, where
 * ``CatalogBrowseLayout.module.css`` hides the side drawer outright and a
 * selection therefore has nowhere to show.
 *
 * Everything here is already on the ``AgentCard`` the listing returns - there is
 * no per-agent GET on the backend and this needs none.
 */
export const AgentDetailModal: React.FC<AgentDetailModalProps> = ({ agent, onClose }) => {
  // The definition behind the card: its manifest and the prompt texts. The card
  // itself carries none of this - `AgentCard` is a summary - so the details
  // screen described an agent's behaviour without ever showing the prompts that
  // ARE its behaviour.
  const [bundle, setBundle] = useState<{
    manifest: Record<string, unknown>;
    prompts: Record<string, string>;
  } | null>(null);
  const [bundleError, setBundleError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  // The export's own failure, shown beside the button that caused it. It used
  // to be folded into ``bundleError`` as a bare "Export failed." rendered under
  // the Prompts heading - nowhere near the button, and without the server's
  // reason (#275).
  const [exportError, setExportError] = useState<string | null>(null);
  // What this agent runs on, read-only here: the choice is made in API
  // Settings. `choosable` is false for a guest on a hosted Curio.
  const [model, setModel] = useState<{ text: string; choosable: boolean } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setModel(null);
    llmConfigsApi
      .listing()
      .then((listing) => {
        if (cancelled) return;
        const row = (listing.agents ?? []).find((r) => r.id === agent.id);
        const answers = row?.answers ?? listing.active;
        setModel({
          text: answers.source ? `${answers.label} · ${answers.model}` : answers.error ?? "none",
          choosable: Boolean(row) && listing.editable,
        });
      })
      .catch(() => {
        if (!cancelled) setModel(null);
      });
    return () => {
      cancelled = true;
    };
  }, [agent.id]);

  useEffect(() => {
    let cancelled = false;
    setBundle(null);
    setBundleError(null);
    agentsApi
      .readDefinition(agent.dirName)
      .then((b) => {
        if (!cancelled) setBundle(b);
      })
      .catch(() => {
        // A built-in that has never been materialized into this account's store
        // has no readable definition. That is not an error worth shouting
        // about - the rest of the screen is still accurate - so the prompts
        // section simply says so.
        if (!cancelled) setBundleError("Prompts are not available for this agent.");
      });
    return () => {
      cancelled = true;
    };
  }, [agent.dirName]);

  const onExport = async () => {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    try {
      const b = bundle ?? (await agentsApi.readDefinition(agent.dirName));
      // One file, not a manifest plus loose prompt files in two directories.
      // `AgentImportModal` accepts this bundle, so an agent exported from one
      // Curio imports into another in a single pick.
      const blob = new Blob([JSON.stringify(b, null, 2)], { type: "application/json" });
      triggerBlobDownload(blob, `${agent.dirName}.curio-agent.json`);
    } catch (err) {
      // apiFetch throws with the server's own ``error`` text, which says what
      // is actually wrong ("no agent definition x") rather than that something is.
      setExportError(err instanceof Error && err.message ? err.message : "Export failed.");
    } finally {
      setExporting(false);
    }
  };

  // Every listing sends these; a card built anywhere else may not.
  const tools = agent.tools ?? [];
  const modes = agent.modes ?? [];
  // When each prompt file runs, by its path. The card lists them in the order
  // to read them: every call, a message you type, then each mode. The bundle
  // arrives sorted by path, so it gives the text and the card the order; a
  // file the card does not know follows, by its name alone.
  const promptRuns = new Map(
    (agent.promptRuns ?? []).map((row): [string, string[]] => [row.path, row.runs]),
  );
  const promptOrder = (prompts: Record<string, string>) => [
    ...(agent.promptRuns ?? []).map((row) => row.path).filter((path) => path in prompts),
    ...Object.keys(prompts).filter((path) => !promptRuns.has(path)),
  ];

  const rows: [string, React.ReactNode][] = [
    ["Identifier", agent.id],
    ["Version", agent.version],
    ["Category", agent.category],
    ["Publisher", agent.provenance?.publisher ?? "curio"],
    ["Trust", agent.provenance?.trust ?? "built-in"],
    ["Attaches to", agent.hooks.length ? agent.hooks.join(", ") : "—"],
    ["In all projects", agent.imported ? "Yes" : "No"],
    ["In the catalog", agent.published ? "Published" : "Not published"],
    [
      "Model",
      model ? (
        <>
          {model.text}
          {model.choosable ? (
            <>
              {" "}
              <button
                type="button"
                className={styles.inlineLink}
                onClick={() => {
                  // Close first: API Settings opens as its own modal.
                  onClose();
                  requestAgentModel(agent.id);
                }}
              >
                Change in API Settings
              </button>
            </>
          ) : null}
        </>
      ) : (
        "…"
      ),
    ],
  ];

  return (
    <ModalShell onClose={onClose} size="xlarge" layer="overlay" label="Agent details">
      <CatalogDetailHeader
        kind="agent"
        title={agent.name}
        subtitle={
          <>
            {agent.provenance?.publisher ?? "curio"} · v{agent.version}
          </>
        }
        actions={
          <button
            type="button"
            className={styles.exportButton}
            disabled={exporting}
            onClick={() => void onExport()}
          >
            {exporting ? "Exporting…" : "Export"}
          </button>
        }
      />

      <div className={styles.body}>
        {/* The docs' three words (docs/AGENT-CATALOG.md, "The agents"): what
            you ask the agent where you dropped it, the tools it uses in that
            chat, and its modes, each with who asks for it. */}
        {agent.purpose ? (
          <section className={styles.section}>
            <h3 className={styles.sectionLabel}>In chat</h3>
            <p className={styles.sectionText}>{agent.purpose}</p>
          </section>
        ) : null}

        {exportError ? (
          <p className={styles.purpose} role="alert" data-curio-export-error="true">
            Export failed: {exportError}
          </p>
        ) : null}

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Tools</h3>
          {tools.length > 0 ? (
            <ul className={styles.list}>
              {tools.map((tool) => (
                <li key={tool.id}>{tool.label}</li>
              ))}
            </ul>
          ) : (
            <p className={styles.sectionText}>None</p>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Modes (who asks)</h3>
          {modes.length > 0 ? (
            <ul className={styles.list}>
              {modes.map((mode) => (
                <li key={mode.label}>
                  <span>
                    {`${mode.label}: ${
                      mode.askedBy.length > 0
                        ? `asked by ${mode.askedBy.join(", ")}`
                        : "no agent asks for this"
                    }`}
                  </span>
                  {/* The capability ids a mode covers, for developers. */}
                  <div className={styles.modeIds}>{mode.capabilities.join(", ")}</div>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.sectionText}>None</p>
          )}
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>Agent info</h3>
          <dl className={styles.infoGrid}>
            {rows.map(([label, value]) => (
              <React.Fragment key={label}>
                <dt className={styles.infoLabel}>{label}</dt>
                <dd className={styles.infoValue}>{value}</dd>
              </React.Fragment>
            ))}
          </dl>
        </section>

        <section className={styles.section}>
          <h3 className={styles.sectionLabel}>
            Prompts{bundle ? ` (${Object.keys(bundle.prompts).length})` : ""}
          </h3>
          {bundleError ? (
            <p className={styles.purpose}>{bundleError}</p>
          ) : !bundle ? (
            <p className={styles.purpose}>Loading…</p>
          ) : Object.keys(bundle.prompts).length === 0 ? (
            <p className={styles.purpose}>This agent ships no prompt files.</p>
          ) : (
            promptOrder(bundle.prompts).map((name) => {
              const runs = promptRuns.get(name) ?? [];
              return (
                <details key={name} className={styles.promptBlock}>
                  {/* Collapsed by default: a prompt runs to hundreds of lines and
                      would otherwise bury every section under it. Its summary
                      says when it runs, then which file it is. */}
                  <summary className={styles.promptName}>
                    {runs.length > 0 ? (
                      <>
                        <span className={styles.promptRuns}>{runs.join(", ")}</span>
                        {" · "}
                      </>
                    ) : null}
                    {name}
                  </summary>
                  <pre className={styles.promptText}>{bundle.prompts[name]}</pre>
                </details>
              );
            })
          )}
        </section>

        {agent.requiresAgents.length > 0 ? (
          <section className={styles.section}>
            {/* Disclosed before the click, the same as the drawer next door:
                adding this agent adds these too. */}
            <h3 className={styles.sectionLabel}>Requires</h3>
            <ul className={styles.list}>
              {agent.requiresAgents.map((requirement) => (
                <li key={requirement.id}>
                  {requirement.name}
                  {requirement.visible ? "" : " (unavailable)"}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
    </ModalShell>
  );
};

export default AgentDetailModal;
