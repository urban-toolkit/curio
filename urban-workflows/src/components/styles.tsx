import React, { ReactNode, useState, useEffect } from "react";
import CSS from "csstype";
import { Dropdown } from "react-bootstrap";

import { useFlowContext } from "../providers/FlowProvider";
import { Box, NodeRemoveChange } from "reactflow";

import { CommentsList, IComment } from "./comments/CommentsList";
import { useRightClickMenu } from "../hook/useRightClickMenu";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faComments,
    faCircle,
    faCircleDot,
} from "@fortawesome/free-solid-svg-icons";
import { useUserContext } from "../providers/UserProvider";

import Col from "react-bootstrap/Col";
import Nav from "react-bootstrap/Nav";
import Row from "react-bootstrap/Row";
import {
    faGear,
    faCircleInfo,
    faCirclePlay,
    faCopy,
    faFloppyDisk,
    faSquareMinus,
    faMinus,
    faUpRightAndDownLeftFromCenter,
    faMagnifyingGlassChart,
    faSquareRootVariable,
    faBroom,
    faDownload,
    faUpload,
    faServer,
    faDatabase,
    faRepeat,
    faCodeMerge,
    faImage,
    faTable,
    faFont,
    faCube,
    faChartLine,
} from "@fortawesome/free-solid-svg-icons";
import { AccessLevelType, BoxType } from "../constants";
import "./styles.css";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { useCode } from "../hook/useCode";

