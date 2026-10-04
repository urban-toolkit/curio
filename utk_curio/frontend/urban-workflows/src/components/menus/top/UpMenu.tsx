import React, { useCallback, useRef, useState } from "react";
import {
    LibraryManagerWindow,
    TrillProvenanceWindow,
} from "components/menus";
import {
    useFlowContext,
    useNodeActionsContext,
} from "../../../providers/FlowProvider";
import { useCode } from "../../../hook/useCode";
import { useEnsureWorkflowDeps } from "../../../providers/packages/useEnsureWorkflowDeps";
import { useCollab } from "../../../providers/CollaborationProvider";
import { TrillGenerator } from "../../../TrillGenerator";
import { trillToNotebook, serializeNotebook } from "../../../NotebookConvertor";
import styles from "./UpMenu.module.css";
import headerStyles from "../../layout/GlobalPageHeader.module.css";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faCircleCheck,
    faClone,
    faCodeBranch,
    faCubes,
    faListUl,
    faObjectGroup,
    faFileArrowDown,
    faFileImport,
    faFileExport,
    faFolderOpen,
    faFloppyDisk,
    faPlus,
    faUsers,
    faUpRightAndDownLeftFromCenter,
    faDownLeftAndUpRightToCenter,
} from "@fortawesome/free-solid-svg-icons";
import { GlobalPageHeader } from "../../layout/GlobalPageHeader";
import { HeaderMenu, HeaderMenuDivider, HeaderMenuItem } from "./HeaderMenu";
import { CatalogButtons } from "./CatalogButtons";
import { useNavigate, useParams } from "react-router-dom";
import { useUserContext } from "../../../providers/UserProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import { getCurrentProjectPackagesList } from "../../../registry/projectPackagesStore";
import {
    looksLikeJsonFile,
    parseDataflowFile,
    loadFailedMessage,
    NOT_JSON_FILE_MESSAGE,
    UNREADABLE_FILE_MESSAGE,
} from "../../../utils/dataflowImport";
import { LEAVE_DATAFLOW, useLeaveGuard } from "../../../hook/useLeaveGuard";
import ShareMenu from "./ShareMenu";
import DataflowCategoryInput from "../../projects/DataflowCategoryInput";
import { projectsApi, type ProjectSummary } from "../../../api/projectsApi";
import { SHARE_UUID_RE } from "../../../utils/shareLinks";
import { useScenarioActions } from "../../scenarios/useScenarioActions";
import { useScenarioUi } from "../../scenarios/scenarioUi";

