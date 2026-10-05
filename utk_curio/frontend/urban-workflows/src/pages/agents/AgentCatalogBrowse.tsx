/**
 * The account-scope Agent Catalog under /catalog/agents.
 *
 * The third peer of `/catalog/nodes` and `/catalog/data`: same three-column
 * grid from `CatalogBrowseLayout.module.css`, same rail (`CatalogRail`), same
 * header (`CatalogPageHeader`: kind icon + h1 + count, then search and import),
 * same card grid, same right-hand detail drawer.
 *
 * Scope is what separates this page from the in-canvas drawer. The drawer adds
 * an agent to ONE dataflow; this page adds it to the user's account, from
 * where it can be installed into any dataflow. The Node Catalog's page says
 * "Add to all projects" because installing there really does reach every
 * project - an agent import only makes the agent AVAILABLE to every project,
 * not present in any one of them. One vocabulary across the three catalogs was
 * judged worth more than that distinction, so the button borrows the label and
 * the intro carries the nuance ("makes it available to all your projects").
 */
import React, { useState } from "react";

import type { AgentCard } from "../../services/agents";
import { agentCategoryKey } from "../../components/menus/nodes/agentsPalette/agentCategoryStyle";
import type { SortMode } from "../../services/packages";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { AgentCatalogBrowseCard } from "./AgentCatalogBrowseCard";
import { AgentCatalogBrowseDrawer } from "./AgentCatalogBrowseDrawer";
import { useAgentCatalogBrowse } from "./useAgentCatalogBrowse";
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import { AgentImportModal } from "../../components/agents/catalog/AgentImportModal";
import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";
import { AgentCatalogSettingsModal } from "../../components/agents/catalog/AgentCatalogSettingsModal";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import {
  agentCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";

export const AgentCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  // Separate from `selectedCoord`, which drives the side drawer. Wiring both to
  // one setter is what made "View details" a no-op: on arrival the drawer is
  // already open on the first card, so the click had nothing left to change
  // (#189). The Data Catalog keeps the same two surfaces apart.
  const [detailCoord, setDetailCoord] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Right-click. The card reports the event, the grid owns the menu - the same
  // division the projects page has used all along (#285).
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    agent: AgentCard;
  } | null>(null);
  const {
    search,
    setSearch,
    sort,
    setSort,
    filter,
    setFilter,
    categoryFilter,
    setCategoryFilter,
    loading,
    busyCoord,
    actionError,
    dismissActionError,
    agents,
    filtered,
    categories,
    allCount,
    importedCount,
    selectedCoord,
    setSelectedCoord,
    selectedAgent,
    onImport,
    onRemoveImport,
    onPublish,
    onUnpublish,
    reload,
  } = useAgentCatalogBrowse();

  const runAgentAction = (id: CatalogCardActionId, agent: AgentCard) => {
    switch (id) {
      case "add-to-all-projects":
        void onImport(agent);
        return;
      case "remove-from-all-projects":
        void onRemoveImport(agent);
        return;
      case "view-details":
        setDetailCoord(agent.dirName);
        return;
      // An agent is never offered the package catalog's update.
      case "update-all-projects":
        return;
    }
  };

  // From the unfiltered roster on purpose - the modal outlives a filter change.
  const detailAgent = detailCoord ? (agents.find((a) => a.dirName === detailCoord) ?? null) : null;

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <CatalogRail
        ariaLabel="Filter agents"
        all={{
          label: "All agents",
          count: allCount,
          active: filter === "all" && categoryFilter === "",
          onClick: () => {
            setFilter("all");
            setCategoryFilter(() => "");
          },
        }}
        scope={{
          label: "In all projects",
          count: importedCount,
          active: filter === "imported",
          onClick: () => setFilter(filter === "imported" ? "all" : "imported"),
        }}
        sections={[
          {
            key: "category",
            label: "By category",
            entries: categories.map(([cat, count]) => ({
              value: cat,
              label: cat,
              count,
              active: categoryFilter === cat,
              onClick: () => setCategoryFilter((prev) => (prev === cat ? "" : cat)),
              // The card strips' palette key for this category.
              dotClassName: browseStyles[`agentDot_${agentCategoryKey(cat)}`] ?? "",
            })),
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="agent"
          iconTitle="Agent catalog"
          title="Agent Catalog"
          count={filtered.length}
          intro={
            <>
              Agents in the shared catalog. Adding one here makes it available to{" "}
              <strong>all your projects</strong>, present and future; add it to a single project from
              that project&apos;s Agent Catalog.
            </>
          }
          viewTools={
            <select
              className={browseStyles.sortSelect}
              aria-label="Sort agents"
              value={sort}
              onChange={(e) => setSort(e.target.value as SortMode)}
            >
              <option value="new">Sort: Newest</option>
              <option value="name">Sort: Name</option>
            </select>
          }
        >
          <input
            className={browseStyles.hubSearch}
            type="search"
            placeholder="Search agents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          {/* No `accept`: an agent package is a manifest plus its prompt
              files, assembled in a modal, not a single archive. */}
          <CatalogHeaderImport
            label="Import agent"
            onClick={() => setImportOpen(true)}
            title="Upload your own agent definition"
          />
          <button
            type="button"
            className={browseStyles.publishButton}
            title="Values your agents read when they run"
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
        </CatalogPageHeader>

        {actionError ? (
          <div className={browseStyles.browseBanner} role="alert">
            <span>{actionError}</span>
            <button
              type="button"
              className={browseStyles.browseBannerDismiss}
              aria-label="Dismiss"
              onClick={dismissActionError}
            >
              ×
            </button>
          </div>
        ) : null}

        {loading ? (
          <div className={browseStyles.empty}>Loading agents…</div>
        ) : filtered.length === 0 ? (
          <div className={browseStyles.empty}>No agents match the current filters.</div>
        ) : (
          <section className={browseStyles.cardGrid}>
            {filtered.map((agent) => (
              <AgentCatalogBrowseCard
                key={agent.dirName}
                agent={agent}
                // Follow what the drawer actually shows, not the raw state:
                // on arrival the selection is `undefined` and the drawer falls
                // back to the first row, which should read as selected.
                selected={selectedAgent?.dirName === agent.dirName}
                onSelect={() => setSelectedCoord(agent.dirName)}
                onViewDetails={() => setDetailCoord(agent.dirName)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first: the menu acts on this agent, so the drawer
                  // beside it should not still be describing another one.
                  setSelectedCoord(agent.dirName);
                  setContextMenu({ x: e.clientX, y: e.clientY, agent });
                }}
              />
            ))}
          </section>
        )}
      </main>

      <AgentCatalogBrowseDrawer
        agent={selectedAgent}
        busyCoord={busyCoord}
        catalogPublishAllowed
        onImport={(a) => void onImport(a)}
        onRemoveImport={(a) => void onRemoveImport(a)}
        onPublish={(a) => void onPublish(a)}
        onUnpublish={(a) => void onUnpublish(a)}
        onViewDetails={(a) => setDetailCoord(a.dirName)}
        onClose={() => setSelectedCoord(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Agent actions"
          items={agentCardActions({ imported: contextMenu.agent.imported })}
          onSelect={(id) => runAgentAction(id as CatalogCardActionId, contextMenu.agent)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

      {detailAgent ? (
        <AgentDetailModal agent={detailAgent} onClose={() => setDetailCoord(null)} />
      ) : null}

      {settingsOpen ? <AgentCatalogSettingsModal onClose={() => setSettingsOpen(false)} /> : null}

      {/* The same modal the drawer's footer opens. Uploading writes a new
          definition into the account, so the roster has to be re-read. */}
      {importOpen ? (
        <AgentImportModal
          onClose={() => setImportOpen(false)}
          onImported={(dirName) => {
            setImportOpen(false);
            setSelectedCoord(dirName);
            void reload();
          }}
        />
      ) : null}
    </div>
  );
};

export default AgentCatalogBrowse;
