import React, { Fragment, memo, useSyncExternalStore } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faChevronLeft, faChevronRight, faShapes } from "@fortawesome/free-solid-svg-icons";
import { Tooltip, OverlayTrigger } from "react-bootstrap";
import { NodeCategory, NodeDescriptor, NodeTemplateId } from "../../../../registry/types";
import { isRegistryReady, subscribeToRegistryReady } from "../../../../registry/registryReadiness";
import { PaletteDragHint } from "../PaletteDragHint";
import { TOOLS_PALETTE_DROPDOWN_ATTR, TOOLS_PALETTE_PANEL_ATTR } from "../toolsPaletteDismiss";
import { OVERLAY_TRIGGER_DELAY_PROPS, type ToolsMenuTooltipSide } from "../toolsMenuPackagePalette/uiConstants";
import styles from "./BuiltinPalette.module.css";

/** The DOM id of a built-in palette tile: `curio.builtin/data-loading@1` is `tile-data-loading`. */
export function paletteTileId(nodeType: NodeTemplateId): string {
    return `tile-${nodeType.replace(/^[^/]*\//, "").replace(/@\d+$/, "")}`;
}

const DraggableTool = memo(function DraggableTool({
    nodeType,
    icon,
    tooltip,
    badge,
    tooltipPlacement = "right",
}: {
    nodeType: NodeTemplateId;
    icon: any;
    tooltip: string;
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
                id={paletteTileId(nodeType)}
                // The tile is an icon and a drag source: nothing in it was text,
                // so it had no accessible name at all and the hover tooltip was
                // its only label. `title` matches how the dataset and agent drag
                // handles are named (DatasetPaletteRows, AgentPaletteRow); the
                // explicit aria-label wins the accname computation and keeps the
                // name stable if the tooltip copy ever diverges.
                aria-label={tooltip}
                title={tooltip}
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
// share one block; flow nodes live in the top data block.
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
                    badge={desc.badge}
                    tooltipPlacement={tooltipPlacement}
                />
            ))}
        </div>
    );
}

/**
 * The Built-in tools-panel palette: the node types of the `curio.builtin`
 * package, which every dataflow has. Shares the Models, Agents, Datasets and
 * Packages pattern (dark vertical trigger card, dark dropdown panel, footer),
 * differing in content: the built-in tiles, grouped data and flow, then
 * computation, then views, each a drag source for its node. Its footer holds
 * the drag hint and no "Browse … Catalog +" button, since there is no catalog
 * of built-in nodes to browse or add from.
 */
export const BuiltinPaletteDropdown = memo(function BuiltinPaletteDropdown({
    nodeTypes,
    open,
    setOpen,
}: {
    /** The built-in node types, in palette order. */
    nodeTypes: NodeDescriptor[];
    /** Owned by ToolsMenu: the palettes share one strip, so only one may be
     *  open. Uncontrolled state here would let two open at once. */
    open: boolean;
    setOpen: (value: boolean) => void;
}) {
    // The tiles are descriptors from the package registry, so for a moment
    // after a load there are none: until the registry has answered once, an
    // empty palette is one still loading, not one with nothing in it.
    const registryReady = useSyncExternalStore(subscribeToRegistryReady, isRegistryReady, () => false);
    const groups = groupPaletteTypes(nodeTypes);
    const total = nodeTypes.length;

    // No Escape / outside-click dismissal on purpose: the palette stays open
    // until its own trigger is clicked again (or another palette claims the
    // strip), the same rule its four peers state.

    return (
        <div
            id="builtin-palette"
            className={styles.root}
            {...{ [TOOLS_PALETTE_DROPDOWN_ATTR]: "true" }}
        >
            <div className={styles.column}>
                <button
                    type="button"
                    className={`${styles.trigger} ${open ? styles.triggerOpen : ""}`}
                    onClick={() => setOpen(!open)}
                    aria-expanded={open}
                    aria-haspopup="true"
                    title={open ? "Close built-in palette" : "Open built-in palette"}
                >
                    <span className={styles.triggerTop}>
                        <FontAwesomeIcon icon={faShapes} className={styles.triggerIcon} />
                        <span className={styles.triggerCount}>{total}</span>
                        <FontAwesomeIcon
                            icon={open ? faChevronLeft : faChevronRight}
                            className={styles.triggerChevron}
                        />
                    </span>
                    <span className={styles.triggerLabel}>Built-in</span>
                </button>
            </div>
            {open ? (
                /* TOOLS_PALETTE_PANEL_ATTR marks this panel as occluding the canvas,
                   as its peers do, so Fit View sizes the graph around it. */
                <div
                    className={styles.panel}
                    role="region"
                    aria-label="Built-in palette"
                    {...{ [TOOLS_PALETTE_PANEL_ATTR]: "true" }}
                >
                    <div className={styles.panelHeader}>
                        <div className={styles.title}>Built-in nodes</div>
                    </div>
                    <div className={styles.scroll}>
                        {groups.length > 0 ? (
                            groups.map((group, i) => (
                                <Fragment key={`core-${i}`}>
                                    {i > 0 && <div className={styles.divider} />}
                                    {renderGroup(group, `core-group-${i}`)}
                                </Fragment>
                            ))
                        ) : (
                            <div className={styles.sectionEmpty}>
                                {registryReady ? "No built-in nodes." : "Loading built-in nodes…"}
                            </div>
                        )}
                    </div>
                    <div className={styles.footer}>
                        <PaletteDragHint item="node" />
                    </div>
                </div>
            ) : null}
        </div>
    );
});
