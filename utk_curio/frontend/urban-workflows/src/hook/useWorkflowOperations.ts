/**
 * useWorkflowOperations
 *
 * Encapsulates workflow-specific operations (trill loading, canvas management,
 * suggestion handling, keyword/subtask/warning updates) that were previously
 * inlined in FlowProvider. Keeps FlowProvider focused on core ReactFlow state
 * and connection logic.
 */

import { useEffect, useState, useCallback } from "react";
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
import { TrillGenerator } from "../TrillGenerator";
import { projectsApi, OutputRef } from "../api/projectsApi";

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
    onConnect: (connection: Connection, custom_nodes?: any, custom_edges?: any, custom_workflow?: string, provenance?: boolean) => void;
    addNode: (node: Node, customWorkflowName?: string, provenance?: boolean) => void;
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
    const [packages, setPackages] = useState<string[]>([]);

    const addPackage = useCallback((pkg: string) => {
        setPackages((prev) => prev.includes(pkg) ? prev : [...prev, pkg]);
    }, []);

    const removePackage = useCallback((pkg: string) => {
        setPackages((prev) => prev.filter((p) => p !== pkg));
    }, []);

    // Project state
    const [projectId, setProjectId] = useState<string | null>(null);
    const [projectName, setProjectName] = useState<string>("");
    const [projectDirty, setProjectDirty] = useState<boolean>(false);
    const [projectSavedAt, setProjectSavedAt] = useState<Date | null>(null);
    const [nodeExecStatus, setNodeExecStatus] = useState<Record<string, "stale" | "executed">>({});

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

            const fitApplied = reactFlow.fitView(fitOptions);

            if (!fitApplied) {
                attempts += 1;

                if (attempts >= 20) {
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
                reactFlow.fitView(fitOptions);
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

    const loadParsedTrill = async (workflowName: string, task: string, loaded_nodes: any, loaded_edges: any, provenance?: boolean, merge?: boolean, incomingPackages?: string[], incomingDescription?: string) => {
        if (!merge) {
            TrillGenerator.reset();
            setWorkflowName(workflowName);
            setWorkflowDescription(incomingDescription || "");
            const empty_trill = TrillGenerator.generateTrill([], [], workflowName, "", [], incomingDescription || "");
            TrillGenerator.intializeProvenance(empty_trill);
            setPackages(incomingPackages || []);
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
            if (merge) {
                for (const edge of loaded_edges) {
                    if (!currentEdgeIds.has(edge.id)) {
                        onConnect(edge, prevNodes, undefined, workflowName, provenance);
                    }
                }
            } else {
                for (const edge of loaded_edges) {
                    onConnect(edge, prevNodes, [], workflowName, provenance);
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
    const buildOutputRefs = (): OutputRef[] =>
        deps.outputsRef.current
            .map((o: any) => {
                const raw = o?.output;
                const filename =
                    typeof raw === "string"
                        ? raw
                        : typeof raw?.path === "string"
                            ? raw.path
                            : null;
                if (!filename || !o?.nodeId) return null;
                return { node_id: o.nodeId, filename };
            })
            .filter((r: OutputRef | null): r is OutputRef => r !== null);

    const saveCurrentProject = useCallback(async (nameOverride?: string) => {
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, "", [], workflowDescriptionRef.current);
        spec.nodeProvenance = getAllNodeProvenance();
        spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();

        const outputRefs: OutputRef[] = buildOutputRefs();

        const name = nameOverride || projectName || workflowNameRef.current;

        if (projectId) {
            const detail = await projectsApi.update(projectId, {
                spec,
                outputs: outputRefs,
                name,
            });
            setProjectSavedAt(new Date());
            setProjectDirty(false);
            return detail;
        } else {
            const detail = await projectsApi.create({
                name,
                spec,
                outputs: outputRefs,
            });
            setProjectId(detail.id);
            setProjectName(detail.name);
            setProjectSavedAt(new Date());
            setProjectDirty(false);
            return detail;
        }
    }, [projectId, projectName, workflowNameRef, reactFlow, deps.outputsRef, blockGuestSaves]);

    // Auto-save every 30 seconds when a project has been explicitly saved at least once
    useEffect(() => {
        if (!projectId || !projectDirty || blockGuestSaves) return;
        const id = window.setInterval(async () => {
            try {
                await saveCurrentProject();
            } catch (err) {
                console.error("Auto-save failed:", err);
            }
        }, 30_000);
        return () => window.clearInterval(id);
    }, [projectId, projectDirty, saveCurrentProject, blockGuestSaves]);

    const saveAsNewProject = useCallback(async (name: string) => {
        if (blockGuestSaves) {
            throw new Error("Guest users cannot save projects");
        }
        const currentNodes = reactFlow.getNodes();
        const currentEdges = reactFlow.getEdges();
        const spec: any = TrillGenerator.generateTrill(currentNodes, currentEdges, workflowNameRef.current, "", [], workflowDescriptionRef.current);
        spec.nodeProvenance = getAllNodeProvenance();
        spec.dataflowProvenance = TrillGenerator.getSerializableDataflowProvenance();

        const outputRefs: OutputRef[] = buildOutputRefs();

        const detail = await projectsApi.create({
            name,
            spec,
            outputs: outputRefs,
        });
        setProjectId(detail.id);
        setProjectName(detail.name);
        setProjectSavedAt(new Date());
        setProjectDirty(false);
        return detail;
    }, [workflowNameRef, reactFlow, deps.outputsRef, blockGuestSaves]);

    const loadProject = useCallback(async (id: string) => {
        const result = await projectsApi.get(id);
        const { project, spec, outputs } = result;

        setProjectId(project.id);
        setProjectName(project.name);
        setProjectDirty(false);
        setProjectSavedAt(project.updated_at ? new Date(project.updated_at) : null);

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

        // Project state
        projectId,
        projectName,
        projectDirty,
        projectSavedAt,
        nodeExecStatus,

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

        // Project operations
        saveCurrentProject,
        saveAsNewProject,
        loadProject,
        discardProject,
        markDirty,
        markNodeExecuted,
        markNodeStale,
    };
}
