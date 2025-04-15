import React from "react";
import CSS from "csstype";

import { useCode } from "../../hook/useCode";
// import { LLMEvents } from "../../constants";
import { BoxType } from "../../constants";
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
    faUpload
} from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
// import { useLLMContext } from "../../providers/LLMProvider";

export function ToolsMenu() {
    const { createCodeNode } = useCode();
    // const { llmEvents } = useLLMContext();

    return (
        <div>
            <div style={{...containerStyle}}>
                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Computation Analysis</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.COMPUTATION_ANALYSIS)}
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
                        onClick={() => createCodeNode(BoxType.DATA_TRANSFORMATION)}
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
                        onClick={() => createCodeNode(BoxType.DATA_LOADING)}
                    >
                        <FontAwesomeIcon icon={faDownload} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>2D Plot (Vega Lite)</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_VEGA)}
                    >
                        <FontAwesomeIcon icon={faChartLine} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                {/* <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Text</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_TEXT)}
                    >
                        <FontAwesomeIcon icon={faFont} style={iconStyle} />
                    </div>
                </OverlayTrigger> */}

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Export</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_EXPORT)}
                    >
                        <FontAwesomeIcon icon={faUpload} style={iconStyle} /> 
                    </div>
                </OverlayTrigger>

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Cleaning</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_CLEANING)}
                    >
                        <FontAwesomeIcon icon={faBroom} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                {/* <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Flow Switch</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.FLOW_SWITCH)}
                    >
                        <FontAwesomeIcon icon={faRepeat} style={iconStyle} />
                    </div>
                </OverlayTrigger> */}

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>3D Visualization (UTK)</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_UTK)}
                    >
                        <FontAwesomeIcon icon={faCube} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                {/* <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Table</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_TABLE)}
                    >
                        <FontAwesomeIcon icon={faTable} style={iconStyle} />
                    </div>
                </OverlayTrigger> */}

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Image</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.VIS_IMAGE)}
                    >
                        <FontAwesomeIcon icon={faImage} style={iconStyle} />
                    </div>
                </OverlayTrigger>

                {/* <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Constant</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.CONSTANTS)}
                    >
                        <FontAwesomeIcon icon={faSquareRootVariable} style={iconStyle} />
                    </div>
                </OverlayTrigger> */}

                <OverlayTrigger
                    placement="right"
                    delay={overlayTriggerProps}
                    overlay={<Tooltip>Data Pool</Tooltip>}
                >
                    <div
                        style={optionStyle}
                        onClick={() => createCodeNode(BoxType.DATA_POOL)}
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
                        onClick={() => createCodeNode(BoxType.MERGE_FLOW)}
                    >
                        <FontAwesomeIcon icon={faCodeMerge} style={iconStyle} />
                    </div>
                </OverlayTrigger>
            </div>

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

const containerStyle: CSS.Properties = {
    position: "fixed",
    zIndex: 100,
    top: "150px",
    left: "50px",
    backgroundColor: "#23c686",
    padding: "5px",
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gridAutoRows: "45px",
    borderRadius: "5px",
    boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px"
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
    color: "#fbfcf6",
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
    top: "150px", 
    left: "180px",
    display: "none", 
    width: "600px", 
    backgroundColor: "white",
    boxShadow: "0px 0px 3px 0px black",
    padding: "10px",
    borderRadius: "5px"
}