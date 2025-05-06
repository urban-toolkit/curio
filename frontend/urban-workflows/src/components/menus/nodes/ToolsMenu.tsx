import React from "react";
import CSS from "csstype";
import { BoxType } from "../../../constants";
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
import styles from "./ToolsMenu.module.css";

function DraggableTool({ boxType, icon, tooltip }: { boxType: BoxType; icon: any; tooltip: string }) {
    return (
        <OverlayTrigger
            placement="right"
            delay={overlayTriggerProps}
            overlay={<Tooltip>{tooltip}</Tooltip>}
        >
            <div
                className={styles.optionStyle}
                draggable
                onDragStart={(event) => {
                    event.dataTransfer.setData("application/reactflow", boxType);
                    event.dataTransfer.effectAllowed = "move";
                }}
            >
                <FontAwesomeIcon icon={icon} className={styles.iconStyle} />
            </div>
        </OverlayTrigger>
    );
}

export default function ToolsMenu() {
    return (
        <div>
            <div className={styles.containerStyle}>
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

