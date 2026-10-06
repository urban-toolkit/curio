import React, { useEffect, useMemo, useState, useRef } from "react";
import Tab from "react-bootstrap/Tab";
import Tabs from "react-bootstrap/Tabs";
import "bootstrap/dist/css/bootstrap.min.css";
import CodeEditor from "./CodeEditor";
import GrammarEditor from "./GrammarEditor";
import WidgetsEditor from "./WidgetsEditor";
import { NodeType } from "../../constants";
import { NodeTemplateId } from "../../registry/types";
import NodeProvenance from "./NodeProvenance";
import Col from "react-bootstrap/Col";
import Nav from "react-bootstrap/Nav";
import Row from "react-bootstrap/Row";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import "./NodeEditor.css";

import {
    faGear,
    faCircleInfo,
    faCirclePlay,
    faExpand,
    faToolbox,
    faCode,
    faList,
    faSpellCheck,
    faRotateLeft,
    faRightFromBracket,
} from "@fortawesome/free-solid-svg-icons";
import { OverlayTrigger, Tooltip } from "react-bootstrap";
import { ICodeData } from "../../types";
import { useFlowContext } from "../../providers/FlowProvider";
import { useNotebookViewContext } from "../../providers/flow/notebookViewContext";
import { resolveInitialEditorTab } from "../../utils/canvasTemplateConfig";
import { unversionedNodeType } from "../../utils/flowNodeCanonicalType";
import { notebookOutputBox } from "../../utils/notebookLayout";
import { normalizeWidgets, type WidgetDef } from "../../utils/widgets/widgetModel";
import {
    describeEmptyInputs,
    describeReferenceProblems,
    resolveReferences,
    type CodeLanguage,
    type ReferenceScope,
} from "../../utils/references/codeReferences";
import { useInputScope } from "../../hook/useInputScope";
import { useSharedWidgets } from "../../hook/useSharedWidgets";
import { useSelectionViews } from "../../hook/useSelectionViews";
import { normalizeSelections, type SelectionTag } from "../../utils/references/selectionTags";

