import React, { ReactNode, useState, useEffect, useMemo, useRef } from "react";
import CSS from "csstype";

import { useFlowContext } from "../providers/FlowProvider";
import { useNotebookViewContext } from "../providers/flow/notebookViewContext";
import { NodeRemoveChange, useReactFlow, useStore } from "reactflow";

import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faCircle,
    faCircleDot,
} from "@fortawesome/free-solid-svg-icons";
import { useToastContext } from "../providers/ToastProvider";
import {
    useDatasetDetails,
    viewDatasetDetailsToast,
} from "./datasets/catalog/datasetDetailsContext";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import { colorForCategory } from "../constants/nodeCategoryPalette";
import type { CanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { readCanvasTemplateConfig } from "../utils/canvasTemplateConfig";
import { HeaderIconButton } from "./HeaderIconButton";
import { useTooltipContent } from "./tooltip/useTooltipContent";
import {
    EditableNodeHeaderLabel,
    NodeSaveAsModal,
    NodeTemplateConfigModal,
    PackageMetaHeader,
} from "./packages/editing";
import {
    faCopy,
    faFloppyDisk,
    faMinus,
    faCircleInfo,
    faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";
import {
    DEFAULT_NODE_HEIGHT,
    DEFAULT_NODE_WIDTH,
    MIN_NODE_HEIGHT,
    MIN_NODE_WIDTH,
    MINIMIZED_NODE_HEIGHT,
    MINIMIZED_NODE_WIDTH,
    SupportedType,
} from "../constants";
import { clampNodeBox } from "../utils/nodeBoxSize";
import { getNodeDescriptor, modelTypeOfPackage, tryGetNodeDescriptor } from "../registry";
import { NodeCategory, NodeTemplateId } from "../registry/types";
import {
    applyDatasetToNodeData,
    applyDatasetToWidget,
    canApplyDatasetToNode,
    hasDatasetDrag,
    isWidgetLoaderCode,
    readDatasetDragPayload,
    widgetLoaderCode,
    type DatasetDragPayload,
} from "../services/datasetCatalog";
import { datasetWidgetBindings, datasetWidgetReadBy } from "../utils/widgets/datasetWidgets";
import { DatasetWidgetContext, type DatasetWidgetNode } from "./editing/widgets/datasetWidgetContext";
import { hasFileDrag, useDataFileImport } from "./datasets/useDataFileImport";
import { useAskForPackage, useAskTheOwner } from "./collab/useAskTheOwner";
import { packageStarterCode } from "../adapters/node/packageNodeBehavior";
import {
    applyModelToNodeData,
    canApplyModelToNode,
    hasModelDrag,
    modelDropRequest,
    modelSwapRefusal,
    nodeModelType,
    readModelDragPayload,
} from "../services/packages/modelApplication";
import "./styles.css";
import { useStarterContext } from "../providers/StarterProvider";
import { useCode } from "../hook/useCode";
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
    sendCodeToWidgets,
    output,
    nodeWidth,
    nodeHeight,
    cellBox,
    noContent,
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
    styles?: CSS.Properties;
    handleType?: string;
    disablePlay?: boolean;
    isLoading?: boolean;
}) => {
    const { showToast } = useToastContext();
    const { openDatasetDetails } = useDatasetDetails();
    const {
        applyRemoveChanges,
        setPinForDashboard,
        dashboardPins,
        allMinimized,
        setExpandStatus,
        updateDataNode,
        updateDefaultCode,
        acceptSuggestion,
        nodeExecStatus,
        playNodesUpTo,
        dashboardOn,
        dashboardLocked,
        markDirty,
        markNodeStale,
        requestAutoRun,
        defaultSaveOutputDataset,
        recordOutputsSoon,
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
    const { getNodes } = useReactFlow();
    // The starters feed tells a dataset drop whether the code is still its
    // template's starter. Nothing reads useCode; it is called so the node
    // keeps the hooks and the renders it had when it read it.
    const { getStarters } = useStarterContext();
    useCode();
    const [saveAsOpen, setSaveAsOpen] = useState(false);
    const [configOpen, setConfigOpen] = useState(false);
    const [pinnedToDashboard, setPinnedToDashboard] = useState<boolean>(!!dashboardPins[nodeId]);
    const [, setExpectedInputType] = useState(data.in);
    const [, setExpectedOutputType] = useState(data.out);
    // A node's warnings: the count names the icon, and the list is its tooltip.
    const warnings: string[] = Array.isArray(data.warnings) ? data.warnings : [];
    const warningsCount = `${warnings.length} warning${warnings.length === 1 ? "" : "s"}`;
    const warningsTooltip = useTooltipContent(
        warnings.length > 0 ? (
            <>
                <div className="curio-tooltip-muted">{warningsCount}</div>
                <ul style={{ margin: "4px 0 0", paddingLeft: "16px" }}>
                    {warnings.map((warning, index) => (
                        <li key={nodeId + "_warning_" + index}>{warning}</li>
                    ))}
                </ul>
            </>
        ) : null,
    );
    // Folded to its chip: the header's Minimize, or View > Minimize Nodes. The
    // fold is kept in the node's data, so a save writes it and a load brings it
    // back. Only the canvas folds a node; a dashboard tile shows it whole.
    // Icon-only nodes (manifest `containerStyle.noContent: true`) are always
    // minimized: they have no body to expand and the 50×180 footprint is their
    // default render. (Spatial Join left this set in #262, when it gained a body
    // with the polygon-property control.)
    const minimized = !!noContent || (data.minimized === true && !dashboardOn);
    // A node with content starts at the size the mount clamp below gives it, so
    // its first render is already its final size: the canvas measures that
    // render for its load fit (#683). An icon-only node keeps its own footprint,
    // and a minimized node starts as its chip.
    const [currentNodeWidth, setCurrentNodeWidth] = useState<number | undefined>(
        () => (noContent ? nodeWidth : minimized ? MINIMIZED_NODE_WIDTH : clampNodeBox(nodeWidth, nodeHeight).width)
    );
    const [currentNodeHeight, setCurrentNodeHeight] = useState<number | undefined>(
        () => (noContent ? nodeHeight : minimized ? MINIMIZED_NODE_HEIGHT : clampNodeBox(nodeWidth, nodeHeight).height)
    );
    /** Fold the node to its chip, or open it, in its data, where a save reads it. */
    const setMinimized = (next: boolean) => {
        if (noContent) return;
        // The live data, not the captured `data`, as keepBoxSize reads it.
        const liveData = getNodes().find((n) => n.id === nodeId)?.data ?? data;
        if ((liveData.minimized === true) === next) return;
        updateDataNode(nodeId, { ...liveData, minimized: next || undefined });
        // A read-only canvas has nothing to save.
        if (!sizeLocked) markDirty();
    };
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

    // View > Minimize Nodes and Expand Nodes fold or open every node. Only a
    // press does: a node that mounts, as on a load, keeps the fold it was saved
    // with.
    const allMinimizedSeen = useRef(allMinimized);
    useEffect(() => {
        if (allMinimizedSeen.current === allMinimized) return;
        allMinimizedSeen.current = allMinimized;
        setMinimized(allMinimized > 0);
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
        // A minimized node keeps its chip; opening it sizes it.
        if (noContent || minimized) return;

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

    useEffect(() => {
        setPinnedToDashboard(!!dashboardPins[nodeId]);
    }, [dashboardPins[nodeId]]);

    const updatePin = (nodeId: string, value: boolean) => {
        setPinnedToDashboard(!value);
        setPinForDashboard(nodeId, !value);
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
            // The output the node holds goes to the Data Catalog once its Save
            // is on, and its recorded output goes once it is off.
            recordOutputsSoon?.();
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

    // Whether a file or a dataset this node takes is dragged over it, which
    // its dataset widget shows.
    const [dropping, setDropping] = useState(false);
    const importDataFile = useDataFileImport();
    const askTheOwner = useAskTheOwner();
    const askForPackage = useAskForPackage();

    // A dataset reaching this node, dropped as a Data Catalog card or as a
    // file it has just imported: it sets the dataset widget the node's code
    // reads, or, on a node with none, its loader goes into the code.
    const takeDatasetRef = useRef<(dataset: DatasetDragPayload) => void>(() => {});
    takeDatasetRef.current = (dataset: DatasetDragPayload) => {
        // The node as it is now: an import may have taken a while.
        const current = getNodes().find((node) => node.id === nodeId)?.data ?? data;
        const live = code ?? current.code ?? current.defaultCode;
        const widget = datasetWidgetReadBy(current.widgets, live);
        if (widget) {
            const next = applyDatasetToWidget(current, widget.name, dataset);
            // While its code is one a drop wrote from the template's starter,
            // it becomes the one for this dataset: what an ONNX model or a
            // NetCDF file loads cannot leave the node, so its loader keeps the
            // value in the code, and a GeoTIFF's names its bounds.
            const starter = packageStarterCode(tryGetNodeDescriptor(current.nodeType), getStarters);
            const written = starter !== undefined && isWidgetLoaderCode(live, widget.name, starter)
                ? widgetLoaderCode(dataset, widget.name, starter)
                : undefined;
            const rewrite = written !== undefined && written !== live;
            updateDataNode(nodeId, rewrite ? { ...next, code: written, defaultCode: written } : next);
            // The editor takes the new code as content that arrived whole and
            // primes the widgets with it (CodeEditor). Sent as a run's code
            // here, it was resolved before the node held the dataset, and an
            // empty Data failed the node.
            if (rewrite) updateDefaultCode(nodeId, written);
            // As a value set in the Widgets tab: out of date, and run when
            // automatic runs are on.
            markNodeStale?.(nodeId);
            markDirty();
            requestAutoRun?.([nodeId]);
        } else {
            const applied = applyDatasetToNodeData(current, live, dataset);
            updateDataNode(nodeId, applied.data);
            updateDefaultCode(nodeId, applied.code);
            sendCodeToWidgets?.(applied.code);
            markDirty();
        }
        showToast(
            `Applied ${dataset.title} to this node.`,
            "success",
            viewDatasetDetailsToast(openDatasetDetails, dataset.datasetId),
        );
    };
    // Files from the computer, dropped on the node or chosen in its dataset
    // widget: imported and added to the dataflow, then taken as a card is.
    const takeFilesRef = useRef<(files: File[]) => void>(() => {});
    takeFilesRef.current = (files: File[]) => {
        void importDataFile(files).then((dataset) => {
            if (dataset) takeDatasetRef.current(dataset);
        });
    };

    // Keep a ref to the handler so the capture listener always uses the latest
    // closure values (data, code, etc.) without needing to re-register.
    const datasetDropHandlerRef = useRef<(e: DragEvent) => void>(() => {});
    datasetDropHandlerRef.current = (e: DragEvent) => {
        if (!e.dataTransfer) return;
        if (hasFileDrag(e.dataTransfer)) {
            // A node that takes no dataset leaves the file to the canvas.
            if (!canTakeFilesRef.current) return;
            e.preventDefault();
            e.stopPropagation();
            takeFilesRef.current(Array.from(e.dataTransfer.files || []));
            return;
        }
        const dataset = readDatasetDragPayload(e.dataTransfer);
        if (!dataset) return;
        if (!canApplyDatasetToNode(data)) {
            // Let the event bubble to the canvas drop target.
            return;
        }
        e.preventDefault();
        e.stopPropagation();
        takeDatasetRef.current(dataset);
        // On the owner's dataflow, an invited editor's card of his own Data
        // Catalog asks her to add it, as his drop on the canvas does.
        if (askTheOwner) void askTheOwner(dataset, { nodeId });
    };
    const canApplyRef = useRef(false);
    canApplyRef.current = canApplyDatasetToNode(data);
    // A read-only canvas adds nothing to the dataflow.
    const canTakeFilesRef = useRef(false);
    canTakeFilesRef.current = canApplyRef.current && !sizeLocked && !dashboardOn;

    // --- Model drag-and-drop, through the same capture-phase listeners ---
    // A model goes only onto a node whose code calls `curio_load_model("...")`,
    // and only in place of a model of its own type, both types known. Every
    // other node still takes the drop, so it can say why nothing changed rather
    // than letting the drop fall through to the canvas, which would make the
    // model's own node.
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
        // The type of model the node runs: the model its code names, else the
        // model package the node comes from. Refused when it or the dropped
        // model's type is unknown, or the two differ.
        const ownType = tryGetNodeDescriptor(data.nodeType as NodeTemplateId)?.package?.modelType;
        const refused = modelSwapRefusal(nodeModelType(live, modelTypeOfPackage, ownType), model);
        if (refused) {
            showToast(refused, "warning");
            return;
        }
        const applied = applyModelToNodeData(live, model);
        updateDataNode(nodeId, applied);
        updateDefaultCode(nodeId, applied.code);
        sendCodeToWidgets?.(applied.code);
        markDirty();
        showToast(`Model set to ${model.name}`, "success");
        // On the owner's dataflow, an invited editor's model asks her to add
        // it, unless her dataflow has it: the node waits for her review.
        const asked = askForPackage ? modelDropRequest(e.dataTransfer) : null;
        if (askForPackage && asked) void askForPackage(asked, { nodeId });
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
            if (hasFileDrag(e.dataTransfer)) {
                if (!canTakeFilesRef.current) return;
            } else {
                if (!hasDatasetDrag(e.dataTransfer)) return;
                if (!canApplyRef.current) return;
            }
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = "copy";
            setDropping(true);
        };

        // Leaving the node, not moving between the elements inside it.
        const handleDragLeave = (e: DragEvent) => {
            const next = e.relatedTarget;
            if (next instanceof globalThis.Node && el.contains(next)) return;
            setDropping(false);
        };

        const handleDrop = (e: DragEvent) => {
            setDropping(false);
            if (e.dataTransfer && hasModelDrag(e.dataTransfer)) {
                modelDropHandlerRef.current(e);
                return;
            }
            datasetDropHandlerRef.current(e);
        };

        el.addEventListener("dragover", handleDragOver, true);
        el.addEventListener("dragleave", handleDragLeave, true);
        el.addEventListener("drop", handleDrop, true);
        return () => {
            el.removeEventListener("dragover", handleDragOver, true);
            el.removeEventListener("dragleave", handleDragLeave, true);
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
        if (hasFileDrag(event.dataTransfer)) {
            if (!canTakeFilesRef.current) return;
        } else {
            if (!hasDatasetDrag(event.dataTransfer)) return;
            if (!canApplyDatasetToNode(data)) return;
        }
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "copy";
    };

    const onDatasetDrop = (event: React.DragEvent<HTMLDivElement>) => {
        // Primary handling is done by the capture-phase native listener above.
        // This synthetic handler is kept only to prevent browser default actions
        // (e.g. Monaco opening dropped file as text) for dataset, model and file
        // drags that the native listener already handled. A file the node does
        // not take goes on to the canvas.
        if (hasFileDrag(event.dataTransfer)) {
            if (!canTakeFilesRef.current) return;
        } else if (!hasDatasetDrag(event.dataTransfer) && !hasModelDrag(event.dataTransfer)) {
            return;
        }
        event.preventDefault();
        event.stopPropagation();
    };

    // What the node's dataset widgets read of it (editing/widgets/
    // datasetWidgetContext): the title and format of the dataset each holds,
    // the files Choose file picks, and whether a drop is over the node.
    const datasetWidgetsKey = JSON.stringify(data.datasetWidgets ?? null);
    const canTakeFiles = canTakeFilesRef.current;
    const datasetWidgetNode: DatasetWidgetNode = useMemo(() => {
        const bound = Object.values(datasetWidgetBindings(data));
        return {
            describe: (id: string) => {
                const binding = bound.find((one) => one.id === id);
                if (binding) return { title: binding.title, format: binding.format };
                const listed = datasetsById?.get(id);
                return listed ? { title: listed.title, format: listed.format } : undefined;
            },
            takeFiles: canTakeFiles ? (files: File[]) => takeFilesRef.current(files) : undefined,
            dropping,
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [datasetWidgetsKey, datasetsById, canTakeFiles, dropping]);

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
                    {/* The list shows in the Curio tooltip, which the card
                        does not clip and the canvas's zoom does not scale. */}
                    <span
                        {...warningsTooltip}
                        role="img"
                        aria-label={warningsCount}
                        style={{ display: "inline-flex" }}
                    >
                        <FontAwesomeIcon
                            style={{ fontSize: "24px", color: "#e8c548" }}
                            icon={faTriangleExclamation}
                        />
                    </span>
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
                        data-tooltip={headerKindLabel}
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
                                nodeId={nodeId}
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
                            and, on the canvas, Minimize and Delete node)
                            right after it. */}
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
                            {/* Delete node comes last. It shows only where the
                                viewer deletes nodes, so not in a notebook cell
                                or on a read-only canvas. */}
                            <NodeDeleteTool
                                style={{ ...headerIconStyle, ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {}) }}
                                onDelete={onDelete}
                            />
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
                        <DatasetWidgetContext.Provider value={datasetWidgetNode}>
                            {children}
                        </DatasetWidgetContext.Provider>
                    </NodeHeaderSlotContext.Provider>
                </div>

            </div>

            {shownMinimized ? (
                <div
                    className="curio-node-chip"
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
                            // A folded node shows its icon and its title from
                            // the left; an icon-only node, its icon centered.
                            padding: noContent ? "5px" : "0 12px 0 14px",
                            justifyContent: noContent ? "center" : "flex-start",
                            gap: "10px",
                            display: "flex",
                            alignItems: "center",
                            position: "relative",
                            boxShadow: NODE_CARD_SHADOW,
                            // Dark, as the open card is, so the highlighted
                            // icon and title read.
                            ...(data.keywordHighlighted ? {backgroundColor: "#1E1F23"} : {}),
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
                            fontSize: noContent ? "23px" : "18px",
                            flexShrink: 0,
                            ...(data.keywordHighlighted ? {color: "rgb(251, 252, 246)"} : {color: "#888787"})
                        }}
                    />
                    {/* The node's title, as its header shows it: one line,
                        cut with an ellipsis, the whole title on hover. A
                        click on it opens the node, as on the rest of the chip. */}
                    {!noContent ? (
                        <EditableNodeHeaderLabel
                            displayLabel={headerKindLabel}
                            editable={false}
                            showConfig={false}
                            executed={nodeExecStatus[nodeId] === "executed"}
                            keywordHighlighted={!!data.keywordHighlighted}
                            onLabelCommit={() => {}}
                            onConfigure={() => {}}
                        />
                    ) : null}
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
    _nodeType: string,
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
    // own title bar shows: the resolved descriptor's. Keyed off the type alone,
    // every package node was grey beside a coloured pill (#524).
    const accent = colorForCategory(state.category);
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
