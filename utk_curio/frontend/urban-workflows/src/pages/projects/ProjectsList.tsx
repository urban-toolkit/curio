import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CSS from "csstype";
import { useNavigate } from "react-router-dom";
import { permanentDeletionNotice } from "../../services/retentionCopy";
import { projectsApi, ProjectSummary } from "../../api/projectsApi";
import { useToastContext } from "../../providers/ToastProvider";
import { projectActions, type ProjectActionId } from "./projectActions";
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
import ConfirmDialog from "../../components/ConfirmDialog";
import PromptDialog from "../../components/PromptDialog";

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
  // Tri-state, like the three catalog browse pages: `undefined` is "nothing
  // chosen yet, fall back to the first card", `null` is "the user closed the
  // drawer". Collapsing those into one value is what let a dismissed drawer
  // come back - see the effect below.
  const [selectedId, setSelectedId] = useState<string | null | undefined>(undefined);
  const [drawerSlotOpen, setDrawerSlotOpen] = useState(false);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; project: ProjectSummary } | null>(null);
  // #197: the rename prompt and the delete confirmation are app modals now,
  // each holding the project it was opened for.
  const [renameTarget, setRenameTarget] = useState<ProjectSummary | null>(null);
  const { showToast } = useToastContext();
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  // The project an action is currently running against. A purge can take a
  // while, and the buttons were re-clickable throughout.
  const [busyId, setBusyId] = useState<string | null>(null);
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
  //
  // `null` is honoured as a decision, not treated as "unset". Before, Close set
  // `null` and this effect read it as falsy and re-selected `filtered[0]`; only
  // the dependency array delayed it, so the drawer stayed shut until the next
  // search keystroke, filter click, sort change or post-mutation refetch - and
  // after a rename or archive it came back on a *different* project than the
  // one the user had been reading.
  useEffect(() => {
    if (filtered.length === 0) {
      setSelectedId(undefined);
      return;
    }
    if (selectedId === null) return;
    if (selectedId != null && filtered.some((p) => p.id === selectedId)) return;
    setSelectedId(undefined);
  }, [filtered, selectedId]);

  const selected = useMemo(() => {
    if (selectedId === null) return null;
    if (selectedId != null) return filtered.find((p) => p.id === selectedId) ?? null;
    return filtered[0] ?? null;
  }, [filtered, selectedId]);

  const openProject = (id: string) => navigate("/dataflow/" + id);

  const performRename = async (project: ProjectSummary, newName: string) => {
    if (!newName || newName === project.name) return;
    try {
      await projectsApi.update(project.id, { name: newName });
      loadProjects();
    } catch (err) {
      console.error("Rename failed:", err);
    }
  };

  const handleRename = (project: ProjectSummary) => setRenameTarget(project);

  const handleDuplicate = async (project: ProjectSummary) => {
    try {
      await projectsApi.duplicate(project.id);
      loadProjects();
    } catch (err) {
      console.error("Duplicate failed:", err);
    }
  };

  const handleArchive = async (project: ProjectSummary) => {
    setBusyId(project.id);
    try {
      await projectsApi.delete(project.id);
      loadProjects();
      showToast(`Archived "${project.name}".`, "success");
    } catch (err) {
      // Was a bare console.error, so a failed archive looked exactly like a
      // successful one to anyone not holding the devtools open.
      showToast((err as Error)?.message || "Couldn't archive that dataflow.", "error");
    } finally {
      setBusyId(null);
    }
  };

  const performDeleteForever = async (project: ProjectSummary) => {
    setBusyId(project.id);
    try {
      await projectsApi.delete(project.id, { purge: true });
      loadProjects();
      showToast(`Deleted "${project.name}".`, "success");
    } catch (err) {
      showToast((err as Error)?.message || "Couldn't delete that dataflow.", "error");
    } finally {
      setBusyId(null);
    }
  };

  const handleDeleteForever = (project: ProjectSummary) => setDeleteTarget(project);

  /**
   * Run one action from {@link projectActions}, whichever surface asked.
   *
   * The single dispatch is what keeps the drawer and the context menu in step:
   * they render the same list and call the same thing, so an action cannot
   * behave differently depending on where it was clicked (#221).
   */
  const runProjectAction = (id: ProjectActionId, project: ProjectSummary) => {
    switch (id) {
      case "open":
        openProject(project.id);
        return;
      case "rename":
        handleRename(project);
        return;
      case "duplicate":
        void handleDuplicate(project);
        return;
      case "archive":
        void handleArchive(project);
        return;
      case "delete":
        handleDeleteForever(project);
        return;
      case "restore":
        // Not offered yet: there is no restore route. Listed in the action
        // union so adding one is a compile error here rather than a silent
        // no-op on whichever surface forgot it.
        return;
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
              Your projects. Open one to keep working on it, or start a new one.
            </p>
            <div className={browseStyles.headerTools}>
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
                      p.id === selected?.id && styles.cardActive
                    )}
                    data-project-id={p.id}
                    role="button"
                    tabIndex={0}
                    aria-pressed={p.id === selected?.id}
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
                // Rendered from ``projectActions`` — the same list the context
                // menu below uses, so the two surfaces cannot disagree about
                // what may be done to a project again (#221). "Open" is the
                // primary action above, so it is dropped here.
                <div className={styles.detailButtonRow}>
                  {projectActions({ archived: Boolean(selected.archived_at) })
                    .filter((action) => action.id !== "open")
                    .map((action) => (
                      <button
                        key={action.id}
                        className={
                          action.destructive
                            ? joined(styles.secondaryButton, styles.dangerButton)
                            : styles.secondaryButton
                        }
                        type="button"
                        disabled={busyId === selected.id}
                        onClick={() => runProjectAction(action.id, selected)}
                      >
                        {action.label}
                      </button>
                    ))}
                </div>
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
          {/* The same list the detail drawer renders. It used to hardcode five
              items with no reference to ``archived_at``, so it offered Archive
              on an already-archived project and disagreed with the drawer about
              Delete forever (#221). Real buttons, not clickable divs: these are
              actions and were unreachable by keyboard. */}
          {projectActions({ archived: Boolean(contextMenu.project.archived_at) }).map(
            (action) => (
              <button
                key={action.id}
                type="button"
                style={
                  action.destructive
                    ? { ...ctxItemStyle, color: "var(--curio-danger)" }
                    : ctxItemStyle
                }
                onClick={() => {
                  runProjectAction(action.id, contextMenu.project);
                  setContextMenu(null);
                }}
              >
                {action.label}
              </button>
            ),
          )}
        </div>
      )}
      {renameTarget ? (
        <PromptDialog
          title="Rename dataflow"
          fieldLabel="Name"
          initialValue={renameTarget.name}
          confirmLabel="Rename"
          onCancel={() => setRenameTarget(null)}
          onConfirm={(name) => {
            const project = renameTarget;
            setRenameTarget(null);
            void performRename(project, name);
          }}
        />
      ) : null}

      {deleteTarget ? (
        <ConfirmDialog
          title={`Permanently delete "${deleteTarget.name}"?`}
          // DEC-057 3.4b: state the live-store scope + the operator's declared
          // backup posture - never claim irreversibility the platform can't
          // control.
          body={permanentDeletionNotice()}
          confirmLabel="Delete forever"
          destructive
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => {
            const project = deleteTarget;
            setDeleteTarget(null);
            void performDeleteForever(project);
          }}
        />
      ) : null}

      <VersionBadge />
    </div>
  );
};

export default ProjectsList;

/* ---- Styles ---- */

const ctxItemStyle: CSS.Properties = {
  // These are <button>s now rather than clickable <div>s, so the browser's own
  // button chrome has to be reset for the row to look as it did. Worth the
  // extra lines: the divs were unreachable by keyboard and announced as nothing.
  display: "block",
  width: "100%",
  textAlign: "left",
  background: "none",
  border: "none",
  padding: "8px 16px",
  color: "var(--curio-text-on-dark)",
  fontSize: "var(--curio-font-size-md)",
  cursor: "pointer",
};



