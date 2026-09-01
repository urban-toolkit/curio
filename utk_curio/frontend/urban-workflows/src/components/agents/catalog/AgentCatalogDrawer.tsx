import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faGear, faRobot, faThumbtack } from "@fortawesome/free-solid-svg-icons";
import type { AgentCard } from "../../../api/agentsApi";

/**
 * Loaded on demand. A static import would pull AI Settings' whole module
 * graph - it reads UserProvider, which reaches the package registry and
 * through it vega - into every canvas that mounts this drawer, to render a
 * modal that is usually closed.
 */
const AiSettingsModal = React.lazy(() => import("../../AiSettingsModal"));
import { AgentImportModal } from "./AgentImportModal";
import { CatalogPublishPill } from "../../packages/CatalogPublishPill";
import { PackageSearchRow } from "../../packages/publishing/PackageSearchRow";
import { DrawerHeader } from "../../packages/publishing/DrawerHeader";
import footerStyles from "../../packages/publishing/DrawerFooter.module.css";
import shell from "../../packages/publishing/CatalogDrawerShell.module.css";
import { SortMode } from "../../packages/publishing/packageTypes";
import {
  agentCategoryIcon,
  agentCategoryKey,
} from "../../menus/nodes/agentsPalette/agentCategoryStyle";
import tabStyles from "../../packages/publishing/DrawerTabs.module.css";
import cardStyles from "../../packages/publishing/PackageCard.module.css";
import styles from "./AgentCatalogDrawer.module.css";
import { matchesAgentSearch, sortAgentCards, installLabel, installTitle } from "./agentListUtils";
import { AgentScope, useAgentCatalogDrawer } from "./useAgentCatalogDrawer";
import { UNSAVED_DATAFLOW_NOTICE } from "../../../constants/catalogCopy";
import ConfirmDialog from "../../ConfirmDialog";

export interface AgentCatalogDrawerProps {
  /** When true, the scrim fades in and the panel slides in from the right
   * (memo dev/43 — the same two-phase presentation as the Nodes/Datasets
   * drawers). The drawer stays mounted while false during the exit slide. */
  presented: boolean;
  projectId: string | null;
  /** Creates and saves the dataflow on first use; see useAgentCatalogDrawer. */
  onEnsureProject?: () => Promise<string | null>;
  /** Pinned keeps the drawer open (backdrop/Escape won't dismiss it). */
  pinned: boolean;
  onPinToggle: () => void;
  /** Scrim-click dismissal (gated by the pin). */
  onRequestClose?: () => void;
  /** Called once the exit transition finishes (the owner unmounts then). */
  onExitComplete?: () => void;
}

// Slot names come from the shared vocabulary (datasetCatalogDrawerTypes'
// TAB_LABEL): "Browse all" and "In dataflow" mean the same thing in every
// catalog, and the third is this kind's own.
//
// No "featured" slot: both peers declare one, but the Node drawer maps it onto
// "Browse all" as a dead member, and agents have nothing to feature. A tab
// that renders the same rows under a second name is worse than three honest
// ones.
const SCOPES: { key: AgentScope; label: string }[] = [
  { key: "browse", label: "Browse all" },
  { key: "imports", label: "My imports" },
  { key: "installed", label: "In dataflow" },
];

const SUBTITLE: Record<AgentScope, string> = {
  browse: "Agents available to this dataflow.",
  imports: "Your own agent definitions. Publish one to the Agent Catalog, or add it here.",
  installed: "Agents added to this dataflow.",
};

/**
 * Three-scope Agent Catalog drawer (the Agents Roster). Reuses the shared
 * catalog chrome — DrawerTabs tab styling, PackageSearchRow (search + sort),
 * the PackageCard row grid with a category-tinted avatar, and the
 * CatalogPublishPill — so agents match the Data / Node catalog drawers
 * (dev/68). Data + lifecycle live in ``useAgentCatalogDrawer``.
 *
 * Per DEC-042 (dev/21) the static dark roster header carries the **Pin button
 * only** — no Close, no agent identity, no agent-cycling controls. Dismissal is
 * the backdrop/Escape (gated by the pin); the opened agent view has its own
 * identity header (AgentChatPanel).
 */
