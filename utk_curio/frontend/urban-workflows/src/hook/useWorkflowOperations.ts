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
import { useToastContext } from "../providers/ToastProvider";
import { useUserContext } from "../providers/UserProvider";
import { updateNodeData, updateNodesByMap, updateEdgesByMap, extractNodeFieldMap, extractKeywordMaps } from "../utils/flowNodeUtils";
import { fitViewWithMenuOffset } from "../utils/fitViewWithMenuOffset";
import { TrillGenerator } from "../TrillGenerator";
import { projectsApi, OutputRef, DatasetInstallWarning } from "../api/projectsApi";
import { buildSaveableLiveOutputs } from "../utils/saveOutputDataset";
import { notifyAgentDockRefresh } from "../utils/agentsPaletteEvents";
import { resolveNodeDisplayLabel } from "../utils/palettePackageFactoryDraft";
import {
    notifyDatasetCatalogRefresh,
    buildInstalledDatasetRef,
    upsertDataflowDatasetRef,
    type InstalledDatasetPayload,
} from "../services/datasetCatalog/datasetCatalogApi";
import type { PendingInstall } from "../services/datasetCatalog/datasetCatalogTypes";
import {
    getCurrentProjectPackagesList,
    setCurrentProject,
    setCurrentProjectPackages,
    subscribe as subscribeProjectPackages,
} from "../registry/projectPackagesStore";

export interface WorkflowOperationsDeps {
    nodes: Node[];
    edges: Edge[];
    setNodes: any;
    setEdges: any;
    setOutputs: any;
    outputsRef: React.MutableRefObject<Array<{ nodeId: string; output: string }>>;
    setInteractions: any;
    setDashboardPins: (value: any) => void;
    setPositionsInDashboard: (data: any) => void;
    setPositionsInWorkflow: (data: any) => void;
    setWorkflowName: (name: string) => void;
    workflowNameRef: React.MutableRefObject<string>;
    setWorkflowDescription: (description: string) => void;
    workflowDescriptionRef: React.MutableRefObject<string>;
    onEdgesDelete: (connections: Edge[]) => void;
    onNodesDelete: (changes: NodeChange[]) => void;
    onNodesChange: (changes: NodeChange[]) => void;
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean, skipValidation?: boolean) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
    // Workflow-wide default for the per-node "Save output dataset" toggle,
    // sourced from the backend (CURIO_DEFAULT_SAVE_NODE_OUTPUT) via FlowProvider.
    defaultSaveOutputDataset: boolean;
}

