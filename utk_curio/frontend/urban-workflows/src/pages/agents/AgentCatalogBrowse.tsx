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
 * project - an agent import does not, so this one says "Add to my account"
 * rather than borrowing a label that would overstate what the click does.
 */
import React, { useState } from "react";

import { CatalogKindIcon } from "../../components/catalog/CatalogKindVisuals";
import type { SortMode } from "../../components/packages/publishing/packageTypes";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { AgentCatalogBrowseCard } from "./AgentCatalogBrowseCard";
import { AgentCatalogBrowseDrawer } from "./AgentCatalogBrowseDrawer";
import { useAgentCatalogBrowse } from "./useAgentCatalogBrowse";

export const AgentCatalogBrowse: React.FC = () => {
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
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
    filtered,
    categories,
    allCount,
    importedCount,
    publishedCount,
    selectedCoord,
    setSelectedCoord,
    selectedAgent,
    onImport,
    onRemoveImport,
    onPublish,
  } = useAgentCatalogBrowse();

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
          <span>In my account</span>
          <span className={browseStyles.railCount}>{importedCount}</span>
        </button>
        <button
          className={`${browseStyles.railButton} ${filter === "published" ? browseStyles.railButtonActive : ""}`}
          type="button"
          onClick={() => setFilter("published")}
        >
          <span>Published</span>
          <span className={browseStyles.railCount}>{publishedCount}</span>
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
            Add agents to <strong>your account</strong>, then add them to a dataflow from that
            dataflow&apos;s Agent Catalog.
          </p>
          <div className={browseStyles.headerTools}>
            <input
              className={browseStyles.hubSearch}
              type="search"
              placeholder="Search agents…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
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
            In my account
          </button>
          <button
            className={`${browseStyles.chip} ${filter === "published" ? browseStyles.chipActive : ""}`}
            type="button"
            onClick={() => setFilter("published")}
          >
            Published
          </button>
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
                busy={busyCoord === agent.dirName}
                catalogPublishAllowed
                onSelect={() => setSelectedCoord(agent.dirName)}
                onViewDetails={() => setSelectedCoord(agent.dirName)}
                onPublish={(a) => void onPublish(a)}
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
        onClose={() => setSelectedCoord(null)}
        onLayoutChange={setDrawerSlotOpen}
      />
    </div>
  );
};

export default AgentCatalogBrowse;
