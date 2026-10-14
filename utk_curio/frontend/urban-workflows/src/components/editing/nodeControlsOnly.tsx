// Whether a node shows only its controls: the "Display as widget" switch, in
// the Widgets tab and in a Parameter node's body, folds a node with widgets,
// or a Parameter node, to its widget rows, so a user sets values and presses
// Play without the code, tabs and output around them. NodeContainer decides it
// from node data (`controlsOnly`, saved by TrillGenerator) and provides it;
// NodeEditor, WidgetsEditor and the Parameter node's body read it. Never on a
// dashboard tile or in a notebook cell, where there is no switch either.
import React, { createContext, useContext } from "react";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";
import { unversionedNodeType } from "../../utils/flowNodeCanonicalType";
import { PARAMETER_NODE_TYPE } from "../../utils/references/sharedParameters";
import styles from "./widgets/WidgetTags.module.css";

/** Where one widget's box stands in a tile whose widgets are separated,
 * from the tile's corner; no width or height is the default one. */
export type WidgetBoxLayout = { x: number; y: number; width?: number; height?: number };

/** A dashboard tile displayed as a widget with "Separate widgets" on: each
 * widget in a box of its own, still the one node. */
export type SeparatedWidgets = {
    /** Saved as `dashboardWidgetLayout`, by widget name. */
    layout: Record<string, WidgetBoxLayout>;
    /** While the layout is edited: the boxes move and resize. */
    editable: boolean;
    onBoxChange: (name: string, box: WidgetBoxLayout) => void;
    defaultWidth: number;
    /** The tile's switches, atop the first box while the layout is edited. */
    toolbar?: React.ReactNode;
};

type NodeControlsOnly = {
    controlsOnly: boolean;
    /** Unset where the node cannot fold or its switch is not shown here. */
    setControlsOnly?: (next: boolean) => void;
    separated?: SeparatedWidgets;
};

export const NodeControlsOnlyContext = createContext<NodeControlsOnly>({ controlsOnly: false });

export const useNodeControlsOnly = () => useContext(NodeControlsOnlyContext).controlsOnly;

export const useSeparatedWidgets = () => useContext(NodeControlsOnlyContext).separated;

/** A node the switch is offered on: one holding a widget, or a Parameter node. */
export function nodeHasControls(data: any): boolean {
    if (unversionedNodeType(String(data?.nodeType ?? "")) === PARAMETER_NODE_TYPE) return true;
    return normalizeWidgets(data?.widgets).length > 0;
}

/** The "Display as widget" switch: under the widget rows, and in the folded
 * node's bar, beside Run; nothing where the node cannot fold. */
export function DisplayAsWidgetSwitch({ style }: { style?: React.CSSProperties }) {
    const { controlsOnly, setControlsOnly } = useContext(NodeControlsOnlyContext);
    if (!setControlsOnly) return null;
    return <SwitchLabel label="Display as widget" checked={controlsOnly} onChange={setControlsOnly} style={style} />;
}

/** A small labelled switch, as "Display as widget" and "Separate widgets" are drawn. */
export function SwitchLabel({
    label,
    checked,
    onChange,
    style,
}: {
    label: string;
    checked: boolean;
    onChange: (next: boolean) => void;
    style?: React.CSSProperties;
}) {
    return (
        <label className={`nodrag ${styles.displayAsWidget}`} style={style}>
            <input type="checkbox" role="switch" checked={checked} onChange={(event) => onChange(event.target.checked)} />
            {label}
        </label>
    );
}
