import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useMemo,
    useRef,
    useEffect,
} from "react";
import {
    useNodesState,
    useEdgesState,
    useReactFlow,
} from "reactflow";
import { useConnect } from "./flow/useConnect";
import { useGraphEdits } from "./flow/useGraphEdits";
import { useDashboardPins, useDashboardPinSave } from "./flow/useDashboardPins";
import { usePlayAll } from "./flow/usePlayAll";
import type { PlayAllState } from "./flow/usePlayAll";
import { useApplyOutput } from "./flow/useApplyOutput";
import { useInteractions } from "./flow/useInteractions";
import { useCollaborationSync } from "./flow/useCollaborationSync";
import { useInstallSave } from "./flow/useInstallSave";
import { useNotebookView } from "./flow/useNotebookView";
import { NotebookViewContext } from "./flow/notebookViewContext";
import type { IOutput, IInteraction } from "./flow/flowTypes";
import type { FlowContextProps, NodeActionsContextProps } from "./flow/flowContextTypes";
import { DEFAULT_WORKFLOW_NAME } from "../constants";
import { TrillGenerator } from "../TrillGenerator";
import { isStandaloneDashboard } from "../standalone/dashboardPayload";
import { useWorkflowOperations } from "../hook/useWorkflowOperations";
import { useToastContext } from "./ToastProvider";
import { useCollab } from "./CollaborationProvider";
import { DEFAULT_SAVE_OUTPUT_DATASET } from "../utils/saveOutputDataset";
import { authApi } from "../utils/authApi";

export type { IOutput, IInteraction, IPropagation, NodeExecOutcome } from "./flow/flowTypes";
export type { NodeActionsContextProps } from "./flow/flowContextTypes";

export const NodeActionsContext = createContext<NodeActionsContextProps>({
    workflowNameRef: { current: "" },
    workflowName: "DefaultWorkflow",
    applyRemoveChanges: () => {},
    setPinForDashboard: () => {},
    allMinimized: 0,
    setAllMinimized: () => {},
    expandStatus: 'expanded',
    setExpandStatus: () => {},
    updateDataNode: () => {},
    updateDefaultCode: () => {},
    workflowGoal: "",
    acceptSuggestion: () => {},
    setWorkflowName: () => {},
});

export const useNodeActionsContext = () => useContext(NodeActionsContext);

export const FlowContext = createContext<FlowContextProps>({
    nodes: [],
    edges: [],
    outputs: [],
    setOutputs: () => { },
    setInteractions: () => { },
    interactionsCallback: () => { },
    applyNewPropagation: () => { },
    addNode: () => { },
    onNodesChange: () => { },
    onEdgesChange: () => { },
    onConnect: () => { },
    isValidConnection: () => true,
    onEdgesDelete: () => { },
    onNodesDelete: () => { },
    setPinForDashboard: () => { },
    dashboardOn: false,
    dashboardLocked: true,
    isDashboardSource: () => false,
    setDashboardLocked: () => { },
    applyNewOutput: () => { },
    hydrateRestoredOutputs: () => { },

    // NEW CODE
    dashboardPins: {},
    workflowNameRef: { current: "" },
    workflowDescriptionRef: { current: "" },
    workflowDescription: "",
    setWorkflowDescription: () => {},
    loading: false,
    suggestionsLeft: 0,
    workflowGoal: "",
    allMinimized: 0,
    expandStatus: 'expanded',
    setWorkflowGoal: () => {},

    applyRemoveChanges: () => { },
    applyReviewedRemovals: () => { },
    setWorkflowName: () => { },
    setAllMinimized: () => { },
    setExpandStatus: () => { },
    eraseWorkflowSuggestions: () => {},
    updateDataNode: () => {},
    flagBasedOnKeyword: () => {},
    updateSubtasks: () => {},
    updateKeywords: () => {},
    updateDefaultCode: () => {},
    applyNodeContent: () => {},
    updateWarnings: () => {},
    cleanCanvas: () => {},
    acceptSuggestion: () => {},
    loadParsedTrill: async () => { },
    packages: [],
    setPackages: () => {},
    addPackage: () => {},
    removePackage: () => {},
    dataflowDatasets: [],
    setDataflowDatasets: () => {},
    pendingInstalls: [],
    beginPendingInstall: () => {},
    endPendingInstall: () => {},
    failPendingInstall: () => {},

    // Project defaults
    projectId: null,
    projectName: "",
    projectDirty: false,
    projectSavedAt: null,
    nodeExecStatus: {},
    viewerMode: "owner",
    workflowCategories: {},
    serverCategories: {},
    renameDataflow: () => false,
    updateDataflowCategories: () => {},
    saveCurrentProject: async () => {},
    saveAsNewProject: async () => {},
    ensureProjectId: async () => null,
    persistDataflowForInstall: async () => ({ saved: false, failedNodeIds: [] }),
    loadProject: async () => {},
    loadSharedProject: async () => {},
    discardProject: () => {},
    markDirty: () => {},
    markNodeExecuted: () => {},
    markNodeStale: () => {},
    markNodeErrored: () => {},
    playAllNodes: () => {},
    playNodesUpTo: () => {},
    signalNodeExecDone: () => {},
    isRunActive: false,
    cancelRun: () => {},
    defaultSaveOutputDataset: false,
    setDefaultSaveOutputDataset: () => {},

    canvasView: "canvas",
    setCanvasView: () => {},
    notebookOn: false,
    notebookContentHeight: 0,
    setNotebookPane: () => {},
    registerNotebookScroller: () => {},
    revealNodes: () => false,
});

