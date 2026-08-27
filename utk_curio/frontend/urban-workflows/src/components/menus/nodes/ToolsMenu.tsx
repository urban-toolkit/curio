import React, { Fragment, memo, useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faForwardStep } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { refreshPackageRegistry } from "../../../api/packagesApi";
import { getPaletteNodeTypes, subscribeToRegistry } from "../../../registry";
import { BUILTIN_PACKAGE_ID } from "../../../registry/packagesClient";
import { NodeCategory, NodeDescriptor, NodeTemplateId } from "../../../registry/types";
import { useFlowContext } from "../../../providers/FlowProvider";
import { useUserContext } from "../../../providers/UserProvider";
import {
    OVERLAY_TRIGGER_DELAY_PROPS,
    PackagesPaletteDropdown,
    groupPalettePackages,
    paletteDescriptorBootstrapKey,
    type ToolsMenuTooltipSide,
} from "./toolsMenuPackagePalette";
import { DatasetsPaletteDropdown } from "./datasetPalette";
import { AgentsPaletteDropdown } from "./agentsPalette";
import styles from "./ToolsMenu.module.css";

const DraggableTool = memo(function DraggableTool({
    nodeType,
    icon,
    tooltip,
    tutorialID,
    badge,
    tooltipPlacement = "right",
}: {
    nodeType: NodeTemplateId;
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
    // Re-render whenever the registry mutates (e.g. when package descriptors
    // land asynchronously via packagesClient.ts).
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
        void refreshPackageRegistry();
    }, [user?.id]);

    const paletteTypes = getPaletteNodeTypes();
    // The curio.builtin package is manifest-driven like any other, but the UI
    // anchors it in the left-side "Built-in" rail. Only third-party packages land
    // in the right-side Packages dropdown.
    const isBuiltin = (d: NodeDescriptor) => d.package?.packageId === BUILTIN_PACKAGE_ID;
    const coreTypes = paletteTypes.filter(isBuiltin);
    const packageTypes = paletteTypes.filter((d) => !isBuiltin(d));
    const coreGroups = groupPaletteTypes(coreTypes);
    const packageGroups = groupPalettePackages(packageTypes);
    const { playAllNodes } = useFlowContext();

    // Every catalog trigger lives in the left rail and their panels open into
    // the same strip to the right of it, so only one may be open at a time. A
    // palette closes ONLY when its own trigger is clicked again (or another
    // trigger takes the strip) - outside clicks and Escape deliberately leave
    // it open.
    const [activePalette, setActivePalette] = useState<
        "datasets" | "packages" | "agents" | null
    >(null);
    const setDatasetsOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "datasets" : prev === "datasets" ? null : prev));
    }, []);
    const setPackagesOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "packages" : prev === "packages" ? null : prev));
    }, []);
    const setAgentsOpen = useCallback((value: boolean) => {
        setActivePalette((prev) => (value ? "agents" : prev === "agents" ? null : prev));
    }, []);

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
                <PackagesPaletteDropdown
                    groups={packageGroups}
                    open={activePalette === "packages"}
                    setOpen={setPackagesOpen}
                />
                <DatasetsPaletteDropdown open={activePalette === "datasets"} setOpen={setDatasetsOpen} />
                <AgentsPaletteDropdown open={activePalette === "agents"} setOpen={setAgentsOpen} />
                <div className={styles.playAllRow}>
                    <button
                        type="button"
                        className={styles.playAllButton}
                        onClick={playAllNodes}
                        title="Run all nodes"
                        aria-label="Run all nodes"
                    >
                        <FontAwesomeIcon icon={faForwardStep} />
                    </button>
                </div>
            </div>
        </div>
    );
});

export default ToolsMenu;
