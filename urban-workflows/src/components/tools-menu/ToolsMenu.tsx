import React, {
    useEffect, useReducer
} from "react";
import CSS from "csstype";
import Icon from "@mui/material/Icon";

import { useCode } from "../../hook/useCode";
import { AccessLevelType, BoxType } from "../../constants";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faBroom,
    faChartLine,
    faCodeMerge,
    faCube,
    faDatabase,
    faDownload,
    faFont,
    faImage,
    faMagnifyingGlassChart,
    faRepeat,
    faServer,
    faSquareRootVariable,
    faTable,
    faUpload,
    faSquareMinus
} from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { Template, useTemplateContext } from "../../providers/TemplateProvider";
import { useUserContext } from "../../providers/UserProvider";
import FileUpload from "./FileUpload";

export function ToolsMenu() {
    const { createCodeNode } = useCode();
    const { getTemplates, deleteTemplate } = useTemplateContext();

    const { user } = useUserContext();

    // const handleClick = (boxType: BoxType) => {
    //     for(const type in BoxType){
    //         let templates_modal = document.getElementById("templates_modal_"+type) as HTMLElement;
    
    //         if(type == boxType){
    //             if (templates_modal.style.display === "none") {
    //                 templates_modal.style.display = "block"; // or "inline" or any other valid display value
    //             } else {
    //                 templates_modal.style.display = "none";
    //             }
    //         }else{
    //             templates_modal.style.display = "none";
    //         }
    //     }
    // }

    // const getBoxesType = () => {
    //     let types = [];

    //     for(const boxType in BoxType){
    //         types.push(boxType);
    //     }

    //     return types;
    // }

    const boxNameTranslation = (boxType: BoxType) => {
        if(boxType === BoxType.COMPUTATION_ANALYSIS){
            return "Computation Analysis"
        }else if(boxType === BoxType.CONSTANTS){
            return "Constants"
        }else if(boxType === BoxType.DATA_CLEANING){
            return "Data Cleaning"
        }else if(boxType === BoxType.DATA_EXPORT){
            return "Data Export"
        }else if(boxType === BoxType.DATA_LOADING){
            return "Data Loading"
        }else if(boxType === BoxType.DATA_POOL){
            return "Data Pool"
        }else if(boxType === BoxType.DATA_TRANSFORMATION){
            return "Data Transformation"
        }else if(boxType === BoxType.FLOW_SWITCH){
            return "Flow Switch"
        }else if(boxType === BoxType.MERGE_FLOW){
            return "Merge Flow"
        }else if(boxType === BoxType.VIS_IMAGE){
            return "Image"
        }else if(boxType === BoxType.VIS_TABLE){
            return "Table"
        }else if(boxType === BoxType.VIS_TEXT){
            return "Text"
        }else if(boxType === BoxType.VIS_UTK){
            return "UTK"
        }else if(boxType === BoxType.VIS_VEGA){
            return "Vega-Lite"
        }
    }

    return (
        <div>
            <div style={containerStyle}>
                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Computation Analysis</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.COMPUTATION_ANALYSIS, null)}
                    >
                        <FontAwesomeIcon icon={faMagnifyingGlassChart} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Transformation</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_TRANSFORMATION, null)}
                    >
                        <FontAwesomeIcon icon={faDatabase} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Loading</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_LOADING, null)}
                    >
                        <FontAwesomeIcon icon={faUpload} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>2D Plot (Vega Lite)</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_VEGA, null)}
                    >
                        <FontAwesomeIcon icon={faChartLine} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Text</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_TEXT, null)}
                    >
                        <FontAwesomeIcon icon={faFont} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Export</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_EXPORT, null)}
                    >
                        <FontAwesomeIcon icon={faDownload} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Cleaning</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_CLEANING, null)}
                    >
                        <FontAwesomeIcon icon={faBroom} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Flow Switch</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.FLOW_SWITCH, null)}
                    >
                        <FontAwesomeIcon icon={faRepeat} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>3D Visualization (UTK)</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_UTK, null)}
                    >
                        <FontAwesomeIcon icon={faCube} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Table</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_TABLE, null)}
                    >
                        <FontAwesomeIcon icon={faTable} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Image</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_IMAGE, null)}
                    >
                        <FontAwesomeIcon icon={faImage} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Constant</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.CONSTANTS, null)}
                    >
                        <FontAwesomeIcon icon={faSquareRootVariable} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Pool</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_POOL, null)}
                    >
                        <FontAwesomeIcon icon={faServer} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Merge Flow</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.MERGE_FLOW, null)}
                    >
                        <FontAwesomeIcon icon={faCodeMerge} style={iconStyle} />
                    </div>
                </OverlayTrigger>
            </div>

            <FileUpload
                style={fileUploadStyle}
            />

            {/* Templates */}
            {/* {getBoxesType().map((type: string, indexType: number) => {
                return <div id={"templates_modal_"+type} key={"templates_modal_"+type+"_"+indexType} style={templatesModalStyle}>
                    <p style={{fontWeight: "bold", color: "#666666", textAlign: "center", fontSize: "22px"}}>{boxNameTranslation(type as BoxType)}</p>
                    {user != null && user.type == "programmer" ? <button style={buttonStyleAny} onClick={() => {createCodeNode(type, null)}}>New blank</button> : null}
                    {getTemplates(type as BoxType, false).length > 0 ? <><hr/><p style={{fontWeight: "bold", color: "#666666"}}>Default Templates</p></> : null}
                    {getTemplates(type as BoxType, false).map((template: Template, index: number) => {
                        if((template.accessLevel == AccessLevelType.PROGRAMMER && user != null && user.type == "expert") || (template.accessLevel != AccessLevelType.ANY && user == null)){
                            return null                            
                        }else{
                            return <button key={"templates_modal_content_default_"+type+index} style={template.accessLevel == AccessLevelType.PROGRAMMER ? buttonStyleProgrammer : template.accessLevel == AccessLevelType.EXPERT ? buttonStyleExpert : buttonStyleAny} onClick={() => {createCodeNode(type, template)}}>{template.name}</button>
                        }
                    })}
                    {getTemplates(type as BoxType, true).length > 0 ? <><hr/><p style={{fontWeight: "bold", color: "#666666"}}>Custom Templates</p></> : null}
                    {getTemplates(type as BoxType, true).map((template: Template, index: number) => {
                        if((template.accessLevel == AccessLevelType.PROGRAMMER && user != null && user.type == "expert") || (template.accessLevel != AccessLevelType.ANY && user == null)){
                            return null                            
                        }else{
                            return <div key={"templates_modal_content_custom_"+type+index}><button style={template.accessLevel == AccessLevelType.PROGRAMMER ? buttonStyleProgrammer : template.accessLevel == AccessLevelType.EXPERT ? buttonStyleExpert : buttonStyleAny} onClick={() => {createCodeNode(type, template)}}>{template.name}</button><FontAwesomeIcon onClick={() => {deleteTemplate(template.id)}} icon={faSquareMinus} style={{fontSize: "1.3em", color: "#888787", marginLeft: -12, marginBottom: 20}} /></div>
                        }
                    })}
                </div>
            })} */}


        </div>
    );
}

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};

