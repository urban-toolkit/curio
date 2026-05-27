import React, { useEffect, useRef, useState } from "react";
import {
    DatasetsWindow,
    PackageManagerWindow,
    TrillProvenanceWindow,
} from "components/menus";
import {
    useFlowContext,
    useNodeActionsContext,
} from "../../../providers/FlowProvider";
import { useCode } from "../../../hook/useCode";
import { TrillGenerator } from "../../../TrillGenerator";
import { trillToNotebook, serializeNotebook } from "../../../NotebookConvertor";
import styles from "./UpMenu.module.css";
import clsx from "clsx";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faCubes,
    faDatabase,
    faFileImport,
    faFileExport,
    faFolderOpen,
    faFloppyDisk,
    faPlus,
    faRobot,
    faTableColumns,
    faUpRightAndDownLeftFromCenter,
    faDownLeftAndUpRightToCenter,
    faSitemap,
    faCircleQuestion,
    faStore,
} from "@fortawesome/free-solid-svg-icons";
import logo from "assets/curio-2.png";
import { UserMenu } from "components/login/UserMenu";
import introJs from "intro.js";
import "intro.js/introjs.css";
import { useNavigate } from "react-router-dom";
import { useUserContext } from "../../../providers/UserProvider";
import { useToastContext } from "../../../providers/ToastProvider";
import { useNodeCatalogDrawer } from "../../../providers/NodeCatalogDrawerProvider";

