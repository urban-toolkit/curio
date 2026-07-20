import React from "react";
import type { AgentCard } from "../../../api/agentsApi";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import styles from "./AgentsCatalogDrawer.module.css";
import { AgentScope, useAgentsCatalogDrawer } from "./useAgentsCatalogDrawer";

export interface AgentsCatalogDrawerProps {
  presented: boolean;
  projectId: string | null;
  onClose: () => void;
}

const SCOPES: { key: AgentScope; label: string }[] = [
  { key: "global", label: "Global Catalog" },
  { key: "my-imports", label: "My Imports" },
  { key: "installed", label: "Installed in this project" },
];

const SUBTITLE: Record<AgentScope, string> = {
  global: "Install agents from the catalog into this project.",
  "my-imports": "Your private account definitions — publish to the Catalog Hub or install.",
  installed: "Templates available in this project's palette.",
};

/**
 * Three-scope Agents Catalog drawer. Reuses the DrawerTabs tab styling and the
 * shared CatalogPublishPill so agents match the Data / Node catalog drawers.
 * Data + lifecycle live in ``useAgentsCatalogDrawer``.
 */
export const AgentsCatalogDrawer: React.FC<AgentsCatalogDrawerProps> = ({
  presented,
  projectId,
  onClose,
}) => {
  const c = useAgentsCatalogDrawer(presented, projectId);
  if (!presented) return null;

  return (
    <div className={styles.drawer} role="dialog" aria-label="Agents Catalog">
      <div className={styles.header}>
        <span className={styles.title}>Agents Catalog</span>
        <button type="button" className={styles.closeBtn} aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </div>

      <nav className={tabStyles.tabs} aria-label="Agent catalog scopes">
        {SCOPES.map((s) => (
          <button
            key={s.key}
            type="button"
            className={`${tabStyles.tab} ${c.scope === s.key ? tabStyles.tabActive : ""}`}
            aria-pressed={c.scope === s.key}
            onClick={() => c.setScope(s.key)}
          >
            {s.label}
          </button>
        ))}
      </nav>

      <p className={styles.subtitle}>{SUBTITLE[c.scope]}</p>

      {c.error ? <p className={styles.error}>{c.error}</p> : null}

      {c.loading ? (
        <p className={styles.empty}>Loading…</p>
      ) : c.cards.length === 0 ? (
        <p className={styles.empty}>No agents in this scope yet.</p>
      ) : (
        <div className={styles.list}>
          {c.cards.map((card) => (
            <AgentRow key={card.dirName} card={card} scope={c.scope} state={c} hasProject={!!projectId} />
          ))}
        </div>
      )}
    </div>
  );
};

const AgentRow: React.FC<{
  card: AgentCard;
  scope: AgentScope;
  state: ReturnType<typeof useAgentsCatalogDrawer>;
  hasProject: boolean;
}> = ({ card, scope, state, hasProject }) => {
  const busy = state.busyCoord === card.dirName;
  return (
    <div className={styles.card}>
      <div className={styles.cardBody}>
        <div className={styles.cardName}>{card.name}</div>
        <div className={styles.cardMeta}>{card.purpose || card.capabilities.join(" · ")}</div>
        <div className={styles.tags}>
          <span className={styles.tag}>{card.category}</span>
          {card.hooks.map((h) => (
            <span key={h} className={styles.tag}>hook: {h}</span>
          ))}
          <span className={styles.tag}>v{card.version.split(".")[0]}</span>
        </div>
      </div>

      <div className={styles.actions}>
        {/* Per-scope action controls, matching the concept:
            Global → Install (or Uninstall if already in project)
            My Imports → Install + Publish pill + Delete
            Installed → Uninstall */}
        {scope === "installed" || card.installedInProject ? (
          <button
            type="button"
            className={styles.btnSecondary}
            disabled={busy || !hasProject}
            onClick={() => state.uninstall(card.dirName)}
          >
            Uninstall
          </button>
        ) : (
          <button
            type="button"
            className={styles.btnInstall}
            disabled={busy || !hasProject}
            title={hasProject ? undefined : "Open a project to install"}
            onClick={() => state.install(card.dirName)}
          >
            Install
          </button>
        )}

        {scope === "my-imports" ? (
          <>
            {/* Publish is rendered here but gated off until the backend Publish
                endpoint exists (allowPublish=false → no dead button). */}
            <CatalogPublishPill
              dirName={card.dirName}
              published={false}
              allowPublish={false}
              busy={false}
              onPublish={() => undefined}
              variant="hub"
            />
            <button
              type="button"
              className={styles.btnSecondary}
              disabled={busy}
              onClick={() => state.removeImport(card.dirName)}
            >
              Delete
            </button>
          </>
        ) : null}

        {scope === "global" && !card.imported ? (
          <button
            type="button"
            className={styles.btnSecondary}
            disabled={busy}
            onClick={() => state.importAgent(card.dirName)}
          >
            Import
          </button>
        ) : null}
      </div>
    </div>
  );
};