const fileUploadStyle: CSS.Properties = {
    position: "fixed",
    zIndex: 100,
    top: "400px",
    width: "100px",
    textAlign: "center",
    height: "35px",
    left: "50px",
    backgroundColor: "white",
    fontWeight: "bold",
    color: "#888787",
    borderRadius: "4px",
    cursor: "pointer", 
    outline: "none",
    padding: "5px",
};

const containerStyle: CSS.Properties = {
    position: "fixed",
    zIndex: 100,
    top: "50px",
    left: "50px",
    backgroundColor: "white",
    boxShadow: "0px 0px 5px 0px black",
    padding: "5px",
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gridAutoRows: "45px",
    borderRadius: "5px",
};

const optionStyle: CSS.Properties = {
    width: "45px",
    cursor: "pointer",
    display: "flex",
    flexDirection: "column",
    justifyContent: "center",
    alignItems: "center",
    padding: "10px",
};

const optionText: CSS.Properties = {
    width: "100%",
    textAlign: "center",
    fontSize: "0.9em",
};

const iconStyle: CSS.Properties = {
    fontSize: "1.5em",
    color: "#888787",
};

const buttonStyleProgrammer: CSS.Properties = {
    backgroundColor: "transparent",
    color: "#545353",
    border: "1.5px solid #d66800",
    marginRight: "5px",
    padding: "8px 16px",
    borderRadius: "4px",
    cursor: "pointer", 
    outline: "none"
}

const buttonStyleExpert: CSS.Properties = {
    backgroundColor: "transparent",
    color: "#545353",
    border: "1.5px dashed #0044d6",
    marginRight: "5px",
    padding: "8px 16px",
    borderRadius: "4px",
    cursor: "pointer", 
    outline: "none"
}

const buttonStyleAny: CSS.Properties = {
    backgroundColor: "transparent",
    color: "#545353",
    border: "1.5px solid #545353",
    marginRight: "5px",
    padding: "8px 16px",
    borderRadius: "4px",
    cursor: "pointer", 
    outline: "none"
}

const templatesModalStyle: CSS.Properties = {
    position: "fixed", 
    zIndex: 100, 
    top: "50px", 
    left: "180px",
    display: "none", 
    width: "600px", 
    backgroundColor: "white",
    boxShadow: "0px 0px 3px 0px black",
    padding: "10px",
    borderRadius: "5px"
}