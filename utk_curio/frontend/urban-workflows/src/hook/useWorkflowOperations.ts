/**
 * useWorkflowOperations
 *
 * Encapsulates workflow-specific operations (trill loading, canvas management,
 * suggestion handling, keyword/subtask/warning updates) that were previously
 * inlined in FlowProvider. Keeps FlowProvider focused on core ReactFlow state
 * and connection logic.
 */

import { useEffect, useState, useCallback, useRef } from "react";
import {
    Node,
    Edge,
    NodeChange,
    NodeRemoveChange,
    Connection,
    useNodesInitialized,
    useReactFlow,
} from "reactflow";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { noteSaved, setServerHistory } from "../providers/history/serverHistory";
import { useToastContext } from "../providers/ToastProvider";
import { useUserContext } from "../providers/UserProvider";
import { isHostedGuest } from "../components/apiSettings/useHostedGuest";
import { DEFAULT_WORKFLOW_NAME } from "../constants";
import { updateNodeData, updateNodesByMap, updateEdgesByMap, extractNodeFieldMap, extractKeywordMaps } from "../utils/flowNodeUtils";
import { fitViewWithMenuOffset } from "../utils/fitViewWithMenuOffset";
import { TrillGenerator } from "../TrillGenerator";
import { projectsApi, OutputRef, DatasetInstallWarning, type ProjectDetail, type TileLayout } from "../api/projectsApi";
import type { DataflowCategories, HandCategories } from "../utils/dataflowCategories";
import { normalizeScenarios, type Scenario } from "../utils/scenarios/scenarioModel";
import { buildSaveableLiveOutputs } from "../utils/saveOutputDataset";
import { prepareDashboardNodes } from "../utils/dashboardLayout";
import { savedSourceNodeIds } from "../utils/scenarios/scenarioParts";
import { scenarioDashboard } from "../utils/scenarios/scenarioDashboard";
import { notifyAgentDockRefresh } from "../services/agents";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import { notifyDatasetCatalogRefresh } from "../services/datasetCatalog/datasetCatalogApi";
import type { InstallSyncOutcome, PendingInstall } from "../services/datasetCatalog/datasetCatalogTypes";
import {
    getCurrentProjectId,
    getCurrentProjectPackagesList,
    setCurrentProject,
    setCurrentProjectPackages,
    subscribe as subscribeProjectPackages,
    whenProjectSettled,
} from "../registry/projectPackagesStore";
import { tryGetNodeDescriptor } from "../registry/nodeRegistry";
import { isRegistryReady } from "../registry/registryReadiness";
import type { WidgetDef } from "../utils/widgets/widgetModel";

/** How long the load fit waits for the package registry to give every node
 *  its descriptor. Without a session the registry never loads, so the wait
 *  must end on its own. */
export const LOAD_FIT_REGISTRY_WAIT_MS = 4000;

export interface WorkflowOperationsDeps {
    nodes: Node[];
    edges: Edge[];
    setNodes: any;
    setEdges: any;
    setOutputs: any;
    // `output` is `unknown`, matching IOutput in FlowProvider (which is what is
    // actually passed) and SaveableOutput in saveOutputDataset (which is what
    // actually consumes it). Declaring it `string` here made the provider's own
    // ref unassignable to the hook it feeds.
    outputsRef: React.MutableRefObject<Array<{ nodeId: string; output: unknown }>>;
    setInteractions: any;
    setDashboardPins: (value: any) => void;
    /**
     * True while this tree is the dashboard page rather than the canvas.
     *
     * Two things turn on it: a load lays the graph out as tiles, and nothing
     * saves on its own. A dashboard's only write is an explicit Save layout, so
     * a viewer who never touches it cannot rewrite the owner's dataflow.
     */
    presentation?: boolean;
    setWorkflowName: (name: string) => void;
    workflowNameRef: React.MutableRefObject<string>;
    setWorkflowDescription: (description: string) => void;
    workflowDescriptionRef: React.MutableRefObject<string>;
    onEdgesDelete: (connections: Edge[]) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean, sourceAddedByLoad?: boolean) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    // Workflow-wide default for the per-node "Save output dataset" toggle,
    // sourced from the backend (CURIO_DEFAULT_SAVE_NODE_OUTPUT) via FlowProvider.
    defaultSaveOutputDataset: boolean;
    /**
     * The canvas's binding to the dataflow's doc (`useDataflowDoc`), which
     * FlowProvider fills once the bridge exists. No tab saves a dataflow it
     * is bound to: the doc keeps each change as it is made, and the server
     * the history.
     */
    docBridgeRef?: React.MutableRefObject<DocBridgeForSaves | null>;
    /** Records now the outputs a run left waiting to be recorded
     *  (`useInstallSave`), and resolves once they are. */
    flushOutputsRef?: React.MutableRefObject<() => Promise<void> | void>;
    /** Records, a moment later, the outputs a pinned tile or a scenario reads
     *  (`useDashboardPinSave`). */
    recordSourcesRef?: React.MutableRefObject<() => void>;
}

/** What the canvas asks its binding to the dataflow's doc. */
export interface DocBridgeForSaves {
    bound(): boolean;
    /** Resolves true once the canvas is bound to the doc, false when it is
     *  not within *timeoutMs*, and false at once for a canvas that binds to
     *  none (the dashboard's). */
    whenBound(timeoutMs?: number): Promise<boolean>;
    whenKept(): Promise<boolean>;
    /** The canvas as the doc would hold it now: what a new dataflow is made
     *  from, so its bind writes only what changed after. */
    canvasNow(): Record<string, any>;
}

/** What File > Save says when the server cannot be reached to keep the
 *  dataflow's changes. */
export const SAVE_OFFLINE_MESSAGE =
    "Curio cannot reach the server right now. Your changes stay on this page and are sent as soon as it can.";

/** The dataflow the canvas was built from or saved as, on which load. */
export interface LoadedDataflow {
    epoch: number;
    projectId: string | null;
    dataflow: any;
    /** The canvas as its doc would hold it when the dataflow was made from
     *  it (a never-saved canvas's first save, Save a copy): its bind writes
     *  what the canvas changed after. */
    canvas?: any;
}