// Box Container
export const BoxContainer = ({
    data,
    children,
    nodeId,
    templateData,
    code,
    promptDescription,
    updateTemplate,
    promptModal,
    user,
    setOutputCallback,
    sendCodeToWidgets,
    output,
    boxWidth,
    boxHeight,
    noContent,
    setTemplateConfig,
    disableComments = false,
    styles = {},
}: {
    data: any;
    children: ReactNode;
    nodeId: string;
    templateData: any;
    code?: string;
    promptDescription: any;
    updateTemplate?: any;
    promptModal?: any;
    user?: any;
    setOutputCallback: any;
    sendCodeToWidgets?: any;
    output?: { code: string; content: string };
    boxWidth?: number;
    boxHeight?: number;
    noContent?: boolean;
    setTemplateConfig?: any;
    disableComments?: boolean;
    styles?: CSS.Properties;
}) => {
    const { onNodesChange, setPinForDashboard } = useFlowContext();
    const { getTemplates, deleteTemplate } = useTemplateContext();
    const { createCodeNode } = useCode();
    const [showComments, setShowComments] = useState(false);
    const [comments, setComments] = useState<IComment[]>([]);
    const [pinnedToDashboard, setPinnedToDashboard] = useState<boolean>(false);
    const [currentBoxWidth, setCurrentBoxWidth] = useState<number | undefined>(
        boxWidth
    );
    const [currentBoxHeight, setCurrentBoxHeight] = useState<
        number | undefined
    >(boxHeight);
    const { showMenu, menuPosition, onContextMenu } = useRightClickMenu();
    const [minimized, setMinimized] = useState(
        data.nodeType == BoxType.MERGE_FLOW
    );

    useEffect(() => {
        if (boxWidth == undefined) {
            setCurrentBoxWidth(525);
        }

        if (boxHeight == undefined) {
            setCurrentBoxHeight(267);
        }

        const resizer = document.getElementById(
            nodeId + "resizer"
        ) as HTMLElement;
        const resizable = document.getElementById(
            nodeId + "resizable"
        ) as HTMLElement;

        resizer.addEventListener("mousedown", initResize, false);

        function initResize(e: any) {
            window.addEventListener("mousemove", resize, false);
            window.addEventListener("mouseup", stopResize, false);
        }

        function resize(e: any) {
            resizable.style.width = e.clientX - resizable.offsetLeft + "px";
            resizable.style.height = e.clientY - resizable.offsetTop + "px";
            setCurrentBoxWidth(e.clientX - resizable.offsetLeft);
            setCurrentBoxHeight(e.clientY - resizable.offsetTop);
        }

        function stopResize(e: any) {
            window.removeEventListener("mousemove", resize, false);
            window.removeEventListener("mouseup", stopResize, false);
        }
    }, []);

    const deleteComment = (commentId: number) => {
        setComments(comments.filter((comment) => comment.id !== commentId));
    };

    const toggleResolveComment = (commentId: number) => {
        setComments(
            comments.map((comment) => {
                if (comment.id === commentId) {
                    comment.resolved = !comment.resolved;
                }
                return comment;
            })
        );
    };

    // const handleCloseMenu = () => {
    //     setShowMenu(false);
    //     document.removeEventListener("click", handleCloseMenu);
    // };

    const onDelete = () => {
        const change: NodeRemoveChange = {
            id: nodeId,
            type: "remove",
        };

        onNodesChange([change]);
    };

    const addComment = (comment: IComment) => {
        setComments([...comments, comment]);
    };

    const options = disableComments
        ? [{ name: "Delete", action: onDelete }]
        : [
              { name: "Delete", action: onDelete },
              {
                  name: showComments ? "Hide Comments" : "Show Comments",
                  action: () => setShowComments(!showComments),
              },
          ];

    const updatePin = (nodeId: string, value: boolean) => {
        setPinnedToDashboard(!value);
        setPinForDashboard(nodeId, !value);
    };

    const boxIconTranslation = (boxType: BoxType) => {
        if (boxType === BoxType.COMPUTATION_ANALYSIS) {
            return faMagnifyingGlassChart;
        } else if (boxType === BoxType.CONSTANTS) {
            return faSquareRootVariable;
        } else if (boxType === BoxType.DATA_CLEANING) {
            return faBroom;
        } else if (boxType === BoxType.DATA_EXPORT) {
            return faDownload;
        } else if (boxType === BoxType.DATA_LOADING) {
            return faUpload;
        } else if (boxType === BoxType.DATA_POOL) {
            return faServer;
        } else if (boxType === BoxType.DATA_TRANSFORMATION) {
            return faDatabase;
        } else if (boxType === BoxType.FLOW_SWITCH) {
            return faRepeat;
        } else if (boxType === BoxType.MERGE_FLOW) {
            return faCodeMerge;
        } else if (boxType === BoxType.VIS_IMAGE) {
            return faImage;
        } else if (boxType === BoxType.VIS_TABLE) {
            return faTable;
        } else if (boxType === BoxType.VIS_TEXT) {
            return faFont;
        } else if (boxType === BoxType.VIS_UTK) {
            return faCube;
        } else if (boxType === BoxType.VIS_VEGA) {
            return faChartLine;
        }
        return faCopy;
    };

    const boxNameTranslation = (boxType: BoxType) => {
        if (boxType === BoxType.COMPUTATION_ANALYSIS) {
            return "Computation Analysis";
        } else if (boxType === BoxType.CONSTANTS) {
            return "Constants";
        } else if (boxType === BoxType.DATA_CLEANING) {
            return "Data Cleaning";
        } else if (boxType === BoxType.DATA_EXPORT) {
            return "Data Export";
        } else if (boxType === BoxType.DATA_LOADING) {
            return "Data Loading";
        } else if (boxType === BoxType.DATA_POOL) {
            return "Data Pool";
        } else if (boxType === BoxType.DATA_TRANSFORMATION) {
            return "Data Transformation";
        } else if (boxType === BoxType.FLOW_SWITCH) {
            return "Flow Switch";
        } else if (boxType === BoxType.MERGE_FLOW) {
            return "Merge Flow";
        } else if (boxType === BoxType.VIS_IMAGE) {
            return "Image";
        } else if (boxType === BoxType.VIS_TABLE) {
            return "Table";
        } else if (boxType === BoxType.VIS_TEXT) {
            return "Text";
        } else if (boxType === BoxType.VIS_UTK) {
            return "UTK";
        } else if (boxType === BoxType.VIS_VEGA) {
            return "Vega-Lite";
        }
    };

    return (
        <>
            <div
                id={nodeId + "resizer"}
                className={"resizer nowheel nodrag"}
            ></div>
            <div
                id={nodeId + "resizable"}
                className={"resizable"}
                style={{
                    ...boxContainerStyles,
                    ...styles,
                    width: currentBoxWidth + "px",
                    height: currentBoxHeight + "px",
                    ...(minimized ? { display: "none" } : {}),
                }}
                onContextMenu={onContextMenu}
            >
                {!noContent ? (
                    <Row
                        style={{
                            width: "95%",
                            marginBottom: "2px",
                            paddingBottom: "2px",
                            marginLeft: "auto",
                            marginRight: "auto",
                            borderBottom: "1px solid rgba(107, 107, 107, 0.3)",
                        }}
                    >
                        <p
                            style={{
                                textAlign: "center",
                                marginBottom: 0,
                                fontSize: "12px",
                                fontWeight: "bold",
                                position: "fixed",
                                top: "10px",
                                left: 0,
                                color: "#888787",
                            }}
                        >
                            {boxNameTranslation(data.nodeType)}
                            {templateData.name != undefined
                                ? " - " + templateData.name
                                : null}
                        </p>

                        <ul
                            style={{
                                listStyle: "none",
                                padding: 0,
                                display: "flex",
                                margin: 0,
                                justifyContent: "flex-end",
                                zIndex: 5,
                            }}
                        >
                            {promptModal != undefined &&
                            user != undefined &&
                            templateData.id != undefined &&
                            templateData.custom &&
                            user != null &&
                            user.type == "programmer" ? (
                                <li style={{ marginLeft: "10px" }}>
                                    <FontAwesomeIcon
                                        onClick={() => {
                                            promptModal();
                                        }}
                                        icon={faGear}
                                        style={iconStyle}
                                    />
                                </li>
                            ) : null}
                            <li style={{ marginLeft: "10px" }}>
                                <FontAwesomeIcon
                                    onClick={() => {
                                        promptDescription();
                                    }}
                                    icon={faCircleInfo}
                                    style={iconStyle}
                                />
                            </li>
                            <li style={{ marginLeft: "10px" }}>
                                <FontAwesomeIcon
                                    icon={faComments}
                                    style={iconStyle}
                                    onClick={() =>
                                        setShowComments(!showComments)
                                    }
                                />
                            </li>
                            {updateTemplate != undefined &&
                            user != undefined &&
                            code != undefined &&
                            templateData.id != undefined &&
                            templateData.custom &&
                            code != templateData.code &&
                            user != null &&
                            user.type == "programmer" ? (
                                <li style={{ marginLeft: "10px" }}>
                                    <FontAwesomeIcon
                                        icon={faFloppyDisk}
                                        style={iconStyle}
                                        onClick={() => {
                                            updateTemplate({
                                                ...templateData,
                                                code: code,
                                            });
                                        }}
                                    />
                                </li>
                            ) : null}
                        </ul>
                    </Row>
                ) : null}

                {children}

                <Row
                    style={{
                        width: "50%",
                        marginRight: "auto",
                        marginLeft: "10px",
                        marginTop: "4px",
                    }}
                >
                    {sendCodeToWidgets != undefined ? (
                        <Row>
                            <Col md={2}>
                                <FontAwesomeIcon
                                    className={"nowheel nodrag"}
                                    icon={faCirclePlay}
                                    style={{
                                        cursor: "pointer",
                                        fontSize: "27px",
                                        color: "#0d6efd",
                                    }}
                                    onClick={() => {
                                        setOutputCallback({
                                            code: "exec",
                                            content: "",
                                        });
                                        sendCodeToWidgets(code); // will resolve markers
                                    }}
                                />
                            </Col>
                            {output != undefined ? (
                                <Col
                                    md={3}
                                    className="d-flex align-items-center"
                                >
                                    <p
                                        style={{
                                            fontSize: "10px",
                                            textAlign: "center",
                                            marginBottom: 0,
                                        }}
                                    >
                                        {output.code == "success" ? (
                                            <span style={{ color: "green" }}>
                                                Done
                                            </span>
                                        ) : output.code == "exec" ? (
                                            "Executing..."
                                        ) : output.code == "error" ? (
                                            <span style={{ color: "red" }}>
                                                Error
                                            </span>
                                        ) : (
                                            ""
                                        )}
                                    </p>
                                </Col>
                            ) : null}
                            {/* <Col md={3}> */}
                            {promptModal != undefined &&
                            user != undefined &&
                            user != null &&
                            user.type == "programmer" ? (
                                <Col md={3}>
                                    <Dropdown>
                                        <Dropdown.Toggle
                                            variant="primary"
                                            style={{ fontSize: "9px" }}
                                        >
                                            Templates
                                        </Dropdown.Toggle>

                                        <Dropdown.Menu
                                            style={{
                                                padding: "5px",
                                                fontSize: "9px",
                                                overflowY: "auto",
                                                maxHeight: "200px",
                                            }}
                                        >
                                            {user != null &&
                                            user.type == "programmer" ? (
                                                <Dropdown.Item
                                                    style={{ padding: 0 }}
                                                    onClick={() => {
                                                        promptModal(true);
                                                    }}
                                                >
                                                    + New Template
                                                </Dropdown.Item>
                                            ) : null}

                                            {getTemplates(
                                                data.nodeType as BoxType,
                                                false
                                            ).length > 0 ? (
                                                <>
                                                    <Dropdown.Divider
                                                        style={{ padding: 0 }}
                                                    />
                                                    <Dropdown.ItemText
                                                        style={{
                                                            padding: 0,
                                                            fontWeight: "bold",
                                                        }}
                                                    >
                                                        Default Templates
                                                    </Dropdown.ItemText>
                                                    {getTemplates(
                                                        data.nodeType as BoxType,
                                                        false
                                                    ).map(
                                                        (
                                                            template: Template,
                                                            index: number
                                                        ) => {
                                                            if (
                                                                (template.accessLevel ==
                                                                    AccessLevelType.PROGRAMMER &&
                                                                    user !=
                                                                        null &&
                                                                    user.type ==
                                                                        "expert") ||
                                                                (template.accessLevel !=
                                                                    AccessLevelType.ANY &&
                                                                    user ==
                                                                        null)
                                                            ) {
                                                                return null;
                                                            } else {
                                                                return (
                                                                    <Dropdown.Item
                                                                        key={
                                                                            "templates_modal_content_default_" +
                                                                            data.nodeType +
                                                                            index +
                                                                            nodeId
                                                                        }
                                                                        style={
                                                                            template.accessLevel ==
                                                                            AccessLevelType.PROGRAMMER
                                                                                ? buttonStyleProgrammer
                                                                                : template.accessLevel ==
                                                                                    AccessLevelType.EXPERT
                                                                                  ? buttonStyleExpert
                                                                                  : buttonStyleAny
                                                                        }
                                                                        onClick={() => {
                                                                            setTemplateConfig(
                                                                                template
                                                                            );
                                                                        }}
                                                                    >
                                                                        {
                                                                            template.name
                                                                        }
                                                                    </Dropdown.Item>
                                                                );
                                                            }
                                                        }
                                                    )}
                                                </>
                                            ) : null}

                                            {getTemplates(
                                                data.nodeType as BoxType,
                                                true
                                            ).length > 0 ? (
                                                <>
                                                    <Dropdown.Divider
                                                        style={{ padding: 0 }}
                                                    />
                                                    <Dropdown.ItemText
                                                        style={{
                                                            padding: 0,
                                                            fontWeight: "bold",
                                                        }}
                                                    >
                                                        Custom Templates
                                                    </Dropdown.ItemText>
                                                    {getTemplates(
                                                        data.nodeType as BoxType,
                                                        true
                                                    ).map(
                                                        (
                                                            template: Template,
                                                            index: number
                                                        ) => {
                                                            if (
                                                                (template.accessLevel ==
                                                                    AccessLevelType.PROGRAMMER &&
                                                                    user !=
                                                                        null &&
                                                                    user.type ==
                                                                        "expert") ||
                                                                (template.accessLevel !=
                                                                    AccessLevelType.ANY &&
                                                                    user ==
                                                                        null)
                                                            ) {
                                                                return null;
                                                            } else {
                                                                return (
                                                                    <Dropdown.Item
                                                                        style={{
                                                                            padding: 0,
                                                                        }}
                                                                        key={
                                                                            "templates_modal_content_custom_" +
                                                                            data.nodeType +
                                                                            index +
                                                                            nodeId
                                                                        }
                                                                        onClick={() => {
                                                                            setTemplateConfig(
                                                                                template
                                                                            );
                                                                        }}
                                                                    >
                                                                        <span
                                                                            style={
                                                                                template.accessLevel ==
                                                                                AccessLevelType.PROGRAMMER
                                                                                    ? buttonStyleProgrammer
                                                                                    : template.accessLevel ==
                                                                                        AccessLevelType.EXPERT
                                                                                      ? buttonStyleExpert
                                                                                      : buttonStyleAny
                                                                            }
                                                                        >
                                                                            {
                                                                                template.name
                                                                            }
                                                                        </span>
                                                                        <FontAwesomeIcon
                                                                            onClick={() => {
                                                                                deleteTemplate(
                                                                                    template.id
                                                                                );
                                                                            }}
                                                                            icon={
                                                                                faSquareMinus
                                                                            }
                                                                            style={{
                                                                                color: "#888787",
                                                                                padding: 0,
                                                                                marginLeft:
                                                                                    "5px",
                                                                            }}
                                                                        />
                                                                    </Dropdown.Item>
                                                                );
                                                            }
                                                        }
                                                    )}
                                                </>
                                            ) : null}
                                        </Dropdown.Menu>
                                    </Dropdown>
                                </Col>
                            ) : null}
                            {/* </Col> */}
                        </Row>
                    ) : null}
                </Row>

                {pinnedToDashboard ? (
                    <FontAwesomeIcon
                        icon={faCircleDot}
                        style={{
                            color: "red",
                            cursor: "pointer",
                            fontSize: "10px",
                            position: "fixed",
                            top: "12px",
                            left: "10px",
                            zIndex: 11,
                        }}
                        onClick={() => {
                            updatePin(nodeId, pinnedToDashboard);
                        }}
                    />
                ) : (
                    <FontAwesomeIcon
                        style={{
                            color: "888",
                            cursor: "pointer",
                            fontSize: "10px",
                            position: "fixed",
                            top: "12px",
                            left: "10px",
                            zIndex: 11,
                        }}
                        icon={faCircle}
                        onClick={() => {
                            updatePin(nodeId, pinnedToDashboard);
                        }}
                    />
                )}
                <RightClickMenu
                    menuPosition={menuPosition}
                    showMenu={showMenu}
                    options={options}
                />
            </div>

            {showComments && (
                <CommentsList
                    comments={comments}
                    addComment={addComment}
                    deleteComment={deleteComment}
                    toggleResolveComment={toggleResolveComment}
                />
            )}

            {minimized ? (
                <div
                    style={{
                        width: currentBoxWidth + "px",
                        height: currentBoxHeight + "px",
                        backgroundColor: "white",
                        boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
                        borderRadius: "10px",
                        padding: "5px",
                        justifyContent: "center",
                        display: "flex",
                        alignItems: "center",
                    }}
                >
                    <FontAwesomeIcon
                        icon={boxIconTranslation(data.nodeType)}
                        style={{ ...iconStyle, fontSize: "23px" }}
                    />
                </div>
            ) : null}

            <FontAwesomeIcon
                icon={!minimized ? faMinus : faUpRightAndDownLeftFromCenter}
                style={{
                    ...iconStyle,
                    position: "fixed",
                    ...(minimized
                        ? { top: "5px", left: "5px" }
                        : { left: "50px", top: "12px" }),
                    fontSize: "10px",
                    zIndex: 8,
                }}
                onClick={() => {
                    if (data.nodeType != BoxType.MERGE_FLOW) {
                        if (!minimized) {
                            setCurrentBoxWidth(70);
                            setCurrentBoxHeight(40);
                        } else {
                            if (boxWidth == undefined) {
                                setCurrentBoxWidth(525);
                            } else {
                                setCurrentBoxWidth(boxWidth);
                            }

                            if (boxHeight == undefined) {
                                setCurrentBoxHeight(267);
                            } else {
                                setCurrentBoxHeight(boxHeight);
                            }
                        }
                    }

                    if (data.nodeType == BoxType.MERGE_FLOW) {
                        setMinimized(true);
                    } else {
                        setMinimized(!minimized);
                    }
                }}
            />
        </>
    );
};

