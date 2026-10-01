import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { permanentDeletionNotice } from "../../services/retentionCopy";
import { CardContextMenu } from "../../components/catalog/CardContextMenu";
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
import DataflowCategoriesDialog from "../../components/projects/DataflowCategoriesDialog";
import { UNREADABLE_FILE_MESSAGE } from "../../utils/dataflowImport";
import { backendUrl } from "../../utils/backendUrl";
import { countLabel } from "../../utils/countLabel";
import {
  FACET_SECTIONS,
  OWNER_YOURS,
  SOURCE_LABELS,
  allCategoryValues,
  facetEntries,
  facetValues,
  matchesSelection,
  type FacetKey,
  type FacetSelection,
  type HandCategories,
} from "../../utils/dataflowCategories";

type ViewMode = "grid" | "list";
/** Mirrors the sorts projectsApi and `list_for_user` already implement. */
type ProjectSort = "last_opened" | "name" | "created";

const SORT_OPTIONS: { value: ProjectSort; label: string }[] = [
  { value: "last_opened", label: "Sort: Recent activity" },
  { value: "name", label: "Sort: Name" },
  { value: "created", label: "Sort: Created" },
];

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

/** The filter bar's quick chips: the source entries, as the Data Catalog's
 *  chip row mirrors its rail. */
const QUICK_SOURCES: { key: FacetKey; value: string; label: string }[] = [
  { key: "source", value: SOURCE_LABELS.use_case, label: SOURCE_LABELS.use_case },
  { key: "source", value: SOURCE_LABELS.example, label: SOURCE_LABELS.example },
  { key: "source", value: SOURCE_LABELS.test, label: SOURCE_LABELS.test },
  { key: "owner", value: OWNER_YOURS, label: "Yours" },
];

/** What a card shows: where it came from and what it is about. */
function cardChips(project: ProjectSummary): string[] {
  return [
    ...facetValues(project.categories, "source"),
    ...facetValues(project.categories, "topic"),
  ];
}

/** A drawer info row per category section, omitted when the section is empty. */
function categoryInfoRows(project: ProjectSummary) {
  const rows: { label: string; value: string }[] = [];
  const source = facetValues(project.categories, "source");
  rows.push({ label: "Source", value: source[0] ?? "Your dataflow" });
  for (const { key, label } of FACET_SECTIONS) {
    if (key === "source" || key === "tags") continue;
    const values = facetValues(project.categories, key);
    if (values.length) rows.push({ label, value: values.join(", ") });
  }
  return rows;
}

