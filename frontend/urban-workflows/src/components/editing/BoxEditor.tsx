import React, { useEffect, useState, useRef } from "react";
import Tab from "react-bootstrap/Tab";
import Tabs from "react-bootstrap/Tabs";
import "bootstrap/dist/css/bootstrap.min.css";
import CodeEditor from "./CodeEditor";
import GrammarEditor from "./GrammarEditor";
import WidgetsEditor from "./WidgetsEditor";
import { BoxType } from "../../constants";
import BoxProvenance from "./BoxProvenance";
import Col from "react-bootstrap/Col";
import Nav from "react-bootstrap/Nav";
import Row from "react-bootstrap/Row";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import "./BoxEditor.css";

import {
    faGear,
    faCircleInfo,
    faCirclePlay,
    faExpand,
    faToolbox,
    faCode,
    faSpellCheck,
    faRotateLeft,
    faRightFromBracket,
} from "@fortawesome/free-solid-svg-icons";
import { OverlayTrigger, Tooltip } from "react-bootstrap";

type BoxEditorProps = {
    outputId?: string;
    setSendCodeCallback: any;
    code: boolean;
    widgets: boolean;
    grammar: boolean;
    setOutputCallback: any;
    data: {
        nodeId: string;
        pythonInterpreter: any;
        input: string;
        outputCallback: any;
    };
    output: { code: string; content: string };
    boxType: BoxType;
    applyGrammar?: any;
    schema?: any;
    readOnly: boolean;
    defaultValue: any;
    floatCode?: any;
    provenance?: boolean;
    customWidgetsCallback?: any;
    contentComponent?: any;
};

function BoxEditor({
    outputId,
    setSendCodeCallback,
    code,
    widgets,
    grammar,
    setOutputCallback,
    data,
    output,
    boxType,
    applyGrammar,
    schema,
    readOnly,
    defaultValue,
    floatCode,
    provenance,
    customWidgetsCallback,
    contentComponent,
}: BoxEditorProps) {
    const [userCode, setUserCode] = useState<string>(""); // python or grammar with marks unresolved
    const [defaultCode, setDefaultCode] = useState<string>("");
    const [markersDirty, setMarkersDirty] = useState<boolean>(false); // make WidgetsEditor update replacedCode
    const [replacedCode, setReplacedCode] = useState<string>(""); // python or grammar with marks resolved
    const [replacedCodeDirty, setReplacedCodeDirty] = useState<boolean>(false); // code has to rerun every time button is pressed (having changes or not)
    const [activeTab, setActiveTab] = useState("widgets");
    const [fullscreen, setFullscreen] = useState<string>("");

    const contentComponentBypass = useRef(false);

    const sendCodeToWidgets = (code: string) => {
        setUserCode(code);
        setMarkersDirty((prev: boolean) => {
            return !prev;
        });
    };

    useEffect(() => {
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

    const sendReplacedCode = (code: string) => {
        if (fullscreen == "" || fullscreen == undefined) setActiveTab("output");
        setReplacedCode(code);
        setReplacedCodeDirty((prev: boolean) => {
            return !prev;
        });
    };

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
                    height: "76%",
                    width: "95%",
                    marginLeft: "auto",
                    marginRight: "auto",
                }}
            >
                <Tab.Container activeKey={activeTab} onSelect={handleTabSelect}>
                    <Row style={{ height: "100%" }}>
                        <Col md={12} style={{ height: "100%", padding: 0 }}>
                            <Tab.Content
                                style={{ ...activeTabContentStyle, zIndex: 10 }}
                            >
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
                                        />
                                    </Tab.Pane>
                                ) : null}

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
                                            sendCodeToWidgets={
                                                sendCodeToWidgets
                                            }
                                            setOutputCallback={
                                                setOutputCallback
                                            }
                                            data={data}
                                            output={output}
                                            boxType={boxType}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                {grammar ? (
                                    <Tab.Pane
                                        eventKey="grammar"
                                        style={{ height: "100%" }}
                                    >
                                        <GrammarEditor
                                            floatCode={floatCode}
                                            readOnly={readOnly}
                                            defaultValue={defaultCode}
                                            replacedCodeDirty={
                                                replacedCodeDirty
                                            }
                                            replacedCode={replacedCode}
                                            sendCodeToWidgets={
                                                sendCodeToWidgets
                                            }
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
                                        <BoxProvenance
                                            data={data}
                                            boxType={boxType}
                                            setCode={navigateProv}
                                        />
                                    </Tab.Pane>
                                ) : null}

                                <Tab.Pane
                                    eventKey="output"
                                    style={{ height: "100%" }}
                                >
                                    {outputId != undefined ? (
                                        <div
                                            id={outputId}
                                            style={{
                                                textAlign: "center",
                                                width: "100%",
                                                height: "100%",
                                            }}
                                        ></div>
                                    ) : contentComponent != undefined ? (
                                        contentComponent
                                    ) : (
                                        <div
                                            style={{
                                                width: "100%",
                                                height: "100%",
                                            }}
                                        >
                                            <p
                                                style={{
                                                    margin: 0,
                                                    padding: "10px",
                                                    fontSize: "10px",
                                                }}
                                            >
                                                {output.content}
                                            </p>
                                        </div>
                                    )}
                                </Tab.Pane>
                            </Tab.Content>
                        </Col>
                    </Row>
                    <Nav
                        variant="pills"
                        className="flex-column"
                        style={{
                            backgroundColor: "#f2f2f2",
                            borderRadius: "10px",
                            width: "55%",
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
                        </Row>
                    </Nav>
                </Tab.Container>
            </div>
            <FontAwesomeIcon
                style={{
                    ...iconStyle,
                    fontSize: "10px",
                    position: "fixed",
                    zIndex: 11,
                    top: "12px",
                    left: "30px",
                }}
                onClick={() =>
                    fullscreen != "" && fullscreen != undefined
                        ? setFullscreen("")
                        : setFullscreen("fs")
                }
                icon={faExpand}
            />
        </>
    );
}

const overlayTriggerProps = {
    show: 120,
    hide: 10,
};

export default BoxEditor;