export const AgentCatalogDrawer: React.FC<AgentCatalogDrawerProps> = ({
  presented,
  projectId,
  onEnsureProject,
  pinned,
  onPinToggle,
  onRequestClose,
  onExitComplete,
}) => {
  const c = useAgentCatalogDrawer(presented, projectId, onEnsureProject);
  const panelRef = useRef<HTMLElement>(null);
  // The header cog opens AI Settings, which owns the account scope.
  const [accountSettingsOpen, setAccountSettingsOpen] = useState(false);
  // Upload-import (dev/36), opened from the footer's Import package button.
  const [importOpen, setImportOpen] = useState(false);
  // Search/sort are pure view state over the hook's per-scope cache (dev/68) —
  // client-side like the Node Catalog drawer, persisting across scope tabs.
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortMode>("new");
  // Add and Remove both confirm here (#196, #197). AgentRow is a child, so the
  // pending card lives in the drawer rather than in the row that opened it.
  const [confirmAction, setConfirmAction] = useState<{
    title: string;
    body: React.ReactNode;
    confirmLabel: string;
    destructive: boolean;
    run: () => Promise<void>;
  } | null>(null);

  const requestInstall = useCallback(
    (card: AgentCard) => {
      const requires = card.requiresAgents ?? [];
      setConfirmAction({
        title: `Add ${card.name}?`,
        confirmLabel: "Add to dataflow",
        destructive: false,
        body: (
          <>
            <p>
              Add {card.name} ({card.dirName}) to this dataflow?
            </p>
            {/* dev/106: the same hard dependencies the card lists, restated
                here so they are disclosed before the click commits. */}
            {requires.length ? (
              <>
                <p>It requires:</p>
                <ul>
                  {requires.map((r) => (
                    <li key={r.id}>
                      {r.name}
                      {r.installedInProject
                        ? " (already in this dataflow)"
                        : r.visible
                          ? " (not installed)"
                          : " (unavailable)"}
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
          </>
        ),
        run: () => c.install(card),
      });
    },
    [c],
  );

  const requestUninstall = useCallback(
    (card: AgentCard) => {
      setConfirmAction({
        title: `Remove ${card.name}?`,
        confirmLabel: "Remove",
        destructive: true,
        // Both peers confirm this one (NodeCatalogDrawer.onUninstall,
        // useDatasetCatalogDrawer.onUnpublish): it is a lockfile write the
        // user cannot undo with a second click, and any agent attached from
        // this dataflow goes with it.
        body: `Remove ${card.name} (${card.dirName}) from this dataflow?`,
        run: () => c.uninstall(card),
      });
    },
    [c],
  );

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
      className={`${shell.overlayRoot} ${styles.overlayRoot} ${
        presented ? shell.overlayRootPresented : ""
      }`}
      data-curio-agent-catalog-drawer="true"
      aria-hidden={!presented}
    >
      {/* The scrim's label is deliberately NOT the header close button's. The
          Node drawer gives both the same accessible name, which makes an
          unscoped get_by_role lookup ambiguous - its own e2e has to resolve
          the dialog by heading to work around it. */}
      <button
        type="button"
        className={shell.scrim}
        aria-label="Dismiss Agent Catalog"
        onClick={() => {
          if (!pinned) onRequestClose?.();
        }}
      />
      <aside
        ref={panelRef}
        className={shell.drawer}
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-catalog-drawer-title"
        tabIndex={-1}
        onTransitionEnd={handlePanelTransitionEnd}
      >
      <DrawerHeader
        kind="agent"
        title="Agent Catalog"
        titleId="agent-catalog-drawer-title"
        subtitle={SUBTITLE[c.scope]}
        closeAriaLabel="Close Agent Catalog drawer"
        pinned={pinned}
        onPinToggle={onPinToggle}
        onClose={() => onRequestClose?.()}
        actions={
          <button
            type="button"
            className={styles.headerSettingsBtn}
            aria-haspopup="dialog"
            onClick={() => setAccountSettingsOpen(true)}
          >
            <FontAwesomeIcon icon={faGear} aria-hidden /> AI Settings
          </button>
        }
      />

      {/* Shared catalog search/sort bar (dev/68) — the same component, order
          and geometry as the Data/Node catalog drawers, per the concept. */}
      <PackageSearchRow
        search={search}
        sort={sort}
        onSearchChange={setSearch}
        onSortChange={setSort}
        placeholder="Search agents, publishers, tags…"
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

      <div className={shell.scrollBody}>
        {c.error ? (
          <div className={shell.error} role="alert">
            {c.error}
          </div>
        ) : null}

        {/* Adding is not blocked on a save, it performs one. Saying so beats a
            disabled button with no explanation, which is what this drawer used
            to show. Shared wording - see constants/catalogCopy. */}
        {!projectId ? (
          <div className={shell.noticeBanner} role="status">
            <span className={shell.noticeBannerText}>{UNSAVED_DATAFLOW_NOTICE}</span>
          </div>
        ) : null}

        {c.loading ? (
          <div className={shell.empty}>Loading agents…</div>
        ) : visibleCards.length === 0 ? (
          <div className={shell.empty}>
            {c.cards.length > 0
              ? "No agents match the current filters."
              : c.scope === "installed"
                ? "No agents added to this dataflow yet."
                : "No agents match the current filters."}
          </div>
        ) : (
          <div className={shell.cardList}>
            {visibleCards.map((card) => (
              <AgentRow
                key={card.dirName}
                card={card}
                scope={c.scope}
                state={c}
                hasProject={!!projectId}
                onRequestInstall={requestInstall}
                onRequestUninstall={requestUninstall}
              />
            ))}
          </div>
        )}
      </div>

      {/* The shared footer's geometry, but its own control: DrawerFooter wraps
          a single-archive file input, and an agent import is a manifest plus
          its prompt files, picked inside AgentImportModal. Reusing the styles
          keeps this footer identical to the other two drawers; reusing the
          component would have meant shipping the wrong picker. */}
      <footer className={footerStyles.footer}>
        <button
          type="button"
          className={footerStyles.footerPrimary}
          aria-haspopup="dialog"
          onClick={() => setImportOpen(true)}
        >
          Import agent
        </button>
      </footer>

      {importOpen ? (
        <AgentImportModal
          onClose={() => setImportOpen(false)}
          onImported={() => {
            setImportOpen(false);
            // The new definition lives in My imports, so show that tab.
            c.setScope("imports");
            void c.reload();
          }}
        />
      ) : null}
      {accountSettingsOpen ? (
        /* The account scope lives in AI Settings now, beside the provider it
           applies to. This drawer opens that one surface rather than a second
           modal for half the answer. On the canvas it is the ONLY way there:
           GlobalPageHeader renders only on /projects and /catalog/*. */
        <React.Suspense fallback={null}>
          <AiSettingsModal isOpen onClose={() => setAccountSettingsOpen(false)} />
        </React.Suspense>
      ) : null}
      {confirmAction ? (
        <ConfirmDialog
          title={confirmAction.title}
          body={confirmAction.body}
          confirmLabel={confirmAction.confirmLabel}
          destructive={confirmAction.destructive}
          // Opened from inside the drawer, which paints above the default
          // modal layer - without this the confirm button is under it.
          layer="overlay"
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => {
            const { run } = confirmAction;
            setConfirmAction(null);
            void run();
          }}
        />
      ) : null}
      </aside>
    </div>
  );
};

const AgentRow: React.FC<{
  card: AgentCard;
  scope: AgentScope;
  state: ReturnType<typeof useAgentCatalogDrawer>;
  hasProject: boolean;
  onRequestInstall: (card: AgentCard) => void;
  onRequestUninstall: (card: AgentCard) => void;
}> = ({ card, scope, state, hasProject, onRequestInstall, onRequestUninstall }) => {
  const busy = state.busyCoord === card.dirName;
  // The shared catalog card grid: 72px avatar | body | action. There is no
  // accent stripe - it was dropped from every catalog card because the
  // avatar tint already carries the category, and PackageCard.module.css no
  // longer defines .cardAccent, so the div was rendering unstyled into the
  // grid's first column and displacing the avatar.
  const categoryKey = agentCategoryKey(card.category);
  const avatarClass = styles[`avatar_${categoryKey}` as keyof typeof styles] ?? "";
  return (
    // The cross-surface identity attribute: this card, its row in the tools
    // palette and its card on /catalog/agents all carry the same coordinate,
    // which is what lets an install be asserted end to end without reading a
    // hashed CSS class. data-pkg-dir and data-dataset-id do the same job.
    <article className={`${cardStyles.card} ${styles.agentCard}`} data-agent-coord={card.dirName}>
      <div className={`${cardStyles.cardAvatar} ${avatarClass}`} aria-hidden>
        <FontAwesomeIcon icon={agentCategoryIcon(card.category)} className={styles.avatarIcon} />
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
        {/* Per-scope action controls:
            Browse all  -> Add to dataflow (or Remove from dataflow if in)
            My imports  -> Add to dataflow + Publish pill + Remove from account
            In dataflow -> Remove from dataflow

            There is no per-agent settings cog. Curio no longer offers a
            surface for capping runs or spend, so the three policy scopes it
            used to open have nothing left to edit. */}
        {scope === "installed" || card.installedInProject ? (
          <button
            type="button"
            className={`${cardStyles.btnSecondary} ${styles.secondaryBtn}`}
            disabled={busy || !hasProject}
            onClick={() => onRequestUninstall(card)}
          >
            Remove from dataflow
          </button>
        ) : (
          <button
            type="button"
            className={`${cardStyles.btnInstall} ${styles.installBtn}`}
            disabled={busy}
            title={installTitle(card)}
            onClick={() => onRequestInstall(card)}
          >
            {installLabel(card)}
          </button>
        )}

        {scope === "imports" ? (
          <>
            {/* Publish to the shared catalog. The pill only shows for eligible (owned,
                store-backed) definitions — built-ins report publishable=false,
                so no dead button appears. */}
            <CatalogPublishPill
              dirName={card.dirName}
              published={card.published}
              allowPublish={card.publishable}
              busy={busy}
              onPublish={() => state.publish(card.dirName)}
              variant="hub"
              publishedTitle="Listed in the Agent Catalog"
              publishActionTitle="Publish this agent into the shared catalog (agents/)"
            />
            <button
              type="button"
              className={`${cardStyles.btnSecondary} ${styles.secondaryBtn}`}
              disabled={busy}
              onClick={() => state.removeImport(card.dirName)}
            >
              {/* Not "Delete": `services.remove_import` drops the registry
                  entry and leaves the definition on disk, so the old label
                  promised a destruction that never happened. This is the same
                  call the browse page makes, under the same name. */}
              Remove from my account
            </button>
          </>
        ) : null}

        {scope === "browse" && !card.imported ? (
          <button
            type="button"
            className={`${cardStyles.btnSecondary} ${styles.secondaryBtn}`}
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
