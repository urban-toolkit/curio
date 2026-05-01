import React, { useState, useRef, useEffect } from "react";
import { TrillProvenanceWindow, DatasetsWindow, PackageManagerWindow } from "components/menus";
import { useNodeActionsContext, useFlowContext } from "../../../providers/FlowProvider";
import { useReactFlow } from "reactflow";
import { useCode } from "../../../hook/useCode";
import { TrillGenerator } from "../../../TrillGenerator";
import styles from "./UpMenu.module.css";
import clsx from 'clsx';
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faDatabase, faFileImport, faFileExport, faRobot,
    faTableColumns, faUpRightAndDownLeftFromCenter, faDownLeftAndUpRightToCenter,
    faCubes, faSitemap, faCircleQuestion
} from "@fortawesome/free-solid-svg-icons";
import logo from 'assets/curio-2.png';
import introJs from 'intro.js';
import "intro.js/introjs.css";

export default function UpMenu({
    setDashBoardMode,
    setDashboardOn,
    dashboardOn,
    setAIMode
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
    const [aiModeOn, setAiModeOn] = useState(false);

    const menuBarRef = useRef<HTMLDivElement>(null);
    const loadTrillInputRef = useRef<HTMLInputElement>(null);

    const { workflowNameRef, workflowName, setWorkflowName, setAllMinimized, allMinimized, expandStatus, setExpandStatus } = useNodeActionsContext();
    const { packages } = useFlowContext();
    const { getNodes, getEdges } = useReactFlow();
    const { loadTrill } = useCode();

    const toggleMenu = (menu: string) => {
        setActiveMenu(prev => prev === menu ? null : menu);
    };

    const closeTrillProvenanceModal = () => setTrillProvenanceOpen(false);
    const openTrillProvenanceModal = () => { setTrillProvenanceOpen(true); setActiveMenu(null); };

    const closeDatasetsModal = () => setDatasetsOpen(false);
    const openDatasetsModal = () => { setDatasetsOpen(true); setActiveMenu(null); };

    const handleNameChange = (e: any) => setWorkflowName(e.target.value);
    const handleNameBlur = () => setIsEditing(false);
    const handleKeyPress = (e: any) => { if (e.key === "Enter") setIsEditing(false); };

    const openTutorial = () => { setTutorialOpen(true); setActiveMenu(null); };

    const toggleExpand = () => {
        if (expandStatus === 'expanded') {
            setExpandStatus('minimized');
            setAllMinimized(allMinimized + 1);
        } else {
            setExpandStatus('expanded');
            setAllMinimized(0);
        }
        setActiveMenu(null);
    };

    const toggleAI = () => {
        const next = !aiModeOn;
        setAiModeOn(next);
        setAIMode(next);
    };

    const exportTrill = () => {
        const trill_spec = TrillGenerator.generateTrill(getNodes(), getEdges(), workflowNameRef.current, "", packages);
        const jsonString = JSON.stringify(trill_spec, null, 2);
        const blob = new Blob([jsonString], { type: 'application/json' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = workflowNameRef.current + '.json';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setActiveMenu(null);
    };

    const handleFileUpload = (e: any) => {
        const file = e.target.files[0];
        if (file && file.type === 'application/json') {
            const reader = new FileReader();
            reader.onload = (e: any) => {
                try {
                    const jsonContent = JSON.parse(e.target.result);
                    loadTrill(jsonContent);
                } catch (err) {
                    console.error('Invalid JSON file:', err);
                }
            };
            reader.onerror = (e: any) => console.error('Error reading file:', e.target.error);
            reader.readAsText(file);
        } else {
            console.error('Please select a valid .json file.');
        }
    };

    const loadTrillFile = () => {
        setActiveMenu(null);
        // Defer the click so the input is not unmounted before the dialog opens
        setTimeout(() => loadTrillInputRef.current?.click(), 0);
    };

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (menuBarRef.current && !menuBarRef.current.contains(event.target as Node)) {
                setActiveMenu(null);
            }
        };
        if (activeMenu) {
            document.addEventListener('click', handleClickOutside);
        } else {
            document.removeEventListener('click', handleClickOutside);
        }
        return () => document.removeEventListener('click', handleClickOutside);
    }, [activeMenu]);

    useEffect(() => {
        if (tutorialOpen) {
            const intro = introJs();
            intro.setOptions({
                steps: [
                    { intro: "Welcome to Curio, a framework for urban analytics. Let's take a quick tour to help you get started." },
                    { element: '#step-loading', intro: "This is a Data Loading Node. Here, you can create an array for basic datasets or import data from a file. Once loaded, add your code to convert the data into a DataFrame for further analysis." },
                    { element: '#step-analysis', intro: "This is a Data Analysis Node. Use it to perform calculations and operations on your dataset, preparing it for visualization." },
                    { element: '#step-transformation', intro: "The Data Transformation Node allows you to filter, segment, or restructure your data." },
                    { element: '#step-cleaning', intro: "This is a Data Cleaning Node. Use it to refine your dataset by handling missing values, removing outliers, and generating identifiers for data quality purposes." },
                    { element: '#step-pool', intro: "This is a Data Pool Node. It enables you to display your processed data in a structured grid format for easy review." },
                    { element: '#step-utk', intro: "This is a UTK Node. It renders your data in an interactive 3D environment using UTK." },
                    { element: '#step-vega', intro: "This is a Vega-Lite Node. Use it to visualize data in 2D formats (bar charts, scatter plots, and line graphs) using a JSON specification." },
                    { element: '#step-image', intro: "The Image Node displays a gallery of images." },
                    { element: '#step-merge', intro: "This is a Merge Flow Node. It allows you to combine multiple data streams into a single dataset. Red handles indicate a missing connection, while green handles show that a connection has been established. Note: each handle can only connect to one edge." },
                    { element: '#step-final', intro: "That's it! Drag and drop nodes into your workspace and begin exploring your data with Curio." }
                ],
                showStepNumbers: false,
                showProgress: false,
                exitOnOverlayClick: false,
                tooltipClass: "custom-intro-tooltip",
            });
            intro.start();
            setTutorialOpen(false);
        }
    }, [tutorialOpen]);

    return (
        <>
            <div className={clsx(styles.menuBar, "nowheel", "nodrag")} ref={menuBarRef}>
                <img className={styles.logo} src={logo} alt="Curio logo" />

                {/* File */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu('file')}>File ⏷</button>
                    {activeMenu === 'file' && (
                        <div className={styles.dropDownMenu}>
                            <div className={styles.dropDownRow} onClick={loadTrillFile}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileImport} />
                                <button className={styles.noStyleButton}>Load specification</button>
                            </div>
                            <div className={styles.dropDownRow} onClick={exportTrill}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileExport} />
                                <button className={styles.noStyleButton}>Save specification</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* View */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu('view')}>View ⏷</button>
                    {activeMenu === 'view' && (
                        <div className={styles.dropDownMenu}>
                            <div className={styles.dropDownRow} onClick={() => { setDashBoardMode(!dashboardOn); setDashboardOn(!dashboardOn); setActiveMenu(null); }}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faTableColumns} />
                                <button className={clsx(styles.noStyleButton, dashboardOn && styles.dashboardOn)}>Dashboard Mode</button>
                            </div>
                            <div className={styles.dropDownRow} onClick={toggleExpand}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={expandStatus === 'expanded' ? faDownLeftAndUpRightToCenter : faUpRightAndDownLeftFromCenter} />
                                <button className={styles.noStyleButton}>{expandStatus === 'expanded' ? 'Minimize Nodes' : 'Expand Nodes'}</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Data */}
                <div className={styles.dropdownWrapper}>
                    <button className={styles.button} onClick={() => toggleMenu('data')}>Data ⏷</button>
                    {activeMenu === 'data' && (
                        <div className={styles.dropDownMenu}>
                            <div className={styles.dropDownRow} onClick={() => { setPackagesOpen(true); setActiveMenu(null); }}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faCubes} />
                                <button className={styles.noStyleButton}>Python Packages</button>
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
                    <button className={styles.button} onClick={() => toggleMenu('provenance')}>Provenance ⏷</button>
                    {activeMenu === 'provenance' && (
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
                    <button className={styles.button} onClick={() => toggleMenu('help')}>Help ⏷</button>
                    {activeMenu === 'help' && (
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
            </div>

            {/* Editable Workflow Name */}
            <div className={styles.workflowNameContainer}>
                {isEditing ? (
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
                    <h1 className={styles.workflowNameStyle} onClick={() => setIsEditing(true)}>
                        {workflowName}
                    </h1>
                )}
            </div>

            <input
                type="file"
                accept=".json"
                ref={loadTrillInputRef}
                style={{ display: 'none' }}
                onChange={handleFileUpload}
            />
            <TrillProvenanceWindow
                open={trillProvenanceOpen}
                closeModal={closeTrillProvenanceModal}
                workflowName={workflowName}
            />
            <DatasetsWindow open={datasetsOpen} closeModal={closeDatasetsModal} />
            <PackageManagerWindow open={packagesOpen} closeModal={() => setPackagesOpen(false)} />
        </>
    );
}
