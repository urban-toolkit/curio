import React, { useEffect, useMemo, useState, useRef } from "react";
import { createPortal } from "react-dom";
import Tab from "react-bootstrap/Tab";
import "bootstrap/dist/css/bootstrap.min.css";
import CodeEditor from "./CodeEditor";
import GrammarEditor from "./GrammarEditor";
import WidgetsEditor from "./WidgetsEditor";
import { NodeType } from "../../constants";
import type { GrammarRedraw, NodeTemplateId } from "../../registry/types";
import { tryGetNodeDescriptor } from "../../registry/nodeRegistry";
import Col from "react-bootstrap/Col";
import Nav from "react-bootstrap/Nav";
import Row from "react-bootstrap/Row";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import "./NodeEditor.css";

import {
    faToolbox,
    faCode,
    faSpellCheck,
    faRotateLeft,
    faRightFromBracket,
} from "@fortawesome/free-solid-svg-icons";
import { ICodeData } from "../../types";
import { useFlowContext } from "../../providers/FlowProvider";
import { useNotebookViewContext } from "../../providers/flow/notebookViewContext";
import { useProvenanceDrawerOptional } from "../../providers/provenanceDrawerContext";
import { resolveInitialEditorTab } from "../../utils/canvasTemplateConfig";
import { resolveNodeDisplayLabel } from "../../utils/palettePackageFactoryDraft";
import { unversionedNodeType } from "../../utils/flowNodeCanonicalType";
import { notebookOutputBox } from "../../utils/notebookLayout";
import { useNodeHeaderSlot } from "./nodeHeaderSlot";
import { normalizeWidgets, type WidgetDef, type WidgetValue } from "../../utils/widgets/widgetModel";
import { readsAWidget } from "../../utils/widgets/datasetWidgets";
import { registerNodeSettingWriter, withWidgetValues } from "../../utils/nodeSettingsWriters";
import { isVegaLiteNodeType } from "../../registry/vegaLiteNodes";
import {
    VEGA_LITE,
    describeEmptyInputs,
    describeReferenceProblems,
    parseReference,
    resolveReferences,
    type CodeLanguage,
    type ReferenceScope,
} from "../../utils/references/codeReferences";
import { useInputScope } from "../../hook/useInputScope";
import { useSelectionViews } from "../../hook/useSelectionViews";
import { normalizeSelections, type SelectionTag } from "../../utils/references/selectionTags";
import { readSelectionRows } from "../../utils/references/viewSelections";
import { nodeLabel } from "../scenarios/scenarioLabels";
import type { ChipPreviewData } from "./widgets/ChipPreview";
import { useChipPreviewSource } from "./widgets/chipPreviewSource";
import { WidgetValueControls } from "./widgets/WidgetValueControls";

const NO_WIDGETS: WidgetDef[] = [];
const NO_SELECTIONS: SelectionTag[] = [];

/** What one resolution of the node's code came from: the code as written,
 * its chips unresolved, and the scope they were resolved in. */
type Resolution = { code: string; written: string; scope: ReferenceScope };

/**
 * How the spec of *resolution* is written again for new scenario labels: its
 * chips resolved in the same scope, each input's label replaced by *labels*',
 * so its widgets, inputs and tags stay as the run read them. Null when a chip
 * no longer resolves.
 */
function redrawOf(resolution: Resolution, language: CodeLanguage, grammar: string | undefined): GrammarRedraw {
    return (labels) => {
        const inputs = resolution.scope.inputs.map((input) =>
            labels.has(input.slot) ? { ...input, scenario: labels.get(input.slot) } : input,
        );
        const { code, problems } = resolveReferences(resolution.written, { ...resolution.scope, inputs }, language, grammar);
        return problems.length > 0 ? null : code;
    };
}

type NodeEditorProps = {
    outputId?: string;
    setSendCodeCallback: any;
    code: boolean;
    widgets: boolean;
    grammar: boolean;
    setOutputCallback: any;
    data: any;
    output: { code: string; content: string } | ICodeData;
    nodeType: NodeTemplateId;
    applyGrammar?: any;
    readOnly: boolean;
    defaultValue: any;
    floatCode?: any;
    provenance?: boolean;
    customWidgetsCallback?: any;
    contentComponent?: any;
    disableWidgets?: boolean; // Added prop to freeze widget buttons
};

