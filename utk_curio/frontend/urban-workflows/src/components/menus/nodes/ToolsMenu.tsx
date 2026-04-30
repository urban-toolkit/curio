import React, { memo, Fragment } from "react";
import { NodeType } from "../../../constants";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faForwardStep } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { getPaletteNodeTypes } from "../../../registry";
import { NodeCategory, NodeDescriptor } from "../../../registry/types";
import { useFlowContext } from "../../../providers/FlowProvider";
import styles from "./ToolsMenu.module.css";


const DraggableTool = memo(function DraggableTool({ nodeType, icon, tooltip, tutorialID, badge }: { nodeType: NodeType; icon: any; tooltip: string; tutorialID?: string; badge?: string }) {
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
                    event.dataTransfer.setData("application/reactflow", nodeType);
                    event.dataTransfer.effectAllowed = "move";
                }}
            >
                <FontAwesomeIcon icon={icon} className={styles.iconStyle} />
                {badge && <span className={styles.iconBadge}>{badge}</span>}
            </div>
        </OverlayTrigger>
    );
});

// Groups (top → bottom). vis_grammar and vis_simple share one block;
// flow nodes (e.g. Merge Flow) live in the top data block.
const PALETTE_GROUPS: NodeCategory[][] = [
    ['data', 'flow'],
    ['computation'],
    ['vis_grammar', 'vis_simple'],
];

function groupPaletteTypes(descriptors: NodeDescriptor[]): NodeDescriptor[][] {
    return PALETTE_GROUPS
        .map(categories => descriptors.filter(d => categories.includes(d.category)))
        .filter(group => group.length > 0);
}

const ToolsMenu = memo(function ToolsMenu() {
    const paletteTypes = getPaletteNodeTypes();
    const groups = groupPaletteTypes(paletteTypes);
    const { playAllNodes } = useFlowContext();
    return (
        <div className={styles.wrapperStyle}>
            <div className={styles.menuStyle}>
                {groups.map((group, i) => (
                    <Fragment key={i}>
                        {i > 0 && <div className={styles.divider} />}
                        <div className={styles.containerStyle}>
                            {group.map(desc => (
                                <DraggableTool
                                    key={desc.id}
                                    nodeType={desc.id}
                                    icon={desc.icon}
                                    tooltip={desc.label}
                                    tutorialID={desc.tutorialId}
                                    badge={desc.badge}
                                />
                            ))}
                        </div>
                    </Fragment>
                ))}
            </div>
            <button
                className={styles.playAllButton}
                onClick={playAllNodes}
                title="Run all nodes"
            >
                <FontAwesomeIcon icon={faForwardStep} />
            </button>
        </div>
    );
});

export default ToolsMenu;

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};
