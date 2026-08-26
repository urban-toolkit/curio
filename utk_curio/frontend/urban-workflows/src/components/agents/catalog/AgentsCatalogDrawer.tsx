import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faRobot, faThumbtack } from "@fortawesome/free-solid-svg-icons";
import type { AgentCard } from "../../../api/agentsApi";
import { AgentSettingsModal } from "../settings/AgentSettingsModal";
import { AgentImportModal } from "./AgentImportModal";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import { SortMode } from "../../packages/publishing/packageTypes";
import { agentCategoryKey } from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import cardStyles from "../../packages/publishing/PackageCard.module.css";
import styles from "./AgentsCatalogDrawer.module.css";
import { matchesAgentSearch, sortAgentCards, installLabel, installTitle } from "./agentListUtils";
import { AgentScope, useAgentsCatalogDrawer } from "./useAgentsCatalogDrawer";

export interface AgentsCatalogDrawerProps {
  /** When true, the scrim fades in and the panel slides in from the right
   * (memo dev/43 — the same two-phase presentation as the Nodes/Datasets
   * drawers). The drawer stays mounted while false during the exit slide. */
  presented: boolean;
  projectId: string | null;
  /** Pinned keeps the drawer open (backdrop/Escape won't dismiss it). */
  pinned: boolean;
  onPinToggle: () => void;
  /** Scrim-click dismissal (gated by the pin). */
  onRequestClose?: () => void;
  /** Called once the exit transition finishes (the owner unmounts then). */
  onExitComplete?: () => void;
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
 * Three-scope Agents Catalog drawer (the Agents Roster). Reuses the shared
 * catalog chrome — DrawerTabs tab styling, PackageSearchRow (search + sort),
 * the PackageCard row grid with a category-tinted avatar, and the
 * CatalogPublishPill — so agents match the Data / Node catalog drawers
 * (dev/68). Data + lifecycle live in ``useAgentsCatalogDrawer``.
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
  onRequestClose,
  onExitComplete,
}) => {
  const c = useAgentsCatalogDrawer(presented, projectId);
  const panelRef = useRef<HTMLElement>(null);
  // Installed-scope card whose Project agent settings modal is open (dev/23).
  const [settingsCoord, setSettingsCoord] = useState<string | null>(null);
  // Account-policy scope (dev/24), opened from the roster header cog.
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  // Upload-import (dev/36), opened from the footer's Import package button.
  const [importOpen, setImportOpen] = useState(false);
  // Search/sort are pure view state over the hook's per-scope cache (dev/68) —
  // client-side like the Node Catalog drawer, persisting across scope tabs.
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");

  const visibleCards = useMemo(
    () => sortAgentCards(c.cards.filter((card) => matchesAgentSearch(card, search)), sort),
    [c.cards, search, sort],
  );

  useEffect(() => {
    if (!presented) return;
    panelRef.current?.focus();
  }, [presented]);

  // The exit slide reports completion from the panel's own transform
  // transition (memo dev/43); the owner's timer is the fallback.
  const handlePanelTransitionEnd = useCallback(
    (e: React.TransitionEvent<HTMLElement>) => {
      if (e.target !== panelRef.current || e.propertyName !== "transform" || presented) return;
      onExitComplete?.();
    },
    [onExitComplete, presented],
  );

  return (
    <div
      className={`${styles.overlayRoot} ${presented ? styles.overlayRootPresented : ""}`}
      data-curio-agents-catalog-drawer="true"
      aria-hidden={!presented}
    >
      <button
        type="button"
        className={styles.scrim}
        aria-label="Close agents catalog"
        onClick={() => {
          if (!pinned) onRequestClose?.();
        }}
      />
      <aside
        ref={panelRef}
        className={styles.panel}
        role="dialog"
        aria-modal="true"
        aria-label="Agents Catalog"
        tabIndex={-1}
        onTransitionEnd={handlePanelTransitionEnd}
      >
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

      <p className={styles.subtitle}>{SUBTITLE[c.scope]}</p>

      {/* Shared catalog search/sort bar (dev/68) — the same component, order
          and geometry as the Data/Node catalog drawers, per the concept. */}
      <PackageSearchRow
        search={search}
        sort={sort}
        onSearchChange={setSearch}
        onSortChange={setSort}
        placeholder="Search agents, hooks, keywords..."
        sortAriaLabel="Sort agents"
      />

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

      {c.error ? <p className={styles.error}>{c.error}</p> : null}

      {c.loading ? (
        <p className={styles.empty}>Loading…</p>
      ) : visibleCards.length === 0 ? (
        <p className={styles.empty}>
          {c.cards.length > 0
            ? "No agents match your search."
            : "No agents in this scope yet."}
        </p>
      ) : (
        <div className={styles.list}>
          {visibleCards.map((card) => (
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
      </aside>
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
  // The shared catalog card grid: 72px avatar | body | action. There is no
  // accent stripe - it was dropped from every catalog card because the
  // avatar tint already carries the category, and PackageCard.module.css no
  // longer defines .cardAccent, so the div was rendering unstyled into the
  // grid's first column and displacing the avatar.
  const categoryKey = agentCategoryKey(card.category);
  const avatarClass = styles[`avatar_${categoryKey}` as keyof typeof styles] ?? "";
  return (
    <article className={cardStyles.card}>
      <div className={`${cardStyles.cardAvatar} ${avatarClass}`} aria-hidden>
        <FontAwesomeIcon icon={faRobot} className={styles.avatarIcon} />
      </div>

      <div className={cardStyles.cardBody}>
        <h3 className={cardStyles.cardTitle}>{card.name}</h3>
        <div className={cardStyles.cardMetaRow}>
          <span className={cardStyles.cardMetaText}>
            {card.purpose || card.capabilities.join(" · ")}
          </span>
        </div>
        <div className={cardStyles.tagRow}>
          <span className={cardStyles.tag}>{card.category}</span>
          {card.hooks.map((h) => (
            <span key={h} className={cardStyles.tag}>hook: {h}</span>
          ))}
          <span className={cardStyles.versionBadge}>v{card.version.split(".")[0]}</span>
        </div>
        {/* dev/106: hard dependencies, disclosed before the click. */}
        {(card.requiresAgents ?? []).length ? (
          <div className={styles.requiresLine}>
            Requires:{" "}
            {(card.requiresAgents ?? []).map((r, i) => (
              <span key={r.id}>
                {i ? ", " : ""}
                <span className={r.installedInProject ? styles.requireMet : styles.requireMissing}>
                  {r.name}
                  {r.installedInProject ? " ✓" : r.visible ? " (not installed)" : " (unavailable)"}
                </span>
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className={cardStyles.cardAction}>
        {/* Per-scope action controls, matching the concept:
            Global → Install (or Uninstall if already in project)
            My Imports → Install + Publish pill + Delete
            Installed → Uninstall */}
        {/* Project-agent-default scope entry (dev/23): labeled cog, installed
            scope only — palette rows and other scopes stay action-free. */}
        {scope === "installed" ? (
          <button
            type="button"
            className={cardStyles.btnSecondary}
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
            className={cardStyles.btnSecondary}
            disabled={busy || !hasProject}
            onClick={() => state.uninstall(card.dirName)}
          >
            Uninstall
          </button>
        ) : (
          <button
            type="button"
            className={cardStyles.btnInstall}
            disabled={busy || !hasProject}
            title={hasProject ? installTitle(card) : "Open a project to install"}
            onClick={() => state.install(card.dirName)}
          >
            {installLabel(card)}
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
              className={cardStyles.btnSecondary}
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
            className={cardStyles.btnSecondary}
            disabled={busy}
            onClick={() => state.importAgent(card.dirName)}
          >
            Import
          </button>
        ) : null}
      </div>
    </article>
  );
};