function NodeEditor({
    outputId,
    setSendCodeCallback,
    code,
    widgets: widgetsTab,
    grammar,
    setOutputCallback,
    data,
    output,
    nodeType,
    applyGrammar,
    readOnly,
    defaultValue,
    floatCode,
    provenance,
    customWidgetsCallback,
    contentComponent,
    disableWidgets,
}: NodeEditorProps) {
    const [userCode, setUserCode] = useState<string>(""); // python or grammar with marks unresolved
    // Seed from the prop so the editors receive the real content on their
    // first render — an initial "" here would read as an external update to
    // GrammarEditor (whose empty model is "{}", not ""). Stays undefined for
    // nodes with no content (dev/70).
    const [defaultCode, setDefaultCode] = useState<string | undefined>(defaultValue);
    // Counts of the sends, which WidgetsEditor and the code or grammar editor
    // act on when they change. As toggles, two sends in one batch flipped the
    // flag twice and left it where it was: nothing resolved the references,
    // and a played node sat at "exec" with nothing drawn. Counted, the node
    // runs once, with the code the last send carried.
    const [markersDirty, setMarkersDirty] = useState<number>(0); // make WidgetsEditor update replacedCode
    const [replacedCode, setReplacedCode] = useState<string>(""); // python or grammar with marks resolved
    const [replacedCodeDirty, setReplacedCodeDirty] = useState<number>(0); // code has to rerun every time button is pressed (having changes or not)
    const [fullscreen, setFullscreen] = useState<string>("");
    const { dashboardOn, markDirty, markNodeStale, requestAutoRun, nodes: flowNodes } = useFlowContext();
    // A template that declares opensOnWidgets (Data Loading) opens on its
    // Widgets tab, where the user sets what its code reads, while its code
    // reads one of its widgets; its code stays on the Code tab. A node whose
    // code reads none, such as an example's literal loader, opens on its code.
    const opensOnWidgets = !dashboardOn && widgetsTab && code
        && tryGetNodeDescriptor(nodeType)?.opensOnWidgets === true;
    const widgetsFirst = (written: unknown, held: unknown) => opensOnWidgets && readsAWidget(held, written);
    // Not the literal "code": grammar-only kinds (autk-grammar, vis-vega declare
    // hasCode:false) have no code pane, so hardcoding it left NO pane active on
    // mount and the editor rendered inside a display:none tab (#157).
    const [activeTab, setActiveTab] = useState<string>(
        () => resolveInitialEditorTab({
            code, grammar, widgets: widgetsTab, widgetsFirst: widgetsFirst(defaultValue, data.widgets),
        })
    );
    // Whether the node's first tab is settled: at once for a node that
    // mounts with its code and widgets, else when they arrive, or when the
    // user picks a tab.
    const tabSettledRef = useRef(Boolean(defaultValue) && normalizeWidgets(data.widgets).length > 0);

    // #662: the node's widgets. Node data holds them (TrillGenerator saves
    // data.widgets), set directly as data.code is, so a value change does not
    // re-render the canvas; this state re-renders the editors.
    const [widgets, setWidgets] = useState<WidgetDef[]>(() => normalizeWidgets(data.widgets));
    const dataWidgets = data.widgets;
    useEffect(() => {
        // Replaced from outside: a package template's widgets seeded on drop.
        setWidgets(normalizeWidgets(dataWidgets));
    }, [dataWidgets]);
    // A fresh node takes its template's starter and widgets after it mounts:
    // it turns to its Widgets tab when they arrive, once, unless the user has
    // picked a tab.
    useEffect(() => {
        if (tabSettledRef.current || !defaultCode || widgets.length === 0) return;
        tabSettledRef.current = true;
        if (widgetsFirst(defaultCode, widgets)) setActiveTab("widgets");
    }, [defaultCode, widgets]);
    const updateWidgets = (next: WidgetDef[]) => {
        data.widgets = next;
        setWidgets(next);
        markNodeStale?.(data.nodeId);
        // A value tried on a dashboard never changes the dataflow (#1117).
        if (!dashboardOn) markDirty?.();
    };
    // An agent's applied change gives widgets new values as the Widgets tab
    // gives one (utils/nodeSettingsWriters): the node is out of date, the
    // dataflow Unsaved, and an automatic run takes it.
    const writeValuesRef = useRef<(values: Record<string, unknown>) => void>(() => undefined);
    writeValuesRef.current = (values) => {
        if (!widgets.some((widget) => Object.prototype.hasOwnProperty.call(values, widget.name))) return;
        updateWidgets(withWidgetValues(widgets, values));
        requestAutoRun?.([data.nodeId]);
    };
    useEffect(() => {
        if (!widgetsTab) return undefined;
        return registerNodeSettingWriter(data.nodeId, "widgets", (values) => writeValuesRef.current(values));
    }, [data.nodeId, widgetsTab]);
    // A control on the node's dashboard tile sets a value as the Widgets tab
    // does, and a viewer's run takes it (#1117). Read from node data, which
    // updateWidgets writes at once: two controls that settle together each
    // keep the other's value.
    const commitTileValue = (name: string, value: WidgetValue) => {
        updateWidgets(withWidgetValues(normalizeWidgets(data.widgets), { [name]: value }));
        requestAutoRun?.([data.nodeId]);
    };

    // #662: the node's selection tags, each holding the ids a view's selection
    // picks. Held in node data as widgets are (saved at metadata.selections);
    // a new selection in the view replaces them from outside
    // (providers/flow/useSelectionTags).
    const [selections, setSelections] = useState<SelectionTag[]>(() => normalizeSelections(data.selections));
    const dataSelections = data.selections;
    useEffect(() => {
        setSelections(normalizeSelections(dataSelections));
    }, [dataSelections]);
    const updateSelections = (next: SelectionTag[]) => {
        data.selections = next;
        setSelections(next);
        markNodeStale?.(data.nodeId);
        markDirty?.();
    };
    const views = useSelectionViews(data.nodeId);
    const nodeIdsKey = (Array.isArray(flowNodes) ? flowNodes : []).map((n: any) => n.id).join("\u0000");
    const nodeIds = useMemo(() => new Set(nodeIdsKey ? nodeIdsKey.split("\u0000") : []), [nodeIdsKey]);
    const widgetLanguage: CodeLanguage = grammar
        ? "json"
        : unversionedNodeType(nodeType) === NodeType.JS_COMPUTATION
            ? "javascript"
            : "python";
    // A Vega-Lite chart's spec, the built-in node's or a package template's
    // (registry/vegaLiteNodes): its references write a column's name escaped
    // where Vega-Lite reads a field.
    const referenceGrammar = grammar && isVegaLiteNodeType(nodeType) ? VEGA_LITE : undefined;

    // #662: what the node's references name: its widgets, its wired inputs
    // and its selection tags. Input, layer, column and selection tags sit above
    // its code or spec.
    const { inputs, emptyInputs, loadColumns, previews: inputPreviews, loadPreview } = useInputScope(data);
    const scope: ReferenceScope = useMemo(
        () => ({
            widgets: widgetsTab ? widgets : NO_WIDGETS,
            inputs,
            selections: widgetsTab ? selections : NO_SELECTIONS,
        }),
        [widgetsTab, widgets, inputs, selections],
    );

    // What the hover of a chip, in the code or in the header, previews
    // (ChipPreview): each input's rows, read as its tooltip first shows, and
    // each selection tag's view and the rows its ids pick there, read as its
    // tooltip shows.
    const [selectionRows, setSelectionRows] = useState<
        Record<string, { columns: string[]; rows: Record<string, unknown>[] } | { unreadable: true } | null>
    >({});
    const flowNodeList: any[] = Array.isArray(flowNodes) ? flowNodes : [];
    const viewsFound: Record<string, string> = Object.fromEntries(
        selections.map((tag) => [tag.name, nodeLabel(flowNodeList.find((node) => node.id === tag.node), tag.node)]),
    );
    const viewsSignature = JSON.stringify(viewsFound);
    const selectionPreviews = useMemo(
        () =>
            Object.fromEntries(
                Object.entries(viewsFound).map(([name, view]) => [
                    name,
                    name in selectionRows ? { view, rows: selectionRows[name] } : { view },
                ]),
            ),
        [viewsSignature, selectionRows],
    );
    const chipData: ChipPreviewData = useMemo(
        () => ({ inputs: inputPreviews, selections: selectionPreviews }),
        [inputPreviews, selectionPreviews],
    );
    const chipSnapshot = useMemo(
        () => ({ scope, language: widgetLanguage, data: chipData }),
        [scope, widgetLanguage, chipData],
    );
    const chipPreviews = useChipPreviewSource(chipSnapshot, (inner) => {
        const parsed = parseReference(inner);
        if (parsed.kind === "input") {
            if (parsed.slot !== null) loadPreview(parsed.slot);
        } else if (parsed.kind === "dataset" || parsed.kind === "stacked") {
            for (const input of inputs) loadPreview(input.slot);
        } else if (parsed.kind === "selection") {
            const tag = selections.find((one) => one.name === parsed.name);
            if (tag) {
                void readSelectionRows(tag).then((rows) => setSelectionRows((held) => ({ ...held, [tag.name]: rows })));
            }
        }
    });
    // The play callback is registered once, so a run without a Widgets tab
    // reads the scope from here.
    const runScopeRef = useRef({ scope, emptyInputs, referenceGrammar });
    runScopeRef.current = { scope, emptyInputs, referenceGrammar };
    // The code last handed to the widgets, its chips unresolved, and what the
    // last resolution came from, so a grammar node's spec can be written again
    // for new scenario labels.
    const userCodeRef = useRef("");
    const resolutionRef = useRef<Resolution | null>(null);
    // A grammar node's spec reaches its behavior with how to write it again
    // when a scenario box is renamed or recolored (registry/types,
    // GrammarRedraw): a chart is then drawn again outside a run, its chips
    // resolved anew. Only for the spec this editor resolved.
    const applyGrammarWithRedraw = applyGrammar
        ? (spec: string) => {
            const resolution = resolutionRef.current;
            const redraw = resolution && resolution.code === spec
                ? redrawOf(resolution, widgetLanguage, referenceGrammar)
                : undefined;
            return applyGrammar(spec, redraw);
        }
        : undefined;
    // A dashboard tile shows its output, not its editor, when it HAS an output
    // pane, a chart's or a map's. A code node's result is the text box under
    // its editor, so forcing the pane unconditionally rendered a pinned code
    // node as an empty tile with nothing reachable on it: it shows its code.
    // A node with widgets shows them as the tile's controls (#1117): above its
    // chart or map, which fills the rest of the tile, or in place of a code
    // node's code, whose pane stays mounted and hidden, since its editor holds
    // the node's run.
    const hasOutputPane = outputId != undefined || contentComponent != undefined;
    const tileControls = dashboardOn && widgetsTab && widgets.length > 0;
    const controlsAboveOutput = tileControls && hasOutputPane;
    // A notebook cell shows its input and its output at once: the output pane
    // stays visible under the input tabs (Node.css), so a run, which would
    // switch to the Output tab, leaves the input tab in place.
    const notebook = useNotebookViewContext();
    // A notebook cell is as tall as its content: nothing here fills a fixed
    // box, and the output gets the height its kind gets in a cell
    // (notebookOutputBox).
    const inCell = notebook.on && !dashboardOn;
    const split = inCell && hasOutputPane && Boolean(code || grammar);
    const effectiveTab = dashboardOn && hasOutputPane
        ? "output"
        : tileControls
            ? "controls"
            : split && activeTab === "output"
                ? resolveInitialEditorTab({ code, grammar, widgets: widgetsTab })
                : activeTab;

    const contentComponentBypass = useRef(false);
    // Set while a *load* is priming the widgets, so the marker round-trip it
    // triggers does not steal the active tab. Only the load path sets it; a play
    // leaves it false and still focuses the output pane.
    //
    // Deliberately a flag rather than inferring "is this a run?" from
    // `output.code === "exec"`: play sets exec and calls sendCode in the same
    // tick, so a hasWidgets=false node's synchronous route reads the stale prop
    // and would never focus its output pane again.
    const primingWidgetsRef = useRef(false);

    const sendReplacedCode = (code: string) => {
        resolutionRef.current = { code, written: userCodeRef.current, scope: runScopeRef.current.scope };
        const priming = primingWidgetsRef.current;
        primingWidgetsRef.current = false;
        if (!priming && (fullscreen == "" || fullscreen == undefined) && (outputId != undefined || contentComponent != undefined)) setActiveTab("output");
        setReplacedCode(code);
        setReplacedCodeDirty((prev: number) => prev + 1);
    };

    /** A reference that does not resolve: on a run, the run ends with the
     * message; on a load, the Widgets tab lists it and nothing else happens. */
    const resolveError = (message: string) => {
        const priming = primingWidgetsRef.current;
        primingWidgetsRef.current = false;
        if (priming) return;
        setOutputCallback?.({ code: "error", content: message });
    };

    const sendCodeToWidgets = (code: string) => {
        userCodeRef.current = String(code ?? "");
        setUserCode(code);
        if (!widgetsTab) {
            // Why: WidgetsEditor is the bridge that resolves references and
            // hands the result to CodeEditor (via sendReplacedCode). It only
            // mounts when the widgets tab is enabled, so for code nodes with
            // hasWidgets=false (e.g. js-computation) a change of markersDirty
            // has no listener and CodeEditor's interpretCode is never reached:
            // the play spinner spins forever. Resolve here instead, with the
            // same table, so input chips work in those nodes too.
            const { scope: runScope, emptyInputs: waiting, referenceGrammar: runGrammar } = runScopeRef.current;
            const resolved = resolveReferences(String(code ?? ""), runScope, widgetLanguage, runGrammar);
            if (waiting.length > 0) resolveError(describeEmptyInputs(waiting, runScope.inputs));
            else if (resolved.problems.length > 0) resolveError(describeReferenceProblems(resolved.problems));
            else sendReplacedCode(resolved.code);
            return;
        }
        setMarkersDirty((prev: number) => prev + 1);
    };

    /** ``sendCodeToWidgets`` for the load path: resolve markers, keep the tab.
     *
     * CodeEditor and GrammarEditor call this from their ``defaultValue`` effect
     * so a templated node's widgets exist before the first run. Switching tabs
     * there would drop the user on the output pane of a node they just opened.
     */
    const primeWidgets = (code: string) => {
        primingWidgetsRef.current = true;
        sendCodeToWidgets(code);
    };

    useEffect(() => {
        // The play path deliberately gets the un-suppressed version.
        setSendCodeCallback(sendCodeToWidgets);
        // Unregister on unmount. An editor the per-node ErrorBoundary has
        // replaced otherwise leaves a live-looking callback behind, so a later
        // play sets "exec", calls into a dead tree and never completes -
        // wedging Run All for the whole dataflow (#271). With it gone,
        // UniversalNode's `!sendCode` branch releases the runner instead.
        return () => setSendCodeCallback(undefined);
    }, []);

    useEffect(() => {
        if (
            contentComponent != undefined &&
            contentComponentBypass.current &&
            (fullscreen == "" || fullscreen == undefined)
        ) {
            setActiveTab("output");
        }

        contentComponentBypass.current = true;
    }, [contentComponent]);

    useEffect(() => {
        setDefaultCode(defaultValue);
    }, [defaultValue]);

    // A run put back from the provenance drawer. The editors write its code in
    // as content that arrived whole and prime the widgets, as a load does, so
    // nothing runs, no input error is raised and the node does not jump to its
    // output; then the editor is shown with that code. Each put-back is a new
    // one, so the first run's code goes back in even when it is the code the
    // node loaded with. Read through a ref: the drawer keeps the callback while
    // the node re-renders.
    const [restoredCode, setRestoredCode] = useState<{ code: string; nonce: number } | null>(null);
    const restoreRunRef = useRef<(runCode: string) => void>(() => undefined);
    restoreRunRef.current = (runCode: string) => {
        setRestoredCode((prev) => ({ code: runCode, nonce: (prev?.nonce ?? 0) + 1 }));
        if (code || grammar) setActiveTab(resolveInitialEditorTab({ code, grammar, widgets: false }));
    };

    // The Provenance pill is not a tab: it opens the node's runs in the
    // provenance drawer, and the node keeps the pane it shows.
    const provenanceDrawer = useProvenanceDrawerOptional();
    const handleTabSelect = (eventKey: any) => {
        if (eventKey === "provenance") {
            provenanceDrawer?.openNodeProvenance({
                nodeId: data.nodeId,
                title: resolveNodeDisplayLabel({ nodeType, packageTemplateLabel: data.packageTemplateLabel }),
                restore: (runCode: string) => restoreRunRef.current(runCode),
            });
            return;
        }
        tabSettledRef.current = true;
        setActiveTab(eventKey);
    };

    // The panes sit on the node's white, as a notebook cell's do; a dashboard
    // tile keeps its gray panel.
    const tabContentStyle: CSS.Properties = inCell
        ? { backgroundColor: "#ffffff" }
        : dashboardOn
            ? {
                height: "100%",
                backgroundColor: "#f2f2f2",
                borderRadius: "10px",
            }
            : { height: "100%", backgroundColor: "#ffffff" };
    // A pane fills the node on the canvas; in a cell it takes its own height.
    const paneStyle: CSS.Properties | undefined = inCell ? undefined : { height: "100%" };
    const widgetsPaneStyle: CSS.Properties = inCell ? { maxHeight: "360px", overflowY: "auto" } : { height: "100%" };
    const outputBox = notebookOutputBox(String(nodeType ?? ""));
    const px = (n: number | undefined) => (n === undefined ? undefined : `${n}px`);

    const tabContentFullscreen: CSS.Properties = {
        height: "100%",
        // marginTop: "auto",
        // marginBottom: "auto",
        width: "100%",
        position: "fixed",
        top: 0,
        left: 0,
        backgroundColor: "#f2f2f2",
        borderRadius: "10px",
    };

    const activeTabContentStyle =
        fullscreen != "" && fullscreen != undefined
            ? tabContentFullscreen
            : tabContentStyle;

    const navItemStyle: CSS.Properties = {
        maxWidth: "100%",
    };

    const navLinkStyle: CSS.Properties = {
        display: "flex",
        justifyContent: "center",
    };

    // The tab pills: among the node's tools in its header, on the canvas and in
    // a notebook cell alike (nodeHeaderSlot, styled by `.curio-node-tabs` in
    // Node.css), or above the panes when the node has no header to hold them.
    const tabSlot = useNodeHeaderSlot();
    const pillsInHeader = tabSlot !== null;
    const pills = !dashboardOn ? (
        <Nav
            variant="pills"
            className="flex-column"
            style={pillsInHeader ? { background: "none", margin: 0 } : {
                backgroundColor: "#f2f2f2",
                borderRadius: "10px",
                width: "40%",
                height: "25px",
                marginLeft: "auto",
                marginTop: "4px",
                marginBottom: "6px",
            }}
        >
            <Row
                style={{
                    fontSize: "10px",
                    paddingRight: 0,
                    paddingLeft: 0,
                }}
            >
                {code ? (
                    <Col>
                        {/* Each tab is an icon: its name is the word its
                            tooltip shows. */}
                        <Nav.Item style={navItemStyle}>
                            <Nav.Link
                                eventKey="code"
                                style={navLinkStyle}
                                aria-label="Code"
                                data-tooltip="Code"
                            >
                                <FontAwesomeIcon
                                    icon={faCode}
                                />
                            </Nav.Link>
                        </Nav.Item>
                    </Col>
                ) : null}

                {widgetsTab ? (
                    <Col>
                        <Nav.Item style={navItemStyle}>
                            <Nav.Link
                                eventKey="widgets"
                                style={navLinkStyle}
                                aria-label="Widgets"
                                data-tooltip="Widgets"
                            >
                                <FontAwesomeIcon
                                    icon={faToolbox}
                                />
                            </Nav.Link>
                        </Nav.Item>
                    </Col>
                ) : null}

                {grammar ? (
                    <Col>
                        <Nav.Item style={navItemStyle}>
                            <Nav.Link
                                eventKey="grammar"
                                style={navLinkStyle}
                                aria-label="Grammar"
                                data-tooltip="Grammar"
                            >
                                <FontAwesomeIcon
                                    icon={faSpellCheck}
                                />
                            </Nav.Link>
                        </Nav.Item>
                    </Col>
                ) : null}

                {provenance == undefined || provenance ? (
                    <Col>
                        <Nav.Item style={navItemStyle}>
                            <Nav.Link
                                eventKey="provenance"
                                style={navLinkStyle}
                                aria-label="Provenance"
                                data-tooltip="Provenance"
                            >
                                <FontAwesomeIcon
                                    icon={faRotateLeft}
                                />
                            </Nav.Link>
                        </Nav.Item>
                    </Col>
                ) : null}

                {(outputId != undefined || contentComponent != undefined) && !split ? (
                    <Col>
                        <Nav.Item style={navItemStyle}>
                            <Nav.Link
                                eventKey="output"
                                style={navLinkStyle}
                                aria-label="Output"
                                data-tooltip="Output"
                            >
                                <FontAwesomeIcon
                                    icon={faRightFromBracket}
                                />
                            </Nav.Link>
                        </Nav.Item>
                    </Col>
                ) : null}
            </Row>
        </Nav>
    ) : null;

    // Under a tile's controls the output fills what they leave.
    const belowControls: CSS.Properties = { flex: 1, minHeight: 0 };
    const outputMount = outputId != undefined ? (
        // Vega sizes its canvas in CSS px from the compiled spec, so a
        // multi-view chart is taller than the pane and was simply cut off
        // (#202). This div scrolls now; the parent Tab.Pane stays
        // overflow:hidden so the node box itself cannot spill onto the
        // canvas.
        //
        // `nowheel` is load-bearing, not decoration: without it React Flow's
        // ZoomPane swallows the wheel event and zooms the canvas instead of
        // scrolling the chart.
        //
        // In a cell the chart needs a definite height to fit to.
        <div
            id={outputId}
            className="nodrag nowheel curio-vega-mount"
            style={{
                textAlign: "center",
                width: "100%",
                ...(controlsAboveOutput ? belowControls : { height: inCell ? px(outputBox.height) : "100%" }),
                ...(inCell && outputBox.maxHeight !== undefined ? { maxHeight: px(outputBox.maxHeight) } : {}),
                overflow: "auto",
            }}
        ></div>
    ) : contentComponent != undefined ? (
        // Each content component lays out and scrolls its own body. In a cell
        // its box comes from its kind.
        <div
            className="curio-content-mount"
            style={inCell
                ? { height: px(outputBox.height), maxHeight: px(outputBox.maxHeight), overflow: outputBox.overflow }
                : controlsAboveOutput ? belowControls : { height: "100%" }}
        >
            {contentComponent}
        </div>
    ) : null;

    return (
        <>
            <div
                style={{
                    ...{
                        height: inCell ? "auto" : "100%",
                        width: "100%",
                        marginLeft: "auto",
                        marginRight: "auto",
                    },
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                }}
            >
                <Tab.Container activeKey={effectiveTab} onSelect={handleTabSelect}>
                    {!pillsInHeader && pills}
                    {pillsInHeader && pills ? createPortal(pills, tabSlot!) : null}
                    {/* No gutter: its negative margins pulled every pane out of
                        the node body, under the port markers (#668). */}
                    <Row className="g-0" style={inCell ? undefined : { height: "100%" }}>
                        <Col md={12} style={inCell ? { padding: 0 } : { height: "100%", padding: 0 }}>
                            <Tab.Content
                                className={split ? "curio-notebook-split" : undefined}
                                style={{ ...activeTabContentStyle, zIndex: 10 }}
                            >
                                {tileControls && !hasOutputPane ? (
                                    <Tab.Pane eventKey="controls" style={paneStyle}>
                                        <WidgetValueControls
                                            widgets={widgets}
                                            dashboard
                                            disabled={disableWidgets}
                                            onCommit={commitTileValue}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {code ? (
                                    <Tab.Pane
                                        eventKey="code"
                                        style={paneStyle}
                                    >
                                        <CodeEditor
                                            floatCode={floatCode}
                                            // A tile's code is read-only: Save
                                            // layout would save a stray edit.
                                            readOnly={readOnly || !!dashboardOn}
                                            defaultValue={defaultCode}
                                            replacedCodeDirty={
                                                replacedCodeDirty
                                            }
                                            replacedCode={replacedCode}
                                            sendCodeToWidgets={primeWidgets}
                                            setOutputCallback={
                                                setOutputCallback
                                            }
                                            data={data}
                                            output={output}
                                            nodeType={nodeType}
                                            references={scope}
                                            stripInputs={inputs}
                                            onLoadColumns={loadColumns}
                                            widgetLanguage={widgetLanguage}
                                            chipPreviews={chipPreviews}
                                            restoredCode={restoredCode}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {widgetsTab ? (
                                    <Tab.Pane
                                        eventKey="widgets"
                                        style={widgetsPaneStyle}
                                    >
                                        <WidgetsEditor
                                            customWidgetsCallback={
                                                customWidgetsCallback
                                            }
                                            markersDirty={markersDirty}
                                            sendReplacedCode={sendReplacedCode}
                                            userCode={userCode}
                                            nodeId={data.nodeId}
                                            data={{...data, nodeType}}
                                            disableWidgets={disableWidgets}
                                            valuesOnly={dashboardOn}
                                            widgets={widgets}
                                            onWidgetsChange={updateWidgets}
                                            onValueChange={() => requestAutoRun?.([data.nodeId])}
                                            language={widgetLanguage}
                                            grammar={referenceGrammar}
                                            onResolveError={resolveError}
                                            inputs={inputs}
                                            emptyInputs={emptyInputs}
                                            selections={selections}
                                            onSelectionsChange={updateSelections}
                                            views={views}
                                            nodeIds={nodeIds}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {grammar ? (
                                    <Tab.Pane
                                        eventKey="grammar"
                                        style={paneStyle}
                                    >
                                        <GrammarEditor
                                            floatCode={floatCode}
                                            readOnly={readOnly}
                                            defaultValue={defaultCode}
                                            replacedCodeDirty={
                                                replacedCodeDirty
                                            }
                                            output={output}
                                            replacedCode={replacedCode}
                                            sendCodeToWidgets={primeWidgets}
                                            nodeId={data.nodeId}
                                            applyGrammar={applyGrammarWithRedraw}
                                            setOutputCallback={setOutputCallback}
                                            references={scope}
                                            stripInputs={inputs}
                                            onLoadColumns={loadColumns}
                                            widgetLanguage={widgetLanguage}
                                            referenceGrammar={referenceGrammar}
                                            chipPreviews={chipPreviews}
                                            restoredCode={restoredCode}
                                        />
                                    </Tab.Pane>
                                ) : null}


                                {(outputId != undefined || contentComponent != undefined) ? (
                                    <Tab.Pane
                                        eventKey="output"
                                        className={split ? "curio-notebook-output" : undefined}
                                        style={inCell ? undefined : { height: "100%", overflow: "hidden" }}
                                    >
                                        {controlsAboveOutput ? (
                                            // The controls at their own
                                            // height, and the output below
                                            // filling the rest of the tile.
                                            <div
                                                data-tile-column="true"
                                                style={{ display: "flex", flexDirection: "column", height: "100%" }}
                                            >
                                                <WidgetValueControls
                                                    widgets={widgets}
                                                    dashboard
                                                    disabled={disableWidgets}
                                                    onCommit={commitTileValue}
                                                    aboveOutput
                                                />
                                                {outputMount}
                                            </div>
                                        ) : outputMount}
                                    </Tab.Pane>
                                ) : null}
                            </Tab.Content>
                        </Col>
                    </Row>
                </Tab.Container>
            </div>
        </>
    );
}

export default NodeEditor;
