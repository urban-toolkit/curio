import React from "react";
import { BoxType } from "../../../constants";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { getPaletteNodeTypes } from "../../../registry";
import styles from "./ToolsMenu.module.css";

function DraggableTool({ boxType, icon, tooltip, tutorialID}: { boxType: BoxType; icon: any; tooltip: string; tutorialID?: string }) {
    return (
        <OverlayTrigger
            placement="right"
            delay={overlayTriggerProps}
            overlay={<Tooltip>{tooltip}</Tooltip>}
        >
            <div
                id={tutorialID}
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
    const paletteTypes = getPaletteNodeTypes();
    return (
        <div>
            <div className={styles.containerStyle}>
                {paletteTypes.map(desc => (
                    <DraggableTool
                        key={desc.id}
                        boxType={desc.id}
                        icon={desc.icon}
                        tooltip={desc.label}
                        tutorialID={desc.tutorialId}
                    />
                ))}
            </div>
        </div>
    );
}

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};