export function useWorkflowOperations(deps: WorkflowOperationsDeps) {
    const {
        nodes, edges,
        setNodes, setEdges,
        setOutputs, setInteractions,
        setDashboardPins, setPositionsInDashboard, setPositionsInWorkflow,
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
    const blockGuestSaves = enableUserAuth && !!user?.is_guest;

    // fitViewOnLoad is internal to workflow loading
    const [fitViewOnLoad, setFitViewOnLoad] = useState(false);

    // Workflow-level state (not used by FlowProvider's core flow logic)
    const [allMinimized, setAllMinimized] = useState<number>(0);
    const [expandStatus, setExpandStatus] = useState<'expanded' | 'minimized'>('expanded');
    const [suggestionsLeft, setSuggestionsLeft] = useState<number>(0); // Number of suggestions left
    const [workflowGoal, setWorkflowGoal] = useState("");
    // ``packages`` is the current project's lockfile (``spec.dataflow.packages``).
    // The authoritative copy lives in ``projectPackagesStore`` so non-React
    // code (palette filter, registry bootstrap) can read it without context.
    // This component subscribes so save callers see fresh state.
    const [packages, setPackagesState] = useState<string[]>(getCurrentProjectPackagesList());
    const [dataflowDatasets, setDataflowDatasets] = useState<any[]>([]);
    // Keep a ref that's always in sync so saveCurrentProject never reads a
    // stale closure value (important: set during render, not in a useEffect,
    // so it's always the value from the most recent completed render).
    const dataflowDatasetsRef = useRef<any[]>([]);
    dataflowDatasetsRef.current = dataflowDatasets;
    // In-flight dataset installs, surfaced as "Installing…" placeholders in the
    // palette + drawer. Volatile/session-only — never serialized into the spec.
    // Mirrored in a ref so begin/clear from async callbacks never read a stale
    // closure, and a per-key timeout map backstops crashed/aborted installs.
    const [pendingInstalls, setPendingInstalls] = useState<PendingInstall[]>([]);
    const pendingInstallsRef = useRef<PendingInstall[]>([]);
    pendingInstallsRef.current = pendingInstalls;
    const pendingInstallTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({});
    useEffect(() => subscribeProjectPackages(() => {
        setPackagesState(getCurrentProjectPackagesList());
    }), []);

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
    // Mirror projectId in a ref so saveCurrentProject can decide create-vs-update
    // from the *live* id, not a stale closure: after a create sets projectId, a
    // follow-up save in the same async flow (e.g. a serialized install save) would
    // otherwise still see ``null`` and POST a second project. Synced on render and
    // set explicitly the instant a create resolves (below).
    const projectIdRef = useRef<string | null>(null);
    projectIdRef.current = projectId;
    const [projectName, setProjectName] = useState<string>("");
    const [projectDirty, setProjectDirty] = useState<boolean>(false);
    const [projectSavedAt, setProjectSavedAt] = useState<Date | null>(null);
    const [nodeExecStatus, setNodeExecStatus] = useState<Record<string, "stale" | "executed">>({});
    const [viewerMode, setViewerMode] = useState<"owner" | "shared">("owner");

    const markDirty = useCallback(() => {
        setProjectDirty(true);
    }, []);

    // beforeunload guard
    useEffect(() => {
        if (!projectDirty) return;
        const handler = (e: BeforeUnloadEvent) => {
            e.preventDefault();
            e.returnValue = "";
        };
        window.addEventListener("beforeunload", handler);
        return () => window.removeEventListener("beforeunload", handler);
    }, [projectDirty]);

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

    const loadParsedTrill = async (workflowName: string, task: string, loaded_nodes: any, loaded_edges: any, provenance?: boolean, merge?: boolean, incomingPackages?: string[], incomingDescription?: string, incomingDatasets?: any[]) => {
        if (!merge) {
            TrillGenerator.reset();
            setWorkflowName(workflowName);
            setWorkflowDescription(incomingDescription || "");
            const empty_trill = TrillGenerator.generateTrill([], [], workflowName, "", [], incomingDescription || "", incomingDatasets || []);
            TrillGenerator.intializeProvenance(empty_trill);
            setPackages(incomingPackages || []);
            setDataflowDatasets(incomingDatasets || []);
            console.log("loadParsedTrill reseting nodes");
            setNodes(() => []);
        }

        if (merge) {
            // Use reactFlow to get fresh state (avoid stale closure)
            const currentNodeIds = new Set(reactFlow.getNodes().map((n: Node) => n.id));
            for (const node of loaded_nodes) {
                if (!currentNodeIds.has(node.id)) {
                    addNode(node, workflowName, provenance);
                }
            }
        } else {
            for (const node of loaded_nodes) {
                addNode(node, workflowName, provenance);
            }
        }

        if (!merge) {
            setEdges(() => []);
        }

        // Use reactFlow to get fresh edge ids (avoid stale closure)
        const currentEdgeIds = new Set(reactFlow.getEdges().map((e: Edge) => e.id));

        console.log("loadParsedTrill second");
        setNodes((prevNodes: any) => {
            // skipValidation=true: these edges come from a saved/imported trill and
            // were validated when created. Re-validating on load races the async
            // node-descriptor registry and would drop valid edges + toast mid-render.
            if (merge) {
                for (const edge of loaded_edges) {
                    if (!currentEdgeIds.has(edge.id)) {
                        onConnect(edge, prevNodes, undefined, workflowName, provenance, true);
                    }
                }
            } else {
                // Accumulate the spec edges connected so far and hand them to
                // onConnect, so merge-handle resolution sees the earlier edges
                // of this load (in_N occupancy) instead of an empty list.
                const connectedSoFar: any[] = [];
                for (const edge of loaded_edges) {
                    onConnect(edge, prevNodes, connectedSoFar, workflowName, provenance, true);
                    connectedSoFar.push(edge);
                }
            }

            if (!merge) {
                setOutputs([]);
                setInteractions([]);
                // Restore dashboard pins from persisted node data
                const pins: Record<string, boolean> = {};
                for (const node of loaded_nodes) {
                    if (node.data?.dashboardPinned) pins[node.id] = true;
                }
                setDashboardPins(pins);
                setPositionsInDashboard({});
                setPositionsInWorkflow({});
            }

            setFitViewOnLoad(true);
            return prevNodes;
        });
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
        setPositionsInDashboard({});
        setPositionsInWorkflow({});
        setSuggestionsLeft(0);
        setPackages([]);
    }

    const applyRemoveChanges = useCallback((changes: NodeRemoveChange[]) => {
        let allowedChanges: NodeRemoveChange[] = [];

        let edges = reactFlow.getEdges();

        for (const change of changes) {
            let allowed = true;

            for (const edge of edges) {
                if (
                    edge.source == change.id ||
                    edge.target == change.id
                ) {
                    showToast(
                        "Connected boxes cannot be removed. Remove the edges first by selecting it and pressing backspace.",
                        "warning"
                    );
                    allowed = false;
                    break;
                }
            }

            if (allowed) allowedChanges.push(change);
        }

        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    }, [reactFlow, showToast, onNodesDelete, onNodesChange]);

    // A reviewed plan apply (dev/62, DEC-049): the user authorized every
    // victim by name and the edge cascade arrived with them, so the manual
    // "remove the edges first" guard does not apply — the edges leave in the
    // same operation. Bookkeeping parity with manual deletion: onEdgesDelete
    // (collab broadcast, provenance, survivor-input reset) and onNodesDelete
    // (output pruning, provenance, broadcast). Already-absent elements no-op.
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

    const saveCurrentProject = useCallback(async (nameOverride?: string) => {
        if (viewerMode === "shared") {
            throw new Error("Shared dataflows are read-only; use Save a copy");
        }
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        // Read packages directly from the store (always up-to-date) rather than
        // from the React state snapshot, which may lag behind the store when a
        // package install/uninstall updates the store before React re-renders.
        const currentPackages = getCurrentProjectPackagesList();
        // Read datasets from the ref (always current) rather than the closure so
        // that a stale snapshot can never overwrite a publish/unpublish that the
        // backend already wrote to the spec.
        const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, "", currentPackages, workflowDescriptionRef.current, dataflowDatasetsRef.current);
        spec.nodeProvenance = getAllNodeProvenance();
        spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();

        const outputRefs: OutputRef[] = buildOutputRefs();

        const name = nameOverride || projectName || workflowNameRef.current;

        // Read the live id from the ref, not the closure: a save chained right
        // after a create (serialized install saves) must take the update branch.
        const existingId = projectIdRef.current;
        if (existingId) {
            const detail = await projectsApi.update(existingId, {
                spec,
                outputs: outputRefs,
                name,
            });
            syncDatasetsFromSavedSpec(detail.spec);
            // The backend prunes attachments for deleted nodes/edges (and
            // preserves the agent lockfile) on save, so reconcile the dock with
            // the freshly-persisted spec — a just-deleted node's tile disappears
            // without a reload. Mirrors the dataset-catalog refresh above.
            notifyAgentDockRefresh();
            setProjectSavedAt(new Date());
            setProjectDirty(false);
            return detail;
        } else {
            const detail = await projectsApi.create({
                name,
                spec,
                outputs: outputRefs,
            });
            // Pin the ref synchronously so a save chained immediately after this
            // create sees the new id and updates instead of creating a duplicate
            // (setProjectId only reaches the ref on the next render).
            projectIdRef.current = detail.id;
            syncDatasetsFromSavedSpec(detail.spec);
            setProjectId(detail.id);
            setProjectName(detail.name);
            setProjectSavedAt(new Date());
            setProjectDirty(false);
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
            const seededPackages: string[] | undefined = detail?.spec?.dataflow?.packages;
            setCurrentProject(detail.id, Array.isArray(seededPackages) ? seededPackages : []);
            return detail;
        }
    }, [projectId, projectName, workflowNameRef, reactFlow, deps.outputsRef, blockGuestSaves, viewerMode, syncDatasetsFromSavedSpec, defaultSaveOutputDataset]);

    // Serialize project saves so concurrent callers (e.g. two producing nodes
    // finishing back-to-back) can never run two creates in parallel and POST
    // duplicate projects. Each request runs strictly after all prior ones; once
    // the first create has set projectIdRef, every chained save takes the update
    // branch. Because saveCurrentProject reads dataflowDatasetsRef/projectIdRef
    // live (not from a closure), a save enqueued after a ref was staged persists
    // that ref even if it rode in on an already-running chain.
    const saveChainRef = useRef<Promise<any> | null>(null);
    const requestProjectSave = useCallback((): Promise<any> => {
        const prior = saveChainRef.current;
        // Start immediately when idle (so the create/update fires synchronously);
        // otherwise chain strictly after the previous save so two creates never run
        // in parallel. ``prior`` is always a never-rejecting tail.
        const next = prior ? prior.then(() => saveCurrentProject()) : saveCurrentProject();
        // Track a caught tail for chaining + cleanup so a failed save can neither
        // surface as an unhandled rejection nor wedge the chain. The caller still
        // gets ``next`` (which may reject) and is expected to handle it.
        const tail = next.then(
            () => undefined,
            () => undefined,
        );
        saveChainRef.current = tail;
        tail.then(() => {
            if (saveChainRef.current === tail) saveChainRef.current = null;
        });
        return next;
    }, [saveCurrentProject]);

    // Resolve the current project id, creating+saving the project when this is a
    // brand-new dataflow that has never been persisted. Centralizes the rule that
    // used to live only in the catalog drawer so the node-execution auto-install
    // path can guarantee a persisted project without a manual save. Does NOT force
    // a save when the project already exists (the catalog Install endpoint persists
    // its own ref) — see persistInstalledDataset for the always-save behavior.
    // Concurrent callers share one create (so two rapid installs can't double-create)
    // and all receive the same id, without triggering a redundant follow-up update.
    const ensureProjectInFlightRef = useRef<Promise<string | null> | null>(null);
    const ensureProjectId = useCallback(async (): Promise<string | null> => {
        if (projectIdRef.current) return projectIdRef.current;
        if (ensureProjectInFlightRef.current) return ensureProjectInFlightRef.current;
        const inFlight = (async () => {
            try {
                const detail = await requestProjectSave();
                return (detail as { id?: string } | undefined)?.id || projectIdRef.current || null;
            } catch (err) {
                showToast(
                    (err as Error)?.message || "Save the dataflow before installing datasets.",
                    "error",
                );
                return null;
            } finally {
                ensureProjectInFlightRef.current = null;
            }
        })();
        ensureProjectInFlightRef.current = inFlight;
        return inFlight;
    }, [requestProjectSave, showToast]);

    // Persist a dataset that the backend auto-installed on node execution and
    // refresh the UI from the resulting saved spec — no manual disk-icon save.
    // This ALWAYS saves the project (create for a brand-new dataflow, update for an
    // existing one) rather than relying on the backend's execution-time spec merge,
    // so re-running a flow after datasets were removed reaches the SAME persisted +
    // visible state as a first-time install: saveCurrentProject round-trips the
    // canonical spec and syncDatasetsFromSavedSpec reconciles the catalog from it.
    const persistInstalledDataset = useCallback(
        async (inst: InstalledDatasetPayload | null | undefined): Promise<void> => {
            if (!inst?.id || !inst?.dirName) return;
            // Build the ref once so the React state and the ref stay byte-identical.
            const ref = buildInstalledDatasetRef(inst);
            // Optimistically merge into in-memory state...
            setDataflowDatasets((prev) => upsertDataflowDatasetRef(prev, inst.id, ref) as any[]);
            // ...and update dataflowDatasetsRef synchronously: setDataflowDatasets only
            // flushes to the ref on the next render, but saveCurrentProject reads
            // dataflowDatasetsRef.current *now*, so without this the saved spec could
            // miss this dataset.
            dataflowDatasetsRef.current = upsertDataflowDatasetRef(
                dataflowDatasetsRef.current,
                inst.id,
                ref,
            ) as any[];
            try {
                // Create-or-update + syncDatasetsFromSavedSpec (which also fires the
                // catalog refresh) — UI ends on the final persisted project state.
                await requestProjectSave();
            } catch (err) {
                // Keep the optimistic in-memory ref so a later manual save still
                // captures it; surface why the auto-save failed.
                showToast((err as Error)?.message || "Could not save the dataflow.", "error");
                notifyDatasetCatalogRefresh();
            }
        },
        [requestProjectSave, setDataflowDatasets, showToast],
    );

    // Persist the dataflow after a producing node ran but the backend did NOT
    // auto-install during execution (it only does so for deliberately-saved
    // tabular/geo datasets or bundles — a raster/raw-artifact output returns no
    // installedDataset payload). The dataset is instead installed at SAVE time
    // from the node's output refs (_auto_install_computed_outputs), so this runs
    // the exact same save the disk icon does — create-or-update + resync — making
    // the dataset appear without a manual save. No dataset ref to stage here: the
    // backend derives it from the saved output refs and returns it in detail.spec.
    // Map a save's install-warnings onto friendly node labels and warn the user.
    // Without this, a computed output that failed to install (e.g. its artifact
    // was missing at save time) was swallowed server-side and the dataset just
    // never appeared — the "Play All didn't generate all datasets" symptom.
    const surfaceInstallWarnings = useCallback(
        (detail: { dataset_install_warnings?: DatasetInstallWarning[] } | undefined) => {
            const warnings = detail?.dataset_install_warnings;
            if (!warnings || warnings.length === 0) return;
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
                    ? `Dataset for "${list}" couldn't be generated — re-run that node.`
                    : `${warnings.length} datasets couldn't be generated (${list}) — re-run those nodes.`,
                "warning",
            );
        },
        [reactFlow, showToast],
    );

    const persistDataflowForInstall = useCallback(async (): Promise<void> => {
        try {
            const detail = await requestProjectSave();
            surfaceInstallWarnings(detail);
        } catch (err) {
            showToast((err as Error)?.message || "Could not save the dataflow.", "error");
            notifyDatasetCatalogRefresh();
        }
    }, [requestProjectSave, showToast, surfaceInstallWarnings]);

    // ── In-flight install placeholders ────────────────────────────────────────
    // Upper bound on how long a placeholder can linger if its clear never fires
    // (crashed/aborted run). Matches the client execution timeout ceiling.
    const PENDING_INSTALL_TIMEOUT_MS = 600_000;

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

    // Drop every placeholder + timer when the dataflow is swapped/discarded so a
    // pending install from the previous project can't leak into the next one.
    useEffect(() => {
        return () => {
            Object.values(pendingInstallTimersRef.current).forEach(clearTimeout);
            pendingInstallTimersRef.current = {};
        };
    }, []);

    // Auto-save every 30 seconds when a project has been explicitly saved at least once
    useEffect(() => {
        if (!projectId || !projectDirty || blockGuestSaves || viewerMode === "shared") return;
        const id = window.setInterval(async () => {
            try {
                await saveCurrentProject();
            } catch (err) {
                console.error("Auto-save failed:", err);
            }
        }, 30_000);
        return () => window.clearInterval(id);
    }, [projectId, projectDirty, saveCurrentProject, blockGuestSaves, viewerMode]);

    const saveAsNewProject = useCallback(async (name: string) => {
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        // Same as saveCurrentProject: read from store to avoid stale React state snapshot.
        const currentPackages = getCurrentProjectPackagesList();
        // Same as saveCurrentProject: read from ref so we always use the latest datasets.
        const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, "", currentPackages, workflowDescriptionRef.current, dataflowDatasetsRef.current);
        spec.nodeProvenance = getAllNodeProvenance();
        spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();

        const outputRefs: OutputRef[] = buildOutputRefs();

        const detail = await projectsApi.create({
            name,
            spec,
            outputs: outputRefs,
        });
        syncDatasetsFromSavedSpec(detail.spec);
        setProjectId(detail.id);
        setProjectName(detail.name);
        setProjectSavedAt(new Date());
        setProjectDirty(false);
        setViewerMode("owner");
        return detail;
    }, [workflowNameRef, reactFlow, deps.outputsRef, blockGuestSaves, syncDatasetsFromSavedSpec, defaultSaveOutputDataset]);

    const loadProject = useCallback(async (id: string) => {
        const result = await projectsApi.get(id);
        const { project, spec, outputs } = result;

        setProjectId(project.id);
        setProjectName(project.name);
        setProjectDirty(false);
        setProjectSavedAt(project.updated_at ? new Date(project.updated_at) : null);
        setViewerMode("owner");

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
        setProjectId(null);
        setProjectName(project.name);
        setProjectDirty(false);
        setProjectSavedAt(null);
        setViewerMode("shared");

        const execStatus: Record<string, "stale" | "executed"> = {};
        for (const o of outputs) {
            execStatus[o.node_id] = "executed";
        }
        setNodeExecStatus(execStatus);

        return result;
    }, []);

    const discardProject = useCallback(() => {
        setProjectId(null);
        setProjectName("");
        setProjectDirty(false);
        setProjectSavedAt(null);
        setNodeExecStatus({});
        setDataflowDatasets([]);
        setViewerMode("owner");
    }, []);

    const markNodeExecuted = useCallback((nodeId: string) => {
        setNodeExecStatus((prev) => ({ ...prev, [nodeId]: "executed" }));
    }, []);

    const markNodeStale = useCallback((nodeId: string) => {
        setNodeExecStatus((prev) => ({ ...prev, [nodeId]: "stale" }));
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
        packages,
        setPackages,
        addPackage,
        removePackage,
        dataflowDatasets,
        setDataflowDatasets,
        pendingInstalls,
        beginPendingInstall,
        endPendingInstall,

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
        saveCurrentProject,
        saveAsNewProject,
        ensureProjectId,
        persistInstalledDataset,
        persistDataflowForInstall,
        loadProject,
        loadSharedProject,
        discardProject,
        markDirty,
        markNodeExecuted,
        markNodeStale,
    };
}
