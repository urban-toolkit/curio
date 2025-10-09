import React, { useState, useRef, useEffect } from "react";
import CSS from "csstype";
import { FileUpload, TrillProvenanceWindow, DatasetsWindow, Expand } from "components/menus";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useCode } from "../../../hook/useCode";
import { TrillGenerator } from "../../../TrillGenerator";
import styles from "./UpMenu.module.css";
import clsx from 'clsx';
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faDatabase, faFileImport, faFileExport } from "@fortawesome/free-solid-svg-icons";
import logo from 'assets/curio.png';
import introJs from 'intro.js';//new import
import "intro.js/introjs.css";//this too

export default function UpMenu({
    setDashBoardMode,
    setDashboardOn,
    dashboardOn,
    fileMenuOpen,
    setFileMenuOpen,
}: {
    setDashBoardMode: (mode: boolean) => void;
    setDashboardOn: (mode: boolean) => void;
    dashboardOn: boolean;
    fileMenuOpen: boolean;
    setFileMenuOpen: (open: boolean) => void;
}) {
    const [isEditing, setIsEditing] = useState(false);
    const [trillProvenanceOpen, setTrillProvenanceOpen] = useState(false);
    const [tutorialOpen, setTutorialOpen] = useState(false);
    const [datasetsOpen, setDatasetsOpen] = useState(false);
    const dropdownRef = useRef<HTMLDivElement>(null);

    const { nodes, edges, workflowNameRef, setWorkflowName } = useFlowContext();
    const { loadTrill } = useCode();

    const fileButtonRef = useRef<HTMLButtonElement>(null);

    const closeTrillProvenanceModal = () => {
        setTrillProvenanceOpen(false);
    }

    const openTrillProvenanceModal = () => {
        setTrillProvenanceOpen(true);
    }

    const closeDatasetsModal = () => {
        setDatasetsOpen(false);
    }

    const openDatasetsModal = () => {
        setDatasetsOpen(true);
    }
    
    const handleNameChange = (e: any) => {
        setWorkflowName(e.target.value);
    };

    const handleNameBlur = () => {
        setIsEditing(false);
    };

    const handleKeyPress = (e: any) => {
        if (e.key === "Enter") {
            setIsEditing(false);
        }
    };
    //James new defintions made here

    const closeTutorial = () => {
        setTutorialOpen(false);
    }

    const openTutorial = () => {
        setTutorialOpen(true);
    }

    //James new defintions end

    const exportTrill = (e:any) => {
        let trill_spec = TrillGenerator.generateTrill(nodes, edges, workflowNameRef.current);
        
        const jsonString = JSON.stringify(trill_spec, null, 2);

        const blob = new Blob([jsonString], { type: 'application/json' });

        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = workflowNameRef.current+'.json';

        document.body.appendChild(link);

        link.click();

        document.body.removeChild(link);
    }

    const handleFileUpload = (e:any) => {
        const file = e.target.files[0]; // Get the selected file

        if (file && file.type === 'application/json') {
            const reader = new FileReader();
    
            reader.onload = (e:any) => {
                try {
                    const jsonContent = JSON.parse(e.target.result);

                    console.log('Uploaded JSON content:', jsonContent);
                    loadTrill(jsonContent);
                } catch (err) {
                    console.error('Invalid JSON file:', err);
                }
            };
    
            reader.onerror = (e:any) => {
                console.error('Error reading file:', e.target.error);
            };
    
            reader.readAsText(file);
        } else {
            console.error('Please select a valid .json file.');
        }
    }

    const loadTrillFile = (e:any) => {
        const fileInput = document.getElementById('loadTrill') as HTMLElement;
        fileInput.click();
    }

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            // if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
            //     console.log("set file menu open to false");
            //     setFileMenuOpen(false);
            // }
            if (
                dropdownRef.current &&
                !dropdownRef.current.contains(event.target as Node) &&
                fileButtonRef.current &&
                !fileButtonRef.current.contains(event.target as Node)
            ) {
                setFileMenuOpen(false);
            }
        };
    
        if (fileMenuOpen) {
            document.addEventListener("click", handleClickOutside);
        } else {
            document.removeEventListener("click", handleClickOutside);
        }
    
        return () => {
            document.removeEventListener("click", handleClickOutside);
        };
    }, [fileMenuOpen]);

    //New code here James

     useEffect(() => {
        if(tutorialOpen){
            const intro = introJs();

        intro.setOptions({
            steps: [
        {
            intro: "Welcome to Curio, a framework for urban analytics. Let's take a quick tour to help you get started."
        },
        {
          element: '#step-loading',  
          intro: "This is a Data Loading Node. Here, you can create an array for basic datasets or import data from a file. Once loaded, add your code to convert the data into a DataFrame for further analysis."
        },
        {
          element: '#step-analysis',  
          intro: "This is a Data Analysis Node. Use it to perform calculations and operations on your dataset, preparing it for visualization."
        },
        {
          element: '#step-transformation',  
          intro: "The Data Transformation Node allows you to filter, segment, or restructure your data."
        },
        {
          element: '#step-cleaning',  
          intro: "This is a Data Cleaning Node. Use it to refine your dataset by handling missing values, removing outliers, and generating identifiers for data quality purposes."
        },
        {
          element: '#step-pool',  
          intro: "This is a Data Pool Node. It enables you to display your processed data in a structured grid format for easy review."
        },
        {
          element: '#step-utk',  
          intro: "This is a UTK Node. It renders your data in an interactive 3D environment using UTK."
        },
        {
          element: '#step-vega',  
          intro: "This is a Vega-Lite Node. Use it to visualize data in 2D formats (bar charts, scatter plots, and line graphs) using a JSON specification."
        },
        {
          element: '#step-image',  
          intro: "The Image Node displays a gallery of images."
        },
        {
          element: '#step-merge',  
          intro: "This is a Merge Flow Node. It allows you to combine multiple data streams into a single dataset. Red handles indicate a missing connection, while green handles show that a connection has been established. Note: each handle can only connect to one edge."
        },
        {
          element: '#step-final',  
          intro: "That's it! Drag and drop nodes into your workspace and begin exploring your data with Curio."
        }
        ],
        
        showStepNumbers: false,
        showProgress: false,
        exitOnOverlayClick: false,
        tooltipClass: "custom-intro-tooltip" ,
    });
        intro.start();
        setTutorialOpen(false);
        }
    }, [tutorialOpen]);

    //new code end

    return (
        <>
            <div className={clsx(styles.menuBar, "nowheel", "nodrag")}>
                <img className={styles.logo} src={logo} alt="Curio logo"/>
                <div className={styles.dropdownWrapper}>
                    <button
                        ref={fileButtonRef}
                        className={styles.button}
                        onClick={(e) => {
                                e.stopPropagation();
                                setFileMenuOpen((prev) => !prev);
                            }
                        }
                    >
                        File⏷
                    </button>
                    {fileMenuOpen && (
                        <div className={styles.dropDownMenu} ref={dropdownRef} onClick={(e) => e.stopPropagation()}>
                            <div className={styles.dropDownRow} onClick={loadTrillFile} >
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileImport} />
                                <button className={styles.noStyleButton}>Load specification</button>
                                <input type="file" accept=".json" id="loadTrill" style={{ display: 'none' }} onChange={handleFileUpload}/>
                            </div>
                            <div className={styles.dropDownRow} onClick={exportTrill}>
                                <FontAwesomeIcon className={styles.dropDownIcon} icon={faFileExport} />
                                <button className={styles.noStyleButton}>Save specification</button>
                            </div>
                        </div>
                    )}
                </div>
                <button   
                    className={clsx(
                        styles.button,
                        dashboardOn ? styles.dashboardOn : styles.dashboardOff
                    )}
                    onClick={() => {setDashBoardMode(!dashboardOn); setDashboardOn(!dashboardOn);}}>
                        Dashboard Mode
                </button>
                <button className={styles.button} onClick={openTrillProvenanceModal}>Provenance</button>
                <button className={styles.button} onClick={openTutorial}>Tutorial</button>
                
            </div>
            {/* Right-side top menu */}
            <div className={styles.rightSide}>
                <Expand />
                <FileUpload />
                <button className={styles.button} onClick={openDatasetsModal}><FontAwesomeIcon icon={faDatabase} /></button>
            </div>
            {/* Editable Workflow Name */}
            <div className={styles.workflowNameContainer}>
                {isEditing ? (
                    <input
                        type="text"
                        value={workflowNameRef.current}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyPress={handleKeyPress}
                        autoFocus
                        className={styles.input}
                    />
                ) : (
                    <h1
                        className={styles.workflowNameStyle}
                        onClick={() => setIsEditing(true)}
                    >
                        {workflowNameRef.current}
                    </h1>
                )}
            </div>
            {/* Trill Provenance Modal */}
            <TrillProvenanceWindow 
                open={trillProvenanceOpen}
                closeModal={closeTrillProvenanceModal}
                workflowName={workflowNameRef.current}
            />
            {/* Datasets Modal */}
            <DatasetsWindow 
                open={datasetsOpen}
                closeModal={closeDatasetsModal}
            />
        </>

    );
}