export function useWorkflowOperations(deps: WorkflowOperationsDeps) {
    const {
        nodes, edges,
        setNodes, setEdges,
        setOutputs, setInteractions,
        setDashboardPins,
        presentation = false,
        setWorkflowName,
        workflowNameRef,
        setWorkflowDescription,
        workflowDescriptionRef,
        onEdgesDelete, onNodesDelete, onNodesChange,
        onConnect, addNode,
        defaultSaveOutputDataset,
    } = deps;

    const reactFlow = useReactFlow();
    const nodesInitialized = useNodesInitialized();
    const { getAllNodeProvenance } = useProvenanceContext();
    const { showToast } = useToastContext();
    const { user, enableUserAuth } = useUserContext();
    const blockGuestSaves = isHostedGuest(user, enableUserAuth);

    // fitViewOnLoad is internal to workflow loading
    const [fitViewOnLoad, setFitViewOnLoad] = useState(false);

    // Workflow-level state (not used by FlowProvider's core flow logic)
    const [allMinimized, setAllMinimized] = useState<number>(0);
    const [expandStatus, setExpandStatus] = useState<'expanded' | 'minimized'>('expanded');
    const [suggestionsLeft, setSuggestionsLeft] = useState<number>(0); // Number of suggestions left
    const [workflowGoal, setWorkflowGoal] = useState("");
    // The save paths run from callbacks that close over stale state, so they
    // read the goal through a ref, the way the name and description already do.
    const workflowGoalRef = useRef("");
    useEffect(() => { workflowGoalRef.current = workflowGoal; }, [workflowGoal]);
    // The hand-set categories (``dataflow.categories``), saved with the dataflow,
    // read through a ref for the same reason as the goal. ``serverCategories`` is
    // the source and the automatic ones, which only the server computes: set from
    // each load and each save's response, so they change when the dataflow saves.
    const [workflowCategories, setWorkflowCategoriesState] = useState<HandCategories>({});
    const workflowCategoriesRef = useRef<HandCategories>({});
    const [serverCategories, setServerCategories] = useState<DataflowCategories>({});
    // #662: the dataflow's scenarios (``dataflow.scenarios``), saved with it and
    // read through a ref, as the categories are. TrillGenerator holds a copy so
    // a version snapshot carries them.
    const [scenarios, setScenariosState] = useState<Scenario[]>([]);
    const scenariosRef = useRef<Scenario[]>([]);
    // #845: "Run stale nodes automatically" (``dataflow.autoRun``), saved with
    // the dataflow, off by default, read through a ref as the categories are.
    const [autoRun, setAutoRunState] = useState(false);
    const autoRunRef = useRef(false);
    // ``packages`` is the current project's lockfile (``spec.dataflow.packages``).
    // The authoritative copy lives in ``projectPackagesStore`` so non-React
    // code (palette filter, registry bootstrap) can read it without context.
    // This component subscribes so save callers see fresh state.
    const [packages, setPackagesState] = useState<string[]>(getCurrentProjectPackagesList());
    const [dataflowDatasets, setDataflowDatasets] = useState<any[]>([]);
    // Keep a ref that's always in sync so a create never reads a stale
    // closure value (important: set during render, not in a useEffect, so
    // it's always the value from the most recent completed render).
    const dataflowDatasetsRef = useRef<any[]>([]);
    dataflowDatasetsRef.current = dataflowDatasets;
    // In-flight dataset installs, surfaced as "Adding…" placeholders in the
    // palette + drawer. Volatile/session-only — never serialized into the spec.
    // Mirrored in a ref so begin/clear from async callbacks never read a stale
    // closure, and a per-key timeout map backstops crashed/aborted installs.
    const [pendingInstalls, setPendingInstalls] = useState<PendingInstall[]>([]);
    const pendingInstallsRef = useRef<PendingInstall[]>([]);
    pendingInstallsRef.current = pendingInstalls;
    const pendingInstallTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
    useEffect(() => {
        // Re-read on subscribe, not only on notify. ``ProjectLoader`` is a
        // DESCENDANT of this provider, so React runs its route effect first:
        // the ``setUnsavedDataflow`` / ``setCurrentProject`` it fires on mount
        // notifies a store nobody is listening to yet, and the mirror keeps the
        // previous dataflow's list forever (#204). Reading once here closes that
        // window; the subscription then keeps it live.
        setPackagesState(getCurrentProjectPackagesList());
        return subscribeProjectPackages(() => {
            setPackagesState(getCurrentProjectPackagesList());
        });
    }, []);

    const setPackages = useCallback((pkgs: string[]) => {
        setCurrentProjectPackages(pkgs);
    }, []);

    const addPackage = useCallback((pkg: string) => {
        const current = getCurrentProjectPackagesList();
        if (!current.includes(pkg)) {
            setCurrentProjectPackages([...current, pkg]);
        }
    }, []);

    const removePackage = useCallback((pkg: string) => {
        const current = getCurrentProjectPackagesList();
        setCurrentProjectPackages(current.filter((p) => p !== pkg));
    }, []);

    // Project state
    const [projectId, setProjectId] = useState<string | null>(null);
    // Mirror projectId in a ref so a caller decides whether to create from the
    // *live* id, not a stale closure: after a create sets projectId, a
    // follow-up action in the same async flow (an outputs record) would
    // otherwise still see ``null`` and POST a second project. Synced on render
    // and set explicitly the instant a create resolves (below).
    const projectIdRef = useRef<string | null>(null);
    projectIdRef.current = projectId;
    const [projectName, setProjectName] = useState<string>("");
    // Same treatment for the name (#270): a create reads the name as it is
    // when it leaves, never as it was when its caller's closure was made.
    // Synced on render, and pinned synchronously by ``renameDataflow``.
    const projectNameRef = useRef<string>("");
    projectNameRef.current = projectName;
    const [projectDirty, setProjectDirty] = useState<boolean>(false);
    // Mirrored for an action in the tick an edit was made in. Synced on
    // render, and set the moment an edit marks it.
    const projectDirtyRef = useRef<boolean>(false);
    projectDirtyRef.current = projectDirty;
    const [projectSavedAt, setProjectSavedAt] = useState<Date | null>(null);
    const [nodeExecStatus, setNodeExecStatus] = useState<Record<string, "stale" | "executed" | "errored">>({});
    const [viewerMode, setViewerMode] = useState<"owner" | "shared">("owner");

    // True only while ``loadParsedTrill`` replays a persisted dataflow onto the
    // canvas. That replay drives the very same ``onConnect`` a user drag does -
    // once per edge - and onConnect marks the project dirty, so a dataflow with
    // even one edge came back from disk already reading "Unsaved changes" (#229).
    //
    // A ref, not state: the replay runs inside a ``setNodes`` updater and has to
    // read this synchronously. Deliberately NOT a timer or a settle window - it
    // is opened and closed around the synchronous replay loop alone, so an edit
    // made a millisecond after the load still marks the dataflow dirty.
    const hydratingRef = useRef(false);

    // Bumped by every edit. A create captures it before its request and clears
    // the dirty flag on return only if it has not moved (#270): an edit made
    // while it was out is not in what it sent, so the dataflow stays Unsaved,
    // with its leave question, until the bind writes that edit into the doc.
    const dirtyGenerationRef = useRef(0);

    // Only a canvas bound to no doc holds unsaved changes: a dataflow not
    // saved yet, or a hosted guest's own canvas. The doc keeps each change a
    // bound canvas makes, as it is made.
    const markDirty = useCallback(() => {
        if (hydratingRef.current) return;
        if (deps.docBridgeRef?.current?.bound()) return;
        dirtyGenerationRef.current += 1;
        projectDirtyRef.current = true;
        setProjectDirty(true);
    }, []);

    /** The canvas bound to its dataflow's doc, which now holds what the canvas
     *  changed before (`useDataflowDoc` writes it with the bind). */
    const noteBound = useCallback(() => {
        dirtyGenerationRef.current += 1;
        projectDirtyRef.current = false;
        setProjectDirty(false);
        setProjectSavedAt(new Date());
    }, []);

    /** Run *apply*, a change the dataflow's doc brought to this canvas, with
     *  nothing it does marking the dataflow Unsaved: the doc keeps it. */
    const quietly = useCallback(<T,>(apply: () => T): T => {
        const was = hydratingRef.current;
        hydratingRef.current = true;
        try {
            return apply();
        } finally {
            hydratingRef.current = was;
        }
    }, []);

    // The dataflow the canvas was last built from or saved as, a new epoch for
    // each: the doc's first sync on it applies what the doc changed since
    // (useDataflowDoc). Leaving a dataflow notes none.
    const loadedDataflowRef = useRef<LoadedDataflow | null>(null);
    const noteLoadedDataflow = useCallback((dataflow: any, projectIdOfIt?: string | null, canvas?: any) => {
        loadedDataflowRef.current = {
            epoch: (loadedDataflowRef.current?.epoch ?? 0) + 1,
            // A load's dataflow is the one the route opened.
            projectId: projectIdOfIt !== undefined ? projectIdOfIt : (getCurrentProjectId() ?? null),
            dataflow,
            ...(canvas ? { canvas } : {}),
        };
    }, []);

    // Loading sets them without dirtying; an edit on the canvas title dirties,
    // like a rename, and is written by the next save.
    const setWorkflowCategories = useCallback((next: HandCategories) => {
        workflowCategoriesRef.current = next;
        setWorkflowCategoriesState(next);
    }, []);
    const updateDataflowCategories = useCallback((next: HandCategories) => {
        setWorkflowCategories(next);
        markDirty();
    }, [setWorkflowCategories, markDirty]);

    // Scenarios the same way: a load sets them without dirtying, an edit dirties.
    const setScenariosQuietly = useCallback((next: Scenario[]) => {
        scenariosRef.current = next;
        TrillGenerator.scenarios = next;
        setScenariosState(next);
    }, []);
    // A scenario's context and outcomes are saved to the Data Catalog, as a
    // pinned tile's sources are (#662).
    const setScenarios = useCallback((next: Scenario[]) => {
        setScenariosQuietly(next);
        markDirty();
        deps.recordSourcesRef?.current?.();
    }, [setScenariosQuietly, markDirty]);

    // And the auto-run toggle.
    const setAutoRunQuietly = useCallback((on: boolean) => {
        autoRunRef.current = on;
        setAutoRunState(on);
    }, []);
    const setAutoRun = useCallback((on: boolean) => {
        setAutoRunQuietly(on);
        markDirty();
    }, [setAutoRunQuietly, markDirty]);

    /** The dataflow's own fields the doc changed (*nodeIds*: the nodes it
     *  holds), set on the canvas as a load sets them. */
    const takeDataflowFields = useCallback((fields: Record<string, any>, nodeIds: string[]) => {
        if ("name" in fields && typeof fields.name === "string") {
            setWorkflowName(fields.name);
            projectNameRef.current = fields.name;
            setProjectName(fields.name);
        }
        if ("task" in fields) {
            workflowGoalRef.current = typeof fields.task === "string" ? fields.task : "";
            setWorkflowGoal(workflowGoalRef.current);
        }
        if ("description" in fields) {
            setWorkflowDescription(typeof fields.description === "string" ? fields.description : "");
        }
        if ("categories" in fields) {
            setWorkflowCategories(fields.categories && typeof fields.categories === "object" ? fields.categories : {});
        }
        if ("autoRun" in fields) setAutoRunQuietly(fields.autoRun === true);
        if ("scenarios" in fields) setScenariosQuietly(normalizeScenarios(fields.scenarios ?? [], nodeIds));
        if ("packages" in fields && Array.isArray(fields.packages)) setPackages(fields.packages);
        if ("datasets" in fields) setDataflowDatasets(Array.isArray(fields.datasets) ? fields.datasets : []);
    }, [setWorkflowName, setWorkflowDescription, setWorkflowCategories, setAutoRunQuietly, setScenariosQuietly, setPackages]);

    // ---------------------------------------------------------------------------
    // Effects
    // ---------------------------------------------------------------------------

    useEffect(() => {
        if (!fitViewOnLoad) {
            return;
        }

        let timeoutId: number | undefined;
        let frameId = 0;
        let attempts = 0;
        const startedAt = Date.now();

        const fitOptions = { padding: 0.2 };

        // React Flow skips fitView until every node has measured dimensions.
        // Loading a workflow can race that measurement, so retry until the
        // fit actually applies instead of clearing the flag after one attempt.
        const attemptFitView = () => {
            const currentNodes = reactFlow.getNodes();

            if (currentNodes.length === 0) {
                setFitViewOnLoad(false);
                return;
            }

            // A node whose package has not registered yet is a small
            // placeholder that grows to its full size when the descriptor
            // lands. Fitting the placeholders leaves the grown nodes past the
            // window's edge (#683), so wait for the registry, within a bound.
            const waitingOnPackages =
                !isRegistryReady() &&
                currentNodes.some((node) => !tryGetNodeDescriptor(node.data?.nodeType));
            if (waitingOnPackages && Date.now() - startedAt < LOAD_FIT_REGISTRY_WAIT_MS) {
                timeoutId = window.setTimeout(attemptFitView, 100);
                return;
            }

            const fitApplied = fitViewWithMenuOffset(reactFlow, fitOptions);

            if (!fitApplied) {
                attempts += 1;

                if (attempts >= 20) {
                    // Measurement never produced positive dimensions for every
                    // node within the retry budget (e.g. a hidden/zero-sized
                    // node, or a context where fitViewWithMenuOffset's pane
                    // fallback is never reached because its measurement gate
                    // keeps short-circuiting). Don't leave the canvas at the
                    // default viewport — do a best-effort plain fitView so
                    // content is at least roughly framed before giving up.
                    reactFlow.fitView(fitOptions);
                    setFitViewOnLoad(false);
                    return;
                }

                timeoutId = window.setTimeout(
                    attemptFitView,
                    nodesInitialized ? 50 : 100,
                );
                return;
            }

            timeoutId = window.setTimeout(() => {
                fitViewWithMenuOffset(reactFlow, fitOptions);
                setFitViewOnLoad(false);
            }, 75);
        };

        frameId = window.requestAnimationFrame(attemptFitView);

        return () => {
            window.cancelAnimationFrame(frameId);
            if (timeoutId !== undefined) {
                window.clearTimeout(timeoutId);
            }
        };
    }, [fitViewOnLoad, nodesInitialized, reactFlow]);

    useEffect(() => {
        flagAcceptableSuggestions(nodes, edges);
    }, [nodes, edges]);

    // ---------------------------------------------------------------------------
    // Trill / Data Operations
    // ---------------------------------------------------------------------------

    const updateDataNode = useCallback((nodeId: string, newData: any) => {
        console.log("updateDataNode");
        setNodes((prevNodes: Node[]) => updateNodeData(prevNodes, nodeId, () => ({ ...newData })));
    }, [setNodes]);

    const loadParsedTrill = async (workflowName: string, task: string, loaded_nodes: any, loaded_edges: any, provenance?: boolean, merge?: boolean, incomingPackages?: string[], incomingDescription?: string, incomingDatasets?: any[], incomingCategories?: HandCategories, incomingScenarios?: unknown, fit?: boolean, incomingAutoRun?: boolean) => {
        if (!merge) {
            // The canvas holds another load now, bound to no doc until its
            // own binds: the versions below are recorded here till then.
            setServerHistory(null);
            TrillGenerator.reset();
            // Before the replay below, whose version snapshots carry them.
            // Absent = keep, as for the categories.
            setScenariosQuietly(
                incomingScenarios !== undefined
                    ? normalizeScenarios(incomingScenarios, (loaded_nodes || []).map((n: any) => n.id))
                    : scenariosRef.current,
            );
            setWorkflowName(workflowName);
            setWorkflowDescription(incomingDescription || "");
            // Absent = keep: a provenance revert loads a version snapshot, which
            // carries no categories, and must not clear the dataflow's.
            if (incomingCategories !== undefined) setWorkflowCategories(incomingCategories);
            // The auto-run toggle the same way (#845).
            if (incomingAutoRun !== undefined) setAutoRunQuietly(incomingAutoRun);
            // `task` is the dataflow's goal. It has always been a spec field
            // and has always been accepted here, but nothing applied it, so a
            // saved goal was silently dropped on every open.
            setWorkflowGoal(task || "");
            const empty_trill = TrillGenerator.generateTrill([], [], workflowName, task || "", [], incomingDescription || "", incomingDatasets || []);
            TrillGenerator.intializeProvenance(empty_trill);
            setPackages(incomingPackages || []);
            setDataflowDatasets(incomingDatasets || []);
            console.log("loadParsedTrill reseting nodes");
            setNodes(() => []);
            // The previous dataflow's outputs go now, not in the setNodes
            // updater below: React runs that updater at its next render, after
            // what the caller queues once this returns, and ProjectLoader puts
            // the saved outputs it restores in `outputs` right then (#407).
            // Cleared in the updater, they were gone: a play on the server
            // handed none of them over as `reuse`, so the server ran those
            // nodes again, and the next save took them out of the manifest.
            setOutputs([]);
        }

        // Pins come off the spec, so they are known before anything is added.
        const pins: Record<string, boolean> = {};
        for (const node of loaded_nodes) {
            if (node.data?.dashboardPinned) pins[node.id] = true;
        }

        // On the dashboard page the graph enters provider state already laid out
        // as tiles. Done here rather than in the page for two reasons: the page
        // has no "the load finished" signal to react to, and a transform applied
        // afterwards would fight React Flow over `position` on every tile drag.
        if (!merge && presentation) {
            // By scenario when a pinned tile is in one (#662); the scenarios
            // were set just above.
            const byScenario = scenarioDashboard(loaded_nodes, loaded_edges, pins, scenariosRef.current);
            const prepared = prepareDashboardNodes(loaded_nodes, loaded_edges, pins, byScenario?.columns);
            loaded_nodes = prepared.nodes;
            loaded_edges = prepared.edges;
        }

        // Provenance is recorded below, from these local arrays, NOT by addNode /
        // onConnect. Those two snapshot `reactFlow.getNodes()`, and React Flow only
        // syncs `useNodesState` into its zustand store from a useEffect - so inside
        // this synchronous loop the store still holds the graph as it was before the
        // load. Every version came out with one node and no edges, which is why a
        // loaded dataflow's provenance thumbnails were blank and its versions carried
        // edges whose endpoints were absent (#186, and the crash in #195).
        const priorNodes: Node[] = merge ? reactFlow.getNodes() : [];
        const priorEdges: Edge[] = merge ? reactFlow.getEdges() : [];
        const addedNodes: Node[] = [];

        if (merge) {
            // Use reactFlow to get fresh state (avoid stale closure)
            const currentNodeIds = new Set(priorNodes.map((n: Node) => n.id));
            for (const node of loaded_nodes) {
                if (!currentNodeIds.has(node.id)) {
                    addNode(node, workflowName, false);
                    addedNodes.push(node);
                }
            }
        } else {
            for (const node of loaded_nodes) {
                addNode(node, workflowName, false);
                addedNodes.push(node);
            }
        }

        if (!merge) {
            setEdges(() => []);
        }

        // Use reactFlow to get fresh edge ids (avoid stale closure)
        const currentEdgeIds = new Set(reactFlow.getEdges().map((e: Edge) => e.id));

        const addedEdges: any[] = merge
            ? loaded_edges.filter((e: Edge) => !currentEdgeIds.has(e.id))
            : [...loaded_edges];

        /** One provenance version per loaded node, then one per loaded edge.
         *
         * Built from the arrays this function was handed rather than from the
         * React Flow store, so each version holds the graph as it stood at that
         * step: cumulative nodes, then the full node set with cumulative edges.
         * The invariant that matters is that every version's edges have both
         * endpoints among its own nodes - `onConnect` dereferences the resolved
         * target, so a version that breaks it crashes the canvas when a user
         * clicks it in the provenance graph (#195).
         */
        const recordLoadProvenance = () => {
            const acc: Node[] = [...priorNodes];
            for (const node of addedNodes) {
                acc.push(node);
                TrillGenerator.addNewVersionProvenance(
                    [...acc], [...priorEdges], workflowName, task || "", "Node added",
                );
            }
            // An edge whose endpoints are not both in `acc` would recreate the very
            // shape #195 crashes on, so it never enters a version.
            const present = new Set(acc.map((n: Node) => n.id));
            const accEdges: any[] = [...priorEdges];
            for (const edge of addedEdges) {
                if (!present.has(edge.source) || !present.has(edge.target)) continue;
                accEdges.push(edge);
                TrillGenerator.addNewVersionProvenance(
                    acc, [...accEdges], workflowName, task || "", "Connection added",
                );
            }
        };

        // A replayed edge from a node this load added hands over none of the
        // outputs the caller restores: the caller passes those down itself,
        // once (`hydrateRestoredOutputs`). An edge from a node the canvas
        // already had (Duplicate selection wiring a copy to what fed the
        // original) hands that node's output to its own target, as any new
        // edge does.
        const addedIds = new Set(addedNodes.map((n: Node) => n.id));

        console.log("loadParsedTrill second");
        setNodes((prevNodes: any) => {
            // Replaying persisted edges must not dirty the project: ``onConnect``
            // marks dirty because a user connecting two nodes IS an edit, and this
            // loop is the same call (#229). Opened and closed INSIDE the updater,
            // because React may run it long after loadParsedTrill returned (and
            // twice under StrictMode) - so the window is scoped to exactly the
            // replay. ``finally`` so a malformed spec throwing inside onConnect
            // cannot leave dirty-tracking wedged off for the rest of the session.
            hydratingRef.current = true;
            try {
                // skipValidation=true: these edges come from a saved/imported trill and
                // were validated when created. Re-validating on load races the async
                // node-descriptor registry and would drop valid edges + toast mid-render.
                //
                // onConnect is handed the edges connected so far, the canvas's
                // first on a merge, so a node's circles (in_N occupancy, and
                // which of them a hand-over finds wired) are read against this
                // load's earlier edges, not the store, which does not hold them.
                const connectedSoFar: any[] = merge ? [...reactFlow.getEdges()] : [];
                for (const edge of loaded_edges) {
                    if (merge && currentEdgeIds.has(edge.id)) continue;
                    onConnect(edge, prevNodes, connectedSoFar, workflowName, false, true, addedIds.has(edge.source));
                    connectedSoFar.push(edge);
                }
            } finally {
                hydratingRef.current = false;
            }

            if (!merge) {
                setInteractions([]);
                setDashboardPins(pins);
            }

            // The dashboard page frames its own tiles (`useDashboardFit`); the
            // canvas fit would fight it, and it cannot even complete there since
            // an unpinned node is `display: none` and never gets measured. A
            // caller that frames what it added asks for no fit (`fit: false`):
            // a dropped scenario's box is not a node, so the fit framed its
            // context alone and left the box out of view (#769).
            if (!presentation && fit !== false) setFitViewOnLoad(true);
            return prevNodes;
        });

        // After the updater, not inside it: a state updater must stay pure, and
        // `addedEdges` never depended on `prevNodes` anyway.
        if (provenance) {
            recordLoadProvenance();
        }
    }

    const updateDefaultCode = useCallback((nodeId: string, content: string) => {
        console.log("updateDefaultCode");
        setNodes((prevNodes: Node[]) => updateNodeData(prevNodes, nodeId, (data: any) => ({ ...data, defaultCode: content })));
    }, [setNodes]);

    // Given a trill specification update the keywords property of the associated nodes
    const updateKeywords = (trill_spec: any) => {
        console.log("updateKeywords");
        const { nodeToKeywords, edgeToKeywords } = extractKeywordMaps(trill_spec);
        setNodes((prevNodes: Node[]) => updateNodesByMap(prevNodes, nodeToKeywords, 'keywords'));
        setEdges((prevEdges: Edge[]) => updateEdgesByMap(prevEdges, edgeToKeywords, 'keywords'));
    }

    // Given a trill specification update the goal property of the associated nodes
    const updateSubtasks = (trill_spec: any) => {
        console.log("updateSubtasks");
        const nodeToGoal = extractNodeFieldMap(trill_spec, 'goal');
        setNodes((prevNodes: Node[]) => updateNodesByMap(prevNodes, nodeToGoal, 'goal'));
    }

    // Given a trill specification update the warnings property of the associated nodes
    const updateWarnings = (trill_spec: any) => {
        console.log("updateWarnings");
        const nodeToWarning = extractNodeFieldMap(trill_spec, 'warnings');
        setNodes((prevNodes: Node[]) => updateNodesByMap(prevNodes, nodeToWarning, 'warnings'));
    }

    // ---------------------------------------------------------------------------
    // Canvas Management
    // ---------------------------------------------------------------------------

    // Considering provenance
    const deleteNode = (nodeId: string) => {
        const change: NodeRemoveChange = {
            id: nodeId,
            type: "remove",
        };

        onNodesDelete([change]);
    };

    const cleanCanvas = () => {
        console.log("cleanCanvas");
        // Use reactFlow to get fresh state (avoid stale closure)
        const currentEdges = reactFlow.getEdges();
        const currentNodes = reactFlow.getNodes();

        const isSuggestion = (data: any) =>
            data && data.suggestionType != "none" && data.suggestionType != undefined;

        const edgesWithProvenance = currentEdges.filter((edge: Edge) => !isSuggestion(edge.data));
        onEdgesDelete(edgesWithProvenance);

        setEdges(() => []);

        for (const node of currentNodes) {
            if (!isSuggestion(node.data)) {
                deleteNode(node.id);
            }
        }

        setNodes(() => []);
        setOutputs([]);
        setInteractions([]);
        setDashboardPins({});
        setSuggestionsLeft(0);
        setPackages([]);
    }

    // Removes nodes together with their edges. Shared by a reviewed plan apply
    // (dev/62, DEC-049) and the node header's Delete node button. Bookkeeping
    // parity with deleting an edge by hand: onEdgesDelete (collab broadcast,
    // provenance, survivor-input reset) and onNodesDelete (output pruning,
    // provenance, broadcast). Already-absent elements no-op.
    const applyReviewedRemovals = useCallback((nodeIds: string[], edgeIds: string[]) => {
        const edgeSet = new Set(edgeIds);
        const victimEdges = reactFlow.getEdges().filter((e: Edge) => edgeSet.has(e.id));
        if (victimEdges.length) {
            onEdgesDelete(victimEdges);
            setEdges((prev: Edge[]) => prev.filter((e: Edge) => !edgeSet.has(e.id)));
        }
        const nodeSet = new Set(nodeIds);
        const changes: NodeRemoveChange[] = reactFlow
            .getNodes()
            .filter((n: Node) => nodeSet.has(n.id))
            .map((n: Node) => ({ id: n.id, type: "remove" as const }));
        if (changes.length) {
            onNodesDelete(changes);
            onNodesChange(changes);
        }
    }, [reactFlow, onEdgesDelete, setEdges, onNodesDelete, onNodesChange]);

    // The node header's Delete node button: the node goes with every edge
    // attached to it (#155), as with the Delete key.
    const applyRemoveChanges = useCallback((changes: NodeRemoveChange[]) => {
        const nodeIds = new Set(changes.map((change) => change.id));
        const edgeIds = reactFlow
            .getEdges()
            .filter((edge: Edge) => nodeIds.has(edge.source) || nodeIds.has(edge.target))
            .map((edge: Edge) => edge.id);
        applyReviewedRemovals([...nodeIds], edgeIds);
    }, [reactFlow, applyReviewedRemovals]);

    // ---------------------------------------------------------------------------
    // Suggestion Management
    // ---------------------------------------------------------------------------

    // Go through all suggestions nodes and flag the nodes that can be accepted (the ones that dont have a dependency on another suggested node)
    const flagAcceptableSuggestions = (currentNodes: any, currentEdges: any) => {
        console.log("flagAcceptableSuggestions");
        const suggestedNodes: string[] = [];
        for (const node of currentNodes) {
            if (node.data.suggestionType == "workflow") {
                suggestedNodes.push(node.id);
            }
        }

        setSuggestionsLeft(suggestedNodes.length);

        const dependOn: string[] = [];
        for (const edge of currentEdges) {
            if (suggestedNodes.includes(edge.source)) {
                dependOn.push(edge.target);
            }
        }

        const nodesToUpdate: string[] = [];
        for (const node of currentNodes) {
            const shouldBeAcceptable =
                (!dependOn.includes(node.id) && node.data.suggestionType == "workflow") ||
                node.data.suggestionType == "connection";

            if (shouldBeAcceptable && !node.data.suggestionAcceptable) {
                nodesToUpdate.push(node.id);
            } else if (!shouldBeAcceptable && node.data.suggestionAcceptable) {
                nodesToUpdate.push(node.id);
            }
        }

        if (nodesToUpdate.length > 0) {
            setNodes((prevNodes: Node[]) =>
                prevNodes.map((node: Node) =>
                    nodesToUpdate.includes(node.id)
                        ? { ...node, data: { ...node.data, suggestionAcceptable: !node.data.suggestionAcceptable } }
                        : node
                )
            );
        }
    }

    // Accept the suggestion for adding a specific node
    const acceptSuggestion = useCallback((nodeId: string) => {
        console.log("acceptSuggestion");
        setNodes((prevNodes: Node[]) => {
            let acceptedConnectionSuggestion = false;
            let acceptedConnectionSuggestionId = "";

            // Update the accepted node and detect connection suggestion acceptance
            const updatedNodes = prevNodes.map((node: Node) => {
                if (node.id !== nodeId) return node;

                const isConnection = node.data.suggestionType == "connection";
                if (isConnection) {
                    acceptedConnectionSuggestion = true;
                    acceptedConnectionSuggestionId = node.id;
                }

                return {
                    ...node,
                    data: { ...node.data, suggestionAcceptable: false, suggestionType: "none" },
                };
            });

            // If a connection suggestion was accepted, remove other connection suggestions
            const filteredNodes = updatedNodes.filter((node: Node) =>
                !(node.data.suggestionType == "connection" && acceptedConnectionSuggestion)
            );

            // Collect remaining suggestion node IDs
            const remainingSuggestionIds = new Set(
                filteredNodes
                    .filter((n: Node) => n.data.suggestionType != "none" && n.data.suggestionType != undefined)
                    .map((n: Node) => n.id)
            );

            setEdges((prevEdges: Edge[]) =>
                prevEdges
                    .filter((edge: Edge) =>
                        !(acceptedConnectionSuggestion && edge.data?.suggestionType == "connection") ||
                        edge.source == acceptedConnectionSuggestionId ||
                        edge.target == acceptedConnectionSuggestionId
                    )
                    .map((edge: Edge) => {
                        if (!remainingSuggestionIds.has(edge.source) && !remainingSuggestionIds.has(edge.target)) {
                            return { ...edge, data: { ...edge.data, suggestionType: "none" } };
                        }
                        return edge;
                    })
            );

            return filteredNodes;
        });
    }, [setNodes, setEdges, workflowNameRef]);

    // If keywordIndex is undefined all components are unflagged
    const flagBasedOnKeyword = (keywordIndex?: number) => {
        console.log("flagBasedOnKeyword");
        const isHighlighted = (keywords: any) =>
            keywords !== undefined && keywordIndex !== undefined && keywords.includes(keywordIndex);

        setNodes((prevNodes: Node[]) =>
            prevNodes.map((node: Node) => ({
                ...node,
                data: { ...node.data, keywordHighlighted: isHighlighted(node.data.keywords) },
            }))
        );

        setEdges((prevEdges: Edge[]) =>
            prevEdges.map((edge: Edge) => ({
                ...edge,
                data: { ...edge.data, keywordHighlighted: isHighlighted(edge.data?.keywords) },
            }))
        );
    }

    // Erase all nodes and edges that are workflow suggestions
    const eraseWorkflowSuggestions = () => {
        console.log("eraseWorkflowSuggestions");
        setEdges((prevEdges: Edge[]) =>
            prevEdges.filter((edge: Edge) => edge.data?.suggestionType != "workflow")
        );

        setNodes((prevNodes: Node[]) =>
            prevNodes
                .filter((node: Node) => node.data.suggestionType != "workflow")
                .map((node: Node) => ({
                    ...node,
                    data: { ...node.data, suggestionAcceptable: false },
                }))
        );

        setSuggestionsLeft(0);
    }

    // ---------------------------------------------------------------------------
    // Project Operations
    // ---------------------------------------------------------------------------

    /**
     * Normalize the heterogeneous ``IOutput.output`` shape into the backend's
     * ``OutputRef`` contract.
     *
     * Different node types populate ``o.output`` differently: code / widget
     * nodes forward the sandbox response object ``{ path, dataType, ... }``
     * verbatim, while other paths store a bare filename string. The backend
     * (see ``app/common/safe_paths.validate_component``) now strictly rejects
     * anything that isn't a single safe string segment, so we coerce here at
     * the serialization boundary and drop refs we can't normalize.
     */
    const buildOutputRefs = (): OutputRef[] => {
        // Honor the per-node "Save output dataset" toggle (defaults to
        // CURIO_DEFAULT_SAVE_NODE_OUTPUT): only saving-enabled nodes persist
        // their output as a computed dataset. Shared with the catalog's live
        // discovery via ``buildSaveableLiveOutputs`` so the save-time and
        // listing-time filters can never drift apart.
        const refs =
            buildSaveableLiveOutputs(
                deps.outputsRef.current,
                reactFlow.getNodes(),
                defaultSaveOutputDataset,
                // Whatever feeds a pinned tile, and a scenario's context and
                // outcomes (#662), are recorded too, whatever their toggle says:
                // the ref is what lets a reload hand that tile its data instead
                // of an empty box, and another project read the scenario's.
                savedSourceNodeIds(
                    reactFlow.getNodes() as any, reactFlow.getEdges() as any, scenariosRef.current,
                ),
            ) ?? [];
        // Attach each producing node's friendly display label so the save-time
        // installer (``_auto_install_computed_outputs``) titles computed datasets
        // by their node — matching execution-time auto-install — instead of the
        // raw generated filename. Non-CodeEditor nodes (grammar, data pool, …)
        // are persisted only via this save path, so without this they kept the
        // filename title even after a "Play All" rerun.
        const labelByNodeId = new Map<string, string>();
        const typeByNodeId = new Map<string, string>();
        for (const node of reactFlow.getNodes()) {
            // Key by both ids: outputs reference node.id or node.data.nodeId
            // depending on the node type (matches buildSaveableLiveOutputs).
            const ids: string[] = [];
            if (typeof node.id === "string") ids.push(node.id);
            const dataNodeId = (node.data as { nodeId?: unknown })?.nodeId;
            if (typeof dataNodeId === "string") ids.push(dataNodeId);

            const label = resolveNodeDisplayLabel(node.data).trim();
            // The node's type slug feeds the computed dataset's producer lineage.
            const nodeType = (
                (node.data as { nodeType?: unknown })?.nodeType ?? node.type ?? ""
            );
            const typeStr = typeof nodeType === "string" ? nodeType.trim() : "";
            for (const id of ids) {
                if (label) labelByNodeId.set(id, label);
                if (typeStr) typeByNodeId.set(id, typeStr);
            }
        }
        return refs.map((ref) => {
            const label = labelByNodeId.get(ref.node_id);
            const nodeType = typeByNodeId.get(ref.node_id);
            return {
                ...ref,
                ...(label ? { node_name: label } : {}),
                ...(nodeType ? { node_type: nodeType } : {}),
            };
        });
    };

    const syncDatasetsFromSavedSpec = useCallback(
        (spec: Record<string, unknown> | null | undefined) => {
            const datasets = (spec as { dataflow?: { datasets?: unknown[] } } | undefined)?.dataflow
                ?.datasets;
            if (Array.isArray(datasets)) {
                setDataflowDatasets(datasets);
            }
            notifyDatasetCatalogRefresh();
        },
        [setDataflowDatasets],
    );

    // The dataflow's name is stored twice: in ``spec.dataflow.name``, which the
    // canvas title renders, and in the project row's ``name``, which the Projects
    // list renders. #230: the canvas rename wrote only ``workflowName`` (the spec
    // side), while a save sent ``projectName`` - so the save faithfully re-sent
    // the name the dataflow was loaded under and the Projects card never moved.
    // One entry point keeps both in step.
    //
    // Deliberately NOT solved by flipping the ``||`` precedence below:
    // ``loadParsedTrill`` also calls ``setWorkflowName``, so preferring the canvas
    // name there would make File -> Load into an open project silently rename it.
    //
    /** The project row's name, sent alone, as the Projects page's rename sends it. */
    const sendRowName = useCallback((id: string, name: string) => {
        projectsApi.update(id, { name }).then(
            (detail) => setServerCategories(detail?.categories ?? {}),
            (err) => showToast((err as Error)?.message || "Could not rename the dataflow.", "error"),
        );
    }, [showToast]);

    // Returns false for a blank entry so the caller can restore the old title.
    const renameDataflow = useCallback((rawName: string): boolean => {
        const next = rawName.trim();
        if (!next) return false;
        setWorkflowName(next);
        projectNameRef.current = next;
        setProjectName(next);
        // A rename is an edit like any other: Unsaved on a canvas bound to no
        // doc, and kept by the doc on a bound one.
        markDirty();
        // The doc holds the dataflow's name (a canvas not bound yet writes it
        // with the bind), and the project row the one the Projects page lists,
        // which no doc writes: the owner's rename sends it there too, as the
        // Projects page's rename does. A rename while the create is out goes
        // there once the create has made the row (createDataflow). An invited
        // editor's tab, bound to the owner's dataflow, renames it through the
        // editors' route.
        const id = projectIdRef.current;
        if (id && viewerMode === "owner") {
            sendRowName(id, next);
        } else if (viewerMode === "shared" && deps.docBridgeRef?.current?.bound()) {
            const shared = getCurrentProjectId();
            if (shared) {
                projectsApi.renameShared(shared, next).catch(
                    (err) => showToast((err as Error)?.message || "Could not rename the dataflow.", "error"),
                );
            }
        }
        return true;
    }, [setWorkflowName, markDirty, viewerMode, sendRowName, showToast]);

    /**
     * A route load that has not delivered an id yet, or ``null`` when there is
     * nothing to wait for.
     *
     * ``null`` rather than a resolved promise, and checked rather than awaited,
     * because the common cases are both "nothing to wait for" -- a dataflow
     * that has loaded, and one that genuinely has no id because it has never
     * been saved (``/dataflow/new`` leaves the store's project id undefined,
     * which is what tells the two apart). Awaiting a resolved promise still
     * costs a microtask, and the create would no longer leave in the tick its
     * caller ran in: two callers in one tick share one create only because
     * the first one's is already out.
     *
     * The promise rejects rather than letting the caller create when the load
     * settles without an id: a 404 that fell through to the shared endpoint, a
     * load that overran {@link PROJECT_LOAD_WAIT_MS}, a failure ProjectLoader
     * has already toasted. Creating there is what duplicated the dataflow.
     */
    const settleRoutedLoad = useCallback((): Promise<void> | null => {
        if (projectIdRef.current) return null;
        if (!getCurrentProjectId()) return null;
        return (async () => {
            await whenProjectSettled();
            if (projectIdRef.current) return;
            throw new Error(
                "This dataflow is still opening. Wait for it to finish loading, then try again.",
            );
        })();
    }, []);

    /**
     * Make the dataflow of a canvas never saved, from what the canvas holds:
     * the server's first transaction builds its doc (`dataflow_docs.create`),
     * which the canvas then binds to (`useDataflowDoc`). What the canvas
     * changed after this left goes in with the bind, so the canvas as it was
     * sent is noted with the load. The history this canvas recorded, bound to
     * no doc, goes with it, and the server imports it.
     *
     * One at a time: a caller while one is out gets that one, so two callers
     * never make two dataflows.
     */
    const createInFlightRef = useRef<Promise<ProjectDetail> | null>(null);
    const createDataflow = useCallback((): Promise<ProjectDetail> => {
        if (createInFlightRef.current) return createInFlightRef.current;
        const create = (async () => {
            const currentNodes = reactFlow.getNodes();
            const currentEdges = reactFlow.getEdges();
            // Read packages directly from the store (always up-to-date) rather
            // than from the React state snapshot, which may lag behind the store
            // when a package install/uninstall updates the store before React
            // re-renders. The datasets section seeds the new project's refs (dev/81).
            const currentPackages = getCurrentProjectPackagesList();
            const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, workflowGoalRef.current, currentPackages, workflowDescriptionRef.current, dataflowDatasetsRef.current, workflowCategoriesRef.current, scenariosRef.current, autoRunRef.current);
            spec.nodeProvenance = getAllNodeProvenance();
            spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();
            // The canvas as its doc would hold it, taken with the spec.
            const sent = deps.docBridgeRef?.current?.canvasNow();
            // The ref, not the closure (#270): see projectNameRef.
            const name = projectNameRef.current || workflowNameRef.current;
            // Anything changed from here on is not in the request, and stays
            // Unsaved until the bind writes it (#270).
            const dirtyAtSend = dirtyGenerationRef.current;
            const detail = await projectsApi.create({
                name,
                spec,
                // A create always sends them: there is no stored manifest to keep.
                outputs: buildOutputRefs(),
            });
            // Pin the ref synchronously so an action right after this one
            // finds the new id (setProjectId only reaches the ref on the next
            // render).
            projectIdRef.current = detail.id;
            // The server built the dataflow's doc from what it stored.
            noteLoadedDataflow(detail?.spec?.dataflow ?? spec.dataflow, detail.id, sent);
            syncDatasetsFromSavedSpec(detail.spec);
            setServerCategories(detail.categories ?? {});
            setProjectId(detail.id);
            if (projectNameRef.current === name) {
                projectNameRef.current = detail.name;
                setProjectName(detail.name);
            } else if (projectNameRef.current) {
                // Renamed while the create was out: the row the create made
                // has the name it sent, and the doc takes the new one with the
                // bind.
                sendRowName(detail.id, projectNameRef.current);
            }
            setProjectSavedAt(new Date());
            if (dirtyGenerationRef.current === dirtyAtSend) {
                setProjectDirty(false);
            }
            // The backend merges the user's defaults (e.g. ``curio.builtin@1``)
            // into the spec's lockfile on first save. We need to:
            //  1. Pin the store's `projectId` to the freshly-created id —
            //     ProjectLoader's ``clearCurrentProject`` ran on `/dataflow/new`
            //     and left it ``undefined``, so the palette filter (which keys
            //     off this) would otherwise stay in "no project" mode.
            //  2. Sync the seeded packages so the drawer immediately treats
            //     ``curio.builtin@1`` (and anything else in defaults) as
            //     installed in the new project — without this the user sees
            //     "Install" buttons for packages they "just got".
            const dataflowSpec = detail?.spec?.dataflow as
                | { packages?: string[] }
                | undefined;
            const seededPackages = dataflowSpec?.packages;
            setCurrentProject(detail.id, Array.isArray(seededPackages) ? seededPackages : []);
            return detail;
        })();
        createInFlightRef.current = create;
        const done = () => {
            if (createInFlightRef.current === create) createInFlightRef.current = null;
        };
        create.then(done, done);
        return create;
    }, [reactFlow, workflowNameRef, deps.outputsRef, defaultSaveOutputDataset, syncDatasetsFromSavedSpec, noteLoadedDataflow, getAllNodeProvenance, sendRowName]);

    /**
     * The dataflow's id, for an action on the server's copy of it (a dataset
     * or package added, an agent attached, a scenario dropped, a run), once
     * the server holds every change this tab made. A dataflow not saved yet is
     * made first, as its first save would make it, and a routed one still
     * loading is waited for (#340). Concurrent callers share one create.
     * Null when there is none to act on, with the reason said but for a
     * hosted guest's, whose action tells it to sign in.
     */
    const ensureProjectId = useCallback(async (): Promise<string | null> => {
        const kept = async () => {
            // A saved dataflow's canvas that changed before it bound holds
            // changes the server has only once the bind writes them: wait for
            // it, for as long as File > Save does. A hosted guest's canvas of
            // an example never binds (its room refuses it), and a shared view
            // acts on no dataflow of its own, so neither waits.
            const mayBind = !blockGuestSaves && viewerMode !== "shared";
            if (mayBind && projectDirtyRef.current && !deps.docBridgeRef?.current?.bound()) {
                await deps.docBridgeRef?.current?.whenBound();
            }
            // The bridge of the render after the bind.
            await deps.docBridgeRef?.current?.whenKept();
            return projectIdRef.current;
        };
        if (projectIdRef.current) return kept();
        // A hosted guest's saves are refused, so a dataflow it never saved
        // gets no id, and no toast from here: the action that asked tells it
        // to sign in (hostedGuestSignInNote). Only a save the guest asks for
        // (File > Save, Save a copy) answers "Guest users cannot save projects".
        if (blockGuestSaves) return null;
        try {
            if (viewerMode === "shared") {
                throw new Error("Shared dataflows are read-only; use Save a copy");
            }
            const routedLoad = settleRoutedLoad();
            if (routedLoad) await routedLoad;
            if (projectIdRef.current) return kept();
            return (await createDataflow()).id;
        } catch (err) {
            showToast(
                (err as Error)?.message || "Save the dataflow before adding datasets.",
                "error",
            );
            return null;
        }
    }, [blockGuestSaves, viewerMode, settleRoutedLoad, createDataflow, showToast]);

    // Map a record's install-warnings onto friendly node labels and warn the user.
    // Without this, a computed output that failed to install (e.g. its artifact
    // was missing when it was recorded) was swallowed server-side and the dataset just
    // never appeared — the "Play All didn't generate all datasets" symptom.
    //
    // ``scopeNodeIds`` is the set of nodes THIS install-sync covered
    // (runInstallSyncNow in providers/flow/useInstallSave.ts passes
    // installSyncPendingIdsRef's contents).
    // It is load-bearing: buildOutputRefs rebuilds refs for EVERY toggle-enabled
    // node on every record, and ProjectLoader repopulates outputsRef from
    // the saved refs on load, so a record triggered by node C used to toast
    // `Dataset for "A" couldn't be generated` about a node the user never
    // touched, for a stale artifact from a previous sandbox session (#180).
    // ``undefined`` means unscoped (surface everything), which keeps every
    // caller that has no id set to offer on the old behavior.
    const surfaceInstallWarnings = useCallback(
        (
            detail: { dataset_install_warnings?: DatasetInstallWarning[] } | undefined,
            scopeNodeIds?: readonly string[],
        ) => {
            const all = detail?.dataset_install_warnings;
            if (!all || all.length === 0) return;
            const scope = scopeNodeIds ? new Set(scopeNodeIds) : null;
            const warnings = scope ? all.filter((w) => scope.has(w.node_id)) : all;
            const outOfScope = scope ? all.filter((w) => !scope.has(w.node_id)) : [];
            // Filtered out, not discarded: these are real backend warnings, just
            // not about anything this run touched. One formatted STRING (not an
            // object argument) so the message survives console capture verbatim.
            if (outOfScope.length > 0) {
                console.warn(
                    `[curio] ${outOfScope.length} dataset install warning(s) for ` +
                        `nodes outside this install-sync (not toasted): ` +
                        outOfScope
                            .map((w) => `${w.node_id} (${w.filename}): ${w.reason}`)
                            .join("; "),
                );
            }
            if (warnings.length === 0) return;
            const labelByNodeId = new Map<string, string>();
            for (const node of reactFlow.getNodes()) {
                const label = resolveNodeDisplayLabel(node.data).trim();
                if (!label) continue;
                if (typeof node.id === "string") labelByNodeId.set(node.id, label);
                const dataNodeId = (node.data as { nodeId?: unknown })?.nodeId;
                if (typeof dataNodeId === "string") labelByNodeId.set(dataNodeId, label);
            }
            const names = warnings.map((w) => labelByNodeId.get(w.node_id) || w.node_id);
            const list = names.join(", ");
            showToast(
                warnings.length === 1
                    ? `Dataset for "${list}" couldn't be generated. Re-run that node.`
                    : `${warnings.length} datasets couldn't be generated (${list}). Re-run those nodes.`,
                "warning",
            );
        },
        [reactFlow, showToast],
    );

    /**
     * Record the outputs the canvas holds that the dataflow records, after a
     * run, a pin or a scenario: each as a computed dataset in the Data
     * Catalog, and in the dataflow's saved outputs a reload and its dashboard
     * show (`POST /api/projects/<id>/outputs`). No tab saves the dataflow,
     * which its doc keeps. Only the owner's tab records them; a dataflow not
     * saved yet is made first, as its first save would make it.
     *
     * ``nodeIds`` scopes the warning toast to the producers this record was
     * made for; omit it to surface every warning the answer carries (see
     * surfaceInstallWarnings). Returns which producers did NOT get their
     * dataset, so the caller can decide what to do with their "Adding…"
     * placeholders (#352).
     */
    const recordOutputs = useCallback(
        async (nodeIds?: readonly string[]): Promise<InstallSyncOutcome> => {
            // Nothing this record covered was installed.
            const none = (): InstallSyncOutcome => ({ saved: false, failedNodeIds: [...(nodeIds ?? [])] });
            if (viewerMode === "shared" || blockGuestSaves) return none();
            const id = await ensureProjectId();
            if (!id) {
                notifyDatasetCatalogRefresh();
                return none();
            }
            try {
                const detail = await projectsApi.recordOutputs(id, buildOutputRefs());
                surfaceInstallWarnings(detail, nodeIds);
                const scope = nodeIds ? new Set(nodeIds) : null;
                const failed = ((detail?.dataset_install_warnings ?? []) as DatasetInstallWarning[])
                    .map((w: DatasetInstallWarning) => w.node_id)
                    .filter((nodeId: string) => !scope || scope.has(nodeId));
                notifyDatasetCatalogRefresh();
                return { saved: true, failedNodeIds: failed };
            } catch (err) {
                showToast((err as Error)?.message || "Could not save the outputs.", "error");
                notifyDatasetCatalogRefresh();
                return none();
            }
        },
        [viewerMode, blockGuestSaves, ensureProjectId, showToast, surfaceInstallWarnings, defaultSaveOutputDataset],
    );

    /**
     * File > Save. A dataflow not saved yet is made (`createDataflow`). A
     * saved one's doc holds every change already: what a run left waiting to
     * be recorded is recorded, and once the server has every change this tab
     * made, the dataflow's history gets a version named Saved.
     */
    const saveDataflow = useCallback(async (): Promise<{ id: string; created: boolean }> => {
        if (viewerMode === "shared") {
            throw new Error("Shared dataflows are read-only; use Save a copy");
        }
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        // A routed dataflow is never unsaved; at most it has not loaded YET
        // (#340): saving in that window must not make a second dataflow.
        const routedLoad = settleRoutedLoad();
        if (routedLoad) await routedLoad;
        if (!projectIdRef.current) {
            const detail = await createDataflow();
            return { id: detail.id, created: true };
        }
        const id = projectIdRef.current;
        // Every output the canvas holds that the dataflow records, as a save
        // sent them: what a run left waiting, and what ran before its Save was
        // on or failed to be recorded then.
        await deps.flushOutputsRef?.current?.();
        await recordOutputs();
        // The bridge of the render after the bind: one read before it holds no doc.
        if (!(await deps.docBridgeRef?.current?.whenBound())) throw new Error(SAVE_OFFLINE_MESSAGE);
        if (!(await deps.docBridgeRef?.current?.whenKept())) throw new Error(SAVE_OFFLINE_MESSAGE);
        const saved = await noteSaved();
        if (saved?.categories) setServerCategories(saved.categories);
        setProjectSavedAt(new Date());
        return { id, created: false };
    }, [viewerMode, blockGuestSaves, settleRoutedLoad, createDataflow, recordOutputs]);

    // ── In-flight install placeholders ────────────────────────────────────────
    // Upper bound on how long a placeholder can linger if its clear never fires
    // (crashed/aborted run). Matches the backend's timeout for one node run.
    const PENDING_INSTALL_TIMEOUT_MS = 600_000;
    // How long a FAILED placeholder stays on screen before it is dropped. Long
    // enough to be noticed beside its toast, short enough not to look like a row.
    const FAILED_INSTALL_VISIBLE_MS = 30_000;

    const endPendingInstall = useCallback((key: string): void => {
        const timer = pendingInstallTimersRef.current[key];
        if (timer !== undefined) {
            clearTimeout(timer);
            delete pendingInstallTimersRef.current[key];
        }
        if (!pendingInstallsRef.current.some((p) => p.key === key)) return;
        setPendingInstalls((prev) => prev.filter((p) => p.key !== key));
    }, []);

    // Mark a dataset install as started so both surfaces can render an
    // "Installing…" placeholder. Idempotent per key: a re-run for the same node
    // replaces the entry and restarts its safety timer (no duplicate placeholder).
    const beginPendingInstall = useCallback(
        (entry: Omit<PendingInstall, "startedAt">): void => {
            const existing = pendingInstallTimersRef.current[entry.key];
            if (existing !== undefined) clearTimeout(existing);
            pendingInstallTimersRef.current[entry.key] = setTimeout(
                () => endPendingInstall(entry.key),
                PENDING_INSTALL_TIMEOUT_MS,
            );
            const next: PendingInstall = { ...entry, startedAt: Date.now() };
            setPendingInstalls((prev) => [...prev.filter((p) => p.key !== entry.key), next]);
        },
        [endPendingInstall],
    );

    // Mark a placeholder as failed rather than clearing it (#352). The toast
    // from surfaceInstallWarnings says what to do; the placeholder stays put
    // long enough to be seen next to the row that never appeared, instead of
    // flashing and vanishing the way #217 described.
    //
    // Still on a timer, a much shorter one: a failed placeholder is a notice,
    // not a permanent row, and the user re-running the node replaces it via
    // beginPendingInstall anyway.
    const failPendingInstall = useCallback((key: string): void => {
        const existing = pendingInstallTimersRef.current[key];
        if (existing !== undefined) clearTimeout(existing);
        if (!pendingInstallsRef.current.some((p) => p.key === key)) return;
        pendingInstallTimersRef.current[key] = setTimeout(
            () => endPendingInstall(key),
            FAILED_INSTALL_VISIBLE_MS,
        );
        setPendingInstalls((prev) =>
            prev.map((p) => (p.key === key ? { ...p, status: "failed" as const } : p)),
        );
    }, [endPendingInstall]);

    // Drop every placeholder + timer when the dataflow is swapped/discarded so a
    // pending install from the previous project can't leak into the next one.
    useEffect(() => {
        return () => {
            Object.values(pendingInstallTimersRef.current).forEach(clearTimeout);
            pendingInstallTimersRef.current = {};
        };
    }, []);

    /**
     * The dashboard's Save layout: where each pinned tile sits and how large
     * it is, which the server writes into the dataflow's doc, and nothing else
     * the page holds: never a value a viewer tried there (#1117).
     */
    const saveDashboardLayout = useCallback(async (): Promise<void> => {
        const id = projectIdRef.current;
        if (!id) throw new Error("Only the dataflow's owner saves its dashboard's layout.");
        const tiles: Record<string, TileLayout> = {};
        for (const node of reactFlow.getNodes()) {
            const data = node.data ?? {};
            if (!data.dashboardPinned) continue;
            const tile: TileLayout = {};
            if (typeof data.dashboardX === "number" && typeof data.dashboardY === "number") {
                tile.dashboardX = data.dashboardX;
                tile.dashboardY = data.dashboardY;
            }
            if (typeof data.dashboardWidth === "number" && typeof data.dashboardHeight === "number") {
                tile.dashboardWidth = data.dashboardWidth;
                tile.dashboardHeight = data.dashboardHeight;
            }
            if (Object.keys(tile).length > 0) tiles[node.id] = tile;
        }
        const dirtyAtSend = dirtyGenerationRef.current;
        await projectsApi.saveLayout(id, tiles);
        setProjectSavedAt(new Date());
        if (dirtyGenerationRef.current === dirtyAtSend) setProjectDirty(false);
    }, [reactFlow]);

    // ``copyOf``: the dataflow the copy is made from, whose saved outputs the
    // copy gets for each node still showing one.
    const saveAsNewProject = useCallback(async (name: string, copyOf?: string | null) => {
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        // Same as createDataflow: read from store to avoid stale React state snapshot.
        const currentPackages = getCurrentProjectPackagesList();
        // Save-a-copy is a CREATE: the serialized datasets section seeds the new
        // project's refs (dev/81) — read from the ref so the copy carries the
        // latest installed datasets.
        // A copy of a dataflow the canvas is bound to gets its history from
        // the server, when you may read it; a canvas bound to none carries
        // its own.
        const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, workflowGoalRef.current, currentPackages, workflowDescriptionRef.current, dataflowDatasetsRef.current, workflowCategoriesRef.current, scenariosRef.current, autoRunRef.current);
        spec.nodeProvenance = getAllNodeProvenance();
        spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();
        // The canvas as the copy's doc would hold it, taken with the spec.
        const sent = deps.docBridgeRef?.current?.canvasNow();

        const outputRefs: OutputRef[] = buildOutputRefs();

        const detail = await projectsApi.create({
            name,
            spec,
            outputs: outputRefs,
            ...(copyOf ? { copy_of: copyOf } : {}),
        });
        syncDatasetsFromSavedSpec(detail.spec);
        setServerCategories(detail.categories ?? {});
        projectIdRef.current = detail.id;
        // The canvas is the copy's now, whose doc the server builds from it:
        // what the canvas changed after this left goes in with the bind.
        noteLoadedDataflow(detail?.spec?.dataflow ?? spec.dataflow, detail.id, sent);
        setProjectId(detail.id);
        setProjectName(detail.name);
        setProjectSavedAt(new Date());
        setProjectDirty(false);
        setViewerMode("owner");
        // Re-pin the package store to the copy, as createDataflow does. Without it the store still names the ORIGINAL dataflow,
        // so the copy's palette and every lockfile write from it would be
        // filtered by, and applied to, the dataflow it was copied from.
        const copiedPackages = (detail?.spec?.dataflow as { packages?: string[] } | undefined)
            ?.packages;
        setCurrentProject(detail.id, Array.isArray(copiedPackages) ? copiedPackages : []);
        return detail;
    }, [workflowNameRef, reactFlow, deps.outputsRef, blockGuestSaves, syncDatasetsFromSavedSpec, defaultSaveOutputDataset]);

    const loadProject = useCallback(async (id: string, options?: { lastResults?: boolean }) => {
        const result = await projectsApi.get(id, options);
        const { project, outputs } = result;

        // Pin the ref here rather than letting the next render carry it over,
        // for the same reason createDataflow does: ``settleRoutedLoad`` reads
        // it the moment ProjectLoader releases the latch, which is sooner than
        // React is obliged to re-render.
        projectIdRef.current = project.id;
        setProjectId(project.id);
        setProjectName(project.name);
        setProjectDirty(false);
        setProjectSavedAt(project.updated_at ? new Date(project.updated_at) : null);
        setViewerMode("owner");
        setServerCategories(project.categories ?? {});

        const execStatus: Record<string, "stale" | "executed"> = {};
        for (const o of outputs) {
            execStatus[o.node_id] = "executed";
        }
        setNodeExecStatus(execStatus);

        return result;
    }, []);

    const loadSharedProject = useCallback(async (id: string) => {
        const result = await projectsApi.getShared(id);
        const { project, outputs } = result;

        // Deliberately leave projectId=null: this dataflow is not "open for
        // editing" in the visitor's workspace. Save-a-copy goes through
        // saveAsNewProject, which creates a fresh project owned by them.
        // Pinned on the ref too, so a save racing this load is refused for
        // being read-only rather than waiting out the latch first.
        projectIdRef.current = null;
        setProjectId(null);
        setProjectName(project.name);
        setProjectDirty(false);
        setProjectSavedAt(null);
        setViewerMode("shared");
        setServerCategories(project.categories ?? {});

        const execStatus: Record<string, "stale" | "executed"> = {};
        for (const o of outputs) {
            execStatus[o.node_id] = "executed";
        }
        setNodeExecStatus(execStatus);

        return result;
    }, []);

    const discardProject = useCallback(() => {
        // The canvas leaves the dataflow, and its doc, before anything clears it.
        noteLoadedDataflow(null, null);
        setProjectId(null);
        setProjectName("");
        setWorkflowName(DEFAULT_WORKFLOW_NAME);
        // The goal and the description too (#428): only loadParsedTrill sets
        // them, and File > New does not go through it, so the next dataflow's
        // first save sent the previous one's. The ref is written here as well,
        // the way the name and description setters write theirs, so a save
        // that runs before the next render reads the cleared goal.
        workflowGoalRef.current = "";
        setWorkflowGoal("");
        setWorkflowDescription("");
        setServerCategories({});
        setWorkflowCategories({});
        setScenariosQuietly([]);
        setAutoRunQuietly(false);
        setProjectDirty(false);
        setProjectSavedAt(null);
        setNodeExecStatus({});
        setDataflowDatasets([]);
        setViewerMode("owner");
    }, [setWorkflowName, setWorkflowDescription, setAutoRunQuietly, noteLoadedDataflow]);

    // Both marks return the SAME state object when the node is already in the
    // target status. CodeEditor calls markNodeStale on every keystroke, and an
    // unconditional spread changed the FlowContext value each time — re-rendering
    // every context consumer on the canvas per keystroke (dev/70).
    const markNodeExecuted = useCallback((nodeId: string) => {
        setNodeExecStatus((prev) =>
            prev[nodeId] === "executed" ? prev : { ...prev, [nodeId]: "executed" },
        );
    }, []);

    const markNodeStale = useCallback((nodeId: string) => {
        setNodeExecStatus((prev) =>
            prev[nodeId] === "stale" ? prev : { ...prev, [nodeId]: "stale" },
        );
    }, []);

    // A node that ran and failed (#347). Previously indistinguishable from one
    // that was never run: the failure branch produces no artifact, so it never
    // calls outputCallback, so nothing downstream changed at all - and the
    // downstream node told the user to run the node they had just watched fail.
    // Same no-op-when-unchanged shape as the two above (dev/70).
    const markNodeErrored = useCallback((nodeId: string) => {
        setNodeExecStatus((prev) =>
            prev[nodeId] === "errored" ? prev : { ...prev, [nodeId]: "errored" },
        );
    }, []);

    // ---------------------------------------------------------------------------
    // Public API
    // ---------------------------------------------------------------------------

    return {
        // State
        allMinimized,
        setAllMinimized,
        expandStatus,
        setExpandStatus,
        suggestionsLeft,
        workflowGoal,
        setWorkflowGoal,
        workflowGoalRef,
        workflowCategories,
        workflowCategoriesRef,
        serverCategories,
        scenarios,
        // For the run's save rule, which must read the list as it is now.
        scenariosRef,
        autoRun,
        autoRunRef,
        setAutoRun,
        // The canvas's binding to the dataflow's doc (useDataflowDoc).
        loadedDataflowRef,
        noteLoadedDataflow,
        takeDataflowFields,
        quietly,
        packages,
        setPackages,
        addPackage,
        removePackage,
        dataflowDatasets,
        setDataflowDatasets,
        pendingInstalls,
        beginPendingInstall,
        endPendingInstall,
        failPendingInstall,

        // Project state
        projectId,
        projectName,
        projectDirty,
        projectSavedAt,
        nodeExecStatus,
        viewerMode,

        // Operations
        updateDataNode,
        loadParsedTrill,
        updateDefaultCode,
        updateKeywords,
        updateSubtasks,
        updateWarnings,
        cleanCanvas,
        flagBasedOnKeyword,
        acceptSuggestion,
        eraseWorkflowSuggestions,
        applyRemoveChanges,
        applyReviewedRemovals,

        // Project operations
        renameDataflow,
        updateDataflowCategories,
        setScenarios,
        saveDataflow,
        saveDashboardLayout,
        saveAsNewProject,
        ensureProjectId,
        recordOutputs,
        surfaceInstallWarnings,
        loadProject,
        loadSharedProject,
        discardProject,
        markDirty,
        noteBound,
        markNodeExecuted,
        markNodeStale,
        markNodeErrored,
    };
}