export default function UpMenu() {
    const [isEditing, setIsEditing] = useState(false);
    const [trillProvenanceOpen, setTrillProvenanceOpen] = useState(false);
    const [librariesOpen, setLibrariesOpen] = useState(false);
    const [activeMenu, setActiveMenu] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);

    const loadTrillInputRef = useRef<HTMLInputElement>(null);
    const navigate = useNavigate();
    const { skipProjectPage } = useUserContext();
    const {
        workflowNameRef,
        projectId,
        projectName,
        projectDirty,
        projectSavedAt,
        cleanCanvas,
        markDirty,
        renameDataflow,
        workflowCategories,
        serverCategories,
        scenarios,
        updateDataflowCategories,
        saveCurrentProject,
        saveAsNewProject,
        discardProject,
        viewerMode,
        packages,
        nodes,
        edges,
    } = useFlowContext();

    /** Run *action* now, or ask first when there is unsaved work to lose.
     *  The same guard every other way out of a dataflow uses (#197). */
    const { leave: guardLeave, dialog: leaveDialog } = useLeaveGuard(projectDirty, LEAVE_DATAFLOW);
    const leaveWithGuard = (body: string, action: () => void) => guardLeave(action, body);

    const collab = useCollab();
    // Mirror the ``isSharedView`` gate in MainCanvas: when collab is on,
    // peers loaded via the shared endpoint are full editors (their edits
    // sync over the socket to the owner), so the read-only banner /
    // gating must stand down.
    const isSharedView = viewerMode === "shared" && !collab.enabled;
    const {
        workflowName,
        setWorkflowName,
        setAllMinimized,
        allMinimized,
        expandStatus,
        setExpandStatus,
    } = useNodeActionsContext();
    const { loadTrill } = useCode();
    const { showToast } = useToastContext();
    // The id the Share links are built from. A shared viewer has no
    // ``projectId`` (the dataflow is not open for editing in their workspace),
    // so fall back to the one in the URL, which is the project they are looking
    // at either way.
    const { id: routeId } = useParams<{ id?: string }>();
    const shareId = projectId ?? (routeId && SHARE_UUID_RE.test(routeId) ? routeId : null);
    const ensureWorkflowDeps = useEnsureWorkflowDeps();

    const toggleMenu = (menu: string) => {
        setActiveMenu((prev) => (prev === menu ? null : menu));
    };

    // Each menu closes itself on an outside click or Escape. A click on
    // another menu's trigger is outside this one, so close only if this is
    // still the open menu, or it would shut the one just opened.
    const closeMenu = useCallback((menu: string) => {
        setActiveMenu((prev) => (prev === menu ? null : prev));
    }, []);
    const closeFile = useCallback(() => closeMenu("file"), [closeMenu]);
    const closeView = useCallback(() => closeMenu("view"), [closeMenu]);
    const closeShare = useCallback(() => closeMenu("share"), [closeMenu]);

    // #662: named selections of the dataflow, compared in the canvas.
    const scenarioActions = useScenarioActions();
    const scenarioUi = useScenarioUi();
    const scenarioItem = (action: () => void) => () => {
        setActiveMenu(null);
        action();
    };

    // The account's other dataflows, for the category suggestions. Fetched the
    // first time "+ Category" opens, not on every canvas load.
    const [categorySuggestions, setCategorySuggestions] = useState<ProjectSummary[]>([]);
    const suggestionsRequested = useRef(false);
    const loadCategorySuggestions = () => {
        if (suggestionsRequested.current) return;
        suggestionsRequested.current = true;
        projectsApi.list().then(setCategorySuggestions).catch(() => {});
    };

    const closeTrillProvenanceModal = () => {
        setTrillProvenanceOpen(false);
    };

    const openTrillProvenanceModal = () => {
        setTrillProvenanceOpen(true);
        setActiveMenu(null);
    };

    const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setWorkflowName(e.target.value);
    };

    // Commit through ``renameDataflow`` so the project row's name - what the
    // Projects list and the details drawer render - moves with the canvas title
    // (#230). Committing used to only close the editor, which left the rename
    // living in ``workflowName`` alone. ``handleNameChange`` is untouched, so
    // typing still updates the visible title live.
    const commitName = () => {
        if (!renameDataflow(workflowName)) {
            // A blank entry is not a rename. Put the dataflow's own name back
            // rather than leaving the title empty.
            setWorkflowName(projectName || workflowNameRef.current || "Untitled dataflow");
        }
        setIsEditing(false);
    };

    const handleNameBlur = () => {
        commitName();
    };

    const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            commitName();
        }
    };

    const toggleExpand = () => {
        if (expandStatus === "expanded") {
            setExpandStatus("minimized");
            setAllMinimized(allMinimized + 1);
        } else {
            setExpandStatus("expanded");
            setAllMinimized(0);
        }
        setActiveMenu(null);
    };

    const handleNewWorkflow = () => {
        leaveWithGuard(
            "Starting a new dataflow discards the changes you have not saved.",
            () => {
                discardProject();
                cleanCanvas();
                setActiveMenu(null);
                navigate("/dataflow/new");
            },
        );
    };

    const handleSave = async () => {
        setSaving(true);
        const wasNew = !projectId;
        try {
            const detail = await saveCurrentProject();
            // First save of a brand-new dataflow: promote the placeholder
            // ``/dataflow/new`` URL to the canonical, shareable one. We use
            // replace so the user's back button still works as expected.
            if (wasNew && detail?.id) {
                navigate(`/dataflow/${detail.id}`, { replace: true });
            }
        } catch (err: any) {
            console.error("Save failed:", err);
            showToast(err?.message || "Save failed", "error");
            setSaving(false);
            return;
        }
        setSaving(false);
        setActiveMenu(null);
    };

    const handleSaveCopy = async () => {
        const sourceName = projectName || workflowNameRef.current || "Untitled";
        setSaving(true);
        try {
            const detail = await saveAsNewProject(`${sourceName} (copy)`);
            showToast("Saved a copy to your workspace", "info");
            navigate(`/dataflow/${detail.id}`);
        } catch (err: any) {
            console.error("Save a copy failed:", err);
            showToast(err?.message || "Save a copy failed", "error");
        } finally {
            setSaving(false);
            setActiveMenu(null);
        }
    };

    const handleSaveAs = () => {
        const trillSpec = TrillGenerator.generateTrill(
            nodes,
            edges,
            workflowNameRef.current,
            "",
            getCurrentProjectPackagesList(),
            undefined,
            undefined,
            workflowCategories,
            // A downloaded file carries scenarios only when there are some.
            scenarios && scenarios.length > 0 ? scenarios : undefined,
        );
        const content = JSON.stringify(trillSpec, null, 2);
        const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `${workflowNameRef.current}.json`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setActiveMenu(null);
    };

    // Every failure here used to be a console.error, so picking a malformed file
    // left the canvas unchanged with nothing on screen to say why (#238). The
    // three failures are told apart deliberately: reporting a wrong-shaped
    // dataflow as "invalid JSON" sends people hunting for a syntax error that
    // is not there.
    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];

        if (!file) {
            setActiveMenu(null);
            return;
        }

        if (!looksLikeJsonFile(file)) {
            showToast(NOT_JSON_FILE_MESSAGE, "error");
            setActiveMenu(null);
            return;
        }

        const reader = new FileReader();

        reader.onload = (event: ProgressEvent<FileReader>) => {
            try {
                const parsed = parseDataflowFile(event.target?.result as string);
                if (!parsed.ok) {
                    showToast(parsed.message, "error");
                    return;
                }
                try {
                    loadTrill(parsed.spec);
                } catch (err) {
                    // A spec can carry the right shape and still throw while it
                    // is replayed, on a node type this build does not know.
                    console.error("Failed to load dataflow:", err);
                    showToast(loadFailedMessage(err), "error");
                    return;
                }
                // Importing REPLACES the canvas, so it does diverge from what
                // is on disk. The edge replay inside loadParsedTrill no longer
                // says so on its own (#229) - and never did for an edgeless
                // import - so say it here, where the intent is known.
                markDirty();
                // Importing a workflow file is a deliberate user action, so
                // warn + auto-install its Python deps the same way opening
                // your own project does.
                ensureWorkflowDeps(parsed.spec);
            } finally {
                setActiveMenu(null);
            }
        };

        reader.onerror = (event: ProgressEvent<FileReader>) => {
            console.error("Error reading file:", event.target?.error);
            showToast(UNREADABLE_FILE_MESSAGE, "error");
            setActiveMenu(null);
        };

        reader.readAsText(file);
    };

    const exportAsJupyterNotebook = () => {
        const trillSpec = TrillGenerator.generateTrill(
            nodes,
            edges,
            workflowNameRef.current,
            "",
            packages,
        );
        const notebook = trillToNotebook(trillSpec);
        const content = serializeNotebook(notebook);
        const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
        const link = document.createElement("a");
        link.href = url;
        link.download = `${workflowNameRef.current}.ipynb`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        setActiveMenu(null);
    };

    const loadTrillFile = () => {
        setActiveMenu(null);
        // Defer the click so the input is not unmounted before the dialog opens
        setTimeout(() => loadTrillInputRef.current?.click(), 0);
    };

    return (
        <>
            <input
                type="file"
                accept=".json"
                ref={loadTrillInputRef}
                style={{ display: "none" }}
                onChange={handleFileUpload}
                onClick={(e) => {
                    (e.target as HTMLInputElement).value = "";
                }}
            />
            {/* The same bar as every other page, with the dataflow's own
                controls in its slot. */}
            <GlobalPageHeader
                className={clsx(styles.canvasHeader, "nowheel", "nodrag")}
                onLeave={(go) =>
                    leaveWithGuard("Leaving this dataflow discards the changes you have not saved.", go)
                }
            >
                <HeaderMenu
                    label="File"
                    testId="file-menu-btn"
                    open={activeMenu === "file"}
                    onToggle={() => toggleMenu("file")}
                    onClose={closeFile}
                >
                    <HeaderMenuItem icon={faPlus} onClick={handleNewWorkflow}>
                        New dataflow
                    </HeaderMenuItem>
                    <HeaderMenuItem icon={faFileImport} onClick={loadTrillFile}>
                        Load dataflow
                    </HeaderMenuItem>
                    <HeaderMenuDivider />
                    {!skipProjectPage && !isSharedView && (
                        <HeaderMenuItem icon={faFloppyDisk} onClick={handleSave} disabled={saving}>
                            {saving ? "Saving..." : "Save dataflow"}
                        </HeaderMenuItem>
                    )}
                    {isSharedView && (
                        <HeaderMenuItem icon={faFloppyDisk} onClick={handleSaveCopy} disabled={saving}>
                            {saving ? "Saving..." : "Save dataflow"}
                        </HeaderMenuItem>
                    )}
                    <HeaderMenuItem icon={faFileArrowDown} onClick={handleSaveAs}>
                        Save dataflow as
                    </HeaderMenuItem>
                    <HeaderMenuItem icon={faFileExport} onClick={exportAsJupyterNotebook}>
                        Export as notebook
                    </HeaderMenuItem>
                    {!isSharedView && (
                        <HeaderMenuItem
                            icon={faCodeBranch}
                            onClick={scenarioItem(scenarioActions.saveDataflowAsScenario)}
                        >
                            Save dataflow as scenario
                        </HeaderMenuItem>
                    )}
                    <HeaderMenuDivider />
                    {/* The Python environment the nodes run in. Not a
                        catalog, so not among the catalog buttons. */}
                    <HeaderMenuItem
                        icon={faCubes}
                        onClick={() => {
                            setLibrariesOpen(true);
                            setActiveMenu(null);
                        }}
                    >
                        Installed libraries
                    </HeaderMenuItem>
                    {!skipProjectPage && (
                        <>
                            <HeaderMenuDivider />
                            <HeaderMenuItem
                                icon={faFolderOpen}
                                onClick={() => {
                                    leaveWithGuard(
                                        "Leaving this dataflow discards the changes you have not saved.",
                                        () => {
                                            navigate("/projects");
                                            setActiveMenu(null);
                                        },
                                    );
                                }}
                            >
                                Go to projects
                            </HeaderMenuItem>
                        </>
                    )}
                </HeaderMenu>

                <HeaderMenu
                    label="View"
                    open={activeMenu === "view"}
                    onToggle={() => toggleMenu("view")}
                    onClose={closeView}
                >
                    <HeaderMenuItem
                        icon={
                            expandStatus === "expanded"
                                ? faDownLeftAndUpRightToCenter
                                : faUpRightAndDownLeftFromCenter
                        }
                        onClick={toggleExpand}
                    >
                        {expandStatus === "expanded" ? "Minimize Nodes" : "Expand Nodes"}
                    </HeaderMenuItem>
                    {/* Scenarios (#662): save a selection as one, duplicate it
                        as another, and the panel that lists them. Here rather
                        than a menu of their own: the bar has no room for one
                        beside every catalog's label. An edit, so not for a
                        shared viewer. */}
                    {!isSharedView && (
                        <>
                            <HeaderMenuDivider />
                            <HeaderMenuItem
                                icon={faObjectGroup}
                                onClick={scenarioItem(scenarioActions.saveSelectionAsScenario)}
                            >
                                Save selection as scenario
                            </HeaderMenuItem>
                            <HeaderMenuItem
                                icon={faClone}
                                onClick={scenarioItem(() => scenarioActions.duplicate(false))}
                            >
                                Duplicate selection
                            </HeaderMenuItem>
                            <HeaderMenuItem
                                icon={faCodeBranch}
                                onClick={scenarioItem(() => scenarioActions.duplicate(true))}
                            >
                                Duplicate as scenario
                            </HeaderMenuItem>
                            <HeaderMenuItem
                                icon={faListUl}
                                onClick={scenarioItem(() => scenarioUi.setPanelOpen(!scenarioUi.panelOpen))}
                            >
                                {scenarioUi.panelOpen ? "Hide scenarios" : "Show scenarios"}
                            </HeaderMenuItem>
                        </>
                    )}
                </HeaderMenu>

                {/* One window, so a button rather than a menu: its menu held
                    a single row with its own name. */}
                <button
                    type="button"
                    className={headerStyles.barButton}
                    data-testid="provenance-btn"
                    onClick={openTrillProvenanceModal}
                >
                    Provenance
                </button>

                {/* Share: the dataflow's dashboard, and a link to either. Shown
                    to a shared viewer too - passing a link on is not an edit. */}
                <ShareMenu
                    id={shareId}
                    includeOpenDashboard
                    open={activeMenu === "share"}
                    onToggle={() => toggleMenu("share")}
                    onClose={closeShare}
                    projectDirty={projectDirty}
                />

                {/* Real-time collaboration side panel toggle. Only rendered
                    when --collab is on; the badge surfaces the live peer
                    count so presence stays glanceable even with the panel
                    closed. */}
                {collab.enabled && (
                    <button
                        type="button"
                        className={clsx(headerStyles.barButton, collab.panelOpen && headerStyles.barButtonActive)}
                        aria-label="Collaboration"
                        aria-pressed={collab.panelOpen}
                        onClick={() => collab.setPanelOpen(!collab.panelOpen)}
                        title={
                            collab.connected
                                ? `Collaboration (${collab.users.length} online)`
                                : "Collaboration disconnected"
                        }
                    >
                        <FontAwesomeIcon icon={faUsers} />
                        {collab.users.length > 1 && (
                            <span className={styles.peerCount}>{collab.users.length}</span>
                        )}
                    </button>
                )}

                {/* Save status indicator.
                    Always present on a dataflow you own, so its absence never
                    has to be interpreted. It used to render only once the
                    dataflow was dirty or had been saved at least once, which
                    meant a brand-new dataflow showed nothing at all - the one
                    moment the state is most worth stating, because nothing is
                    on disk yet. A never-saved dataflow reads as unsaved, the
                    same as a dirty one; "Saved" means, and only means, "what
                    you see is on disk". The word says it as well as the
                    colour, so the state does not rest on telling two hues
                    apart. Hidden for a shared viewer, who has nothing to save. */}
                {!isSharedView && (
                    <button
                        type="button"
                        className={clsx(headerStyles.barButton, styles.saveStatus)}
                        disabled={saving}
                        onClick={handleSave}
                        title={
                            saving          ? "Saving…"
                            : projectDirty  ? "Unsaved changes - click to save"
                            : !projectSavedAt ? "Not saved yet - click to save"
                            : `Saved at ${projectSavedAt.toLocaleTimeString()} - click to save`
                        }
                        data-curio-save-state={
                            saving ? "saving"
                            : projectDirty || !projectSavedAt ? "unsaved"
                            : "saved"
                        }
                    >
                        <FontAwesomeIcon
                            icon={saving || projectDirty || !projectSavedAt ? faFloppyDisk : faCircleCheck}
                            className={clsx(
                                saving || projectDirty || !projectSavedAt
                                    ? styles.unsavedIcon
                                    : styles.savedIcon,
                                saving && styles.savingPulse,
                            )}
                        />
                        <span>
                            {saving ? "Saving..." : projectDirty || !projectSavedAt ? "Unsaved" : "Saved"}
                        </span>
                    </button>
                )}

                <span className={headerStyles.divider} aria-hidden="true" />
                <CatalogButtons projectId={projectId} crowded={collab.enabled} />
            </GlobalPageHeader>

            {/* Editable Workflow Name */}
            <div className={styles.workflowNameContainer} data-curio-canvas-title="true">
                {isEditing && !isSharedView ? (
                    <input
                        type="text"
                        value={workflowName}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyPress={handleKeyPress}
                        autoFocus
                        className={styles.input}
                    />
                ) : (
                    <h1
                        className={styles.workflowNameStyle}
                        onClick={() => { if (!isSharedView) setIsEditing(true); }}
                    >
                        {workflowName}
                    </h1>
                )}
                {/* The dataflow's categories. The automatic ones come from the
                    last load or save; the hand-set ones save with the dataflow. */}
                <DataflowCategoryInput
                    className={styles.workflowCategories}
                    categories={serverCategories ?? {}}
                    hand={workflowCategories ?? {}}
                    onChange={isSharedView ? undefined : updateDataflowCategories}
                    suggestionItems={categorySuggestions}
                    onOpenAdd={loadCategorySuggestions}
                    maxVisible={6}
                />
            </div>

            {/* "Save dataflow as" is not named here: it downloads a file, which
                does not make the dataflow yours. */}
            {isSharedView && (
                <div className={styles.sharedBanner} data-testid="shared-view-banner">
                    Viewing a shared dataflow (read-only). Use File → Save dataflow to keep a copy in your projects.
                </div>
            )}

            <TrillProvenanceWindow
                open={trillProvenanceOpen}
                closeModal={closeTrillProvenanceModal}
                workflowName={workflowNameRef.current}
            />
            <LibraryManagerWindow
                open={librariesOpen}
                closeModal={() => setLibrariesOpen(false)}
            />
            {leaveDialog}
        </>
    );
}
