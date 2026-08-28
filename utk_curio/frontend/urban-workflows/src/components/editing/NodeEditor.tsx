import React, { useEffect, useState, useRef } from "react";
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
import { resolveInitialEditorTab } from "../../utils/canvasTemplateConfig";

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
    markNodeStale?: (nodeId: string) => void;
    provenance?: boolean;
    customWidgetsCallback?: any;
    contentComponent?: any;
    disableWidgets?: boolean; // Added prop to freeze widget buttons
};

function NodeEditor({
    outputId,
    setSendCodeCallback,
    code,
    widgets,
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
    markNodeStale,
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
        () => resolveInitialEditorTab({ code, grammar, widgets })
    );
    const { dashboardOn } = useFlowContext();
    const effectiveTab = dashboardOn ? "output" : activeTab;

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

    const sendCodeToWidgets = (code: string) => {
        setUserCode(code);
        if (!widgets) {
            // Why: WidgetsEditor is the bridge that resolves widget markers and
            // hands the result to CodeEditor (via sendReplacedCode). It only
            // mounts when the widgets tab is enabled, so for code nodes with
            // hasWidgets=false (e.g. js-computation) the markersDirty toggle
            // has no listener and CodeEditor's interpretCode is never reached
            // — the play spinner spins forever. Forward the code straight to
            // CodeEditor here so the play flow completes without a widgets tab.
            sendReplacedCode(code);
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

    const tabContentStyle: CSS.Properties = {
        height: "100%",
        backgroundColor: "#f2f2f2",
        borderRadius: "10px",
    };

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

    return (
        <>
            <div
                style={{
                    ...{
                        height: dashboardOn ? "100%" : "calc(100% - 30px)",
                        width: "100%",
                        marginLeft: "auto",
                        marginRight: "auto",
                    },
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                }}
            >
                <Tab.Container activeKey={effectiveTab} onSelect={handleTabSelect}>
                    <Row style={{ height: "100%" }}>
                        <Col md={12} style={{ height: "100%", padding: 0 }}>
                            <Tab.Content
                                style={{ ...activeTabContentStyle, zIndex: 10 }}
                            >
                                {code ? (
                                    <Tab.Pane
                                        eventKey="code"
                                        style={{ height: "100%" }}
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
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {widgets ? (
                                    <Tab.Pane
                                        eventKey="widgets"
                                        style={{ height: "100%" }}
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
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {grammar ? (
                                    <Tab.Pane
                                        eventKey="grammar"
                                        style={{ height: "100%" }}
                                    >
                                        <GrammarEditor
                                            markNodeStale={markNodeStale}
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
                                        />
                                    </Tab.Pane>
                                ) : null}


                                {provenance == undefined || provenance ? (
                                    <Tab.Pane
                                        eventKey="provenance"
                                        style={{ height: "100%" }}
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
                                        style={{ height: "100%", overflow: "hidden" }}
                                    >
                                        {outputId != undefined ? (
                                            <div
                                                id={outputId}
                                                className="nodrag"
                                                style={{
                                                    textAlign: "center",
                                                    width: "100%",
                                                    height: "100%",
                                                }}
                                            ></div>
                                        ) : (
                                            contentComponent
                                        )}
                                    </Tab.Pane>
                                ) : null}
                            </Tab.Content>
                        </Col>
                    </Row>
                    {!dashboardOn && <Nav
                        variant="pills"
                        className="flex-column"
                        style={{
                            backgroundColor: "#f2f2f2",
                            borderRadius: "10px",
                            width: "75%",
                            height: "25px",
                            marginLeft: "auto",
                            marginTop: "6px",
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

                            {widgets ? (
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

                            {(outputId != undefined || contentComponent != undefined) ? (
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
                    </Nav>}
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
