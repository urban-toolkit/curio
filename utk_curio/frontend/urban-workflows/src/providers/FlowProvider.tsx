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
    applyEdgeChanges,
    useNodesState,
    useEdgesState,
    useReactFlow,
    type EdgeChange,
    type NodeRemoveChange,
} from "reactflow";
import { useInRouterContext } from "react-router-dom";
import { useConnect } from "./flow/useConnect";
import { useGraphEdits, type AppliedCodeDoc } from "./flow/useGraphEdits";
import { useDashboardPins, useDashboardPinSave } from "./flow/useDashboardPins";
import { usePlayAll } from "./flow/usePlayAll";
import type { PlayAllState } from "./flow/usePlayAll";
import { useApplyOutput } from "./flow/useApplyOutput";
import { useInteractions } from "./flow/useInteractions";
import { useSelectionTags } from "./flow/useSelectionTags";
import { useDataflowDoc } from "./flow/useDataflowDoc";
import { useRemovalAsk } from "./flow/useRemovalAsk";
import { useInstallSave } from "./flow/useInstallSave";
import { useLeavePageGuard } from "./flow/useSaveState";
import { useServerRun } from "./flow/useServerRun";
import { useCategoriesRefresh } from "./flow/useCategoriesRefresh";
import { useStepOutcomes } from "./flow/useStepOutcomes";
import { useDashboardRun } from "./flow/useDashboardRun";
import { autoRunTargets, useAutoRun } from "./flow/useAutoRun";
import { CanvasViewAddress, useNotebookView } from "./flow/useNotebookView";
import { NotebookViewContext } from "./flow/notebookViewContext";
import type { IOutput, IInteraction } from "./flow/flowTypes";
import type { FlowContextProps, NodeActionsContextProps } from "./flow/flowContextTypes";
import type { Scenario } from "../utils/scenarios/scenarioModel";
import { DEFAULT_WORKFLOW_NAME } from "../constants";
import { TrillGenerator } from "../TrillGenerator";
import { isStandaloneDashboard } from "../standalone/dashboardPayload";
import { useWorkflowOperations, type DocBridgeForSaves } from "../hook/useWorkflowOperations";
import { useToastContext } from "./ToastProvider";
import { useCollab } from "./CollaborationProvider";
import { CONNECTION_DROPPED_EVENT, useDocBinding } from "./collab/docContext";
import type { DataflowDocProvider } from "./collab/docProvider";
import { canvasRole } from "./collab/participants";
import { numberedName } from "./collab/presence";
import { useProvenanceContext } from "./ProvenanceProvider";
import { useUserContext } from "./UserProvider";
import { isHostedGuest } from "../components/apiSettings/useHostedGuest";
import { DEFAULT_SAVE_OUTPUT_DATASET } from "../utils/saveOutputDataset";
import { writeNodeSettings, type NodeSettings } from "../utils/nodeSettingsWriters";
import { authApi } from "../utils/authApi";
import { refreshAgentsWhenKept } from "./flow/agentDockAfterRemovals";

/** How long leaving a dataflow bound to its doc waits for the server to keep
 *  this tab's last change before it asks whether to leave without it. */
