import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CSS from "csstype";
import { useNavigate } from "react-router-dom";
import { projectsApi, ProjectSummary } from "../../api/projectsApi";
import { notebookToTrill } from "../../NotebookConvertor";
import DataflowThumbnail from "../../components/DataflowThumbnail";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";
import browseStyles from "../catalog/CatalogBrowseLayout.module.css";
import { CatalogBrowseDrawerShell } from "../catalog/CatalogBrowseDrawerShell";
import styles from "./ProjectsBrowseLayout.module.css";

type ViewMode = "grid" | "list";
type FilterTab = "all" | "recent" | "archived";

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

const ACCENT_COLORS: Record<string, { bg: string; fg: string }> = {
  peach:  { bg: "#FFE3DA", fg: "#E86A3C" },
  sky:    { bg: "#DCE8FF", fg: "#3567C7" },
  mint:   { bg: "#DFF2E1", fg: "#2F8F4A" },
  lilac:  { bg: "#EADCFB", fg: "#7A4BD1" },
};

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "—" : parsed.toLocaleDateString();
}

function joined(...parts: (string | false | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

/** Feeds a project's accent colour to .cardActive / .cardSelectedMark, mirroring
 *  how the catalog keys a selected card's border to the item's kind. */
function accentVar(color: string): React.CSSProperties {
  return { "--projectAccent": color } as React.CSSProperties;
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
          .list({ scope: SCOPE_BY_TAB[tab], sort: "last_opened" })
          .catch(() => [] as ProjectSummary[])
      )
    );
    setByTab({ all: results[0], recent: results[1], archived: results[2] });
  }, []);

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

  const accent = (a: string) => ACCENT_COLORS[a] || ACCENT_COLORS.peach;

  return (
    <div style={pageStyle}>
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
              <h1>Projects</h1>
              <span className={browseStyles.titleCount}>{filtered.length}</span>
            </div>
            <div className={browseStyles.headerTools}>
              <input
                className={browseStyles.hubSearch}
                type="search"
                placeholder="Search projects..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <button
                style={importNotebookBtnStyle}
                onClick={() => importNotebookRef.current?.click()}
              >
                Import Jupyter notebook
              </button>
              <button
                style={newWorkflowBtnStyle}
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
                      p.id === selectedId && styles.cardActive
                    )}
                    style={accentVar(accent(p.thumbnail_accent).fg)}
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
                    {p.id === selectedId && (
                      <span className={styles.cardSelectedMark}>
                        <span className={browseStyles.selectedDot} />
                      </span>
                    )}
                    <div style={cardThumbnailStyle}>
                      <DataflowThumbnail preview={p.graph_preview} accentColor={accent(p.thumbnail_accent).fg} bgColor={accent(p.thumbnail_accent).bg} />
                    </div>
                    <div style={cardBodyStyle}>
                      <span style={cardTitleStyle}>{p.name}</span>
                      <span style={cardSubStyle}>
                        {p.description || "Rev " + p.spec_revision}
                        {p.last_opened_at
                          ? " · " + new Date(p.last_opened_at).toLocaleDateString()
                          : ""}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </main>

        <CatalogBrowseDrawerShell presented={selected !== null} onLayoutChange={setDrawerSlotOpen}>
          {selected && (
            <>
              <div className={browseStyles.drawerHeader}>
                <p className={browseStyles.drawerTitle}>Dataflow details</p>
                <button
                  className={browseStyles.drawerClose}
                  type="button"
                  aria-label="Close details"
                  onClick={() => setSelectedId(null)}
                >
                  ×
                </button>
              </div>

              <div className={styles.detailThumb}>
                <DataflowThumbnail
                  preview={selected.graph_preview}
                  accentColor={accent(selected.thumbnail_accent).fg}
                  bgColor={accent(selected.thumbnail_accent).bg}
                />
              </div>
              <h2 className={styles.detailName}>{selected.name}</h2>
              {selected.description && (
                <p className={styles.detailDescription}>{selected.description}</p>
              )}

              <div className={browseStyles.drawerSection}>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Nodes</span>
                  <span className={styles.detailValue}>
                    {selected.graph_preview?.nodes.length ?? 0}
                  </span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Connections</span>
                  <span className={styles.detailValue}>
                    {selected.graph_preview?.edges.length ?? 0}
                  </span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Revision</span>
                  <span className={styles.detailValue}>{selected.spec_revision}</span>
                </div>
              </div>

              <div className={browseStyles.drawerSection}>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Last opened</span>
                  <span className={styles.detailValue}>{formatDate(selected.last_opened_at)}</span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Updated</span>
                  <span className={styles.detailValue}>{formatDate(selected.updated_at)}</span>
                </div>
                <div className={styles.detailRow}>
                  <span className={styles.detailKey}>Created</span>
                  <span className={styles.detailValue}>{formatDate(selected.created_at)}</span>
                </div>
                {selected.archived_at && (
                  <div className={styles.detailRow}>
                    <span className={styles.detailKey}>Archived</span>
                    <span className={styles.detailValue}>{formatDate(selected.archived_at)}</span>
                  </div>
                )}
              </div>

              <div className={styles.detailActions}>
                <button
                  className={styles.openButton}
                  type="button"
                  onClick={() => openProject(selected.id)}
                >
                  Open dataflow
                </button>
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
              </div>
            </>
          )}
        </CatalogBrowseDrawerShell>
      </div>

      {contextMenu && (
        <div
          style={{
            position: "fixed",
            top: contextMenu.y,
            left: contextMenu.x,
            backgroundColor: "#1E1F23",
            border: "1px solid #333",
            borderRadius: "4px",
            zIndex: 9999,
            minWidth: "160px",
            boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
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
          <div style={{ ...ctxItemStyle, color: "#ff6b6b" }} onClick={() => { handleDeleteForever(contextMenu.project); setContextMenu(null); }}>
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
  color: "#fff",
  fontSize: "13px",
  cursor: "pointer",
};

const pageStyle: CSS.Properties = {
  // Bounded height, not minHeight: html/body never scroll (overflow:hidden in
  // MainCanvas.css, injected app-wide), so this page has to own its scroll
  // within the viewport or overflowing content is unreachable (#161). Same
  // shape as .pageShell in pages/catalog/CatalogMasterPage.module.css.
  height: "100vh",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
  backgroundColor: "#f0f0f0",
  fontFamily:
    "Rubik, -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif",
};

const importNotebookBtnStyle: CSS.Properties = {
  height: "34px",
  padding: "0 14px",
  backgroundColor: "#fff",
  color: "#1E1F23",
  border: "1px solid #D0D0D5",
  borderRadius: "6px",
  fontSize: "12px",
  fontWeight: 500,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const newWorkflowBtnStyle: CSS.Properties = {
  height: "34px",
  padding: "0 16px",
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
  border: "none",
  borderRadius: "6px",
  fontSize: "12px",
  fontWeight: 600,
  cursor: "pointer",
  whiteSpace: "nowrap",
};

const cardThumbnailStyle: CSS.Properties = {
  position: "absolute",
  inset: 0,
};

const cardBodyStyle: CSS.Properties = {
  position: "absolute",
  bottom: 0,
  left: 0,
  right: 0,
  padding: "28px 14px 14px",
  display: "flex",
  flexDirection: "column",
  gap: "3px",
  background: "linear-gradient(to bottom, transparent 0%, rgba(255,255,255,0.93) 35%, rgba(255,255,255,1) 65%)",
};

const cardTitleStyle: CSS.Properties = {
  fontSize: "14px",
  fontWeight: 600,
  color: "#1E1F23",
};

const cardSubStyle: CSS.Properties = {
  fontSize: "12px",
  color: "#9E9E9E",
};
