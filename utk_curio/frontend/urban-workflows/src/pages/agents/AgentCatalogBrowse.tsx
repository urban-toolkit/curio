/**
 * The account-scope Agent Catalog under /catalog/agents.
 *
 * The third peer of `/catalog/nodes` and `/catalog/data`: same three-column
 * grid from `CatalogBrowseLayout.module.css`, same header anatomy (crumb, kind
 * icon + h1 + count, intro, search), same filter bar, same card grid, same
 * right-hand detail drawer.
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

import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { AgentCatalogBrowseCard } from "./AgentCatalogBrowseCard";
import { AgentCatalogBrowseDrawer } from "./AgentCatalogBrowseDrawer";
import { useAgentCatalogBrowse } from "./useAgentCatalogBrowse";
import { CatalogHeaderImport } from "../catalog/CatalogHeaderImport";
import { AgentImportModal } from "../../components/agents/catalog/AgentImportModal";
import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";

export const AgentCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  // Separate from `selectedCoord`, which drives the side drawer. Wiring both to
  // one setter is what made "View details" a no-op: on arrival the drawer is
  // already open on the first card, so the click had nothing left to change
  // (#189). The Data Catalog keeps the same two surfaces apart.
  const [detailCoord, setDetailCoord] = useState<string | null>(null);
  const [importOpen, setImportOpen] = useState(false);
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

  // From the unfiltered roster on purpose - the modal outlives a filter change.
  const detailAgent = detailCoord
    ? (agents.find((a) => a.dirName === detailCoord) ?? null)
    : null;

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <aside className={browseStyles.categoryRail}>
        <p className={browseStyles.railLabel}>By status</p>
        <button
          className={`${browseStyles.railButton} ${filter === "all" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("all")}
        >
          <span>All agents</span>
          <span className={browseStyles.railCountBadge}>{allCount}</span>
        </button>
        <button
          className={`${browseStyles.railButton} ${filter === "imported" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("imported")}
        >
          <span>In all projects</span>
          <span className={browseStyles.railCount}>{importedCount}</span>
        </button>

        <div className={browseStyles.railDivider} />
        <p className={browseStyles.railLabel}>By category</p>
        <button
          className={`${browseStyles.railButton} ${categoryFilter === "" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setCategoryFilter(() => "")}
        >
          <span>All categories</span>
        </button>
        {categories.map(([cat, count]) => (
          <button
            key={cat}
            className={`${browseStyles.railButton} ${categoryFilter === cat ? browseStyles.railButtonActive : ""}`}
            type="button"
            onClick={() => setCategoryFilter((prev) => (prev === cat ? "" : cat))}
          >
            <span>{cat}</span>
            <span className={browseStyles.railCount}>{count}</span>
          </button>
        ))}
      </aside>

      <main className={browseStyles.browseMain}>
        <section className={browseStyles.browseHeader}>
          <p className={browseStyles.crumb}>Agent Catalog</p>
          <div className={browseStyles.titleRow}>
            <CatalogKindIcon kind="agent" size="md" title="Agent catalog" />
            <h1>Agent Catalog</h1>
            <span className={browseStyles.titleCount}>{filtered.length}</span>
          </div>
          <p className={browseStyles.pageIntro}>
            Agents in the shared catalog. Adding one here makes it available to{" "}
            <strong>all your projects</strong>, present and future; add it to a single
            project from that project&apos;s Agent Catalog.
          </p>
          <div className={browseStyles.headerTools}>
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
          </div>
        </section>

        <div className={browseStyles.filterBar}>
          <button
            className={`${browseStyles.chip} ${filter === "all" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("all")}
          >
            All
          </button>
          <button
            className={`${browseStyles.chip} ${filter === "imported" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("imported")}
          >
            In all projects
          </button>
          {/* The agent's own types - canvas, data, and the rest. The rail has
              had a "By category" section all along and the filter state was
              already wired (`categoryFilter`); the chip row simply never
              offered it, so the two filter surfaces on one page disagreed about
              what you could filter by. Mirrors the Node page's chips. */}
          {categories.map(([category]) => {
            const dotSlug = category.toLowerCase().replace(/[^a-z0-9-]/g, "");
            const dotClass =
              (browseStyles as Record<string, string>)[`chipDot_${dotSlug}`] ??
              browseStyles.chipDotDefault;
            return (
              <button
                key={category}
                className={`${browseStyles.chip} ${
                  categoryFilter === category ? browseStyles.chipActive : ""
                }`}
                type="button"
                onClick={() =>
                  setCategoryFilter((prev) => (prev === category ? "" : category))
                }
              >
                <span className={`${browseStyles.chipDot} ${dotClass}`} />
                {category}
              </button>
            );
          })}
          <span className={browseStyles.filterSpacer} />
          <select
            className={browseStyles.sortSelect}
            value={sort}
            onChange={(e) => setSort(e.target.value as SortMode)}
          >
            <option value="new">Sort: Newest</option>
            <option value="name">Sort: Name</option>
          </select>
        </div>

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

      {detailAgent ? (
        <AgentDetailModal agent={detailAgent} onClose={() => setDetailCoord(null)} />
      ) : null}

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