const LEAVE_WAIT_MS = 3000;

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
    applyNodeSettings: () => {},
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
    boundDoc: null,
    whenChangesKept: async () => true,
    nodeExecStatus: {},
    viewerMode: "owner",
    workflowCategories: {},
    serverCategories: {},
    scenarios: [],
    autoRun: false,
    renameDataflow: () => false,
    updateDataflowCategories: () => {},
    setScenarios: () => {},
    setAutoRun: () => {},
    saveDataflow: async () => ({ id: "", created: false }),
    saveDashboardLayout: async () => {},
    saveAsNewProject: async () => {},
    ensureProjectId: async () => null,
    recordOutputs: async () => ({ saved: false, failedNodeIds: [] }),
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
    serverRunActive: false,
    dashboardStopped: null,
    cancelRun: () => {},
    attachLatestRun: async () => {},
    autoRunAvailable: false,
    requestAutoRun: () => {},
    runDownstream: () => {},
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
    // A hosted guest cannot save the dataflow (isHostedGuest, the rule the
    // saves themselves apply as blockGuestSaves). Its runs stay in the browser,
    // and the saves Curio makes on its own, after an output lands or a pin
    // changes, are skipped without a word: only a save the guest asks for
    // (File > Save, Save a copy) says why it cannot.
    const { user, enableUserAuth, skipProjectPage } = useUserContext();
    const hostedGuest = isHostedGuest(user, enableUserAuth);
    const [nodes, setNodes, onNodesChange] = useNodesState([]);
    const [edges, setEdges] = useEdgesState([]);
    // An edge added with an id the canvas holds is not added again: the doc
    // and an agent's apply can both bring one before the canvas renders.
    const onEdgesChange = useCallback((changes: EdgeChange[]) => {
        setEdges((eds) => applyEdgeChanges(
            changes.filter((change) => change.type !== "add" || !eds.some((edge) => edge.id === change.item.id)),
            eds,
        ));
    }, [setEdges]);
    const [outputs, _setOutputs] = useState<IOutput[]>([]);
    const outputsRef = useRef<IOutput[]>([]);
    const playAllStateRef = useRef<PlayAllState | null>(null);
    // Mirrors "playAllStateRef.current != null" as React state. The ref is what
    // the runner reads; this is what the UI reads. The guard used to live only
    // in the ref, so every play control stayed enabled and a click during (or
    // after a wedged) run silently did nothing (#271).
    const [isRunActive, setIsRunActive] = useState(false);
    // The input each node had when it last emitted through applyNewOutput. The
    // Data Pool never records a success on node.data.output, so this is how
    // playNodesUpTo tells it is current (#479): its input is
    // still the object it emitted for. Every delivery builds a new one.
    const emittedForInputRef = useRef(new Map<string, unknown>());
    const markNodeExecutedRef = useRef<(nodeId: string) => void>(() => {});
    const markNodeStaleRef = useRef<(nodeId: string) => void>(() => {});
    const markNodeErroredRef = useRef<(nodeId: string) => void>(() => {});
    const markDirtyRef = useRef<() => void>(() => {});
    // Records, right after a pin or a scenario changes (assigned below, next to
    // markDirtyRef), the outputs a pinned tile or a scenario reads: the
    // dashboard draws its tiles from the dataflow's saved outputs, and the
    // doc keeps the pin itself.
    const savePinChangeRef = useRef<() => void>(() => {});
    // Set after workflowOps exists; called from applyNewOutput (a genuine runtime
    // output, NOT project load — load writes outputs via setOutputs directly) to
    // auto-install + surface a produced dataset without a manual disk-icon save.
    const scheduleInstallSyncRef = useRef<(nodeId: string) => void>(() => {});
    // Forces the debounced outputs record to run NOW (assigned below, next to
    // scheduleInstallSyncRef), resolving once it is done. The Play-All runner
    // calls it on completion, File > Save before its version, and the provider
    // on unmount, so the final burst is never lost to the timer.
    const flushInstallSyncRef = useRef<() => Promise<void> | void>(() => {});
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

    // The room, and the dataflow's doc this canvas binds to (useDataflowDoc).
    // The dashboard binds to none: a viewer's tried values never reach it.
    const collab = useCollab();
    const docBinding = useDocBinding();
    const docBridgeRef = useRef<DocBridgeForSaves | null>(null);

    // The ref is written now, not when React renders: a save reads the outputs
    // from it, and the save a run's end flushes runs in the tick the run's last
    // output lands. Written in the state updater, the ref did not hold that
    // output yet whenever another update to this provider was pending, so the
    // save left it out and took it out of the dataflow's saved outputs.
    const setOutputs = useCallback((fnOrValue: ((prev: IOutput[]) => IOutput[]) | IOutput[]) => {
        const next = typeof fnOrValue === "function" ? fnOrValue(outputsRef.current) : fnOrValue;
        outputsRef.current = next;
        _setOutputs(next);
    }, []);
    const [interactions, setInteractions] = useState<IInteraction[]>([]);

    const [dashboardPins, setDashboardPins] = useState<any>({}); // {[nodeId] -> boolean}
    // Whether the dashboard's tiles can be moved and resized. Session-only and
    // owner-only: the page starts locked and unlocks for an explicit edit.
    const [dashboardLocked, setDashboardLocked] = useState<boolean>(true);

    const reactFlow = useReactFlow();
    const [loading, setLoading] = useState<boolean>(false);

    const notebook = useNotebookView({ nodes, edges, setNodes, reactFlow, dashboardOn });
    // The app always renders the dataflow inside its router, which keeps the
    // view in the address; some tests render this provider without one.
    const inRouter = useInRouterContext();

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

    // The scenarios as they are now, for the save rule a run reads (#662).
    // Assigned once workflowOps exists, as markDirtyRef is.
    const scenariosNowRef = useRef<() => readonly Scenario[]>(() => []);
    const { isDashboardSource, setPinForDashboard } = useDashboardPins({
        reactFlow, setDashboardPins, setNodes, markDirtyRef, savePinChangeRef, showToast, scenariosNowRef,
        hostedGuest,
    });

    // The nodes' Provenance drawers: a run files an entry, and so does an
    // agent's applied change to a node's code.
    const { nodeExecProv, agentEditProv } = useProvenanceContext();

    // The doc an agent's applied code is the server's in, once the canvas binds.
    const codeDocRef = useRef<AppliedCodeDoc | null>(null);
    const {
        applyNodeContent, addNode, propagateDownstreamInputs, applyOutput,
        onEdgesDelete: dropEdges, onNodesDelete: dropNodes,
    } = useGraphEdits({
        setNodes, setEdges, reactFlow, workflowNameRef, outputsRef, markNodeStaleRef, setOutputs,
        agentEditProv, markDirtyRef, codeDocRef,
    });
    // A node or a connection removed takes the agents attached to it along,
    // once the server has the removal (agentDockAfterRemovals.ts).
    const onNodesDelete = useCallback((...removed: Parameters<typeof dropNodes>) => {
        dropNodes(...removed);
        void refreshAgentsWhenKept(docBridgeRef.current?.whenKept);
    }, [dropNodes]);
    const onEdgesDelete = useCallback((...removed: Parameters<typeof dropEdges>) => {
        dropEdges(...removed);
        void refreshAgentsWhenKept(docBridgeRef.current?.whenKept);
    }, [dropEdges]);

    const { onConnect, isValidConnection } = useConnect({
        markDirtyRef, reactFlow, showToast, markNodeStaleRef, applyOutput, setEdges,
        workflowNameRef, outputsRef,
    });

    const { cancelRun, signalNodeExecDone, playAllNodes, playNodesUpTo, playNodes } = usePlayAll({
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

    // #662: a view's new selection reaches the selection tags that read it,
    // and a view drawn again without it empties them (#884).
    const { clearViewTags } = useSelectionTags({ interactions, reactFlow, setNodes, markNodeStaleRef, markDirtyRef });

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
        docBridgeRef,
        flushOutputsRef: flushInstallSyncRef,
        recordSourcesRef: savePinChangeRef,
    });

    markNodeExecutedRef.current = workflowOps.markNodeExecuted;
    markNodeStaleRef.current = workflowOps.markNodeStale;
    markNodeErroredRef.current = workflowOps.markNodeErrored ?? (() => {});
    markDirtyRef.current = workflowOps.markDirty;
    scenariosNowRef.current = () => workflowOps.scenariosRef?.current ?? workflowOps.scenarios ?? [];

    // The canvas and the dataflow's doc, both ways. A watcher's canvas takes
    // the doc's changes and writes none, and has no history to read.
    const role = canvasRole(workflowOps.viewerMode, collab);
    // The doc the canvas is bound to, for what the top bar says of it.
    const [boundProvider, setBoundProvider] = useState<DataflowDocProvider | null>(null);
    const dataflowDoc = useDataflowDoc({
        binding: dashboardOn ? null : docBinding,
        bindable: !dashboardOn,
        onBound: (provider) => {
            setBoundProvider(provider);
            workflowOps.noteBound?.();
        },
        onUnbound: () => setBoundProvider(null),
        canWrite: role !== "watcher" && !!docBinding?.provider.canWrite,
        readsHistory: role !== "watcher",
        nodes, edges, setNodes, setEdges, reactFlow,
        workflowNameRef, workflowGoalRef: workflowOps.workflowGoalRef, workflowDescriptionRef,
        workflowCategoriesRef: workflowOps.workflowCategoriesRef, scenariosRef: workflowOps.scenariosRef,
        autoRunRef: workflowOps.autoRunRef,
        scenarios: workflowOps.scenarios, workflowName, workflowGoal: workflowOps.workflowGoal, workflowDescription,
        workflowCategories: workflowOps.workflowCategories, autoRun: workflowOps.autoRun,
        loadedDataflowRef: workflowOps.loadedDataflowRef,
        takeDataflowFields: workflowOps.takeDataflowFields,
        quietly: workflowOps.quietly,
        markNodeStale: workflowOps.markNodeStale,
        addNode, onConnect, onEdgesDelete, onNodesDelete, onNodesChange,
        applyNewOutput, interactionsCallback, applyNewPropagation, defaultSaveOutputDataset,
        takeCanvasPosition: notebook.takeCanvasPosition, setDashboardPins, showToast,
    });
    docBridgeRef.current = dataflowDoc;
    codeDocRef.current = dataflowDoc;
    // The categories the title shows, asked again as the dataflow changes and
    // as a run on the server ends, in every tab bound to its doc: no save
    // answers them any more.
    const categoriesRefresh = useCategoriesRefresh({
        provider: boundProvider,
        taken: workflowOps.categoriesTaken,
        take: workflowOps.takeServerCategories,
    });
    // Closing the tab asks while changes wait: a bound canvas's the server
    // does not have yet, or one bound to no doc that holds changes no one keeps.
    useLeavePageGuard(boundProvider, workflowOps.projectDirty);
    // A connection this tab drew to a node someone removed meanwhile: the
    // server took it out, and says who removed the node, a tab of the shared
    // guest account by its number.
    useEffect(() => {
        if (typeof collab.onRemote !== "function") return;
        return collab.onRemote(CONNECTION_DROPPED_EVENT, (payload: any) => {
            const who = numberedName(payload?.by?.name || payload?.by?.username || "Someone", payload?.by);
            showToast(`${who} removed that node, so this connection was not kept.`, "warning", { stay: true });
        });
    }, [collab.onRemote, showToast]);
    // Removing a node someone else is editing asks first.
    const removal = useRemovalAsk(dataflowDoc.editorsOf);
    const applyRemoveChanges = useCallback((changes: NodeRemoveChange[]) => {
        removal.ask(changes.map((change) => change.id), () => workflowOps.applyRemoveChanges(changes));
    }, [removal.ask, workflowOps.applyRemoveChanges]);

    useDashboardPinSave({
        savePinChangeRef, dashboardOn, workflowOps, showToast, hostedGuest,
    });

    useInstallSave({
        scheduleInstallSyncRef, dashboardOn, reactFlow, defaultSaveOutputDataset,
        isDashboardSource, workflowOps, flushInstallSyncRef, hostedGuest,
    });

    // Runs go to the server for whoever may save the dataflow, since a run
    // records its outputs in it. Hosted guests, viewers of a shared dataflow
    // and `--no-project` keep the run in the browser, and so does a canvas
    // with nobody signed in, which cannot save either.
    const runsOnServer =
        !dashboardOn &&
        !isStandaloneDashboard() &&
        !skipProjectPage &&
        user != null &&
        !hostedGuest &&
        workflowOps.viewerMode === "owner";
    // What a step of a run on the server does to its node: one set for the
    // canvas's runs and a dashboard viewer's.
    const stepOutcomes = useStepOutcomes({
        reactFlow, setNodes, applyNewOutput, setOutputs, hydrateRestoredOutputs,
        markNodeErroredRef, workflowNameRef, nodeExecProv,
    });
    const serverRun = useServerRun({
        reactFlow, setNodes, showToast,
        keepDataflow: workflowOps.ensureProjectId,
        applyNewOutput, setOutputs, hydrateRestoredOutputs, markNodeErroredRef,
        playNodes, playAllStateRef, emittedForInputRef, outputsRef, workflowNameRef,
        nodeExecProv, flushInstallSyncRef,
        surfaceInstallWarnings: workflowOps.surfaceInstallWarnings,
        outcomes: stepOutcomes,
        onRunEnded: categoriesRefresh.now,
    });
    // #1117: on a dashboard, a change to a control a pinned tile shows reruns
    // the dataflow on the server as a viewer's run, which never changes it.
    const dashboardRun = useDashboardRun({
        enabled: dashboardOn, reactFlow, outcomes: stepOutcomes, outputsRef, showToast, playNodes,
    });
    // #845: where Run All runs on the server, a widget change can run the
    // nodes it touched through the same start, once the changes settle.
    // On a dashboard every change does, with no toggle, as a viewer's run (#1117).
    const autoRunner = useAutoRun({
        enabled: dashboardOn || (runsOnServer && !!workflowOps.autoRun),
        runActive: isRunActive || serverRun.serverRunActive || dashboardRun.active,
        reactFlow,
        start: (targets) => {
            if (dashboardOn) void dashboardRun.start();
            else void serverRun.startRun(targets);
        },
    });
    // The Map Editor node's Commit edits: the nodes it names and every node
    // below them, as an automatic run takes them, run now through the same
    // start; in the browser where runs stay there.
    const runDownstream = (nodeIds: readonly string[]) => {
        const targets = autoRunTargets(nodeIds, reactFlow.getNodes(), reactFlow.getEdges());
        if (targets.length === 0) return;
        if (runsOnServer) void serverRun.startRun(targets);
        else playNodesUpTo(targets);
    };
    // An agent's applied settings change: each setting through the setter its
    // node registered, as a pick in the node makes it; the rest into the
    // node's data, a widget's new value leaving what reads it out of date.
    const applyNodeSettings = (nodeId: string, settings: NodeSettings) => writeNodeSettings({
        nodes: () => reactFlow.getNodes(),
        updateDataNode: workflowOps.updateDataNode,
        markNodeStale: workflowOps.markNodeStale,
        markDirty: workflowOps.markDirty,
        requestAutoRun: autoRunner.requestAutoRun,
    }, nodeId, settings);
    // Stop ends whichever run is going, on the server or in the browser, and
    // the automatic run waiting for it.
    const stopRuns = () => { autoRunner.dropWaiting(); cancelRun(); serverRun.stopRun(); };
    // Opening another dataflow leaves a run on the server going.
    const leaveRuns = () => { autoRunner.dropWaiting(); cancelRun(); serverRun.detachRun(); };

    const nodeActionsValue = useMemo<NodeActionsContextProps>(() => ({
        workflowNameRef,
        workflowName,
        applyRemoveChanges,
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
        applyRemoveChanges,
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
                clearSelectionTagsOf: clearViewTags,
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
                playAllNodes: runsOnServer ? () => { void serverRun.startRun(); } : playAllNodes,
                // A run on the server takes one target node, so a list (a
                // scenario's levers) runs in the browser, once no server run
                // is going.
                playNodesUpTo: runsOnServer
                    ? (target: string | readonly string[]) => {
                        if (typeof target === "string") {
                            void serverRun.startRun(target);
                        } else if (serverRun.serverRunActive) {
                            showToast(
                                "A run is already in progress. Wait for it to finish, or cancel it with the stop button.",
                                "info",
                            );
                        } else {
                            playNodesUpTo(target);
                        }
                    }
                    : playNodesUpTo,
                signalNodeExecDone,
                isRunActive,
                serverRunActive: serverRun.serverRunActive || dashboardRun.active,
                dashboardStopped: dashboardRun.stopped,
                cancelRun: stopRuns,
                attachLatestRun: runsOnServer ? serverRun.attachLatestRun : async () => {},
                autoRunAvailable: runsOnServer,
                requestAutoRun: autoRunner.requestAutoRun,
                runDownstream,
                dashboardOpened: dashboardOn ? dashboardRun.opened : undefined,

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
                boundDoc: boundProvider,
                recordOutputsSoon: () => savePinChangeRef.current(),
                whenChangesKept: () => {
                    if (!dataflowDoc.bound() || boundProvider?.isKept()) return Promise.resolve(true);
                    // Offline, what waits in the tab is lost on leaving: ask at once.
                    if (collab.connected === false) return Promise.resolve(false);
                    return Promise.race([
                        dataflowDoc.whenKept(),
                        new Promise<boolean>((resolve) => setTimeout(() => resolve(false), LEAVE_WAIT_MS)),
                    ]);
                },
                applyRemoveChanges,
                dataflowDoc: {
                    bound: dataflowDoc.bound,
                    noteDrag: dataflowDoc.noteDrag,
                    editorsOf: dataflowDoc.editorsOf,
                    noteRemoval: dataflowDoc.noteRemoval,
                    askBeforeRemoving: removal.ask,
                    noteNodeData: dataflowDoc.noteNodeData,
                },
                // A project switch must not inherit a run in flight: the guard
                // is provider state, and the provider outlives the dataflow
                // when the user loads another one in place (#271).
                loadProject: async (id: string, options?: { lastResults?: boolean }) => {
                    leaveRuns();
                    return workflowOps.loadProject(id, options);
                },
                loadSharedProject: async (id: string) => { leaveRuns(); return workflowOps.loadSharedProject(id); },
                cleanCanvas: () => { leaveRuns(); workflowOps.cleanCanvas(); },
                discardProject: () => { leaveRuns(); workflowOps.discardProject(); },
                applyNodeContent,
                applyNodeSettings,
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
                {inRouter && !dashboardOn && <CanvasViewAddress view={notebook.canvasView} />}
                {children}
                {removal.dialog}
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