export default function UpMenu({
    setDashBoardMode,
    setDashboardOn,
    dashboardOn,
    setAIMode,
}: {
    setDashBoardMode: (mode: boolean) => void;
    setDashboardOn: (mode: boolean) => void;
    dashboardOn: boolean;
    setAIMode: (value: boolean) => void;
}) {
    const [isEditing, setIsEditing] = useState(false);
    const [trillProvenanceOpen, setTrillProvenanceOpen] = useState(false);
    const [tutorialOpen, setTutorialOpen] = useState(false);
    const [datasetsOpen, setDatasetsOpen] = useState(false);
    const [packagesOpen, setPackagesOpen] = useState(false);
    const [activeMenu, setActiveMenu] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [aiModeOn, setAiModeOn] = useState(false);

    const menuBarRef = useRef<HTMLDivElement>(null);
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
        saveCurrentProject,
        saveAsNewProject,
        discardProject,
        viewerMode,
        packages,
        nodes,
        edges,
    } = useFlowContext();

    const isSharedView = viewerMode === "shared";
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
    const { openNodeCatalogDrawer } = useNodeCatalogDrawer();

    const toggleMenu = (menu: string) => {
        setActiveMenu((prev) => (prev === menu ? null : menu));
    };

    const closeTrillProvenanceModal = () => {
        setTrillProvenanceOpen(false);
    };

    const openTrillProvenanceModal = () => {
        setTrillProvenanceOpen(true);
        setActiveMenu(null);
    };

    const closeDatasetsModal = () => {
        setDatasetsOpen(false);
    };

    const openDatasetsModal = () => {
        setDatasetsOpen(true);
        setActiveMenu(null);
    };

    const handleNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        setWorkflowName(e.target.value);
    };

    const handleNameBlur = () => {
        setIsEditing(false);
    };

    const handleKeyPress = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            setIsEditing(false);
        }
    };

    const openTutorial = () => {
        setTutorialOpen(true);
        setActiveMenu(null);
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

    const toggleAI = () => {
        const next = !aiModeOn;
        setAiModeOn(next);
        setAIMode(next);
    };

    const handleNewWorkflow = () => {
        if (projectDirty && !window.confirm("You have unsaved changes. Continue?")) {
            return;
        }
        discardProject();
        cleanCanvas();
        setActiveMenu(null);
        navigate("/dataflow/new");
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
            packages,
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

    const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];

        if (file && file.type === "application/json") {
            const reader = new FileReader();

            reader.onload = (event: ProgressEvent<FileReader>) => {
                try {
                    const jsonContent = JSON.parse(event.target?.result as string);
                    loadTrill(jsonContent);
                } catch (err) {
                    console.error("Invalid JSON file:", err);
                } finally {
                    setActiveMenu(null);
                }
            };

            reader.onerror = (event: ProgressEvent<FileReader>) => {
                console.error("Error reading file:", event.target?.error);
                setActiveMenu(null);
            };

            reader.readAsText(file);
        } else {
            console.error("Please select a valid .json file.");
            setActiveMenu(null);
        }
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

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (
                menuBarRef.current &&
                !menuBarRef.current.contains(event.target as Node)
            ) {
                setActiveMenu(null);
            }
        };

        if (activeMenu) {
            document.addEventListener("click", handleClickOutside);
        } else {
            document.removeEventListener("click", handleClickOutside);
        }

        return () => {
            document.removeEventListener("click", handleClickOutside);
        };
    }, [activeMenu]);

    useEffect(() => {
        if (!tutorialOpen) return;

        const intro = introJs();
        intro.setOptions({
            steps: [
                {
                    intro: "Welcome to Curio, a framework for urban analytics. Let's take a quick tour to help you get started.",
                },
                {
                    element: "#step-loading",
                    intro: "This is a Data Loading Node. Here, you can create an array for basic datasets or import data from a file. Once loaded, add your code to convert the data into a DataFrame for further analysis.",
                },
                {
                    element: "#step-analysis",
                    intro: "This is a Data Analysis Node. Use it to perform calculations and operations on your dataset, preparing it for visualization.",
                },
                {
                    element: "#step-transformation",
                    intro: "The Data Transformation Node allows you to filter, segment, or restructure your data.",
                },
                {
                    element: "#step-cleaning",
                    intro: "This is a Data Cleaning Node. Use it to refine your dataset by handling missing values, removing outliers, and generating identifiers for data quality purposes.",
                },
                {
                    element: "#step-pool",
                    intro: "This is a Data Pool Node. It enables you to display your processed data in a structured grid format for easy review.",
                },
                {
                    element: "#step-utk",
                    intro: "This is an Autark Map Node. It renders your data in an interactive 3D environment using Autark (autk-map).",
                },
                {
                    element: "#step-vega",
                    intro: "This is a Vega-Lite Node. Use it to visualize data in 2D formats (bar charts, scatter plots, and line graphs) using a JSON specification.",
                },
                {
                    element: "#step-image",
                    intro: "The Image Node displays a gallery of images.",
                },
                {
                    element: "#step-merge",
                    intro: "This is a Merge Flow Node. It allows you to combine multiple data streams into a single dataset. Red handles indicate a missing connection, while green handles show that a connection has been established. Note: each handle can only connect to one edge.",
                },
                {
                    element: "#step-final",
                    intro: "That's it! Drag and drop nodes into your workspace and begin exploring your data with Curio.",
                },
            ],
            showStepNumbers: false,
            showProgress: false,
            exitOnOverlayClick: false,
            tooltipClass: "custom-intro-tooltip",
        });
        intro.start();
        setTutorialOpen(false);
    }, [tutorialOpen]);

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
            <div
                className={clsx(styles.menuBar, "nowheel", "nodrag")}
                ref={menuBarRef}
            >
                <img
                    className={styles.logo}
                    src={logo}
                    alt="Curio logo"
                    onClick={() => {
                        if (projectDirty && !window.confirm("You have unsaved changes. Leaving will lose your work.")) return;
                        navigate("/projects");
                    }}
                />

                {/* File */}
                <div className={styles.dropdownWrapper}>
                    <button
                        className={styles.button}
                        data-testid="file-menu-btn"
                        onClick={(e) => {
                            e.stopPropagation();
                            toggleMenu("file");
                        }}
                    >
                        File▾
                    </button>
                    {activeMenu === "file" && (
                        <div className={styles.dropDownMenu} onClick={(e) => e.stopPropagation()}>
                            <div className={styles.dropDownRow} onClick={handleNewWorkflow}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faPlus} />
                                <button className={styles.noStyleButton}>New dataflow</button>
                            </div>
                            <div className={styles.dropDownRow} onClick={loadTrillFile}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileImport} />
                                <button className={styles.noStyleButton}>Load dataflow</button>
                            </div>
                            {!skipProjectPage && !isSharedView && (
                                <div className={styles.dropDownRow} onClick={handleSave}>
                                    <FontAwesomeIcon className={styles.dropDownIcon} icon={faFloppyDisk} />
                                    <button className={styles.noStyleButton} disabled={saving}>
                                        {saving ? "Saving..." : "Save dataflow"}
                                    </button>
                                </div>
                            )}
                            {isSharedView && (
                                <div className={styles.dropDownRow} onClick={handleSaveCopy}>
                                    <FontAwesomeIcon className={styles.dropDownIcon} icon={faFloppyDisk} />
                                    <button className={styles.noStyleButton} disabled={saving}>
                                        {saving ? "Saving..." : "Save dataflow"}
                                    </button>
                                </div>
                            )}
                            <div className={styles.dropDownRow} onClick={handleSaveAs}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFloppyDisk} />
                                <button className={styles.noStyleButton}>Save dataflow as</button>
                            </div>
                            <div className={styles.dropDownRow} onClick={exportAsJupyterNotebook}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileExport} />
                                <button className={styles.noStyleButton}>Export as notebook</button>
                            </div>
                            {!skipProjectPage && (
                                <>
                                    <div className={styles.dropDownDivider} />
                                    <div
                                        className={styles.dropDownRow}
                                        onClick={() => {
                                            if (projectDirty && !window.confirm("You have unsaved changes. Leaving will lose your work.")) return;
                                            navigate("/projects");
                                            setActiveMenu(null);
                                        }}
                                    >
                                        <FontAwesomeIcon className={styles.dropDownIcon} icon={faFolderOpen} />
                                        <button className={styles.noStyleButton}>Go to projects</button>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                </div>

                {/* View */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu("view")}>
                        View ⏷
                    </button>
                    {activeMenu === "view" && (
                        <div className={styles.dropDownMenu}>
                            <div
                                className={styles.dropDownRow}
                                onClick={() => {
                                    setDashBoardMode(!dashboardOn);
                                    setDashboardOn(!dashboardOn);
                                    setActiveMenu(null);
                                }}
                            >
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faTableColumns} />
                                <button
                                    className={clsx(
                                        styles.noStyleButton,
                                        dashboardOn && styles.dashboardOn,
                                    )}
                                >
                                    Dashboard Mode
                                </button>
                            </div>
                            <div className={styles.dropDownRow} onClick={toggleExpand}>
                                <FontAwesomeIcon
                                    className={styles.dropDownIcon}
                                    icon={
                                        expandStatus === "expanded"
                                            ? faDownLeftAndUpRightToCenter
                                            : faUpRightAndDownLeftFromCenter
                                    }
                                />
                                <button className={styles.noStyleButton}>
                                    {expandStatus === "expanded" ? "Minimize Nodes" : "Expand Nodes"}
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Data */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu("data")}>
                        Data ⏷
                    </button>
                    {activeMenu === "data" && (
                        <div className={styles.dropDownMenu}>
                            <div
                                className={styles.dropDownRow}
                                onClick={() => {
                                    openNodeCatalogDrawer();
                                    setActiveMenu(null);
                                }}
                            >
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faStore} />
                                <button className={styles.noStyleButton}>Node Catalog</button>
                            </div>
                            <div
                                className={styles.dropDownRow}
                                onClick={() => {
                                    setPackagesOpen(true);
                                    setActiveMenu(null);
                                }}
                            >
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faCubes} />
                                <button className={styles.noStyleButton}>Installed libraries</button>
                            </div>
                            <div className={styles.dropDownRow} onClick={openDatasetsModal}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faDatabase} />
                                <button className={styles.noStyleButton}>Datasets</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Provenance */}
                <div className={styles.dropdownWrapper}>
                    <button
                        className={styles.button}
                        onClick={() => toggleMenu("provenance")}
                    >
                        Provenance ⏷
                    </button>
                    {activeMenu === "provenance" && (
                        <div className={styles.dropDownMenu}>
                            <div className={styles.dropDownRow} onClick={openTrillProvenanceModal}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faSitemap} />
                                <button className={styles.noStyleButton}>Provenance</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Help */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu("help")}>
                        Help ⏷
                    </button>
                    {activeMenu === "help" && (
                        <div className={styles.dropDownMenu}>
                            <div className={styles.dropDownRow} onClick={openTutorial}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faCircleQuestion} />
                                <button className={styles.noStyleButton}>Tutorial</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Urbanite AI toggle */}
                <button
                    className={clsx(styles.button, aiModeOn && styles.aiIconActive)}
                    onClick={toggleAI}
                    title="Urbanite AI"
                >
                    <FontAwesomeIcon icon={faRobot} />
                </button>

                {/* Save status indicator */}
                {(saving || projectDirty || projectSavedAt) && (
                    <button
                        className={clsx(styles.button, styles.saveStatus)}
                        style={{ cursor: saving ? "default" : "pointer" }}
                        disabled={saving}
                        onClick={handleSave}
                        title={
                            saving          ? "Saving…"
                            : projectDirty  ? "Unsaved changes — click to save"
                            : `Saved at ${projectSavedAt!.toLocaleTimeString()} — click to save`
                        }
                    >
                        <FontAwesomeIcon
                            icon={faFloppyDisk}
                            className={clsx(
                                saving || projectDirty ? styles.unsavedIcon : styles.savedIcon,
                                saving && styles.savingPulse,
                            )}
                        />
                    </button>
                )}

                <UserMenu />
            </div>

            {/* Editable Workflow Name */}
            <div className={styles.workflowNameContainer}>
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
            </div>

            {isSharedView && (
                <div
                    style={{
                        position: "absolute",
                        top: 60,
                        left: "50%",
                        transform: "translateX(-50%)",
                        background: "#FFF4D6",
                        color: "#7A5A00",
                        border: "1px solid #E6CD7A",
                        borderRadius: 6,
                        padding: "6px 14px",
                        fontSize: 12,
                        fontWeight: 500,
                        zIndex: 1000,
                        boxShadow: "0 2px 6px rgba(0,0,0,0.08)",
                    }}
                    data-testid="shared-view-banner"
                >
                    Viewing a shared dataflow (read-only). Use File → Save dataflow or File → Save dataflow as to make it yours.
                </div>
            )}

            <TrillProvenanceWindow
                open={trillProvenanceOpen}
                closeModal={closeTrillProvenanceModal}
                workflowName={workflowNameRef.current}
            />
            <DatasetsWindow open={datasetsOpen} closeModal={closeDatasetsModal} />
            <PackageManagerWindow
                open={packagesOpen}
                closeModal={() => setPackagesOpen(false)}
            />
        </>
    );
}