export const iconStyle: CSS.Properties = {
    cursor: "pointer",
    fontSize: "14px",
    color: "#888787",
};

const boxContainerStyles: CSS.Properties = {
    position: "relative",
    backgroundColor: "white",
    boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
    borderRadius: "10px",
    padding: "5px",
};

export const RightClickMenu = ({
    showMenu,
    menuPosition,
    options,
}: {
    showMenu: boolean;
    menuPosition: { y: number; x: number };
    options: { name: string; action: () => void }[];
}) => {
    return (
        <Dropdown show={showMenu} drop="end">
            <Dropdown.Menu
                style={{
                    position: "fixed",
                    top: menuPosition.y,
                    left: menuPosition.x,
                    transform: "translate(0, 0)",
                }}
            >
                {options.map((option) => (
                    <Dropdown.Item key={option.name} onClick={option.action}>
                        {option.name}
                    </Dropdown.Item>
                ))}
            </Dropdown.Menu>
        </Dropdown>
    );
};

const boxContentStyle: CSS.Properties = {
    backgroundColor: "white",
};

export const buttonStyle: CSS.Properties = {
    backgroundColor: "transparent",
    color: "#545353",
    border: "1px solid #545353",
    padding: "4px 8px",
    borderRadius: "4px",
    cursor: "pointer",
    outline: "none",
};

const buttonStyleProgrammer: CSS.Properties = {
    color: "#d66800",
    padding: 0,
};

const buttonStyleExpert: CSS.Properties = {
    color: "#0044d6",
    padding: 0,
};

const buttonStyleAny: CSS.Properties = {
    color: "#545353",
    padding: 0,
};
