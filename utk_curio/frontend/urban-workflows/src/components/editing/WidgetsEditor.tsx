import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import "./WidgetsEditor.css";
import styles from "./widgets/WidgetTags.module.css";
import { SharedTag, WidgetTag, uniqueSharedNames } from "./widgets/WidgetTag";
import { WidgetControl } from "./widgets/WidgetControl";
import { WidgetForm } from "./widgets/WidgetForm";
import { SelectionSection } from "./widgets/SelectionTags";
import { DisplayAsWidgetSwitch, useSeparatedWidgets } from "./nodeControlsOnly";
import { SeparatedWidgetBox } from "./widgets/SeparatedWidgetBox";
import { checkWidgetValue, effectiveValue, type WidgetDef } from "../../utils/widgets/widgetModel";
import type { SelectionTag } from "../../utils/references/selectionTags";
import type { SelectionView } from "../../hook/useSelectionViews";
import {
    describeEmptyInputs,
    describeReferenceProblems,
    resolveReferences,
    widgetLiteral,
    type CodeLanguage,
    type InputScope,
} from "../../utils/references/codeReferences";

const NO_INPUTS: InputScope[] = [];
const NO_SLOTS: number[] = [];
const NO_SHARED: WidgetDef[] = [];
const NO_SELECTIONS: SelectionTag[] = [];
const NO_VIEWS: SelectionView[] = [];
const NO_NODE_IDS: ReadonlySet<string> = new Set();
const keepSelections = () => {};

type WidgetsEditorProps = {
    userCode: any; // grammar or python, references unresolved
    sendReplacedCode: (code: string) => void; // bubble up the code with the references resolved
    nodeId: string;
    markersDirty: boolean; // a toggle here resolves the references and sends the code on
    /** #662: the node's widgets, declared here and saved at metadata.widgets. */
    widgets: WidgetDef[];
    onWidgetsChange: (widgets: WidgetDef[]) => void;
    /** The language the node's code is written in, which decides how a value is written into it. */
    language: CodeLanguage;
    /** A reference that cannot be resolved: the run ends with this message. */
    onResolveError: (message: string) => void;
    /** The node's wired inputs, which its input and column references name. */
    inputs?: InputScope[];
    /** Wired circles that hold no value yet: a run waits for them. */
    emptyInputs?: number[];
    /** The Parameter nodes' widgets, offered under Shared as `[!! @name !!]`. */
    shared?: WidgetDef[];
    /** The node's selection tags, `[!! selection name !!]`, saved at metadata.selections. */
    selections?: SelectionTag[];
    onSelectionsChange?: (selections: SelectionTag[]) => void;
    /** The views a selection tag can read: the dataflow's Vega-Lite and Autark nodes. */
    views?: SelectionView[];
    /** Every node of the dataflow, so a tag whose view was deleted says so. */
    nodeIds?: ReadonlySet<string>;
    customWidgetsCallback?: any;
    data?: any;
    disableWidgets?: boolean; // freeze the widget controls instead of hiding them
    /** "Display as widget": each widget's label and control, nothing to edit. */
    compact?: boolean;
};

type Editing = { mode: "add" } | { mode: "edit"; name: string } | null;

/**
 * A node's Widgets tab (#662). Widgets are declared here, not typed into the
 * code: each one shows as a tag, which is dragged into the code (or clicked in
 * the strip above it) as a `[!! name !!]` reference. On a run, every reference
 * is replaced by its widget's value before the code goes to the sandbox.
 */
