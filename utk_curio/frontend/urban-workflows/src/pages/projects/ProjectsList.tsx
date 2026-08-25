import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CSS from "csstype";
import { useNavigate } from "react-router-dom";
import { projectsApi, ProjectSummary } from "../../api/projectsApi";
import { notebookToTrill } from "../../NotebookConvertor";
import DataflowThumbnail from "../../components/DataflowThumbnail";
import {
  CatalogItemStripHeader,
  CatalogKindIcon,
} from "../../components/catalog/CatalogKindVisuals";
import {
  catalogIsFresh,
  catalogRelativeTime,
} from "../../components/catalog/catalogTimeFormat";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { CatalogBrowseDrawerBody } from "../catalog/CatalogBrowseDrawerBody";
import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import shellStyles from "../catalog/CatalogMasterPage.module.css";
import styles from "./ProjectsBrowseLayout.module.css";

type ViewMode = "grid" | "list";
type FilterTab = "all" | "recent" | "archived";
/** Mirrors the sorts projectsApi and `list_for_user` already implement. */
type ProjectSort = "last_opened" | "name" | "created";

const SORT_OPTIONS: { value: ProjectSort; label: string }[] = [
  { value: "last_opened", label: "Sort: Recent activity" },
  { value: "name", label: "Sort: Name" },
  { value: "created", label: "Sort: Created" },
];

const FILTER_TABS: FilterTab[] = ["all", "recent", "archived"];

const SCOPE_BY_TAB: Record<FilterTab, "mine" | "recent" | "archived"> = {
  all: "mine",
  recent: "recent",
  archived: "archived",
};

const TAB_LABELS: Record<FilterTab, string> = {
  all: "All projects",
  recent: "Recent",
  archived: "Archived",
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString();
}

