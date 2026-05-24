import React, { Fragment, memo, useEffect, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faForwardStep } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { refreshPackRegistry } from "../../../api/packsApi";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { BUILTIN_PACK_ID } from "../../../registry/packsClient";
import { NodeCategory, NodeDescriptor, NodeKindId } from "../../../registry/types";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useUserContext } from "../../../providers/UserProvider";
import {
    OVERLAY_TRIGGER_DELAY_PROPS,
    PacksPaletteDropdown,
    groupPalettePacks,
    paletteDescriptorBootstrapKey,
    type ToolsMenuTooltipSide,
} from "./toolsMenuPackPalette";
import styles from "./ToolsMenu.module.css";

const DraggableTool = memo(function DraggableTool({
    nodeType,
    icon,
    tooltip,
    tutorialID,
    badge,
    tooltipPlacement = "right",
}: {
    nodeType: NodeKindId;
    icon: any;
    tooltip: string;
    tutorialID?: string;
    badge?: string;
    tooltipPlacement?: ToolsMenuTooltipSide;
}) {
    return (
        <OverlayTrigger
            placement={tooltipPlacement}
            delay={OVERLAY_TRIGGER_DELAY_PROPS}
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

// Groups (top → bottom) for the BUILT-IN section. vis_grammar and vis_simple
// share one block; flow nodes (e.g. Merge Flow) live in the top data block.
const PALETTE_GROUPS: NodeCategory[][] = [
    ["data", "flow"],
    ["computation"],
    ["vis_grammar", "vis_simple"],
];

function groupPaletteTypes(descriptors: NodeDescriptor[]): NodeDescriptor[][] {
    return PALETTE_GROUPS.map((categories) => descriptors.filter((d) => categories.includes(d.category))).filter(
        (group) => group.length > 0,
    );
}

function renderGroup(group: NodeDescriptor[], key: string, tooltipPlacement: ToolsMenuTooltipSide = "right") {
    return (
        <div key={key} className={styles.containerStyle}>
            {group.map((desc) => (
                <DraggableTool
                    key={desc.id}
                    nodeType={desc.id}
                    icon={desc.icon}
                    tooltip={desc.label}
                    tutorialID={desc.tutorialId}
                    badge={desc.badge}
                    tooltipPlacement={tooltipPlacement}
                />
            ))}
        </div>
    );
}

const NOOP = () => () => {};

const ToolsMenu = memo(function ToolsMenu() {
    // Re-render whenever the registry mutates (e.g. when pack descriptors
    // land asynchronously via packsClient.ts).
    const paletteVersion = useSyncExternalStore(
        typeof window !== "undefined" ? subscribeToRegistry : NOOP,
        paletteDescriptorBootstrapKey,
        () => "ssr",
    );
    void paletteVersion;

    const { user } = useUserContext();
    useEffect(() => {
        const uid = user?.id;
        if (uid == null) return;
        void refreshPackRegistry();
    }, [user?.id]);

    const paletteTypes = getPaletteNodeTypes();
    // The curio.builtin pack is manifest-driven like any other, but the UI
    // anchors it in the left-side "Built-in" rail. Only third-party packs land
    // in the right-side Packs dropdown.
    const isBuiltin = (d: NodeDescriptor) => d.pack?.packId === BUILTIN_PACK_ID;
    const coreTypes = paletteTypes.filter(isBuiltin);
    const packTypes = paletteTypes.filter((d) => !isBuiltin(d));
    const coreGroups = groupPaletteTypes(coreTypes);
    const packGroups = groupPalettePacks(packTypes);
    const { playAllNodes } = useFlowContext();
    return (
        <div id="tools-palette-dock" className={styles.paletteDock}>
            <div id="tools-menu" className={styles.builtinStack}>
                <div className={styles.menuStyle}>
                    <div className={styles.sectionHeader}>Built-in</div>
                    {coreGroups.map((group, i) => (
                        <Fragment key={`core-${i}`}>
                            {i > 0 && <div className={styles.divider} />}
                            {renderGroup(group, `core-group-${i}`)}
                        </Fragment>
                    ))}
                </div>
                <button className={styles.playAllButton} onClick={playAllNodes} title="Run all nodes">
                    <FontAwesomeIcon icon={faForwardStep} />
                </button>
            </div>
            <PacksPaletteDropdown groups={packGroups} />
        </div>
    );
});

export default ToolsMenu;
