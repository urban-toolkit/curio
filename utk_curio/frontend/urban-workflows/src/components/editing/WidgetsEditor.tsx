import React, { useEffect, useMemo, useRef, useState } from "react";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import "./WidgetsEditor.css";
import styles from "./widgets/WidgetTags.module.css";
import { SharedTag, WidgetTag, uniqueSharedNames } from "./widgets/WidgetTag";
import { WidgetControl } from "./widgets/WidgetControl";
import { WidgetForm } from "./widgets/WidgetForm";
import { checkWidgetValue, effectiveValue, type WidgetDef } from "../../utils/widgets/widgetModel";
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
    customWidgetsCallback?: any;
    data?: any;
    disableWidgets?: boolean; // freeze the widget controls instead of hiding them
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
    customWidgetsCallback,
    disableWidgets,
}: WidgetsEditorProps) {
    const markersDirtyBypass = useRef(false);
    const [editing, setEditing] = useState<Editing>(null);
    const scope = useMemo(() => ({ widgets, inputs, shared }), [widgets, inputs, shared]);
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

    return (
        <div
            id={"widgetsEditor" + nodeId}
            className={`nowheel nodrag ${styles.panel}`}
            data-widgets-panel="true"
        >
            {widgets.length === 0 && editing === null ? (
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
                        <WidgetTag name={widget.name} disabled={disableWidgets} />
                        <span className={styles.rowControl}>
                            <WidgetControl
                                widget={widget}
                                value={effectiveValue(widget)}
                                disabled={disableWidgets}
                                onChange={(value) => setValue(widget.name, value)}
                            />
                        </span>
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
                    </div>
                ),
            )}
            {editing?.mode === "add" ? (
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
            {sharedNames.length > 0 ? (
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
        </div>
    );
}

export default WidgetsEditor;
