import React, { useCallback, useEffect, useRef, useState } from "react";
import CSS from "csstype";
import { useNavigate } from "react-router-dom";
import { projectsApi, ProjectSummary } from "../../api/projectsApi";
import { notebookToTrill } from "../../NotebookConvertor";
import DataflowThumbnail from "../../components/DataflowThumbnail";
import AppSectionTabs from "../../components/layout/AppSectionTabs";
import { GlobalPageHeader } from "../../components/layout/GlobalPageHeader";
import VersionBadge from "../../components/VersionBadge";

type ViewMode = "grid" | "list";
type FilterTab = "all" | "recent" | "archived";

const ACCENT_COLORS: Record<string, { bg: string; fg: string }> = {
  peach:  { bg: "#FFE3DA", fg: "#E86A3C" },
  sky:    { bg: "#DCE8FF", fg: "#3567C7" },
  mint:   { bg: "#DFF2E1", fg: "#2F8F4A" },
  lilac:  { bg: "#EADCFB", fg: "#7A4BD1" },
};

const ProjectsList: React.FC = () => {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; project: ProjectSummary } | null>(null);
  const importNotebookRef = useRef<HTMLInputElement>(null);

  const loadProjects = useCallback(async () => {
    try {
      const scope = filter === "archived" ? "archived" : filter === "recent" ? "recent" : "mine";
      const data = await projectsApi.list({ scope, sort: "last_opened" });
      setProjects(data);
    } catch {
      setProjects([]);
    }
  }, [filter]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    const dismiss = () => setContextMenu(null);
    if (contextMenu) document.addEventListener("click", dismiss);
    return () => document.removeEventListener("click", dismiss);
  }, [contextMenu]);

  const filtered = projects.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

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
    if (!window.confirm(`Permanently delete "${project.name}"?`)) return;
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

      {/* Main Content */}
      <main style={mainStyle} data-curio-projects-scroll="true">
        <div style={mainInnerStyle}>
          <div style={headerActionsStyle}>
            <input
              type="text"
              placeholder="Search projects..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={searchInputStyle}
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

          {/* Filter Tabs + View Toggle */}
          <div style={controlsRowStyle}>
            <div style={tabsStyle}>
              {(["all", "recent", "archived"] as FilterTab[]).map((tab) => (
                <button
                  key={tab}
                  style={{
                    ...tabBtnStyle,
                    ...(filter === tab ? tabActiveStyle : {}),
                  }}
                  onClick={() => setFilter(tab)}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>
            <div style={viewToggleStyle}>
              <button
                style={{
                  ...viewBtnStyle,
                  ...(viewMode === "grid" ? viewActiveStyle : {}),
                }}
                onClick={() => setViewMode("grid")}
              >
                Grid
              </button>
              <button
                style={{
                  ...viewBtnStyle,
                  ...(viewMode === "list" ? viewActiveStyle : {}),
                }}
                onClick={() => setViewMode("list")}
              >
                List
              </button>
            </div>
          </div>

          {/* Project Cards */}
          <div style={viewMode === "grid" ? gridStyle : listGridStyle}>
            {filtered.length === 0 && (
              <p style={emptyStyle}>No projects yet. Create a new dataflow!</p>
            )}
            {filtered.map((p) => (
              <div
                key={p.id}
                style={cardStyle}
                onClick={() => navigate(`/dataflow/${p.id}`)}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setContextMenu({ x: e.clientX, y: e.clientY, project: p });
                }}
              >
                <div style={cardThumbnailStyle}>
                  <DataflowThumbnail preview={p.graph_preview} accentColor={accent(p.thumbnail_accent).fg} bgColor={accent(p.thumbnail_accent).bg} />
                </div>
                <div style={cardBodyStyle}>
                  <span style={cardTitleStyle}>{p.name}</span>
                  <span style={cardSubStyle}>
                    {p.description || `Rev ${p.spec_revision}`}
                    {p.last_opened_at ? ` · ${new Date(p.last_opened_at).toLocaleDateString()}` : ""}
                  </span>
                </div>
              </div>
            ))}
          </div>

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
      </main>
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

const searchInputStyle: CSS.Properties = {
  width: "240px",
  height: "38px",
  padding: "0 12px",
  borderRadius: "6px",
  border: "1px solid #D0D0D5",
  backgroundColor: "#fff",
  color: "#1E1F23",
  fontSize: "13px",
  outline: "none",
};

const mainStyle: CSS.Properties = {
  flex: 1,
  minHeight: 0,
  overflowY: "auto",
};

const mainInnerStyle: CSS.Properties = {
  maxWidth: "1200px",
  margin: "0 auto",
  padding: "32px 24px",
};

const headerActionsStyle: CSS.Properties = {
  // Actions only — the active tab in AppSectionTabs names the page now, so
  // this row no longer has a title to sit opposite.
  display: "flex",
  justifyContent: "flex-end",
  alignItems: "center",
  gap: "12px",
  marginBottom: "24px",
};

const importNotebookBtnStyle: CSS.Properties = {
  height: "38px",
  padding: "0 16px",
  backgroundColor: "#fff",
  color: "#1E1F23",
  border: "1px solid #D0D0D5",
  borderRadius: "6px",
  fontSize: "14px",
  fontWeight: 500,
  cursor: "pointer",
};

const newWorkflowBtnStyle: CSS.Properties = {
  height: "38px",
  padding: "0 20px",
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
  border: "none",
  borderRadius: "6px",
  fontSize: "14px",
  fontWeight: 600,
  cursor: "pointer",
};

const controlsRowStyle: CSS.Properties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  marginBottom: "20px",
};

const tabsStyle: CSS.Properties = { display: "flex", gap: "4px" };
const tabBtnStyle: CSS.Properties = {
  padding: "6px 14px",
  border: "none",
  background: "none",
  fontSize: "13px",
  fontWeight: 500,
  cursor: "pointer",
  borderRadius: "4px",
  color: "#6B6B76",
};
const tabActiveStyle: CSS.Properties = {
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
};

const viewToggleStyle: CSS.Properties = { display: "flex", gap: "4px" };
const viewBtnStyle: CSS.Properties = {
  padding: "6px 12px",
  border: "1px solid #D0D0D5",
  background: "#fff",
  fontSize: "12px",
  borderRadius: "4px",
  cursor: "pointer",
  color: "#6B6B76",
};
const viewActiveStyle: CSS.Properties = {
  backgroundColor: "#1E1F23",
  color: "#fbfcf6",
  borderColor: "#1E1F23",
};

const gridStyle: CSS.Properties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
  gap: "16px",
};

const listGridStyle: CSS.Properties = {
  display: "flex",
  flexDirection: "column",
  gap: "8px",
};

const cardStyle: CSS.Properties = {
  position: "relative",
  height: "180px",
  borderRadius: "8px",
  overflow: "hidden",
  cursor: "pointer",
  border: "1px solid #E5E5E7",
  transition: "box-shadow 0.15s",
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

const emptyStyle: CSS.Properties = {
  color: "#9E9E9E",
  fontSize: "14px",
  gridColumn: "1 / -1",
  textAlign: "center",
  padding: "40px 0",
};
