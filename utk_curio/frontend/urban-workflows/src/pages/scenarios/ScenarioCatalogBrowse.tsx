import React, { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { CardContextMenu } from "../../components/catalog/CardContextMenu";
import { CatalogPageHeader } from "../catalog/CatalogPageHeader";
import { CatalogRail } from "../catalog/CatalogRail";
import {
  scenarioCardActions,
  type CatalogCardActionId,
} from "../../components/catalog/catalogCardActions";
import { ScenarioDetailModal } from "../../components/scenarios/catalog/ScenarioDetailModal";
import { scenarioProjectPath } from "../../components/scenarios/catalog/scenarioFacts";
import {
  SCENARIO_SORT_OPTIONS,
  sortScenarios,
  useScenarioCatalog,
  type ScenarioRow,
  type ScenarioSortMode,
} from "../../services/scenarioCatalog";
import { ORIGIN_FILTERS, scenarioOrigin, type ScenarioOrigin } from "./scenarioBrowseConstants";
import { ScenarioCatalogBrowseCard } from "./ScenarioCatalogBrowseCard";
import { ScenarioCatalogBrowseDrawer } from "./ScenarioCatalogBrowseDrawer";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";

/** A scenario's address: its id is unique in its project only. */
interface ScenarioRef {
  projectId: string;
  scenarioId: string;
}

function safeDecode(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

/**
 * The account-scope Scenario Catalog under `/catalog/scenarios`.
 *
 * A peer of `/catalog/models` and the other catalogs: the same three-column
 * grid from `CatalogBrowseLayout.module.css`, the same rail (`CatalogRail`),
 * header (`CatalogPageHeader`), card grid, right-hand drawer, right-click menu
 * and details modal.
 *
 * What differs is where a scenario lives. It is a named selection of one
 * project's nodes, saved in that project, so this page only reads: nothing
 * here renames or deletes one, and the way to change it is to open its
 * project. `/catalog/scenarios/<project>/<scenario>` is this page with that
 * scenario's details open.
 */
export const ScenarioCatalogBrowse: React.FC = () => {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [projectFilter, setProjectFilter] = useState("");
  const [origin, setOrigin] = useState<ScenarioOrigin | "">("");
  const [sort, setSort] = useState<ScenarioSortMode>("recent");
  // The peers' tri-state: undefined follows the first card, so the drawer is
  // open on arrival; null is the user having closed it.
  const [selectedKey, setSelectedKey] = useState<string | null | undefined>(undefined);
  // Its own state, not `selectedKey`: the card click drives the drawer and
  // "View details" opens the modal.
  const [detail, setDetail] = useState<ScenarioRef | null>(null);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    scenario: ScenarioRow;
  } | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);

  // A link to a scenario lands where every "View details" does.
  const { projectId: linkedProjectId, scenarioId: linkedScenarioId } = useParams<{
    projectId?: string;
    scenarioId?: string;
  }>();
  useEffect(() => {
    if (linkedProjectId && linkedScenarioId) {
      setDetail({
        projectId: safeDecode(linkedProjectId),
        scenarioId: safeDecode(linkedScenarioId),
      });
    }
  }, [linkedProjectId, linkedScenarioId]);
  const closeDetails = () => {
    setDetail(null);
    // Back to the plain page, so a reload does not reopen what was closed.
    if (linkedProjectId) navigate("/catalog/scenarios", { replace: true });
  };

  // The search is the server's (`?q=`); project and origin narrow the rows
  // here, and their counts are read off the same rows.
  const { data, loading, error, reload } = useScenarioCatalog({ q: search });

  const counts = useMemo(() => {
    const projects = new Map<string, { name: string; count: number }>();
    const origins: Record<string, number> = {};
    for (const item of data.items) {
      const entry = projects.get(item.project.id);
      if (entry) entry.count += 1;
      else projects.set(item.project.id, { name: item.project.name, count: 1 });
      const key = scenarioOrigin(item);
      origins[key] = (origins[key] ?? 0) + 1;
    }
    return { projects, origins };
  }, [data.items]);

  const projectEntries = useMemo(
    () =>
      [...counts.projects.entries()]
        .map(([id, { name, count }]) => ({ id, name, count }))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [counts.projects],
  );

  const scenarios = useMemo(
    () =>
      sortScenarios(
        data.items.filter(
          (item) =>
            (!projectFilter || item.project.id === projectFilter) &&
            (!origin || scenarioOrigin(item) === origin),
        ),
        sort,
      ),
    [data.items, projectFilter, origin, sort],
  );

  const selected = useMemo(() => {
    if (selectedKey === null) return null;
    if (selectedKey !== undefined) {
      return scenarios.find((s) => s.key === selectedKey) ?? scenarios[0] ?? null;
    }
    return scenarios[0] ?? null;
  }, [scenarios, selectedKey]);

  // From the unfiltered rows, so the modal outlives a filter change; the modal
  // reads the scenario itself as well, for a link to one the search hides.
  const detailFallback = detail
    ? data.items.find(
        (s) => s.project.id === detail.projectId && s.id === detail.scenarioId,
      ) ?? null
    : null;

  const viewDetails = (scenario: ScenarioRow) =>
    setDetail({ projectId: scenario.project.id, scenarioId: scenario.id });

  // No canvas on this page, so nothing unsaved to ask about.
  const openProject = (scenario: ScenarioRow) => navigate(scenarioProjectPath(scenario.project.id));

  const runScenarioAction = (id: CatalogCardActionId, scenario: ScenarioRow) => {
    switch (id) {
      case "open-source-project":
        openProject(scenario);
        return;
      case "view-details":
        viewDetails(scenario);
        return;
      // A scenario is not added, removed or deleted from the catalog.
      default:
        return;
    }
  };

  const filtered = Boolean(search.trim() || projectFilter || origin);

  return (
    <div
      className={[browseStyles.page, drawerSlotOpen ? browseStyles.pageWithDrawer : ""]
        .filter(Boolean)
        .join(" ")}
    >
      <CatalogRail
        ariaLabel="Filter scenarios"
        all={{
          label: "All scenarios",
          count: data.items.length,
          active: projectFilter === "" && origin === "",
          onClick: () => {
            setProjectFilter("");
            setOrigin("");
          },
        }}
        sections={[
          {
            key: "project",
            label: "By project",
            entries: projectEntries.map(({ id, name, count }) => ({
              value: id,
              label: name,
              count,
              active: projectFilter === id,
              onClick: () => setProjectFilter((prev) => (prev === id ? "" : id)),
            })),
          },
          {
            key: "origin",
            label: "By origin",
            entries: ORIGIN_FILTERS.map(({ value, label }) => ({
              value,
              label,
              count: counts.origins[value] ?? 0,
              active: origin === value,
              onClick: () => setOrigin((prev) => (prev === value ? "" : value)),
            })),
          },
        ]}
      />

      <main className={browseStyles.browseMain}>
        <CatalogPageHeader
          kind="scenario"
          iconTitle="Scenario Catalog"
          title="Scenario Catalog"
          count={scenarios.length}
          intro={
            <>
              Named selections of a project&apos;s nodes. A scenario lives in its project and
              changes when the project is edited.
            </>
          }
          viewTools={
            <select
              className={browseStyles.sortSelect}
              value={sort}
              aria-label="Sort scenarios"
              onChange={(e) => setSort(e.target.value as ScenarioSortMode)}
            >
              {SCENARIO_SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          }
        >
          <input
            className={browseStyles.hubSearch}
            type="search"
            placeholder="Search scenarios…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            aria-label="Search scenarios"
          />
        </CatalogPageHeader>

        {error ? (
          <div className={browseStyles.browseBanner} role="alert">
            <span>{error}</span>
            <button
              type="button"
              className={browseStyles.browseBannerDismiss}
              aria-label="Retry"
              onClick={reload}
            >
              ↻
            </button>
          </div>
        ) : null}

        {loading && data.items.length === 0 ? (
          <div className={browseStyles.empty}>Loading scenarios…</div>
        ) : !loading && !error && scenarios.length === 0 ? (
          <div className={browseStyles.empty}>
            {filtered
              ? "No scenarios match the current filters."
              : "No scenarios yet. Select nodes on a canvas and choose View > Save selection as scenario."}
          </div>
        ) : (
          <div
            className={[browseStyles.cardGrid, loading ? browseStyles.cardGridRefreshing : ""]
              .filter(Boolean)
              .join(" ")}
          >
            {scenarios.map((scenario) => (
              <ScenarioCatalogBrowseCard
                key={scenario.key}
                scenario={scenario}
                selected={selected?.key === scenario.key}
                onSelect={() => setSelectedKey(scenario.key)}
                onViewDetails={() => viewDetails(scenario)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  // Select first, as the peer pages do: the menu acts on this
                  // scenario, so the drawer should not describe another one.
                  setSelectedKey(scenario.key);
                  setContextMenu({ x: e.clientX, y: e.clientY, scenario });
                }}
              />
            ))}
          </div>
        )}
      </main>

      <ScenarioCatalogBrowseDrawer
        scenario={selected}
        onOpenProject={openProject}
        onViewDetails={viewDetails}
        onClose={() => setSelectedKey(null)}
        onLayoutChange={setDrawerSlotOpen}
      />

      {contextMenu ? (
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Scenario actions"
          items={scenarioCardActions()}
          onSelect={(id) => runScenarioAction(id as CatalogCardActionId, contextMenu.scenario)}
          onDismiss={() => setContextMenu(null)}
        />
      ) : null}

      {detail ? (
        <ScenarioDetailModal
          key={`${detail.projectId}/${detail.scenarioId}`}
          projectId={detail.projectId}
          scenarioId={detail.scenarioId}
          fallbackScenario={detailFallback}
          onClose={closeDetails}
        />
      ) : null}
    </div>
  );
};

export default ScenarioCatalogBrowse;