const NO_WIDGETS: WidgetDef[] = [];
const NO_SELECTIONS: SelectionTag[] = [];

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
    schema?: any;
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
    schema,
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
    const [markersDirty, setMarkersDirty] = useState<boolean>(false); // make WidgetsEditor update replacedCode
    const [replacedCode, setReplacedCode] = useState<string>(""); // python or grammar with marks resolved
    const [replacedCodeDirty, setReplacedCodeDirty] = useState<boolean>(false); // code has to rerun every time button is pressed (having changes or not)
    const [fullscreen, setFullscreen] = useState<string>("");
    // Not the literal "code": grammar-only kinds (autk-grammar, vis-vega declare
    // hasCode:false) have no code pane, so hardcoding it left NO pane active on
    // mount and the editor rendered inside a display:none tab (#157).
    const [activeTab, setActiveTab] = useState<string>(
        () => resolveInitialEditorTab({ code, grammar, widgets: widgetsTab })
    );
    const { dashboardOn, markDirty, markNodeStale, nodes: flowNodes } = useFlowContext();

    // #662: the node's widgets. Node data holds them (TrillGenerator saves
    // data.widgets), set directly as data.code is, so a value change does not
    // re-render the canvas; this state re-renders the editors.
    const [widgets, setWidgets] = useState<WidgetDef[]>(() => normalizeWidgets(data.widgets));
    const dataWidgets = data.widgets;
    useEffect(() => {
        // Replaced from outside: a package template's widgets seeded on drop.
        setWidgets(normalizeWidgets(dataWidgets));
    }, [dataWidgets]);
    const updateWidgets = (next: WidgetDef[]) => {
        data.widgets = next;
        setWidgets(next);
        markNodeStale?.(data.nodeId);
        markDirty?.();
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

    // #662: what the node's references name: its widgets, its wired inputs,
    // the Parameter nodes' shared tags and its selection tags. Input, layer,
    // column, selection and shared tags sit above its code or spec.
    const { inputs, emptyInputs, loadColumns } = useInputScope(data);
    const shared = useSharedWidgets();
    const scope: ReferenceScope = useMemo(
        () => ({
            widgets: widgetsTab ? widgets : NO_WIDGETS,
            inputs,
            shared,
            selections: widgetsTab ? selections : NO_SELECTIONS,
        }),
        [widgetsTab, widgets, inputs, shared, selections],
    );
    // The play callback is registered once, so a run without a Widgets tab
    // reads the scope from here.
    const runScopeRef = useRef({ scope, emptyInputs });
    runScopeRef.current = { scope, emptyInputs };
    // A dashboard tile shows its output, not its editor. Only when it HAS an
    // output pane: a code node's result is the text box under its editor, so
    // forcing the pane unconditionally rendered a pinned code node as an empty
    // tile with nothing reachable on it.
    const hasOutputPane = outputId != undefined || contentComponent != undefined;
    // A notebook cell shows its input and its output at once: the output pane
    // stays visible under the input tabs (Node.css), so a run, which would
    // switch to the Output tab, leaves the input tab in place.
    const notebook = useNotebookViewContext();
    // A notebook cell is as tall as its content: nothing here fills a fixed
    // box, the tab pills sit above the input, and the output gets the height
    // its kind gets in a cell (notebookOutputBox).
    const inCell = notebook.on && !dashboardOn;
    const split = inCell && hasOutputPane && Boolean(code || grammar);
    const effectiveTab = dashboardOn && hasOutputPane
        ? "output"
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
        const priming = primingWidgetsRef.current;
        primingWidgetsRef.current = false;
        if (!priming && (fullscreen == "" || fullscreen == undefined) && (outputId != undefined || contentComponent != undefined)) setActiveTab("output");
        setReplacedCode(code);
        setReplacedCodeDirty((prev: boolean) => {
            return !prev;
        });
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
        setUserCode(code);
        if (!widgetsTab) {
            // Why: WidgetsEditor is the bridge that resolves references and
            // hands the result to CodeEditor (via sendReplacedCode). It only
            // mounts when the widgets tab is enabled, so for code nodes with
            // hasWidgets=false (e.g. js-computation) the markersDirty toggle
            // has no listener and CodeEditor's interpretCode is never reached
            // — the play spinner spins forever. Resolve here instead, with the
            // same table, so input chips work in those nodes too.
            const { scope: runScope, emptyInputs: waiting } = runScopeRef.current;
            const resolved = resolveReferences(String(code ?? ""), runScope, widgetLanguage);
            if (waiting.length > 0) resolveError(describeEmptyInputs(waiting, runScope.inputs));
            else if (resolved.problems.length > 0) resolveError(describeReferenceProblems(resolved.problems));
            else sendReplacedCode(resolved.code);
            return;
        }
        setMarkersDirty((prev: boolean) => {
            return !prev;
        });
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

    const navigateProv = (code: string) => {
        setDefaultCode(code);
        sendCodeToWidgets(code);
    };

    const handleTabSelect = (eventKey: any) => {
        setActiveTab(eventKey);
    };

    const tabContentStyle: CSS.Properties = inCell
        ? { backgroundColor: "#ffffff" }
        : {
            height: "100%",
            backgroundColor: "#f2f2f2",
            borderRadius: "10px",
        };
    // A pane fills the node on the canvas; in a cell it takes its own height.
    // The provenance graph has none of its own, so it gets one.
    const paneStyle: CSS.Properties | undefined = inCell ? undefined : { height: "100%" };
    const provenancePaneStyle: CSS.Properties = inCell ? { height: "320px" } : { height: "100%" };
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

    const iconStyle: CSS.Properties = {
        cursor: "pointer",
        fontSize: "14px",
        color: "#888787",
    };

    const navItemStyle: CSS.Properties = {
        maxWidth: "100%",
    };

    const navLinkStyle: CSS.Properties = {
        display: "flex",
        justifyContent: "center",
    };

    // The tab pills: under the panes on the canvas, above the input in a
    // notebook cell, as a notebook puts a cell's toolbar.
    const pills = !dashboardOn ? (
        <Nav
            variant="pills"
            className="flex-column"
            style={{
                backgroundColor: "#f2f2f2",
                borderRadius: "10px",
                width: inCell ? "40%" : "75%",
                height: "25px",
                marginLeft: "auto",
                marginTop: inCell ? "4px" : "6px",
                ...(inCell ? { marginBottom: "6px" } : {}),
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
                        <OverlayTrigger
                            placement="right"
                            delay={overlayTriggerProps}
                            overlay={<Tooltip>Code</Tooltip>}
                        >
                            <Nav.Item style={navItemStyle}>
                                <Nav.Link
                                    eventKey="code"
                                    style={navLinkStyle}
                                >
                                    <FontAwesomeIcon
                                        icon={faCode}
                                    />
                                </Nav.Link>
                            </Nav.Item>
                        </OverlayTrigger>
                    </Col>
                ) : null}

                {widgetsTab ? (
                    <Col>
                        <OverlayTrigger
                            placement="right"
                            delay={overlayTriggerProps}
                            overlay={<Tooltip>Widgets</Tooltip>}
                        >
                            <Nav.Item style={navItemStyle}>
                                <Nav.Link
                                    eventKey="widgets"
                                    style={navLinkStyle}
                                >
                                    <FontAwesomeIcon
                                        icon={faToolbox}
                                    />
                                </Nav.Link>
                            </Nav.Item>
                        </OverlayTrigger>
                    </Col>
                ) : null}

                {grammar ? (
                    <Col>
                        <OverlayTrigger
                            placement="right"
                            delay={overlayTriggerProps}
                            overlay={<Tooltip>Grammar</Tooltip>}
                        >
                            <Nav.Item style={navItemStyle}>
                                <Nav.Link
                                    eventKey="grammar"
                                    style={navLinkStyle}
                                >
                                    <FontAwesomeIcon
                                        icon={faSpellCheck}
                                    />
                                </Nav.Link>
                            </Nav.Item>
                        </OverlayTrigger>
                    </Col>
                ) : null}

                {provenance == undefined || provenance ? (
                    <Col>
                        <OverlayTrigger
                            placement="right"
                            delay={overlayTriggerProps}
                            overlay={<Tooltip>Provenance</Tooltip>}
                        >
                            <Nav.Item style={navItemStyle}>
                                <Nav.Link
                                    eventKey="provenance"
                                    style={navLinkStyle}
                                >
                                    <FontAwesomeIcon
                                        icon={faRotateLeft}
                                    />
                                </Nav.Link>
                            </Nav.Item>
                        </OverlayTrigger>
                    </Col>
                ) : null}

                {(outputId != undefined || contentComponent != undefined) && !split ? (
                    <Col>
                        <OverlayTrigger
                            placement="right"
                            delay={overlayTriggerProps}
                            overlay={<Tooltip>Output</Tooltip>}
                        >
                            <Nav.Item style={navItemStyle}>
                                <Nav.Link
                                    eventKey="output"
                                    style={navLinkStyle}
                                >
                                    <FontAwesomeIcon
                                        icon={faRightFromBracket}
                                    />
                                </Nav.Link>
                            </Nav.Item>
                        </OverlayTrigger>
                    </Col>
                ) : null}
            </Row>
        </Nav>
    ) : null;

    return (
        <>
            <div
                style={{
                    ...{
                        height: inCell ? "auto" : dashboardOn ? "100%" : "calc(100% - 30px)",
                        width: "100%",
                        marginLeft: "auto",
                        marginRight: "auto",
                    },
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                }}
            >
                <Tab.Container activeKey={effectiveTab} onSelect={handleTabSelect}>
                    {inCell && pills}
                    {/* No gutter: its negative margins pulled every pane out of
                        the node body, under the port markers (#668). */}
                    <Row className="g-0" style={inCell ? undefined : { height: "100%" }}>
                        <Col md={12} style={inCell ? { padding: 0 } : { height: "100%", padding: 0 }}>
                            <Tab.Content
                                className={split ? "curio-notebook-split" : undefined}
                                style={{ ...activeTabContentStyle, zIndex: 10 }}
                            >
                                {code ? (
                                    <Tab.Pane
                                        eventKey="code"
                                        style={paneStyle}
                                    >
                                        <CodeEditor
                                            floatCode={floatCode}
                                            readOnly={readOnly}
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
                                            widgets={widgets}
                                            onWidgetsChange={updateWidgets}
                                            language={widgetLanguage}
                                            onResolveError={resolveError}
                                            inputs={inputs}
                                            emptyInputs={emptyInputs}
                                            shared={shared}
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
                                            applyGrammar={applyGrammar}
                                            schema={schema}
                                            setOutputCallback={setOutputCallback}
                                            references={scope}
                                            stripInputs={inputs}
                                            onLoadColumns={loadColumns}
                                            widgetLanguage={widgetLanguage}
                                        />
                                    </Tab.Pane>
                                ) : null}


                                {provenance == undefined || provenance ? (
                                    <Tab.Pane
                                        eventKey="provenance"
                                        style={provenancePaneStyle}
                                    >
                                        <NodeProvenance
                                            data={data}
                                            nodeType={nodeType}
                                            setCode={navigateProv}
                                            active={activeTab === "provenance"}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {(outputId != undefined || contentComponent != undefined) ? (
                                    <Tab.Pane
                                        eventKey="output"
                                        className={split ? "curio-notebook-output" : undefined}
                                        style={inCell ? undefined : { height: "100%", overflow: "hidden" }}
                                    >
                                        {outputId != undefined ? (
                                            // Vega sizes its canvas in CSS px
                                            // from the compiled spec, so a
                                            // multi-view chart is taller than
                                            // the pane and was simply cut off
                                            // (#202). This div scrolls now;
                                            // the parent Tab.Pane stays
                                            // overflow:hidden so the node box
                                            // itself cannot spill onto the
                                            // canvas.
                                            //
                                            // `nowheel` is load-bearing, not
                                            // decoration: without it React
                                            // Flow's ZoomPane swallows the
                                            // wheel event and zooms the canvas
                                            // instead of scrolling the chart.
                                            //
                                            // In a cell the chart needs a
                                            // definite height to fit to.
                                            <div
                                                id={outputId}
                                                className="nodrag nowheel curio-vega-mount"
                                                style={{
                                                    textAlign: "center",
                                                    width: "100%",
                                                    height: inCell ? px(outputBox.height) : "100%",
                                                    ...(inCell && outputBox.maxHeight !== undefined ? { maxHeight: px(outputBox.maxHeight) } : {}),
                                                    overflow: "auto",
                                                }}
                                            ></div>
                                        ) : (
                                            // Each content component lays out
                                            // and scrolls its own body. In a
                                            // cell its box comes from its kind.
                                            <div
                                                className="curio-content-mount"
                                                style={inCell
                                                    ? { height: px(outputBox.height), maxHeight: px(outputBox.maxHeight), overflow: outputBox.overflow }
                                                    : { height: "100%" }}
                                            >
                                                {contentComponent}
                                            </div>
                                        )}
                                    </Tab.Pane>
                                ) : null}
                            </Tab.Content>
                        </Col>
                    </Row>
                    {!inCell && pills}
                </Tab.Container>
            </div>
        </>
    );
}

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};

export default NodeEditor;