function joined(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

function nodeCount(project: ProjectSummary): number {
  return project.graph_preview?.nodes.length ?? 0;
}

function edgeCount(project: ProjectSummary): number {
  return project.graph_preview?.edges.length ?? 0;
}

const ProjectsList: React.FC = () => {
  const navigate = useNavigate();
  // Every scope is held at once so the rail can show counts and switching
  // filters does not wait on a round trip.
  const [byTab, setByTab] = useState<Record<FilterTab, ProjectSummary[]>>({
    all: [],
    recent: [],
    archived: [],
  });
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [sort, setSort] = useState<ProjectSort>("last_opened");
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; project: ProjectSummary } | null>(null);
  const importNotebookRef = useRef<HTMLInputElement>(null);

  const loadProjects = useCallback(async () => {
    const results = await Promise.all(
      FILTER_TABS.map((tab) =>
        projectsApi
          .list({ scope: SCOPE_BY_TAB[tab], sort })
          .catch(() => [] as ProjectSummary[])
      )
    );
    setByTab({ all: results[0], recent: results[1], archived: results[2] });
  }, [sort]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    const dismiss = () => setContextMenu(null);
    if (contextMenu) document.addEventListener("click", dismiss);
    return () => document.removeEventListener("click", dismiss);
  }, [contextMenu]);

  const filtered = useMemo(
    () =>
      byTab[filter].filter((p) =>
        p.name.toLowerCase().includes(search.toLowerCase())
      ),
    [byTab, filter, search]
  );

  // Mirrors the catalog browse pages: the first item is selected so the detail
  // drawer arrives populated instead of empty.
  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(null);
      return;
    }
    setSelectedId((prev) =>
      prev && filtered.some((p) => p.id === prev) ? prev : filtered[0].id
    );
  }, [filtered]);

  const selected = filtered.find((p) => p.id === selectedId) ?? null;

  const openProject = (id: string) => navigate("/dataflow/" + id);

  const handleRename = async (project: ProjectSummary) => {
    const newName = window.prompt("Rename project:", project.name);
    if (!newName || newName === project.name) return;
    try {
      await projectsApi.update(project.id, { name: newName });
      loadProjects();
    } catch (err) {
      console.error("Rename failed:", err);
    }
  };

  const handleDuplicate = async (project: ProjectSummary) => {
    try {
      await projectsApi.duplicate(project.id);
      loadProjects();
    } catch (err) {
      console.error("Duplicate failed:", err);
    }
  };

  const handleArchive = async (project: ProjectSummary) => {
    try {
      await projectsApi.delete(project.id);
      loadProjects();
    } catch (err) {
      console.error("Archive failed:", err);
    }
  };

  const handleDeleteForever = async (project: ProjectSummary) => {
    if (!window.confirm('Permanently delete "' + project.name + '"?')) return;
    try {
      await projectsApi.delete(project.id, { purge: true });
      loadProjects();
    } catch (err) {
      console.error("Delete failed:", err);
    }
  };

  const handleNotebookImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (event: ProgressEvent<FileReader>) => {
      try {
        const json = JSON.parse(event.target?.result as string) as Record<string, unknown>;
        const trillSpec = await notebookToTrill(json, process.env.BACKEND_URL as string);
        const name = file.name.replace(/\.ipynb$/i, "");
        await projectsApi.create({ name, spec: trillSpec as unknown as Record<string, unknown>, outputs: [] });
        loadProjects();
      } catch (err) {
        console.error("Failed to import Jupyter notebook:", err);
      }
    };
    reader.onerror = (event: ProgressEvent<FileReader>) =>
      console.error("Error reading notebook file:", event.target?.error);
    reader.readAsText(file);
  };

  return (
    <div className={shellStyles.pageShell}>
      <input
        type="file"
        accept=".ipynb"
        ref={importNotebookRef}
        style={{ display: "none" }}
        onChange={handleNotebookImport}
        onClick={(e) => { (e.target as HTMLInputElement).value = ""; }}
      />
      <GlobalPageHeader />
      <AppSectionTabs />

      <div className={joined(browseStyles.page, drawerSlotOpen && browseStyles.pageWithDrawer)}>
        <aside className={browseStyles.categoryRail} aria-label="Project filters">
          <p className={browseStyles.railLabel}>By status</p>
          {FILTER_TABS.map((tab) => (
            <button
              key={tab}
              className={joined(
                browseStyles.railButton,
                filter === tab && browseStyles.railButtonActive
              )}
              type="button"
              aria-pressed={filter === tab}
              onClick={() => setFilter(tab)}
            >
              <span>{TAB_LABELS[tab]}</span>
              <span className={tab === "all" ? browseStyles.railCountBadge : browseStyles.railCount}>
                {byTab[tab].length}
              </span>
            </button>
          ))}
        </aside>

        <main className={styles.main}>
          <section className={browseStyles.browseHeader}>
            <p className={browseStyles.crumb}>Projects</p>
            <div className={browseStyles.titleRow}>
              <CatalogKindIcon kind="dataflow" size="md" title="Dataflows" />
              <h1>Projects</h1>
              <span className={browseStyles.titleCount}>{filtered.length}</span>
            </div>
            <p className={browseStyles.pageIntro}>
              Your dataflows. Open one to keep working on it, or start a new one.
            </p>
            <div className={browseStyles.headerTools}>
              <span className={browseStyles.hubStatusChip}>
                <span className={browseStyles.hubStatusDot} />
                My dataflows
              </span>
              <input
                className={browseStyles.hubSearch}
                type="search"
                placeholder="Search projects…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <button
                type="button"
                className={browseStyles.publishButton}
                onClick={() => importNotebookRef.current?.click()}
              >
                Import Jupyter notebook
              </button>
              <button
                type="button"
                className={browseStyles.primaryHeaderButton}
                onClick={() => navigate("/dataflow/new")}
              >
                + New Dataflow
              </button>
            </div>
          </section>

          <div className={browseStyles.filterBar}>
            {FILTER_TABS.map((tab) => (
              <button
                key={tab}
                className={joined(browseStyles.chip, filter === tab && browseStyles.chipActive)}
                type="button"
                onClick={() => setFilter(tab)}
              >
                {TAB_LABELS[tab]}
              </button>
            ))}
            <span className={browseStyles.filterSpacer} />
            <select
              className={browseStyles.sortSelect}
              aria-label="Sort projects"
              value={sort}
              onChange={(e) => setSort(e.target.value as ProjectSort)}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <div className={styles.viewSwitch}>
              {(["grid", "list"] as ViewMode[]).map((mode) => (
                <button
                  key={mode}
                  className={joined(
                    styles.viewButton,
                    viewMode === mode && styles.viewButtonActive
                  )}
                  type="button"
                  onClick={() => setViewMode(mode)}
                >
                  {mode === "grid" ? "Grid" : "List"}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className={browseStyles.empty}>
              {search
                ? "No projects match the current filters."
                : "No projects yet. Create a new dataflow!"}
            </div>
          ) : (
            <div className={styles.cardScroll} data-curio-projects-scroll="true">
              <div className={viewMode === "grid" ? styles.cardGrid : styles.cardList}>
                {filtered.map((p) => (
                  <div
                    key={p.id}
                    className={joined(
                      styles.card,
                      viewMode === "list" && styles.cardRow,
                      p.id === selectedId && styles.cardActive
                    )}
                    data-project-id={p.id}
                    role="button"
                    tabIndex={0}
                    aria-pressed={p.id === selectedId}
                    onClick={() => setSelectedId(p.id)}
                    onDoubleClick={() => openProject(p.id)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        setSelectedId(p.id);
                      }
                    }}
                    onContextMenu={(e) => {
                      e.preventDefault();
                      setSelectedId(p.id);
                      setContextMenu({ x: e.clientX, y: e.clientY, project: p });
                    }}
                  >
                    <div className={styles.cardStrip}>
                      <CatalogItemStripHeader
                        kind="dataflow"
                        badge={
                          <span className={browseStyles.stripBadgePopular}>
                            Rev {p.spec_revision}
                          </span>
                        }
                      />
                    </div>
                    <div className={styles.cardBody}>
                      <span className={styles.cardTitle}>{p.name}</span>
                      <span className={styles.cardSub}>
                        {p.description || "Rev " + p.spec_revision}
                        {p.last_opened_at
                          ? " · " + new Date(p.last_opened_at).toLocaleDateString()
                          : ""}
                      </span>
                    </div>
                    <div className={styles.cardThumbnail}>
                      <DataflowThumbnail preview={p.graph_preview} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>

        <CatalogBrowseDrawerShell presented={selected !== null} onLayoutChange={setDrawerSlotOpen}>
          {selected && (
            <CatalogBrowseDrawerBody
              kind="dataflow"
              headerTitle="Dataflow details"
              onClose={() => setSelectedId(null)}
              hero={
                <div className={browseStyles.drawerKindHero}>
                  <DataflowThumbnail preview={selected.graph_preview} />
                </div>
              }
              title={selected.name}
              badges={
                <>
                  <span className={browseStyles.drawerCategoryBadge}>
                    Rev {selected.spec_revision}
                  </span>
                  {selected.archived_at ? (
                    <span className={browseStyles.drawerInstalledBadge}>Archived</span>
                  ) : null}
                </>
              }
              subtitle={selected.slug}
              metaLeft={
                nodeCount(selected) +
                " nodes · " +
                edgeCount(selected) +
                " connections"
              }
              metaRight={catalogRelativeTime(selected.updated_at)}
              fresh={catalogIsFresh(selected.updated_at)}
              description={selected.description}
              infoLabel="Dataflow info"
              infoRows={[
                { label: "Revision", value: selected.spec_revision },
                { label: "Last opened", value: catalogRelativeTime(selected.last_opened_at) },
                { label: "Updated", value: formatDate(selected.updated_at) },
                { label: "Created", value: formatDate(selected.created_at) },
                selected.archived_at
                  ? { label: "Archived", value: formatDate(selected.archived_at) }
                  : null,
              ]}
              primaryAction={
                <button
                  type="button"
                  className={browseStyles.addToPaletteBtn}
                  onClick={() => openProject(selected.id)}
                >
                  Open dataflow
                </button>
              }
              secondaryAction={
                <>
                  <div className={styles.detailButtonRow}>
                    <button
                      className={styles.secondaryButton}
                      type="button"
                      onClick={() => handleRename(selected)}
                    >
                      Rename
                    </button>
                    <button
                      className={styles.secondaryButton}
                      type="button"
                      onClick={() => handleDuplicate(selected)}
                    >
                      Duplicate
                    </button>
                  </div>
                  <div className={styles.detailButtonRow}>
                    {selected.archived_at ? (
                      <button
                        className={joined(styles.secondaryButton, styles.dangerButton)}
                        type="button"
                        onClick={() => handleDeleteForever(selected)}
                      >
                        Delete forever
                      </button>
                    ) : (
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() => handleArchive(selected)}
                      >
                        Archive
                      </button>
                    )}
                  </div>
                </>
              }
            />
          )}
        </CatalogBrowseDrawerShell>
      </div>

      {contextMenu && (
        <div
          style={{
            position: "fixed",
            top: contextMenu.y,
            left: contextMenu.x,
            backgroundColor: "var(--curio-top-bar-bg)",
            border: "1px solid var(--curio-border-context-menu)",
            borderRadius: "var(--curio-radius-sm)",
            zIndex: 9999,
            minWidth: "160px",
            boxShadow: "var(--curio-shadow-context-menu)",
          }}
        >
          <div style={ctxItemStyle} onClick={() => openProject(contextMenu.project.id)}>
            Open
          </div>
          <div style={ctxItemStyle} onClick={() => { handleRename(contextMenu.project); setContextMenu(null); }}>
            Rename
          </div>
          <div style={ctxItemStyle} onClick={() => { handleDuplicate(contextMenu.project); setContextMenu(null); }}>
            Duplicate
          </div>
          <div style={ctxItemStyle} onClick={() => { handleArchive(contextMenu.project); setContextMenu(null); }}>
            Archive
          </div>
          <div style={{ ...ctxItemStyle, color: "var(--curio-danger)" }} onClick={() => { handleDeleteForever(contextMenu.project); setContextMenu(null); }}>
            Delete forever
          </div>
        </div>
      )}
      <VersionBadge />
    </div>
  );
};

export default ProjectsList;

/* ---- Styles ---- */

const ctxItemStyle: CSS.Properties = {
  padding: "8px 16px",
  color: "var(--curio-text-on-dark)",
  fontSize: "var(--curio-font-size-md)",
  cursor: "pointer",
};



