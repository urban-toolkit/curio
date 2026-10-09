import React, { ReactNode, useState, useEffect, useMemo, useRef } from "react";
import CSS from "csstype";
import { Dropdown } from "react-bootstrap";

import { useFlowContext } from "../providers/FlowProvider";
import { useNotebookViewContext } from "../providers/flow/notebookViewContext";
import { NodeRemoveChange, useReactFlow, useStore } from "reactflow";

import { CommentsList, IComment } from "./comments/CommentsList";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faComments,
    faCircle,
    faCircleDot,
} from "@fortawesome/free-solid-svg-icons";
import { useToastContext } from "../providers/ToastProvider";
import {
    useDatasetDetails,
    viewDatasetDetailsToast,
} from "./datasets/catalog/datasetDetailsContext";
import { useUserContext } from "../providers/UserProvider";
import { commentsFromMetadata, commentsToMetadata } from "../utils/nodeComments";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import { NODE_CATEGORY_KEY, categoryFg, colorForNodeType } from "../constants/nodeCategoryPalette";
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
import {
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
    faCircleInfo,
    faTriangleExclamation,
    faChartLine,
    faAnglesUp
} from "@fortawesome/free-solid-svg-icons";
import {
    AccessLevelType,
    DEFAULT_NODE_HEIGHT,
    DEFAULT_NODE_WIDTH,
    MIN_NODE_HEIGHT,
    MIN_NODE_WIDTH,
    MINIMIZED_NODE_HEIGHT,
    MINIMIZED_NODE_WIDTH,
    SupportedType,
} from "../constants";
import { clampNodeBox } from "../utils/nodeBoxSize";
import { getNodeDescriptor, tryGetNodeDescriptor } from "../registry";
import { NodeCategory, NodeTemplateId } from "../registry/types";
import {
    applyDatasetToNodeData,
    canApplyDatasetToNode,
    hasDatasetDrag,
    readDatasetDragPayload,
} from "../services/datasetCatalog";
import {
    applyModelToNodeData,
    canApplyModelToNode,
    hasModelDrag,
    readModelDragPayload,
} from "../services/modelCatalog";
import "./styles.css";
import { useStarterContext } from "../providers/StarterProvider";
import { useCode } from "../hook/useCode";
import { TrillGenerator } from "TrillGenerator";
import { ICodeData } from "types";
import { NodeRunControls } from "./nodes/NodeRunControls";
import { NodeResizeHandle } from "./nodes/NodeResizeHandle";
import { NodeDeleteTool } from "./nodes/NodeDeleteTool";
import { useSharedView } from "../hook/useSharedView";
import { NodeHeaderSlotContext } from "./editing/nodeHeaderSlot";
import { resolveSaveOutputDataset, showsSaveOutputToggle } from "../utils/saveOutputDataset";
import { nodeRunStatus, nodeRunError } from "../utils/nodeRunStatus";
import { hasNodeDescription } from "../utils/nodeDescription";
import { droppedDatasetSource, isDatasetPaletteNode } from "../services/datasetCatalog/datasetApplication";
import { DatasetMetaHeader } from "./datasets/DatasetMetaHeader";
import { useDatasetPalette } from "../providers/DatasetPaletteContext";


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
    cellBox,
    noContent,
    setTemplateConfig,
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
    /** The notebook cell's width and least height, only in the notebook view;
     *  the cell is otherwise as tall as its content. Kept apart from
     *  `nodeWidth`/`nodeHeight`, which feed the node's own size state: that
     *  state is the canvas size the node goes back to. */
    cellBox?: { width: number; minHeight: number };
    noContent?: boolean;
    setTemplateConfig?: any;
    styles?: CSS.Properties;
    handleType?: string;
    disablePlay?: boolean;
    isLoading?: boolean;
}) => {
    const { showToast } = useToastContext();
    const { openDatasetDetails } = useDatasetDetails();
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
    // A notebook cell is never minimized or resized: its width comes from the
    // column and its height from its content, and the node's own size stays its
    // canvas size. An icon-only node keeps its chip, stretched to the column.
    const notebook = useNotebookViewContext();
    const notebookCell = notebook.on && !dashboardOn && !noContent;
    // A read-only canvas keeps every node at its size; only an owner resizes.
    const sizeLocked = useSharedView();
    const saveOutputDataset = resolveSaveOutputDataset(data, defaultSaveOutputDataset);
    // Nodes created from the dataset palette load an installed listing and can't
    // regenerate a dataset — hide the save toggle and show the dataset chip instead.
    const datasetPaletteNode = isDatasetPaletteNode(data);
    // Producer linkage: if this node generated an installed computed dataset, show
    // an OUTPUT chip linking to its palette row. Derived from the catalog (not
    // stamped) so it tracks install/uninstall. Distinct from the save-lock above —
    // producer nodes keep their save toggle.
    const { installedComputedByProducer: producerByNode, datasetsById } = useDatasetPalette();
    const producerDataset = producerByNode.get(nodeId);
    // A node a dataset was dropped onto reads it too, so it gets a DATASET
    // pill as well (#442), without becoming a palette node: saving stays on.
    const consumerSource = datasetPaletteNode
        ? (data.datasetSource ?? null)
        : droppedDatasetSource(data, (id) => datasetsById?.get(id));
    // Whether this node is selected on the canvas — drives a more vibrant dataset
    // chip. Read reactively from the React Flow store so it updates on selection.
    const isNodeSelected = useStore((s) => !!s.nodeInternals.get(nodeId)?.selected);
    const { getNodes, getEdges } = useReactFlow();
    const { getStarters, deleteStarter, fetchStarters } = useStarterContext();
    const { createCodeNode, loadTrill } = useCode();
    const [showComments, setShowComments] = useState(false);
    const { user: currentUser } = useUserContext();
    const [saveAsOpen, setSaveAsOpen] = useState(false);
    const [configOpen, setConfigOpen] = useState(false);
    // Derived from node data rather than held in local state (#237). Comments
    // used to live in a `useState` that nothing ever wrote back, so they were
    // lost on save and on every remount - reopening the project was the path
    // the reporter took.
    // Reading through `data` makes the canvas node the single source of truth,
    // so there is no second copy to fall out of step with the saved spec.
    const viewer = useMemo(
        () =>
            currentUser
                ? {
                      username: currentUser.username,
                      name: currentUser.name,
                      photo: currentUser.profile_image,
                  }
                : null,
        [currentUser],
    );
    const comments = useMemo<IComment[]>(
        () => commentsFromMetadata(data.comments, viewer),
        [data.comments, viewer],
    );

    /** Write the whole list back to the node and mark the project dirty.
     *  Reads live node data first, for the same reason the resize handler
     *  does: the captured `data` prop can be stale and would clobber fields
     *  that changed under it. */
    const commitComments = (next: IComment[]) => {
        const liveData = getNodes().find((n) => n.id === nodeId)?.data ?? data;
        updateDataNode(nodeId, {
            ...liveData,
            comments: commentsToMetadata(next),
        });
        markDirty();
    };
    const [pinnedToDashboard, setPinnedToDashboard] = useState<boolean>(!!dashboardPins[nodeId]);
    const [expectedInputType, setExpectedInputType] = useState(data.in);
    const [expectedOutputType, setExpectedOutputType] = useState(data.out);
    const [showWarnings, setShowWarnings] = useState<boolean>(false);
    // A node with content starts at the size the mount clamp below gives it, so
    // its first render is already its final size: the canvas measures that
    // render for its load fit (#683). An icon-only node keeps its own footprint.
    const [currentNodeWidth, setCurrentNodeWidth] = useState<number | undefined>(
        () => (noContent ? nodeWidth : clampNodeBox(nodeWidth, nodeHeight).width)
    );
    const [currentNodeHeight, setCurrentNodeHeight] = useState<number | undefined>(
        () => (noContent ? nodeHeight : clampNodeBox(nodeWidth, nodeHeight).height)
    );
    // Icon-only nodes (manifest `containerStyle.noContent: true`)
    // start minimized: they have no body to expand and the 50×180 footprint is
    // their default render. (Spatial Join left this set in #262, when it gained
    // a body with the polygon-property control.)
    const [minimized, setMinimized] = useState(!!noContent);
    // Hover state for the minimized chip's delete control (noContent nodes have
    // no header band to put it in).
    const [chipHovered, setChipHovered] = useState(false);
    const shownMinimized = minimized && !notebookCell;
    const boxWidth = notebookCell && cellBox ? cellBox.width : currentNodeWidth;
    // The cell's box: as tall as its content, never shorter than its dots need.
    const cellBoxStyle: CSS.Properties = notebookCell
        ? { height: "auto", minHeight: `${cellBox?.minHeight ?? 0}px` }
        : { height: currentNodeHeight + "px" };

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
                setCurrentNodeWidth(MINIMIZED_NODE_WIDTH);
                setCurrentNodeHeight(MINIMIZED_NODE_HEIGHT);
            } else {
                if (nodeWidth == undefined) {
                    setCurrentNodeWidth(DEFAULT_NODE_WIDTH);
                } else {
                    setCurrentNodeWidth(nodeWidth);
                }

                if (nodeHeight == undefined) {
                    setCurrentNodeHeight(DEFAULT_NODE_HEIGHT);
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
            setCurrentNodeWidth(DEFAULT_NODE_WIDTH);
        }

        if (nodeHeight == undefined || nodeHeight < MIN_NODE_HEIGHT) {
            setCurrentNodeHeight(DEFAULT_NODE_HEIGHT);
        }
    }, []);

    // The corner handle (NodeResizeHandle) sizes the box as it is dragged.
    const resizeBox = (width: number, height: number) => {
        setCurrentNodeWidth(width);
        setCurrentNodeHeight(height);
    };

    // The size the drag ends at goes into the node's data.
    const keepBoxSize = (newWidth: number, newHeight: number) => {
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
                // Tile geometry is saved state, so resizing one is an edit.
                markDirty();
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
    };

    const deleteComment = (commentId: string) => {
        commitComments(comments.filter((comment) => comment.id !== commentId));
    };

    const toggleResolveComment = (commentId: string) => {
        commitComments(
            comments.map((comment) =>
                comment.id === commentId
                    ? { ...comment, resolved: !comment.resolved }
                    : comment,
            ),
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
        commitComments([...comments, comment]);
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
    // The header holds Play, the title, the pills, the status and the tools,
    // on the canvas and in a notebook cell alike.
    const nodeHeaderBandPx = 36;
    // Where the header holds the editor's tab switchers (nodeHeaderSlot).
    const [tabSlot, setTabSlot] = useState<HTMLElement | null>(null);
    // Play, the Save output toggle and the status, each in its place in the
    // header.
    const runControls = {
        nodeId,
        disablePlay: !!disablePlay,
        isLoading,
        output,
        showSaveToggle: showsSaveOutputToggle(data, !!disablePlay),
        saveOutput: saveOutputDataset,
        onSaveOutputChange: (next: boolean) => {
            updateDataNode(nodeId, { ...data, saveOutputDataset: next });
        },
        onPlay: () => {
            playNodesUpTo(data.nodeId);
        },
    };
    // A dashboard tile's title band: narrower than the canvas header, and the
    // only thing on the tile that can be dragged while the layout is unlocked.
    const dashboardTitleBandPx = 28;

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
        showToast(
            `Applied ${dataset.title} to this node.`,
            "success",
            viewDatasetDetailsToast(openDatasetDetails, dataset.datasetId),
        );
    };
    const canApplyRef = useRef(false);
    canApplyRef.current = canApplyDatasetToNode(data);

    // --- Model drag-and-drop, through the same capture-phase listeners ---
    // A model goes only onto a node whose code calls `curio_load_model("...")`. Every
    // other node still takes the drop, so it can say why nothing changed rather
    // than letting the drop fall through to the canvas, which would make a new
    // node that runs the model.
    const modelDropHandlerRef = useRef<(e: DragEvent) => void>(() => {});
    modelDropHandlerRef.current = (e: DragEvent) => {
        if (!e.dataTransfer) return;
        const model = readModelDragPayload(e.dataTransfer);
        if (!model) return;
        e.preventDefault();
        e.stopPropagation();
        // The editor's live text, which can be ahead of `data.code`.
        const live = { ...data, code: code ?? data.code ?? data.defaultCode };
        if (!canApplyModelToNode(live)) {
            showToast("This node does not run a model", "warning");
            return;
        }
        const applied = applyModelToNodeData(live, model);
        updateDataNode(nodeId, applied);
        updateDefaultCode(nodeId, applied.code);
        sendCodeToWidgets?.(applied.code);
        markDirty();
        showToast(`Model set to ${model.name}`, "success");
    };

    useEffect(() => {
        const el = resizableRef.current;
        if (!el) return;

        const handleDragOver = (e: DragEvent) => {
            if (!e.dataTransfer) return;
            // Accepted on every node, eligible or not: a refused dragover
            // cancels the drop, and the drop is what explains the refusal.
            if (hasModelDrag(e.dataTransfer)) {
                e.preventDefault();
                e.stopPropagation();
                e.dataTransfer.dropEffect = "copy";
                return;
            }
            if (!hasDatasetDrag(e.dataTransfer)) return;
            if (!canApplyRef.current) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = "copy";
        };

        const handleDrop = (e: DragEvent) => {
            if (e.dataTransfer && hasModelDrag(e.dataTransfer)) {
                modelDropHandlerRef.current(e);
                return;
            }
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
        if (hasModelDrag(event.dataTransfer)) {
            event.preventDefault();
            event.stopPropagation();
            event.dataTransfer.dropEffect = "copy";
            return;
        }
        if (!hasDatasetDrag(event.dataTransfer)) return;
        if (!canApplyDatasetToNode(data)) return;
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "copy";
    };

    const onDatasetDrop = (event: React.DragEvent<HTMLDivElement>) => {
        // Primary handling is done by the capture-phase native listener above.
        // This synthetic handler is kept only to prevent browser default actions
        // (e.g. Monaco opening dropped file as text) for dataset and model drags
        // that the native listener already handled.
        if (!hasDatasetDrag(event.dataTransfer) && !hasModelDrag(event.dataTransfer)) return;
        event.preventDefault();
        event.stopPropagation();
    };

    // The header's icons, among the node's tools, which show while the pointer
    // is over the node or it is selected.
    const headerIcons = (
        <>
        {/* Right-side action icons */}
        {/* The node's own documentation. ``DescriptionModal`` was
            already implemented and already mounted for every node,
            and ``promptDescription`` was already threaded down to
            here -- destructured at the top of this component and
            then never called. So every kind's manifest description
            shipped unreachable (#225). This is the trigger.

            Generic on purpose: Spatial Join is the kind the issue
            names, but the fix is one button that any kind with a
            description gets, rather than help bolted onto one node. */}
        {hasNodeDescription(packageDescriptor) ? (
            <HeaderIconButton
                icon={faCircleInfo}
                style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                title={`About ${headerKindLabel}`}
                onActivate={promptDescription}
            />
        ) : null}
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
        <NodeDeleteTool
            style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
            onDelete={onDelete}
        />
        {updateTemplate != undefined && code != undefined && templateData.id != undefined && templateData.custom && code != templateData.code ? (
            <HeaderIconButton
                icon={faFloppyDisk}
                style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                title="Save template"
                onActivate={() => updateTemplate({ ...templateData, code: code })}
            />
        ) : null}
        </>
    );

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
            {!shownMinimized && Array.isArray(data.warnings) && data.warnings.length > 0 ? (
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

            {(!dashboardOn || !dashboardLocked) && !noContent && !notebookCell && (
                <NodeResizeHandle
                    nodeId={nodeId}
                    box={resizableRef}
                    disabled={data.suggestionType != "none" && data.suggestionType != undefined}
                    onResize={resizeBox}
                    onResizeEnd={keepBoxSize}
                />
            )}
            <div
                ref={resizableRef}
                id={nodeId + "resizable"}
                // A node's tools show while it is hovered or selected (Node.css);
                // a dashboard tile has none.
                className={dashboardOn ? "resizable" : `resizable curio-node-card${isNodeSelected ? " is-selected" : ""}`}
                data-curio-node-status={nodeRunStatus(output)}
                data-curio-node-error={nodeRunError(output)}
                onDragOver={onDatasetDragOver}
                onDrop={onDatasetDrop}
                style={{
                    ...getNodeContainerStyles(data.nodeType, {
                        dashboardOn,
                        suggested: data.suggestionType != "none" && data.suggestionType != undefined,
                        acceptable: data.suggestionAcceptable,
                        category: packageDescriptor?.category,
                        notebookCell,
                        selected: isNodeSelected,
                    }),
                    ...styles,
                    width: boxWidth + "px",
                    ...cellBoxStyle,
                    // `.resizable` draws the browser's own resize grip, which
                    // the canvas covers with its resize handle; a cell has
                    // none, and nor does a read-only canvas's node, which keeps
                    // its size.
                    ...(notebookCell || sizeLocked ? { resize: "none" } : {}),
                    ...(shownMinimized ? { display: "none" } : {}),
                    ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {opacity: 0.5, pointerEvents: "none"} : {}),
                    ...(data.keywordHighlighted ? {backgroundColor: "#1E1F23"} : {}),
                }}
            >
                {!noContent && dashboardOn ? (
                    <div
                        // Matches DASHBOARD_TILE_DRAG_HANDLE, which the dashboard
                        // page hands React Flow as the tile's ``dragHandle``. No
                        // ``nodrag`` here, deliberately: this band is the handle.
                        className="curio-dashboard-tile-handle"
                        title={headerKindLabel}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            height: `${dashboardTitleBandPx}px`,
                            marginBottom: "1px",
                            padding: "0 4px",
                            boxSizing: "border-box",
                            width: "100%",
                            flexShrink: 0,
                            fontSize: "13px",
                            fontWeight: 600,
                            color: "var(--curio-text-primary)",
                            whiteSpace: "nowrap",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            cursor: dashboardLocked ? "default" : "grab",
                        }}
                    >
                        {headerKindLabel}
                    </div>
                ) : null}

                {!noContent && !dashboardOn ? (
                    <>
                        <div className="curio-node-header" style={{
                        display: "flex",
                        alignItems: "center",
                        height: `${nodeHeaderBandPx}px`,
                        marginBottom: "1px",
                        gap: "4px",
                        padding: "0 4px",
                        boxSizing: "border-box",
                        width: "100%",
                        flexShrink: 0,
                        ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                        }}>
                        {/* Play first, as a notebook cell has it. */}
                        {sendCodeToWidgets != undefined ? (
                            <NodeRunControls {...runControls} part="play" />
                        ) : null}

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
                        {consumerSource ? (
                            <DatasetMetaHeader
                                source={consumerSource}
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

                        {/* The run status, at the right, which pushes the
                            tools (the editor's tabs, Save output, the icons
                            and, on the canvas, Minimize) right after it. */}
                        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", flexShrink: 0 }}>
                            {sendCodeToWidgets != undefined ? (
                                <NodeRunControls {...runControls} part="status" />
                            ) : null}
                        </span>

                        <span className="curio-node-tools" style={{ display: "flex", alignItems: "center", gap: "4px", flexShrink: 0 }}>
                            <span ref={setTabSlot} className="curio-node-tabs" style={{ display: "flex" }} />
                            {sendCodeToWidgets != undefined ? (
                                <NodeRunControls {...runControls} part="save" />
                            ) : null}
                            {headerIcons}
                            {/* A notebook cell keeps its size. */}
                            {!notebookCell ? (
                                <HeaderIconButton
                                    icon={faMinus}
                                    style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                                    title="Minimize"
                                    onActivate={() => setMinimized(true)}
                                />
                            ) : null}
                        </span>
                    </div>
                    </>
                ) : null}

                <div style={{
                    // A notebook cell's body is as tall as what it holds; on
                    // the canvas the body fills the node under its header.
                    height: notebookCell ? "auto" : `calc(100% - ${dashboardOn ? dashboardTitleBandPx : nodeHeaderBandPx}px)`,
                    width: "calc(100% - 30px)",
                    marginLeft: "auto",
                    marginRight: "auto",
                    ...(notebookCell ? { paddingBottom: "8px" } : {}),
                }}>
                    <NodeHeaderSlotContext.Provider value={dashboardOn ? null : tabSlot}>
                        {children}
                    </NodeHeaderSlotContext.Provider>
                </div>

            </div>

            {showComments && (
                <CommentsList
                    comments={comments}
                    addComment={addComment}
                    deleteComment={deleteComment}
                    toggleResolveComment={toggleResolveComment}
                />
            )}

            {shownMinimized ? (
                <div
                    onMouseEnter={() => setChipHovered(true)}
                    onMouseLeave={() => setChipHovered(false)}
                    style={{
                        ...{
                            // An icon-only node in the notebook view is a chip
                            // stretched to the column, as tall as its dots need.
                            width: (cellBox?.width ?? currentNodeWidth) + "px",
                            height: (cellBox ? Math.max(cellBox.minHeight, MINIMIZED_NODE_HEIGHT) : currentNodeHeight) + "px",
                            // The node's card, folded: the same hairline,
                            // radius and soft shadow.
                            backgroundColor: "#ffffff",
                            border: "1px solid var(--curio-border)",
                            borderRadius: "8px",
                            padding: "5px",
                            justifyContent: "center",
                            display: "flex",
                            alignItems: "center",
                            position: "relative",
                            boxShadow: NODE_CARD_SHADOW,
                        },
                        ...((data.suggestionType != "none" && data.suggestionType != undefined) ? {pointerEvents: "none"} : {})
                    }}
                    onClick={() => {
                        if (!noContent) {
                            if (nodeWidth == undefined) {
                                setCurrentNodeWidth(DEFAULT_NODE_WIDTH);
                            } else {
                                setCurrentNodeWidth(nodeWidth);
                            }

                            if (nodeHeight == undefined) {
                                setCurrentNodeHeight(DEFAULT_NODE_HEIGHT);
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
                    {/* A noContent node is the one
                        shape that never renders the header band, and it can
                        never be expanded to reach one - so without this it has
                        no on-node control at all, and the only way to remove a
                        mis-dropped one is the Delete key, which nothing on
                        screen suggests. Revealed on hover so the 50x180 chip
                        reads the same at rest.

                        Info joins Delete here because this shape is exactly the
                        one that needs it most: Spatial Join is a noContent node,
                        it is the kind #225 was reported against, and with no
                        header band this chip is the ONLY surface it has. */}
                    {noContent && !dashboardOn ? (
                        <div
                            style={{
                                position: "absolute",
                                top: "2px",
                                right: "3px",
                                display: "flex",
                                gap: "2px",
                                // Quiet at rest, legible on hover. This file
                                // styles inline, so the transition is state
                                // rather than a :hover rule.
                                opacity: chipHovered ? 1 : 0.35,
                                transition: "opacity 120ms ease",
                            }}
                        >
                            {hasNodeDescription(packageDescriptor) ? (
                                <HeaderIconButton
                                    icon={faCircleInfo}
                                    style={{ ...headerIconStyle, fontSize: "10px" }}
                                    title={`About ${headerKindLabel}`}
                                    onActivate={promptDescription}
                                />
                            ) : null}
                            <NodeDeleteTool
                                style={{ ...headerIconStyle, fontSize: "10px" }}
                                onDelete={onDelete}
                            />
                        </div>
                    ) : null}
                </div>
            ) : null}

            {/* No maximize button: noContent nodes have no body to expand
                to. */}

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

/** A canvas node's soft shadow: the one a raised Curio card carries. */
const NODE_CARD_SHADOW = "var(--curio-shadow-browse-card-raised)";

/** The node container's border and surface, resolved in one place.
 *
 * Longhands only, never the `border` shorthand. The two used to be layered: this
 * function supplied `borderLeft` and the inline style added `border` when
 * dashboard mode was on, so toggling it changed which of the two was present
 * between renders and React warned "Removing border borderLeft". The suggestion
 * state added `borderWidth`/`borderStyle`/`borderColor` on top, colliding with
 * the same shorthand. Deciding the whole border here removes the layering
 * instead of reordering it.
 */
export const getNodeContainerStyles = (
    nodeType: string,
    state: {
        dashboardOn?: boolean;
        suggested?: boolean;
        acceptable?: boolean;
        /** The resolved descriptor's category, the one the title-bar pill shows. */
        category?: NodeCategory | null;
        /** The node is a notebook cell. */
        notebookCell?: boolean;
        /** The node is selected, which a canvas node and a notebook cell show with a ring. */
        selected?: boolean;
    } = {},
): CSS.Properties => {
    // Node border colour = node category, the same one the pill in the node's
    // own title bar shows. Keyed off the type alone, every package node was
    // grey beside a coloured pill (#524). The type map is for a node with no
    // resolved descriptor. `nodeType` arrives versioned for palette-dragged
    // nodes (`curio.builtin/data-pool@1`) but the map is keyed unversioned, so
    // an unnormalized lookup silently falls back to grey (#159).
    const accent = state.category
        ? categoryFg(NODE_CATEGORY_KEY[state.category] ?? "package")
        : colorForNodeType(unversionedNodeType(nodeType));
    const base: CSS.Properties = {
        position: "relative",
        backgroundColor: "#ffffff",
        borderRadius: "10px",
        padding: "5px",
        boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
    };

    if (state.dashboardOn) {
        // A dashboard tile is a card on a page, so it drops the canvas's accent
        // stripe for the same hairline border, radius and resting shadow every
        // other Curio card carries. The old 2px black square read as a node
        // lifted off the canvas rather than as published content.
        return {
            ...base,
            borderStyle: "solid",
            borderColor: "var(--curio-border)",
            borderWidth: "1px",
            borderRadius: "var(--curio-radius-lg)",
            boxShadow: "var(--curio-shadow-browse-card)",
            padding: "10px",
            resize: "none",
        };
    }

    // A selected node is ringed in its kind's color.
    const ring = state.selected ? `0 0 0 2px ${accent}` : null;

    if (state.notebookCell) {
        // A notebook cell sits on a white page with no outline or shadow, as a
        // Jupyter cell does: only the kind's stripe on the left. The other
        // sides keep a transparent hairline, so `.resizable`'s own border
        // never shows.
        return {
            ...base,
            borderRadius: "8px",
            boxShadow: ring ?? "none",
            borderTopStyle: "solid",
            borderRightStyle: "solid",
            borderBottomStyle: "solid",
            borderLeftStyle: "solid",
            borderTopWidth: "1px",
            borderRightWidth: "1px",
            borderBottomWidth: "1px",
            borderLeftWidth: "4px",
            borderTopColor: "transparent",
            borderRightColor: "transparent",
            borderBottomColor: "transparent",
            borderLeftColor: accent,
        };
    }

    // On the canvas the cell's card stands off the dotted background: a light
    // hairline and a soft shadow, with the kind's stripe on the left. A
    // suggestion keeps its dashed border.
    const suggested = state.suggested === true;
    const sideStyle = suggested ? "dashed" : "solid";
    const sideWidth = suggested ? "2px" : "1px";
    const sideColor = state.acceptable ? "#1d3853" : suggested ? undefined : "var(--curio-border)";
    return {
        ...base,
        borderRadius: "8px",
        boxShadow: ring ? `${ring}, ${NODE_CARD_SHADOW}` : NODE_CARD_SHADOW,
        borderTopStyle: sideStyle,
        borderRightStyle: sideStyle,
        borderBottomStyle: sideStyle,
        borderLeftStyle: "solid",
        borderTopWidth: sideWidth,
        borderRightWidth: sideWidth,
        borderBottomWidth: sideWidth,
        borderLeftWidth: "4px",
        borderTopColor: sideColor,
        borderRightColor: sideColor,
        borderBottomColor: sideColor,
        borderLeftColor: state.acceptable ? "#1d3853" : accent,
    };
};

const nodeContentStyle: CSS.Properties = {
    backgroundColor: "white",
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
