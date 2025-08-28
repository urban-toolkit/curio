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
        const intro = introJs();

        intro.setOptions({
            steps: [
        {
            intro: "Welcome to Curio! An IDE used for urban analytics. Let's take a tour!"
        },
        {
          element: '#step-one',  
          intro: 'This is a Data Loading node. You can code an array for basic sets of data, or load in a file. Then add your code to add it to a dataframe to return.'
        },
        {
          element: '#step-two',  
          intro: 'Please read this! This is very important.'
        },
        {
          element: '#step-three',  
          intro: 'Please read this! This is very important.'
        },
        {
          element: '#step-four',  
          intro: 'The Data Transformation Node can select different parts of your data to narrow down the focus of your analysis.'
        },
        {
          element: '#step-five',  
          intro: 'This is a Data Cleaning Node. You can polish your data by removing outliers, fill in missing values, etc. It can also create identifiers for your data.'
        },
        {
          element: '#step-six',  
          intro: 'Please read this! This is very important.'
        },
        {
          element: '#step-seven',  
          intro: 'Please read this! This is very important.'
        },
        {
          element: '#step-eight',  
          intro: 'A 2D Plot Node - also known as a Vega Lite Node - can be used to graph your data on various 2D graphs such as heatmats and bar charts.'
        },
        {
          element: '#step-nine',  
          intro: 'Please read this! This is very important.'
        },
        {
          element: '#step-ten',  
          intro: 'This is a merge flow box. Use it to merge multiple pieces of data into one. It can take up to 5 inputs. Red handles indicate that there is not an edge for the handle. Green indicates that there is an edge. One handle may not have multiple edges.'
        },
        {
          element: '#step-final',  
          intro: 'Drag and drop nodes into your environment. Now get started!'
        }
        ],
        
        showStepNumbers: false,
        showProgress: false,
        exitOnOverlayClick: false,
        tooltipClass: "custom-intro-tooltip" 
    });

        intro.start();
    }, []);

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