function WidgetsEditor({
    userCode,
    sendReplacedCode,
    nodeId,
    markersDirty,
    widgets,
    onWidgetsChange,
    language,
    onResolveError,
    inputs = NO_INPUTS,
    emptyInputs = NO_SLOTS,
    shared = NO_SHARED,
    selections = NO_SELECTIONS,
    onSelectionsChange = keepSelections,
    views = NO_VIEWS,
    nodeIds = NO_NODE_IDS,
    customWidgetsCallback,
    disableWidgets,
    compact = false,
}: WidgetsEditorProps) {
    const markersDirtyBypass = useRef(false);
    const [editing, setEditing] = useState<Editing>(null);
    const scope = useMemo(
        () => ({ widgets, inputs, shared, selections }),
        [widgets, inputs, shared, selections],
    );
    const sharedNames = uniqueSharedNames(shared);

    useEffect(() => {
        if (markersDirtyBypass.current) {
            const { code, problems } = resolveReferences(String(userCode ?? ""), scope, language);
            if (emptyInputs.length > 0) onResolveError(describeEmptyInputs(emptyInputs, inputs));
            else if (problems.length > 0) onResolveError(describeReferenceProblems(problems));
            else sendReplacedCode(code);
        }
        markersDirtyBypass.current = true;
    }, [markersDirty]);

    useEffect(() => {
        if (customWidgetsCallback != undefined) {
            customWidgetsCallback(document.getElementById("widgetsEditor" + nodeId));
        }
    }, []);

    const problems = useMemo(
        () => resolveReferences(String(userCode ?? ""), scope, language).problems,
        [userCode, scope, language],
    );

    // A dashboard tile with "Separate widgets" on: each widget in a box of its
    // own. A box not placed yet stands under the one before it, as measured.
    const separatedLayout = useSeparatedWidgets();
    const separated = compact ? separatedLayout : undefined;
    const boxEls = useRef<Record<string, HTMLDivElement | null>>({});
    const [boxHeights, setBoxHeights] = useState<Record<string, number>>({});
    useLayoutEffect(() => {
        if (!separated) return;
        const next: Record<string, number> = {};
        for (const w of widgets) next[w.name] = boxEls.current[w.name]?.offsetHeight ?? 0;
        if (JSON.stringify(next) !== JSON.stringify(boxHeights)) setBoxHeights(next);
    });

    const setValue = (name: string, value: any) =>
        onWidgetsChange(widgets.map((w) => (w.name === name ? { ...w, value } : w)));

    const saveEdited = (previous: WidgetDef, next: WidgetDef) => {
        // The set value survives an edit that keeps it valid.
        const keep =
            previous.value !== undefined &&
            previous.type === next.type &&
            checkWidgetValue(next, previous.value) === null;
        const edited: WidgetDef = keep ? { ...next, value: previous.value } : next;
        onWidgetsChange(widgets.map((w) => (w.name === previous.name ? edited : w)));
        setEditing(null);
    };

    if (separated) {
        let stackedY = 0;
        return (
            <div id={"widgetsEditor" + nodeId} className={styles.separatedLayer} data-widgets-panel="true">
                {widgets.map((widget, index) => {
                    const fallback = { x: 0, y: stackedY };
                    stackedY += (boxHeights[widget.name] || 60) + 12;
                    return (
                        <SeparatedWidgetBox
                            key={widget.name}
                            nodeId={nodeId}
                            name={widget.name}
                            box={separated.layout[widget.name] ?? fallback}
                            defaultWidth={separated.defaultWidth}
                            editable={separated.editable}
                            onChange={(box) => separated.onBoxChange(widget.name, box)}
                            header={index === 0 ? separated.toolbar : null}
                            boxRef={(el) => {
                                boxEls.current[widget.name] = el;
                            }}
                        >
                            <div className={styles.row} data-widget-row={widget.name}>
                                <span className={styles.rowLabel}>{widget.label || widget.name}</span>
                                <span className={styles.rowControl}>
                                    <WidgetControl
                                        widget={widget}
                                        value={effectiveValue(widget)}
                                        disabled={disableWidgets}
                                        onChange={(value) => setValue(widget.name, value)}
                                    />
                                </span>
                            </div>
                        </SeparatedWidgetBox>
                    );
                })}
            </div>
        );
    }

    return (
        <div
            id={"widgetsEditor" + nodeId}
            className={`nowheel nodrag ${styles.panel}${widgets.length > 0 && !compact ? ` ${styles.panelWithSwitch}` : ""}`}
            data-widgets-panel="true"
        >
            {widgets.length === 0 && editing === null && !compact ? (
                <p className={styles.empty}>
                    No widgets yet. Add one, then drag its tag into the code.
                </p>
            ) : null}
            {widgets.map((widget) =>
                editing?.mode === "edit" && editing.name === widget.name ? (
                    <WidgetForm
                        key={widget.name}
                        initial={widget}
                        others={widgets.filter((w) => w.name !== widget.name)}
                        onSave={(next) => saveEdited(widget, next)}
                        onCancel={() => setEditing(null)}
                    />
                ) : (
                    <div key={widget.name} className={styles.row} data-widget-row={widget.name}>
                        <span className={styles.rowLabel}>{widget.label || widget.name}</span>
                        {!compact ? <WidgetTag name={widget.name} disabled={disableWidgets} /> : null}
                        <span className={styles.rowControl}>
                            <WidgetControl
                                widget={widget}
                                value={effectiveValue(widget)}
                                disabled={disableWidgets}
                                onChange={(value) => setValue(widget.name, value)}
                            />
                        </span>
                        {!compact ? (
                            <span className={styles.rowActions}>
                                <button
                                    type="button"
                                    className={styles.button}
                                    aria-label={`Edit widget ${widget.name}`}
                                    disabled={disableWidgets || editing !== null}
                                    onClick={() => setEditing({ mode: "edit", name: widget.name })}
                                >
                                    Edit
                                </button>
                                <button
                                    type="button"
                                    className={styles.danger}
                                    aria-label={`Delete widget ${widget.name}`}
                                    disabled={disableWidgets || editing !== null}
                                    onClick={() => onWidgetsChange(widgets.filter((w) => w.name !== widget.name))}
                                >
                                    Delete
                                </button>
                            </span>
                        ) : null}
                    </div>
                ),
            )}
            {compact ? null : editing?.mode === "add" ? (
                <WidgetForm
                    others={widgets}
                    onSave={(def) => {
                        onWidgetsChange([...widgets, def]);
                        setEditing(null);
                    }}
                    onCancel={() => setEditing(null)}
                />
            ) : (
                <button
                    type="button"
                    className={`${styles.primary} ${styles.add}`}
                    disabled={disableWidgets || editing !== null}
                    onClick={() => setEditing({ mode: "add" })}
                >
                    Add widget
                </button>
            )}
            {!compact ? (
                <SelectionSection
                    selections={selections}
                    onSelectionsChange={onSelectionsChange}
                    views={views}
                    allNodeIds={nodeIds}
                    disabled={disableWidgets}
                    locked={editing !== null}
                />
            ) : null}
            {sharedNames.length > 0 && !compact ? (
                <div className={styles.shared} data-shared-panel="true">
                    <p className={styles.sharedHeading}>Shared</p>
                    {sharedNames.map((name) => {
                        const widget = shared.find((w) => w.name === name) as WidgetDef;
                        return (
                            <div
                                key={name}
                                className={styles.row}
                                data-shared-row={name}
                                title="Set in its Parameter node"
                            >
                                <span className={styles.rowLabel}>{widget.label || name}</span>
                                <SharedTag name={name} disabled={disableWidgets} />
                                <span className={styles.sharedValue}>
                                    {widgetLiteral(effectiveValue(widget), language)}
                                </span>
                            </div>
                        );
                    })}
                </div>
            ) : null}
            {problems.length > 0 ? (
                <ul className={styles.problems} aria-label="References that do not resolve">
                    {problems.map((p, index) => (
                        <li key={`${index}:${p.reference}`}>{p.message}</li>
                    ))}
                </ul>
            ) : null}
            {widgets.length > 0 && !compact ? <DisplayAsWidgetSwitch /> : null}
        </div>
    );
}

export default WidgetsEditor;
