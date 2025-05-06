import React from "react";
import CSS from "csstype";
import { BoxType } from "../../constants";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faBroom,
    faChartLine,
    faCodeMerge,
    faCube,
    faDatabase,
    faDownload,
    faImage,
    faMagnifyingGlassChart,
    faServer,
    faUpload
} from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";

function DraggableTool({ boxType, icon, tooltip }: { boxType: BoxType; icon: any; tooltip: string }) {
    return (
        <OverlayTrigger
            placement="right"
            delay={overlayTriggerProps}
            overlay={<Tooltip>{tooltip}</Tooltip>}
        >
            <div
                style={optionStyle}
                draggable
                onDragStart={(event) => {
                    event.dataTransfer.setData("application/reactflow", boxType);
                    event.dataTransfer.effectAllowed = "move";
                }}
            >
                <FontAwesomeIcon icon={icon} style={iconStyle} />
            </div>
        </OverlayTrigger>
    );
}


export function ToolsMenu() {
    return (
        <div>
            <div style={{...containerStyle}}>
                <DraggableTool boxType={BoxType.COMPUTATION_ANALYSIS} icon={faMagnifyingGlassChart} tooltip="Computation Analysis" />
                <DraggableTool boxType={BoxType.DATA_TRANSFORMATION} icon={faDatabase} tooltip="Data Transformation" />
                <DraggableTool boxType={BoxType.DATA_LOADING} icon={faUpload} tooltip="Data Loading" />
                <DraggableTool boxType={BoxType.VIS_VEGA} icon={faChartLine} tooltip="2D Plot (Vega Lite)" />
                <DraggableTool boxType={BoxType.DATA_EXPORT} icon={faDownload} tooltip="Data Export" />
                <DraggableTool boxType={BoxType.DATA_CLEANING} icon={faBroom} tooltip="Data Cleaning" />
                <DraggableTool boxType={BoxType.VIS_UTK} icon={faCube} tooltip="3D Visualization (UTK)" />
                <DraggableTool boxType={BoxType.VIS_IMAGE} icon={faImage} tooltip="Image" />
                <DraggableTool boxType={BoxType.DATA_POOL} icon={faServer} tooltip="Data Pool" />
                <DraggableTool boxType={BoxType.MERGE_FLOW} icon={faCodeMerge} tooltip="Merge Flow" />
            </div>
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