const ProjectsList: React.FC = () => {
  const navigate = useNavigate();
  const { showToast } = useToastContext();
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [viewMode, setViewMode] = useState<ViewMode>("grid");
  const [sort, setSort] = useState<ProjectSort>("last_opened");
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
  const [deleteTarget, setDeleteTarget] = useState<ProjectSummary | null>(null);
  const [categoriesTarget, setCategoriesTarget] = useState<ProjectSummary | null>(null);
  // One entry per rail section; sections combine. Empty is "All dataflows".
  const [selection, setSelection] = useState<FacetSelection>({});
  // The project an action is currently running against. A delete can take a
  // while, and the buttons were re-clickable throughout.
  const [busyId, setBusyId] = useState<string | null>(null);
  const importNotebookRef = useRef<HTMLInputElement>(null);

  // One request. There used to be a "Recent" tab fetched alongside this one,
  // but it returned the same projects in the same order — its only filter was
  // on ``archived_at``, which no scope varied and #261 removed (#286).
  const loadProjects = useCallback(async () => {
    const rows = await projectsApi
      .list({ sort })
      .catch(() => [] as ProjectSummary[]);
    setProjects(rows);
  }, [sort]);

  useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // What the search box leaves; the rail counts and filters within it.
  const searched = useMemo(() => {
    // Trim first, the same normalization the catalog predicates this page's chrome
    // mirrors already do (packageUtils.matchesSearch, agentListUtils.matchesAgentSearch)
    // - so a name pasted with a trailing space still matches (#231). No empty-query
    // short-circuit: `"anything".includes("")` is already true, and keeping the
    // `.filter()` keeps `filtered` a fresh array every render, which is what the
    // tri-state auto-select effect below is written against. A category matches
    // too, so "Autark" finds every dataflow with an Autark node.
    const needle = search.trim().toLowerCase();
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        allCategoryValues(p.categories).some((v) => v.toLowerCase().includes(needle)),
    );
  }, [projects, search]);

  const filtered = useMemo(
    () => searched.filter((p) => matchesSelection(p, selection)),
    [searched, selection],
  );

  const toggleFacet = (key: FacetKey, value: string) =>
    setSelection((prev) => {
      const next = { ...prev };
      if (next[key] === value) delete next[key];
      else next[key] = value;
      return next;
    });

  // "All dataflows" clears every section, so its count is everything searched.
  const allCount = searched.length;
  const yoursCount = useMemo(
    () => facetEntries(searched, "owner", selection)[0]?.count ?? 0,
    [searched, selection],
  );
  const railSections = useMemo(
    () =>
      FACET_SECTIONS.map((section) => ({
        ...section,
        entries: facetEntries(searched, section.key, selection),
      })).filter((section) => section.entries.length > 0),
    [searched, selection],
  );
  const filtering = Object.keys(selection).length > 0;

  // Mirrors the catalog browse pages: the first item is selected so the detail
  // drawer arrives populated instead of empty.
  //
  // `null` is honoured as a decision, not treated as "unset". Before, Close set
  // `null` and this effect read it as falsy and re-selected `filtered[0]`; only
  // the dependency array delayed it, so the drawer stayed shut until the next
  // search keystroke, filter click, sort change or post-mutation refetch - and
  // after a rename or a delete it came back on a *different* project than the
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

  const performCategories = async (project: ProjectSummary, hand: HandCategories) => {
    setBusyId(project.id);
    try {
      await projectsApi.update(project.id, { categories: hand });
      loadProjects();
    } catch (err) {
      showToast((err as Error)?.message || "Couldn't save those categories.", "error");
    } finally {
      setBusyId(null);
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

  const performDelete = async (project: ProjectSummary) => {
    setBusyId(project.id);
    try {
      await projectsApi.delete(project.id);
      loadProjects();
      showToast(`Deleted "${project.name}".`, "success");
    } catch (err) {
      showToast((err as Error)?.message || "Couldn't delete that dataflow.", "error");
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = (project: ProjectSummary) => setDeleteTarget(project);

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
      case "categories":
        setCategoriesTarget(project);
        return;
      case "duplicate":
        void handleDuplicate(project);
        return;
      case "delete":
        handleDelete(project);
        return;
    }
  };

  // Same silence as the canvas's "Load dataflow" had (#238): a notebook that
  // would not parse produced a console line and a projects list that simply did
  // not grow, which reads as the click having missed.
  const handleNotebookImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async (event: ProgressEvent<FileReader>) => {
      let json: Record<string, unknown>;
      try {
        json = JSON.parse(event.target?.result as string) as Record<string, unknown>;
      } catch (err) {
        const detail = err instanceof Error ? err.message : String(err);
        console.error("Failed to import Jupyter notebook:", err);
        showToast(
          `That file is not valid JSON, so it could not be imported (${detail}).`,
          "error",
        );
        return;
      }
      try {
        const trillSpec = await notebookToTrill(json, backendUrl());
        const name = file.name.replace(/\.ipynb$/i, "");
        await projectsApi.create({ name, spec: trillSpec as unknown as Record<string, unknown>, outputs: [] });
        loadProjects();
      } catch (err) {
        // Was console-only: picking a file and getting no response at all
        // reads as a broken button, and a malformed .ipynb is the common case.
        console.error("Failed to import Jupyter notebook:", err);
        showToast(
          (err as Error)?.message ||
            "That notebook could not be converted into a dataflow.",
          "error",
        );
      }
    };
    reader.onerror = (event: ProgressEvent<FileReader>) => {
      console.error("Error reading notebook file:", event.target?.error);
      showToast(UNREADABLE_FILE_MESSAGE, "error");
    };
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
        {/* The catalogs' rail, with the sections the owner chose. Its source,
            tags and data types are computed by the server; city, topic and
            complexity are what each dataflow says it is. */}
        <aside className={browseStyles.categoryRail} aria-label="Filter dataflows">
          <div className={styles.railTop} />
          <button
            className={joined(browseStyles.railButton, !filtering && browseStyles.railButtonActive)}
            type="button"
            onClick={() => setSelection({})}
          >
            <span>All dataflows</span>
            <span className={browseStyles.railCountBadge}>{allCount}</span>
          </button>
          <button
            className={joined(
              browseStyles.railButton,
              selection.owner === OWNER_YOURS && browseStyles.railButtonActive,
            )}
            type="button"
            onClick={() => toggleFacet("owner", OWNER_YOURS)}
          >
            <span>Your dataflows</span>
            <span className={browseStyles.railCount}>{yoursCount}</span>
          </button>
          {railSections.map((section) => (
            <React.Fragment key={section.key}>
              <div className={browseStyles.railDivider} />
              <p className={browseStyles.railLabel}>{section.label}</p>
              {section.entries.map((entry) => (
                <button
                  key={entry.value}
                  className={joined(
                    browseStyles.railButton,
                    selection[section.key] === entry.value && browseStyles.railButtonActive,
                  )}
                  type="button"
                  onClick={() => toggleFacet(section.key, entry.value)}
                >
                  <span>{entry.value}</span>
                  <span className={browseStyles.railCount}>{entry.count}</span>
                </button>
              ))}
            </React.Fragment>
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
            <button
              className={joined(browseStyles.chip, !filtering && browseStyles.chipActive)}
              type="button"
              onClick={() => setSelection({})}
            >
              All
            </button>
            {QUICK_SOURCES.map((chip) => (
              <button
                key={chip.label}
                className={joined(
                  browseStyles.chip,
                  selection[chip.key] === chip.value && browseStyles.chipActive,
                )}
                type="button"
                onClick={() => toggleFacet(chip.key, chip.value)}
              >
                {chip.label}
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
              {/* `search.trim()`, matching the needle above: a whitespace-only box
                  is not a filter, so an empty account must not be told its
                  projects were filtered out (#231). */}
              {filtering && projects.length > 0
                ? "No dataflows match the current filters."
                : search.trim()
                  ? "No projects match that search."
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
                      {cardChips(p).length > 0 ? (
                        <span className={styles.cardTags}>
                          {cardChips(p).map((value) => (
                            <span key={value} className={browseStyles.tag} data-curio-tag-chip="true">
                              {value}
                            </span>
                          ))}
                        </span>
                      ) : null}
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
                <span className={browseStyles.drawerCategoryBadge}>
                  Rev {selected.spec_revision}
                </span>
              }
              subtitle={selected.slug}
              metaLeft={
                countLabel(nodeCount(selected), "node") +
                " · " +
                countLabel(edgeCount(selected), "connection")
              }
              metaRight={catalogRelativeTime(selected.updated_at)}
              fresh={catalogIsFresh(selected.updated_at)}
              description={selected.description}
              infoLabel="Dataflow info"
              infoRows={[
                ...categoryInfoRows(selected),
                { label: "Revision", value: selected.spec_revision },
                { label: "Last opened", value: catalogRelativeTime(selected.last_opened_at) },
                { label: "Updated", value: formatDate(selected.updated_at) },
                { label: "Created", value: formatDate(selected.created_at) },
              ]}
              tags={facetValues(selected.categories, "tags")}
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
                  {projectActions({ isExample: selected.is_example })
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
        /* The same list the detail drawer renders. Both used to hardcode their
           own, and disagreed about what a project allowed (#221). The menu
           itself is shared with the three catalog grids, which had no menu at
           all until #285. */
        <CardContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          ariaLabel="Dataflow actions"
          items={projectActions({ isExample: contextMenu.project.is_example })}
          onSelect={(id) =>
            runProjectAction(id as ProjectActionId, contextMenu.project)
          }
          onDismiss={() => setContextMenu(null)}
        />
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

      {categoriesTarget ? (
        <DataflowCategoriesDialog
          dataflowName={categoriesTarget.name}
          categories={categoriesTarget.categories}
          suggestionItems={projects}
          busy={busyId === categoriesTarget.id}
          onCancel={() => setCategoriesTarget(null)}
          onConfirm={(hand) => {
            const project = categoriesTarget;
            setCategoriesTarget(null);
            void performCategories(project, hand);
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
          confirmLabel="Delete"
          destructive
          onCancel={() => setDeleteTarget(null)}
          onConfirm={() => {
            const project = deleteTarget;
            setDeleteTarget(null);
            void performDelete(project);
          }}
        />
      ) : null}

      <VersionBadge />
    </div>
  );
};

export default ProjectsList;
