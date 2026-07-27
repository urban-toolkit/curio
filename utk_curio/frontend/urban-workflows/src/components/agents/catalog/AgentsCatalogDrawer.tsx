import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faRobot, faThumbtack } from "@fortawesome/free-solid-svg-icons";
import type { AgentCard } from "../../../api/agentsApi";
import { AgentSettingsModal } from "../settings/AgentSettingsModal";
import { AgentImportModal } from "./AgentImportModal";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import styles from "./AgentsCatalogDrawer.module.css";
import { AgentScope, useAgentsCatalogDrawer } from "./useAgentsCatalogDrawer";

export interface AgentsCatalogDrawerProps {
  presented: boolean;
  projectId: string | null;
  /** Pinned keeps the drawer open (backdrop/Escape won't dismiss it). */
  pinned: boolean;
  onPinToggle: () => void;
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
 * Three-scope Agents Catalog drawer (the Agents Roster). Reuses the DrawerTabs
 * tab styling and the shared CatalogPublishPill so agents match the Data / Node
 * catalog drawers. Data + lifecycle live in ``useAgentsCatalogDrawer``.
 *
 * Per DEC-042 (dev/21) the static dark roster header carries the **Pin button
 * only** — no Close, no agent identity, no agent-cycling controls. Dismissal is
 * the backdrop/Escape (gated by the pin); the opened agent view has its own
 * identity header (AgentChatPanel).
 */
export const AgentsCatalogDrawer: React.FC<AgentsCatalogDrawerProps> = ({
  presented,
  projectId,
  pinned,
  onPinToggle,
}) => {
  const c = useAgentsCatalogDrawer(presented, projectId);
  // Installed-scope card whose Project agent settings modal is open (dev/23).
  const [settingsCoord, setSettingsCoord] = useState<string | null>(null);
  // Account-policy scope (dev/24), opened from the roster header cog.
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  // Upload-import (dev/36), opened from the footer's Import package button.
  const [importOpen, setImportOpen] = useState(false);
  if (!presented) return null;

  return (
    <div className={styles.drawer} role="dialog" aria-label="Agents Catalog">
      <div className={styles.header}>
        <button
          type="button"
          className={`${styles.pinBtn} ${pinned ? styles.pinBtnActive : ""}`}
          aria-label={pinned ? "Unpin drawer" : "Pin drawer open"}
          aria-pressed={pinned}
          title={pinned ? "Unpin drawer" : "Pin drawer (backdrop won't close)"}
          onClick={onPinToggle}
        >
          <FontAwesomeIcon icon={faThumbtack} aria-hidden />
        </button>
        <FontAwesomeIcon icon={faRobot} className={styles.titleIcon} aria-hidden />
        <span className={styles.title}>Agents Catalog</span>
        {/* Account-policy entry (docs/02 cog #1; the DEC-042-sanctioned header
            control besides the Pin). */}
        <button
          type="button"
          className={styles.headerSettingsBtn}
          aria-haspopup="dialog"
          onClick={() => setAccountSettingsOpen(true)}
        >
          <FontAwesomeIcon icon={faGear} aria-hidden /> Agent settings
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
            <AgentRow
              key={card.dirName}
              card={card}
              scope={c.scope}
              state={c}
              hasProject={!!projectId}
              onOpenSettings={() => setSettingsCoord(card.dirName)}
            />
          ))}
        </div>
      )}

      {/* Upload-import entry (dev/36) — the concept's footer button. */}
      <button type="button" className={styles.importPackageBtn} onClick={() => setImportOpen(true)}>
        Import package
      </button>

      {importOpen ? (
        <AgentImportModal
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            // The new definition lives in My Imports — show it.
            c.setScope("my-imports");
            void c.reload();
          }}
        />
      ) : null}
      {settingsCoord && projectId ? (
        <AgentSettingsModal
          scope="project"
          projectId={projectId}
          coord={settingsCoord}
          onClose={() => setSettingsCoord(null)}
        />
      ) : null}
      {accountSettingsOpen ? (
        <AgentSettingsModal scope="account" onClose={() => setAccountSettingsOpen(false)} />
      ) : null}
    </div>
  );
};

const AgentRow: React.FC<{
  card: AgentCard;
  scope: AgentScope;
  state: ReturnType<typeof useAgentsCatalogDrawer>;
  hasProject: boolean;
  onOpenSettings: () => void;
}> = ({ card, scope, state, hasProject, onOpenSettings }) => {
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
        {/* Project-agent-default scope entry (dev/23): labeled cog, installed
            scope only — palette rows and other scopes stay action-free. */}
        {scope === "installed" ? (
          <button
            type="button"
            className={styles.btnSecondary}
            disabled={!hasProject}
            aria-haspopup="dialog"
            onClick={onOpenSettings}
          >
            <FontAwesomeIcon icon={faGear} aria-hidden /> Project agent settings
          </button>
        ) : null}
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
            {/* Publish → Catalog Hub. The pill only shows for eligible (owned,
                store-backed) definitions — built-ins report publishable=false,
                so no dead button appears. */}
            <CatalogPublishPill
              dirName={card.dirName}
              published={card.published}
              allowPublish={card.publishable}
              busy={busy}
              onPublish={() => state.publish(card.dirName)}
              variant="hub"
              publishedTitle="Listed in the Agents Catalog Hub"
              publishActionTitle="Publish this owned definition to the Agents Catalog Hub"
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
