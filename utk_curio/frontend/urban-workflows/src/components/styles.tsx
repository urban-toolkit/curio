import React, { ReactNode, useState, useEffect, useRef } from "react";
import CSS from "csstype";
import { Dropdown, Spinner } from "react-bootstrap";

import { useFlowContext } from "../providers/FlowProvider";
import { NodeRemoveChange, useReactFlow, useStore } from "reactflow";

import { CommentsList, IComment } from "./comments/CommentsList";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faComments,
    faCircle,
    faCircleDot,
} from "@fortawesome/free-solid-svg-icons";
import { useToastContext } from "../providers/ToastProvider";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import { CATEGORY_FALLBACK_FG, categoryFg } from "../constants/nodeCategoryPalette";
import type { CanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { readCanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { ConnectionValidator } from "../ConnectionValidator";
import { unversionedNodeType } from "../utils/flowNodeCanonicalType";
import { HeaderIconButton } from "./HeaderIconButton";
import {
    EditableNodeHeaderLabel,
    NodeSaveAsModal,
    NodeTemplateConfigModal,
    PackageMetaHeader,
} from "./packages/editing";
import Col from "react-bootstrap/Col";
import Row from "react-bootstrap/Row";
import {
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
    faTable,
    faCirclePlus,
    faFont,
    faCube,
    faTriangleExclamation,
    faChartLine,
    faXmark,
    faAnglesUp
} from "@fortawesome/free-solid-svg-icons";
import { AccessLevelType, NodeType, SupportedType } from "../constants";
import { getNodeDescriptor, tryGetNodeDescriptor } from "../registry";
import { NodeTemplateId } from "../registry/types";
import {
    applyDatasetToNodeData,
    canApplyDatasetToNode,
    hasDatasetDrag,
    readDatasetDragPayload,
} from "../services/datasetCatalog";
import "./styles.css";
import { useStarterContext } from "../providers/StarterProvider";
import { useCode } from "../hook/useCode";
import { TrillGenerator } from "TrillGenerator";
import { ICodeData } from "types";
import { SaveOutputToggle } from "./nodes/SaveOutputToggle";
import { resolveSaveOutputDataset } from "../utils/saveOutputDataset";
import { nodeRunStatus } from "../utils/nodeRunStatus";
import { isDatasetPaletteNode } from "../services/datasetCatalog/datasetApplication";
import { DatasetMetaHeader } from "./datasets/DatasetMetaHeader";
import { useDatasetPalette } from "../providers/DatasetPaletteContext";

const MIN_NODE_WIDTH = 200;
const MIN_NODE_HEIGHT = 150;

// Node Container
export const NodeContainer = ({
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
    nodeWidth,
    nodeHeight,
    noContent,
    setTemplateConfig,
    disableComments = false,
    handleType,
    styles = {},
    disablePlay = false,
    isLoading = false,
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
    output?: ICodeData;
    nodeWidth?: number;
    nodeHeight?: number;
    noContent?: boolean;
    setTemplateConfig?: any;
    disableComments?: boolean;
    styles?: CSS.Properties;
    handleType?: string;
    disablePlay?: boolean;
    isLoading?: boolean;
}) => {
    const { showToast } = useToastContext();
    const {
        nodes,
        edges,
        workflowNameRef,
        applyRemoveChanges,
        setPinForDashboard,
        dashboardPins,
        allMinimized,
        setExpandStatus,
        updateDataNode,
        updateDefaultCode,
        workflowGoal,
        acceptSuggestion,
        nodeExecStatus,
        playNodesUpTo,
        dashboardOn,
        dashboardLocked,
        markDirty,
        defaultSaveOutputDataset,
    } = useFlowContext();
    const saveOutputDataset = resolveSaveOutputDataset(data, defaultSaveOutputDataset);
    // Nodes created from the dataset palette load an installed listing and can't
    // regenerate a dataset — hide the save toggle and show the dataset chip instead.
    const datasetPaletteNode = isDatasetPaletteNode(data);
    // Producer linkage: if this node generated an installed computed dataset, show
    // an OUTPUT chip linking to its palette row. Derived from the catalog (not
    // stamped) so it tracks install/uninstall. Distinct from the save-lock above —
    // producer nodes keep their save toggle.
    const { installedComputedByProducer: producerByNode } = useDatasetPalette();
    const producerDataset = producerByNode.get(nodeId);
    // Whether this node is selected on the canvas — drives a more vibrant dataset
    // chip. Read reactively from the React Flow store so it updates on selection.
    const isNodeSelected = useStore((s) => !!s.nodeInternals.get(nodeId)?.selected);
    const { getNodes, getEdges } = useReactFlow();
    const { getStarters, deleteStarter, fetchStarters } = useStarterContext();
    const { createCodeNode, loadTrill } = useCode();
    const [showComments, setShowComments] = useState(false);
    const [saveAsOpen, setSaveAsOpen] = useState(false);
    const [configOpen, setConfigOpen] = useState(false);
    const [comments, setComments] = useState<IComment[]>([]);
    const [pinnedToDashboard, setPinnedToDashboard] = useState<boolean>(!!dashboardPins[nodeId]);
    const [expectedInputType, setExpectedInputType] = useState(data.in);
    const [expectedOutputType, setExpectedOutputType] = useState(data.out);
    const [showWarnings, setShowWarnings] = useState<boolean>(false);
    const [currentNodeWidth, setCurrentNodeWidth] = useState<number | undefined>(
        nodeWidth
    );
    const [currentNodeHeight, setCurrentNodeHeight] = useState<
        number | undefined
    >(nodeHeight);
    // Icon-only nodes (manifest `containerStyle.noContent: true` — merge-flow,
    // spatial-join, etc.) start minimized: they have no body to expand and the
    // 50×180 footprint is their default render.
    const [minimized, setMinimized] = useState(!!noContent);
    // Hover state for the minimized chip's delete control (noContent nodes have
    // no header band to put it in).
    const [chipHovered, setChipHovered] = useState(false);

    useEffect(() => {
        if (nodeWidth !== undefined) {
            setCurrentNodeWidth(nodeWidth);
        }
    }, [nodeWidth]);

    useEffect(() => {
        if (nodeHeight !== undefined) {
            setCurrentNodeHeight(nodeHeight);
        }
    }, [nodeHeight]);

    useEffect(() => {

        if(data.output != undefined && data.output.code == 'success'){
            setExpectedOutputType(data.output.outputType);
        }

        if(data.input != undefined && data.input != ""){
            try {
                let parsed_input = typeof data.input === 'string' ? JSON.parse(data.input) : data.input;

                let dataType = parsed_input.dataType;
                
                if(dataType == 'int' || dataType == 'str' || dataType == 'float' || dataType == 'bool')
                    setExpectedInputType(SupportedType.VALUE)
                else if(dataType == 'list')
                    setExpectedInputType(SupportedType.LIST)
                else if(dataType == 'dict')
                    setExpectedInputType(SupportedType.JSON)
                else if(dataType == 'dataframe')
                    setExpectedInputType(SupportedType.DATAFRAME)
                else if(dataType == 'geodataframe')
                    setExpectedInputType(SupportedType.GEODATAFRAME)
                else if(dataType == 'raster')
                    setExpectedInputType(SupportedType.RASTER)
                else if(dataType == 'outputs')
                    setExpectedInputType("MULTIPLE")

            } catch (error) {
                console.error("Invalid input type", error);
            }
        }

    }, [data.output, data.input])

    useEffect(() => {
        if (!noContent) {
            if(allMinimized > 0){
                setMinimized(true);
            }else{
                setMinimized(false);
            }
        }
    }, [allMinimized])

    useEffect(() => {
        if (!noContent) {
            if (minimized) {
                setCurrentNodeWidth(70);
                setCurrentNodeHeight(40);
            } else {
                if (nodeWidth == undefined) {
                    setCurrentNodeWidth(525);
                } else {
                    setCurrentNodeWidth(nodeWidth);
                }

                if (nodeHeight == undefined) {
                    setCurrentNodeHeight(350);
                } else {
                    setCurrentNodeHeight(nodeHeight);
                }
            }

            if(!minimized)
                setExpandStatus("expanded");
        }

    }, [minimized]);

    useEffect(() => {
        if (noContent) return;

        if (nodeWidth == undefined || nodeWidth < MIN_NODE_WIDTH) {
            setCurrentNodeWidth(525);
        }

        if (nodeHeight == undefined || nodeHeight < MIN_NODE_HEIGHT) {
            setCurrentNodeHeight(350);
        }
    }, []);

    useEffect(() => {
        if (noContent) return;

        const resizer = document.getElementById(
            nodeId + "resizer"
        ) as HTMLElement;
        const resizable = document.getElementById(
            nodeId + "resizable"
        ) as HTMLElement;

        if (!resizer || !resizable) return;

        let startX = 0;
        let startY = 0;
        let startWidth = 0;
        let startHeight = 0;

        function resize(e: any) {
            const newWidth = Math.max(MIN_NODE_WIDTH, startWidth + (e.clientX - startX));
            const newHeight = Math.max(MIN_NODE_HEIGHT, startHeight + (e.clientY - startY));

            resizable.style.width = newWidth + "px";
            resizable.style.height = newHeight + "px";

            setCurrentNodeWidth(newWidth);
            setCurrentNodeHeight(newHeight);
        }

        function stopResize(e: any) {
            window.removeEventListener("mousemove", resize, false);
            window.removeEventListener("mouseup", stopResize, false);

            const newWidth = resizable.offsetWidth;
            const newHeight = resizable.offsetHeight;
            // Read the live node data instead of the closure-captured `data`,
            // which can be stale (e.g. captured before upstream `input` flowed
            // in) and would overwrite live fields when spread back.
            const liveData = getNodes().find((n) => n.id === nodeId)?.data ?? data;
            if (dashboardOn) {
                if (liveData.dashboardWidth !== newWidth || liveData.dashboardHeight !== newHeight) {
                    updateDataNode(nodeId, {
                        ...liveData,
                        dashboardWidth: newWidth,
                        dashboardHeight: newHeight,
                    });
                }
            } else {
                if (liveData.nodeWidth !== newWidth || liveData.nodeHeight !== newHeight) {
                    updateDataNode(nodeId, {
                        ...liveData,
                        nodeWidth: newWidth,
                        nodeHeight: newHeight,
                    });
                }
            }
        }

        function initResize(e: any) {
            startX = e.clientX;
            startY = e.clientY;
            startWidth = resizable.offsetWidth;
            startHeight = resizable.offsetHeight;

            window.addEventListener("mousemove", resize, false);
            window.addEventListener("mouseup", stopResize, false);
        }

        resizer.addEventListener("mousedown", initResize, false);

        return () => {
            resizer.removeEventListener("mousedown", initResize, false);
        };
    }, [dashboardOn, dashboardLocked]);

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

        // onNodesChange([change]);
        applyRemoveChanges([change]);
    };

    const addComment = (comment: IComment) => {
        setComments([...comments, comment]);
    };

    useEffect(() => {
        setPinnedToDashboard(!!dashboardPins[nodeId]);
    }, [dashboardPins[nodeId]]);

    const updatePin = (nodeId: string, value: boolean) => {
        setPinnedToDashboard(!value);
        setPinForDashboard(nodeId, !value);
    };

    const handleChangeExpectedInputType = (event: React.ChangeEvent<HTMLSelectElement>) => {
        setExpectedInputType(event.target.value as SupportedType);
    };

    const handleChangeExpectedOutputType = (event: React.ChangeEvent<HTMLSelectElement>) => {
        setExpectedOutputType(event.target.value as SupportedType);
    };

    const nodeIconTranslation = (nodeType: NodeTemplateId) => {
        try { return getNodeDescriptor(nodeType).icon; }
        catch { return faCopy; }
    };

    const packageDescriptor = tryGetNodeDescriptor(data.nodeType as NodeTemplateId);
    const headerKindLabel = resolveNodeDisplayLabel(data);
    const hasPackageMetaHeader = packageDescriptor?.source === "package" && !!packageDescriptor.package;
    const showPackageNodeActions = hasPackageMetaHeader && !dashboardOn;
    const suggestionActive = data.suggestionType != "none" && data.suggestionType != undefined;
    const nodeHeaderBandPx = 28;

    // --- Dataset drag-and-drop via capture-phase native listeners ---
    // Monaco editor installs its own native dragover/drop handlers that call
    // stopPropagation() before React's event delegation layer runs. Using
    // capture-phase listeners lets us intercept the event *before* Monaco.
    const resizableRef = useRef<HTMLDivElement>(null);

    // Keep a ref to the handler so the capture listener always uses the latest
    // closure values (data, code, etc.) without needing to re-register.
    const datasetDropHandlerRef = useRef<(e: DragEvent) => void>(() => {});
    datasetDropHandlerRef.current = (e: DragEvent) => {
        if (!e.dataTransfer) return;
        const dataset = readDatasetDragPayload(e.dataTransfer);
        if (!dataset) return;
        if (!canApplyDatasetToNode(data)) {
            // Let the event bubble to the canvas drop target.
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        const applied = applyDatasetToNodeData(data, code ?? data.code ?? data.defaultCode, dataset);
        updateDataNode(nodeId, applied.data);
        updateDefaultCode(nodeId, applied.code);
        sendCodeToWidgets?.(applied.code);
        markDirty();
        showToast(`Applied ${dataset.title} to this node.`, "success");
    };
    const canApplyRef = useRef(false);
    canApplyRef.current = canApplyDatasetToNode(data);

    useEffect(() => {
        const el = resizableRef.current;
        if (!el) return;

        const handleDragOver = (e: DragEvent) => {
            if (!e.dataTransfer || !hasDatasetDrag(e.dataTransfer)) return;
            if (!canApplyRef.current) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = "copy";
        };

        const handleDrop = (e: DragEvent) => {
            datasetDropHandlerRef.current(e);
        };

        el.addEventListener("dragover", handleDragOver, true);
        el.addEventListener("drop", handleDrop, true);
        return () => {
            el.removeEventListener("dragover", handleDragOver, true);
            el.removeEventListener("drop", handleDrop, true);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [nodeId]);

    // Keep React synthetic handlers as pass-throughs so the browser still
    // sees preventDefault() called (belt-and-suspenders).
    const onDatasetDragOver = (event: React.DragEvent<HTMLDivElement>) => {
        if (!hasDatasetDrag(event.dataTransfer)) return;
        if (!canApplyDatasetToNode(data)) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "copy";
    };

    const onDatasetDrop = (event: React.DragEvent<HTMLDivElement>) => {
        // Primary handling is done by the capture-phase native listener above.
        // This synthetic handler is kept only to prevent browser default actions
        // (e.g. Monaco opening dropped file as text) for dataset drags that the
        // native listener already handled.
        if (!hasDatasetDrag(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
    };

    return (
        <>

            {/* <div 
                id={nodeId+"resizer"} 
                className={"resizer nowheel nodrag"} 
                style={{
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                }}>
            </div> */}
            
            {data.suggestionAcceptable ?
                <button 
                    style={
                        {...buttonAcceptSuggestion}
                    } 
                    onClick={() => {
                        acceptSuggestion(nodeId)
                    }}>
                        Accept Suggestion
                </button> :
                null
            }

            {/* Per-node warnings. `updateWarnings` maps them onto nodes from
                the spec and `useCode.loadTrill` round-trips them, so the data
                has never stopped flowing; the indicator was deleted along with
                the retired AI-mode chrome, which left the channel writing into
                nothing and a user with no way to see a flagged node. */}
            {!minimized && Array.isArray(data.warnings) && data.warnings.length > 0 ? (
                <div
                    style={{
                        display: "flex",
                        flexDirection: "row",
                        position: "absolute",
                        bottom: "-45px",
                        right: "20px",
                        ...((data.suggestionType != "none" && data.suggestionType != undefined)
                            ? { opacity: "50%" }
                            : {}),
                    }}
                >
                    <FontAwesomeIcon
                        style={{ fontSize: "24px", color: "#e8c548" }}
                        icon={faTriangleExclamation}
                        title={`${data.warnings.length} warning${data.warnings.length === 1 ? "" : "s"}`}
                        onMouseEnter={() => setShowWarnings(true)}
                        onMouseLeave={() => setShowWarnings(false)}
                    />
                    <ul
                        style={{
                            padding: "5px",
                            backgroundColor: "white",
                            border: "1px solid black",
                            zIndex: 300,
                            position: "fixed",
                            width: "300px",
                            maxHeight: "200px",
                            marginLeft: "30px",
                            overflowY: "auto",
                            ...(showWarnings ? {} : { display: "none" }),
                        }}
                    >
                        {data.warnings.map((warning: string, index: number) => (
                            <li key={nodeId + "_warning_" + index}>
                                <p>{warning}</p>
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}

            {(!dashboardOn || !dashboardLocked) && !noContent && <div
                id={nodeId + "resizer"}
                className={"resizer nowheel nodrag"}
                style={{
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                }}
            ></div>}
            <div
                ref={resizableRef}
                id={nodeId + "resizable"}
                className={"resizable"}
                data-curio-node-status={nodeRunStatus(output)}
                onDragOver={onDatasetDragOver}
                onDrop={onDatasetDrop}
                style={{
                    ...getNodeContainerStyles(data.nodeType),
                    ...styles,
                    width: currentNodeWidth + "px",
                    height: currentNodeHeight + "px",
                    ...(minimized ? { display: "none" } : {}),
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {opacity: 0.5, borderWidth: "2px", borderStyle: "dashed", pointerEvents: "none"} : {}),
                    ...(data.suggestionAcceptable ? {borderColor: "#1d3853"} : {}),
                    ...(data.keywordHighlighted ? {backgroundColor: "#1E1F23"} : {}),
                    ...(dashboardOn ? {border: "2px solid #000", boxShadow: "none", borderRadius: "0", resize: "none"} : {})
                }}
            >
                {!noContent && !dashboardOn ? (
                    <>
                        <div style={{
                        display: "flex",
                        alignItems: "center",
                        height: `${nodeHeaderBandPx}px`,
                        marginBottom: "1px",
                        borderBottom: "1px solid rgba(107, 107, 107, 0.3)",
                        gap: "4px",
                        padding: "0 4px",
                        boxSizing: "border-box",
                        width: "100%",
                        flexShrink: 0,
                        ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                        }}>
                        {/* Minimize toggle */}
                        <HeaderIconButton
                            icon={faMinus}
                            style={{ ...headerIconStyle, flexShrink: 0, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                            title="Minimize"
                            onActivate={() => setMinimized(true)}
                        />

                        {/* Node title — editable on package nodes (same visibility as PACKAGE pills) */}
                        <EditableNodeHeaderLabel
                            displayLabel={headerKindLabel}
                            editable={showPackageNodeActions}
                            showConfig={showPackageNodeActions}
                            executed={nodeExecStatus[nodeId] === "executed"}
                            keywordHighlighted={!!data.keywordHighlighted}
                            onLabelCommit={(label) => {
                                updateDataNode(nodeId, { ...data, packageTemplateLabel: label });
                            }}
                            onConfigure={() => setConfigOpen(true)}
                        />

                        {hasPackageMetaHeader && packageDescriptor?.package ? (
                            <PackageMetaHeader
                                pkg={packageDescriptor.package}
                                category={packageDescriptor.category}
                                suggestionActive={suggestionActive}
                            />
                        ) : null}

                        {/* Dataset linkage pills — independent of the PACKAGE pill
                            and of each other; any combination may render. */}
                        {datasetPaletteNode && data.datasetSource ? (
                            <DatasetMetaHeader
                                source={data.datasetSource}
                                variant="consumer"
                                selected={isNodeSelected}
                                suggestionActive={suggestionActive}
                            />
                        ) : null}

                        {producerDataset ? (
                            <DatasetMetaHeader
                                source={{
                                    datasetId: producerDataset.id,
                                    title: producerDataset.title,
                                    format: producerDataset.format,
                                    origin: producerDataset.origin,
                                }}
                                variant="producer"
                                selected={isNodeSelected}
                                suggestionActive={suggestionActive}
                            />
                        ) : null}

                        {/* Right-side action icons */}
                        <HeaderIconButton
                            icon={pinnedToDashboard ? faCircleDot : faCircle}
                            style={{
                                ...headerIconStyle,
                                color: pinnedToDashboard ? "red" : (data.keywordHighlighted ? "rgb(251, 252, 246)" : "#888787"),
                            }}
                            title={pinnedToDashboard ? "Unpin from dashboard" : "Pin to dashboard"}
                            onActivate={() => updatePin(nodeId, pinnedToDashboard)}
                        />
                        <HeaderIconButton
                            icon={faComments}
                            style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                            title="Comments"
                            onActivate={() => setShowComments(!showComments)}
                        />
                        <HeaderIconButton
                            icon={faXmark}
                            style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                            title="Delete node"
                            onActivate={onDelete}
                        />
                        {updateTemplate != undefined && code != undefined && templateData.id != undefined && templateData.custom && code != templateData.code ? (
                            <HeaderIconButton
                                icon={faFloppyDisk}
                                style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                                title="Save template"
                                onActivate={() => updateTemplate({ ...templateData, code: code })}
                            />
                        ) : null}
                    </div>
                    </>
                ) : null}

                <div style={{height: dashboardOn ? "100%" : `calc(100% - ${nodeHeaderBandPx}px)`, width: "calc(100% - 30px)", marginLeft: "auto", marginRight: "auto"}}>
                    {children}
                </div>

                {!dashboardOn && <Row
                    style={{
                        ...{
                            width: "25%",
                            height: "25px",
                            marginLeft: "10px",
                            marginTop: "-25px",
                        },
                        ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})      
                    }}
                >
                    {sendCodeToWidgets != undefined ? (
                        <Row style={{gap: "8px", paddingRight: 0}}>
                            {!disablePlay ?
                                <Col md={3} style={{padding: 0}}>
                                    {isLoading ? (
                                        <Spinner
                                            animation="border"
                                            size="sm"
                                            style={{
                                                color: "rgb(251, 170, 105)",
                                                width: "24px",
                                                height: "24px",
                                                marginTop: "2px",
                                            }}
                                        />
                                    ) : (
                                        <FontAwesomeIcon
                                            className={"nowheel nodrag"}
                                            icon={faCirclePlay}
                                            style={{
                                                cursor: "pointer",
                                                fontSize: "27px",
                                                color: "rgb(251, 170, 105)",
                                            }}
                                            onClick={() => {
                                                playNodesUpTo(data.nodeId);
                                            }}
                                        />
                                    )}
                                </Col> : null
                            }
                            {!disablePlay && !datasetPaletteNode ? (
                                <Col md="auto" style={{ padding: 0, display: "flex", alignItems: "center" }}>
                                    <SaveOutputToggle
                                        variant="node"
                                        id={`save-output-${data.nodeId}`}
                                        checked={saveOutputDataset}
                                        disabled={isLoading}
                                        onChange={(next) => {
                                            updateDataNode(nodeId, { ...data, saveOutputDataset: next });
                                        }}
                                    />
                                </Col>
                            ) : null}
                            {output != undefined ? (
                                <Col
                                    md={2}
                                    className="d-flex align-items-center"
                                    style={{padding: 0}}
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
                                            <>
                                                <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
                                                {' '}
                                            </>
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
                            {/*{promptModal != undefined ? (*/}
                            {/*    <Col md={5} style={{padding: 0}}>*/}
                            {/*        <Dropdown>*/}
                            {/*            <Dropdown.Toggle*/}
                            {/*                variant="primary"*/}
                            {/*                style={{ */}
                            {/*                    fontSize: "8.5px",*/}
                            {/*                    padding: "6px 2px",*/}
                            {/*                    backgroundColor: "rgb(251, 170, 105)",*/}
                            {/*                    border: "none",*/}
                            {/*                    width: "100%"*/}
                            {/*                 }}*/}
                            {/*                 onMouseEnter={() => {fetchStarters()}}*/}
                            {/*            >*/}
                            {/*                Templates*/}
                            {/*            </Dropdown.Toggle>*/}

                            {/*            <Dropdown.Menu*/}
                            {/*                style={{*/}
                            {/*                    padding: "5px",*/}
                            {/*                    fontSize: "9px",*/}
                            {/*                    overflowY: "auto",*/}
                            {/*                    maxHeight: "200px",*/}
                            {/*                }}*/}
                            {/*            >*/}
                            {/*                <Dropdown.Item*/}
                            {/*                    style={{ padding: 0 }}*/}
                            {/*                    onClick={() => {*/}
                            {/*                        promptModal(true);*/}
                            {/*                    }}*/}
                            {/*                >*/}
                            {/*                    + New Template*/}
                            {/*                </Dropdown.Item>*/}

                            {/*                {getStarters(*/}
                            {/*                    data.nodeType as NodeType,*/}
                            {/*                    false*/}
                            {/*                ).length > 0 ? (*/}
                            {/*                    <>*/}
                            {/*                        <Dropdown.Divider*/}
                            {/*                            style={{ padding: 0 }}*/}
                            {/*                        />*/}
                            {/*                        <Dropdown.ItemText*/}
                            {/*                            style={{*/}
                            {/*                                padding: 0,*/}
                            {/*                                fontWeight: "bold",*/}
                            {/*                            }}*/}
                            {/*                        >*/}
                            {/*                            Default Templates*/}
                            {/*                        </Dropdown.ItemText>*/}
                            {/*                        {getStarters(*/}
                            {/*                            data.nodeType as NodeType,*/}
                            {/*                            false*/}
                            {/*                        ).map(*/}
                            {/*                            (*/}
                            {/*                                template: Template,*/}
                            {/*                                index: number*/}
                            {/*                            ) => {*/}
                            {/*                                return (*/}
                            {/*                                    <Dropdown.Item*/}
                            {/*                                        key={*/}
                            {/*                                            "templates_modal_content_default_" +*/}
                            {/*                                            data.nodeType +*/}
                            {/*                                            index +*/}
                            {/*                                            nodeId*/}
                            {/*                                        }*/}
                            {/*                                        style={*/}
                            {/*                                            template.accessLevel ==*/}
                            {/*                                            AccessLevelType.PROGRAMMER*/}
                            {/*                                                ? buttonStyleProgrammer*/}
                            {/*                                                : template.accessLevel ==*/}
                            {/*                                                    AccessLevelType.EXPERT*/}
                            {/*                                                    ? buttonStyleExpert*/}
                            {/*                                                    : buttonStyleAny*/}
                            {/*                                        }*/}
                            {/*                                        onClick={() => {*/}
                            {/*                                            setTemplateConfig(*/}
                            {/*                                                template*/}
                            {/*                                            );*/}
                            {/*                                        }}*/}
                            {/*                                    >*/}
                            {/*                                        {*/}
                            {/*                                            template.name*/}
                            {/*                                        }*/}
                            {/*                                    </Dropdown.Item>*/}
                            {/*                                );*/}
                            {/*                            }*/}
                            {/*                        )}*/}
                            {/*                    </>*/}
                            {/*                ) : null}*/}

                            {/*                {getStarters(*/}
                            {/*                    data.nodeType as NodeType,*/}
                            {/*                    true*/}
                            {/*                ).length > 0 ? (*/}
                            {/*                    <>*/}
                            {/*                        <Dropdown.Divider*/}
                            {/*                            style={{ padding: 0 }}*/}
                            {/*                        />*/}
                            {/*                        <Dropdown.ItemText*/}
                            {/*                            style={{*/}
                            {/*                                padding: 0,*/}
                            {/*                                fontWeight: "bold",*/}
                            {/*                            }}*/}
                            {/*                        >*/}
                            {/*                            Custom Templates*/}
                            {/*                        </Dropdown.ItemText>*/}
                            {/*                        {getStarters(*/}
                            {/*                            data.nodeType as NodeType,*/}
                            {/*                            true*/}
                            {/*                        ).map(*/}
                            {/*                            (*/}
                            {/*                                template: Template,*/}
                            {/*                                index: number*/}
                            {/*                            ) => {*/}
                            {/*                                return (*/}
                            {/*                                    <Dropdown.Item*/}
                            {/*                                        style={{*/}
                            {/*                                            padding: 0,*/}
                            {/*                                        }}*/}
                            {/*                                        key={*/}
                            {/*                                            "templates_modal_content_custom_" +*/}
                            {/*                                            data.nodeType +*/}
                            {/*                                            index +*/}
                            {/*                                            nodeId*/}
                            {/*                                        }*/}
                            {/*                                        onClick={() => {*/}
                            {/*                                            setTemplateConfig(*/}
                            {/*                                                template*/}
                            {/*                                            );*/}
                            {/*                                        }}*/}
                            {/*                                    >*/}
                            {/*                                        <span*/}
                            {/*                                            style={*/}
                            {/*                                                template.accessLevel ==*/}
                            {/*                                                AccessLevelType.PROGRAMMER*/}
                            {/*                                                    ? buttonStyleProgrammer*/}
                            {/*                                                    : template.accessLevel ==*/}
                            {/*                                                        AccessLevelType.EXPERT*/}
                            {/*                                                        ? buttonStyleExpert*/}
                            {/*                                                        : buttonStyleAny*/}
                            {/*                                            }*/}
                            {/*                                        >*/}
                            {/*                                            {*/}
                            {/*                                                template.name*/}
                            {/*                                            }*/}
                            {/*                                        </span>*/}
                            {/*                                        <FontAwesomeIcon*/}
                            {/*                                            onClick={() => {*/}
                            {/*                                                deleteStarter(*/}
                            {/*                                                    template.id*/}
                            {/*                                                );*/}
                            {/*                                            }}*/}
                            {/*                                            icon={*/}
                            {/*                                                faSquareMinus*/}
                            {/*                                            }*/}
                            {/*                                            style={{*/}
                            {/*                                                color: "#888787",*/}
                            {/*                                                padding: 0,*/}
                            {/*                                                marginLeft:*/}
                            {/*                                                    "5px",*/}
                            {/*                                            }}*/}
                            {/*                                        />*/}
                            {/*                                    </Dropdown.Item>*/}
                            {/*                                );*/}
                            {/*                            }*/}
                            {/*                        )}*/}
                            {/*                    </>*/}
                            {/*                ) : null}*/}
                            {/*            </Dropdown.Menu>*/}
                            {/*        </Dropdown>*/}
                            {/*    </Col>*/}
                            {/*) : null}*/}
                            {/* </Col> */}
                        </Row>
                    ) : null}
                </Row>}

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
                    onMouseEnter={() => setChipHovered(true)}
                    onMouseLeave={() => setChipHovered(false)}
                    style={{
                        ...{
                            width: currentNodeWidth + "px",
                            height: currentNodeHeight + "px",
                            backgroundColor: "#ffffff",
                            borderRadius: "10px",
                            padding: "5px",
                            justifyContent: "center",
                            display: "flex",
                            alignItems: "center",
                            position: "relative",
                            boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
                        },
                        ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                    }}
                    onClick={() => {
                        if (!noContent) {
                            if (nodeWidth == undefined) {
                                setCurrentNodeWidth(525);
                            } else {
                                setCurrentNodeWidth(nodeWidth);
                            }

                            if (nodeHeight == undefined) {
                                setCurrentNodeHeight(350);
                            } else {
                                setCurrentNodeHeight(nodeHeight);
                            }

                            setMinimized(false);
                        }
                    }}
                >
                    <FontAwesomeIcon
                        icon={nodeIconTranslation(data.nodeType)}
                        style={{ 
                            ...iconStyle, 
                            fontSize: "23px",
                            ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {color: "#888787"})
                        }}
                    />
                    {/* A noContent node (merge-flow, spatial-join) is the one
                        shape that never renders the header band, and it can
                        never be expanded to reach one - so without this it has
                        no on-node control at all, and the only way to remove a
                        mis-dropped one is the Delete key, which nothing on
                        screen suggests. Delete alone: an icon-only flow node
                        renders no output to pin to a dashboard and has no body
                        to annotate. Revealed on hover so the 50x180 chip reads
                        the same at rest. */}
                    {noContent && !dashboardOn ? (
                        <div
                            style={{
                                position: "absolute",
                                top: "2px",
                                right: "3px",
                                // Quiet at rest, legible on hover. This file
                                // styles inline, so the transition is state
                                // rather than a :hover rule.
                                opacity: chipHovered ? 1 : 0.35,
                                transition: "opacity 120ms ease",
                            }}
                        >
                            <HeaderIconButton
                                icon={faXmark}
                                style={{ ...headerIconStyle, fontSize: "10px" }}
                                title="Delete node"
                                onActivate={onDelete}
                            />
                        </div>
                    ) : null}
                </div>
            ) : null}

            {/* Maximize button removed: noContent nodes (merge-flow,
                spatial-join, …) have no body to expand to, so the previous
                `noContent && nodeType != MERGE_FLOW` dead-code branch is
                gone. */}

            <NodeSaveAsModal show={saveAsOpen} nodeId={nodeId} onClose={() => setSaveAsOpen(false)} />
            <NodeTemplateConfigModal
                show={configOpen}
                nodeId={nodeId}
                nodeType={data.nodeType}
                storedConfig={readCanvasTemplateConfig({ data })}
                storedLabel={data.packageTemplateLabel}
                templateCode={code ?? data.defaultCode ?? ""}
                onClose={() => setConfigOpen(false)}
                onSave={(config: CanvasTemplateConfig) => {
                    updateDataNode(nodeId, {
                        ...data,
                        packageTemplateLabel: config.label.trim(),
                        packageTemplateConfig: config,
                    });
                    setConfigOpen(false);
                    setSaveAsOpen(true);
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

const headerIconStyle: CSS.Properties = {
    cursor: "pointer",
    fontSize: "11px",
    color: "#888787",
    flexShrink: 0,
};

// Node border colour = node category, read from the shared palette rather than
// restated here. DataflowThumbnail used to carry a hand-kept copy of the same
// hexes, and the Node Catalog picked a third set by hashing a directory name.
const nodeTypeBorderColor: Record<string, string> = {
    [NodeType.DATA_LOADING]: categoryFg("data"),
    [NodeType.DATA_EXPORT]: categoryFg("data"),
    [NodeType.DATA_TRANSFORMATION]: categoryFg("data"),
    [NodeType.DATA_SUMMARY]: categoryFg("data"),
    [NodeType.COMPUTATION_ANALYSIS]: categoryFg("computation"),
    [NodeType.MERGE_FLOW]: categoryFg("computation"),
    [NodeType.DATA_POOL]: categoryFg("computation"),
    [NodeType.VIS_VEGA]: categoryFg("vis"),
    [NodeType.VIS_SIMPLE]: categoryFg("vis"),
};

const getNodeContainerStyles = (nodeType: string): CSS.Properties => ({
    position: "relative",
    backgroundColor: "#ffffff",
    // `nodeType` arrives versioned for palette-dragged nodes
    // (`curio.builtin/merge-flow@1`) but this map is keyed by the unversioned
    // NodeType enum, so an unnormalized lookup silently falls back to grey (#159).
    borderLeft: `4px solid ${nodeTypeBorderColor[unversionedNodeType(nodeType)] ?? CATEGORY_FALLBACK_FG}`,
    borderRadius: "10px",
    padding: "5px",
    boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
});

const nodeContentStyle: CSS.Properties = {
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

const buttonAcceptSuggestion: CSS.Properties = {
    position: "absolute",
    top: "-50px",
    cursor: "pointer",
    backgroundColor: "#1E1F23",
    color: "rgb(251, 252, 246)",
    fontFamily: "Rubik",
    padding: "6px 10px",
    fontWeight: "bold",
    border: "none",
    borderRadius: "4px",
};

const openSubtasksButton: CSS.Properties = {
    position: "absolute",
    bottom: "-80px",
    left: "calc(50% - 12px)"
}

const closedSubtasksButton: CSS.Properties = {
    position: "absolute",
    bottom: "-25px",
    left: "calc(50% - 12px)"
}

const openConnectionLeftButton: CSS.Properties = {
    position: "absolute",
    left: "-190px",
    top: "calc(50% - 12px)"
}

const closedConnectionLeftButton: CSS.Properties = {
    position: "absolute",
    left: "-35px",
    top: "calc(50% - 12px)"
}

const openConnectionRightButton: CSS.Properties = {
    position: "absolute",
    right: "-190px",
    top: "calc(50% - 12px)"
}

const closedConnectionRightButton: CSS.Properties = {
    position: "absolute",
    right: "-35px",
    top: "calc(50% - 12px)"
}

const goalInput: CSS.Properties = {
    position: "absolute",
    bottom: "-50px",
    left: "2px",
    backgroundColor: "#1E1F23",
    color: "rgb(251, 252, 246)",
    borderRadius: "0 0 10px 10px",
    fontFamily: "Rubik",
    paddingTop: "10px",
    height: "60px",
    display: "flex", 
    justifyContent: "center",
    alignItems: "center"
}

const inputTypeSelect: CSS.Properties = {
    position: "absolute",
    left: "-160px",
    fontSize: "13px",
    top: "calc(50% - 13px)",
    fontFamily: "Rubik",
    color: "#1E1F23"
}

const newInConnectionStyle: CSS.Properties = {
    position: "absolute",
    left: "-105px",
    fontSize: "25px",
    top: "calc(50% - 50px)",
    color: "#1E1F23"
};

const outputTypeSelect: CSS.Properties = {
    position: "absolute",
    right: "-160px",
    fontSize: "13px",
    top: "calc(50% - 13px)",
    fontFamily: "Rubik",
    color: "#1E1F23"
}

const newOutConnectionStyle: CSS.Properties = {
    position: "absolute",
    right: "-100px",
    fontSize: "25px",
    top: "calc(50% - 50px)",
    color: "#1E1F23"
};