/**
 * ``dashboardOn`` is a PROP, not state: it says which route mounted this tree.
 * It used to be a mode the canvas toggled into, which is why the nodes had two
 * sets of coordinates and no URL to share. The dashboard is its own route now,
 * so the flag is decided once, above the provider, and everything that reads it
 * means "I am rendering a dashboard tile" rather than "the canvas is pretending".
 */
const FlowProvider = ({
    children,
    dashboardOn = false,
}: { children: ReactNode; dashboardOn?: boolean }) => {
    const { showToast } = useToastContext();
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges, onEdgesChange] = useEdgesState([]);
    const [outputs, _setOutputs] = useState<IOutput[]>([]);
    const outputsRef = useRef<IOutput[]>([]);
    const playAllStateRef = useRef<PlayAllState | null>(null);
    // Mirrors "playAllStateRef.current != null" as React state. The ref is what
    // the runner reads; this is what the UI reads. The guard used to live only
    // in the ref, so every play control stayed enabled and a click during (or
    // after a wedged) run silently did nothing (#271).
    const [isRunActive, setIsRunActive] = useState(false);
    // The input each node had when it last emitted through applyNewOutput. Merge
    // Flow and the Data Pool never record a success on node.data.output, so
    // this is how playNodesUpTo tells they are current (#479): their input is
    // still the object they emitted for. Every delivery builds a new one.
    const emittedForInputRef = useRef(new Map<string, unknown>());
    const markNodeExecutedRef = useRef<(nodeId: string) => void>(() => {});
    const markNodeStaleRef = useRef<(nodeId: string) => void>(() => {});
    const markNodeErroredRef = useRef<(nodeId: string) => void>(() => {});
    const markDirtyRef = useRef<() => void>(() => {});
    // Saves the project right after a pin changes (assigned below, next to
    // markDirtyRef). Pinning is the one edit whose entire purpose is to change
    // a DIFFERENT page, and that page renders what is on disk, so leaving it to
    // the 30 second auto-save meant "pin a tile, open the dashboard" showed
    // "nothing is pinned yet" for up to half a minute. That reads as a broken
    // feature rather than as a save that has not happened yet.
    const savePinChangeRef = useRef<() => void>(() => {});
    // Set after workflowOps exists; called from applyNewOutput (a genuine runtime
    // output, NOT project load — load writes outputs via setOutputs directly) to
    // auto-install + surface a produced dataset without a manual disk-icon save.
    const scheduleInstallSyncRef = useRef<(nodeId: string) => void>(() => {});
    // Forces the debounced install-save to run NOW (assigned below, next to
    // scheduleInstallSyncRef). The Play-All runner calls it on completion and the
    // provider calls it on unmount so the final burst is never lost to the timer.
    const flushInstallSyncRef = useRef<() => void>(() => {});
    const [defaultSaveOutputDataset, setDefaultSaveOutputDataset] = useState(
        DEFAULT_SAVE_OUTPUT_DATASET,
    );

    // The backend (CURIO_DEFAULT_SAVE_NODE_OUTPUT) is the authoritative source
    // for the workflow-wide default. Read it once from /api/config/public so
    // the per-node "Save output dataset" default (and the save-time gate in
    // buildOutputRefs) matches the deployment's runtime setting rather than the
    // build-time env baked into the bundle. Mirrors CollaborationProvider.
    useEffect(() => {
        // Nothing on a standalone dashboard can save an output: there is no
        // session to save under and no Play to produce one. Asking a server
        // that may not be reachable what the default should be would be a
        // request made purely to answer a question nobody asks.
        if (isStandaloneDashboard()) return;
        let cancelled = false;
        authApi
            .getPublicConfig()
            .then((cfg) => {
                if (!cancelled && typeof cfg?.default_save_node_output === "boolean") {
                    setDefaultSaveOutputDataset(cfg.default_save_node_output);
                }
            })
            .catch(() => {
                /* keep build-time DEFAULT_SAVE_OUTPUT_DATASET fallback */
            });
        return () => {
            cancelled = true;
        };
    }, []);

    // Collaboration broadcasters. The provider may be a no-op (when
    // --collab is off or no project is loaded), in which case every
    // broadcast call is a noop too. We hold the latest value in a ref
    // so the mutation callbacks below don't have to list `collab` in
    // their dependency arrays and risk re-creating themselves on every
    // presence change.
    const collab = useCollab();
    const collabRef = useRef(collab);
    collabRef.current = collab;

    const setOutputs = useCallback((fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => {
        _setOutputs((prev) => {
            const next = typeof fnOrValue === "function" ? fnOrValue(prev) : fnOrValue;
            outputsRef.current = next;
            return next;
        });
    }, []);
    const [interactions, setInteractions] = useState<IInteraction[]>([]);

    const [dashboardPins, setDashboardPins] = useState<any>({}); // {[nodeId] -> boolean}
    // Whether the dashboard's tiles can be moved and resized. Session-only and
    // owner-only: the page starts locked and unlocks for an explicit edit.
    const [dashboardLocked, setDashboardLocked] = useState<boolean>(true);

    const reactFlow = useReactFlow();
    const [loading, setLoading] = useState<boolean>(false);

    const notebook = useNotebookView({ nodes, edges, setNodes, reactFlow, dashboardOn });

    const [workflowName, _setWorkflowName] = useState<string>(DEFAULT_WORKFLOW_NAME);
    const workflowNameRef = React.useRef(workflowName);
    const setWorkflowName = useCallback((data: any) => {
        workflowNameRef.current = data;
        _setWorkflowName(data);
    }, []);

    const [workflowDescription, _setWorkflowDescription] = useState<string>("");
    const workflowDescriptionRef = React.useRef(workflowDescription);
    const setWorkflowDescription = useCallback((data: string) => {
        workflowDescriptionRef.current = data || "";
        _setWorkflowDescription(data || "");
    }, []);

    const initializeProvenance = () => {
        setLoading(true);
        try {
            const empty_trill = TrillGenerator.generateTrill(
                [],
                [],
                workflowNameRef.current,
            );
            TrillGenerator.intializeProvenance(empty_trill);
        } catch (e) {
            console.error("initializeProvenance failed:", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        initializeProvenance();
    }, []);

    const { isDashboardSource, setPinForDashboard } = useDashboardPins({
        reactFlow, setDashboardPins, setNodes, markDirtyRef, savePinChangeRef, showToast,
    });

    const {
        applyNodeContent, addNode, propagateDownstreamInputs, applyOutput, onEdgesDelete, onNodesDelete,
    } = useGraphEdits({
        setNodes, setEdges, reactFlow, workflowNameRef, collabRef, outputsRef, markNodeStaleRef, setOutputs,
    });

    const { onConnect, isValidConnection } = useConnect({
        markDirtyRef, reactFlow, showToast, markNodeStaleRef, applyOutput, setEdges,
        workflowNameRef, collabRef, outputsRef, propagateDownstreamInputs,
    });

    const { cancelRun, signalNodeExecDone, playAllNodes, playNodesUpTo } = usePlayAll({
        playAllStateRef, setIsRunActive, flushInstallSyncRef, showToast, reactFlow,
        markNodeErroredRef, setNodes, emittedForInputRef,
    });

    const { applyNewOutput, hydrateRestoredOutputs } = useApplyOutput({
        propagateDownstreamInputs, emittedForInputRef, reactFlow, setOutputs,
        markNodeExecutedRef, scheduleInstallSyncRef, signalNodeExecDone,
    });

    const { applyNewPropagation, interactionsCallback } = useInteractions({
        interactions, setInteractions, nodes, edges, reactFlow, setNodes,
    });

    useCollaborationSync({
        collab, applyNewOutput, interactionsCallback, applyNewPropagation, setNodes, setEdges,
        takeCanvasPosition: notebook.takeCanvasPosition,
    });
    // NEW CODE

    // Workflow operations extracted into a dedicated hook
    // NOTE: markNodeExecutedRef/markNodeStaleRef are updated here so functions defined earlier
    // (applyNewOutput, onEdgesDelete, onConnect) can access them without stale closures.
    const workflowOps = useWorkflowOperations({
        nodes, edges,
        setNodes, setEdges,
        setOutputs, outputsRef, setInteractions,
        setDashboardPins,
        presentation: dashboardOn,
        setWorkflowName,
        workflowNameRef,
        setWorkflowDescription,
        workflowDescriptionRef,
        onEdgesDelete, onNodesDelete, onNodesChange,
        onConnect, addNode,
        defaultSaveOutputDataset,
    });

    markNodeExecutedRef.current = workflowOps.markNodeExecuted;
    markNodeStaleRef.current = workflowOps.markNodeStale;
    markNodeErroredRef.current = workflowOps.markNodeErrored ?? (() => {});
    markDirtyRef.current = workflowOps.markDirty;

    useDashboardPinSave({
        savePinChangeRef, dashboardOn, workflowOps, showToast,
    });

    useInstallSave({
        scheduleInstallSyncRef, dashboardOn, reactFlow, defaultSaveOutputDataset,
        isDashboardSource, workflowOps, flushInstallSyncRef,
    });

    const nodeActionsValue = useMemo<NodeActionsContextProps>(() => ({
        workflowNameRef,
        workflowName,
        applyRemoveChanges: workflowOps.applyRemoveChanges,
        setPinForDashboard,
        allMinimized: workflowOps.allMinimized,
        setAllMinimized: workflowOps.setAllMinimized,
        expandStatus: workflowOps.expandStatus,
        setExpandStatus: workflowOps.setExpandStatus,
        updateDataNode: workflowOps.updateDataNode,
        updateDefaultCode: workflowOps.updateDefaultCode,
        workflowGoal: workflowOps.workflowGoal,
        acceptSuggestion: workflowOps.acceptSuggestion,
        setWorkflowName,
    }), [
        workflowNameRef,
        workflowName,
        workflowOps.applyRemoveChanges,
        setPinForDashboard,
        workflowOps.allMinimized,
        workflowOps.setAllMinimized,
        workflowOps.expandStatus,
        workflowOps.setExpandStatus,
        workflowOps.updateDataNode,
        workflowOps.updateDefaultCode,
        workflowOps.workflowGoal,
        workflowOps.acceptSuggestion,
        setWorkflowName,
    ]);

    return (
        <NodeActionsContext.Provider value={nodeActionsValue}>
        <FlowContext.Provider
            value={{
                nodes,
                edges,
                outputs,
                setOutputs,
                setInteractions,
                interactionsCallback,
                applyNewPropagation,
                addNode,
                onNodesChange,
                onEdgesChange,
                onConnect,
                isValidConnection,
                onEdgesDelete,
                onNodesDelete,
                setPinForDashboard,
                isDashboardSource,
                applyNewOutput,
                hydrateRestoredOutputs,
                playAllNodes,
                playNodesUpTo,
                signalNodeExecDone,
                isRunActive,
                cancelRun,

                // NEW CODE
                dashboardPins,
                dashboardOn,
                dashboardLocked,
                setDashboardLocked,
                workflowNameRef,
                setWorkflowName,
                workflowDescriptionRef,
                workflowDescription,
                setWorkflowDescription,
                loading,

                ...workflowOps,
                // A project switch must not inherit a run in flight: the guard
                // is provider state, and the provider outlives the dataflow
                // when the user loads another one in place (#271).
                loadProject: async (id: string) => { cancelRun(); return workflowOps.loadProject(id); },
                loadSharedProject: async (id: string) => { cancelRun(); return workflowOps.loadSharedProject(id); },
                cleanCanvas: () => { cancelRun(); workflowOps.cleanCanvas(); },
                discardProject: () => { cancelRun(); workflowOps.discardProject(); },
                applyNodeContent,
                defaultSaveOutputDataset,
                setDefaultSaveOutputDataset,

                canvasView: notebook.canvasView,
                setCanvasView: notebook.setCanvasView,
                notebookOn: notebook.notebookOn,
                notebookContentHeight: notebook.notebookContentHeight,
                setNotebookPane: notebook.setNotebookPane,
                registerNotebookScroller: notebook.registerNotebookScroller,
                revealNodes: notebook.revealNodes,
            }}
        >
            <NotebookViewContext.Provider value={notebook.notebookViewValue}>
                {children}
            </NotebookViewContext.Provider>
        </FlowContext.Provider>
        </NodeActionsContext.Provider>
    );
};

export const useFlowContext = () => {
    const context = useContext(FlowContext);

    if (!context) {
        throw new Error("useFlowContext must be used within a FlowProvider");
    }

    return context;
};

export default FlowProvider;
