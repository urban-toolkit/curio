/**
 * useWorkflowOperations
 *
 * Encapsulates workflow-specific operations (trill loading, canvas management,
 * suggestion handling, keyword/subtask/warning updates) that were previously
 * inlined in FlowProvider. Keeps FlowProvider focused on core ReactFlow state
 * and connection logic.
 */

import { useEffect, useState } from "react";
import { Node, Edge, NodeChange, NodeRemoveChange, Connection, useReactFlow } from "reactflow";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { updateNodeData, updateNodesByMap, updateEdgesByMap, extractNodeFieldMap, extractKeywordMaps } from "../utils/flowNodeUtils";
import { TrillGenerator } from "../TrillGenerator";

export interface WorkflowOperationsDeps {
    nodes: Node[];
    edges: Edge[];
    setNodes: any;
    setEdges: any;
    setOutputs: any;
    setInteractions: any;
    setDashboardPins: (value: any) => void;
    setPositionsInDashboard: (data: any) => void;
    setPositionsInWorkflow: (data: any) => void;
    setWorkflowName: (name: string) => void;
    workflowNameRef: React.MutableRefObject<string>;
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
        onEdgesDelete, onNodesDelete, onNodesChange,
        onConnect, addNode,
    } = deps;

    const reactFlow = useReactFlow();
    const { newBox, addWorkflow } = useProvenanceContext();

    // fitViewOnLoad is internal to workflow loading
    const [fitViewOnLoad, setFitViewOnLoad] = useState(false);

    // Workflow-level state (not used by FlowProvider's core flow logic)
    const [allMinimized, setAllMinimized] = useState<number>(0);
    const [expandStatus, setExpandStatus] = useState<'expanded' | 'minimized'>('expanded');
    const [suggestionsLeft, setSuggestionsLeft] = useState<number>(0); // Number of suggestions left
    const [workflowGoal, setWorkflowGoal] = useState("");

    // ---------------------------------------------------------------------------
    // Effects
    // ---------------------------------------------------------------------------

    useEffect(() => {
        if (fitViewOnLoad) {
            const timeout = setTimeout(() => {
                const currentNodes = reactFlow.getNodes();
                if (currentNodes.length > 0) {
                    reactFlow.fitView({ padding: 0.2 });
                    setFitViewOnLoad(false);
                }
            }, 100); // small delay to ensure render cycle

            return () => clearTimeout(timeout);
        }
    }, [fitViewOnLoad]);

    useEffect(() => {
        flagAcceptableSuggestions(nodes, edges);
    }, [nodes, edges]);

    // ---------------------------------------------------------------------------
    // Trill / Data Operations
    // ---------------------------------------------------------------------------

    const updateDataNode = (nodeId: string, newData: any) => {
        console.log("updateDataNode");
        setNodes((prevNodes: Node[]) => updateNodeData(prevNodes, nodeId, () => ({ ...newData })));
    }

    const loadParsedTrill = async (workflowName: string, task: string, loaded_nodes: any, loaded_edges: any, provenance?: boolean, merge?: boolean) => {
        if (!merge) {
            TrillGenerator.reset();
            setWorkflowName(workflowName);
            await addWorkflow(workflowName);
            const empty_trill = TrillGenerator.generateTrill([], [], workflowName);
            TrillGenerator.intializeProvenance(empty_trill);
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
                    onConnect(edge, prevNodes, undefined, workflowName, provenance);
                }
            }

            if (!merge) {
                setOutputs([]);
                setInteractions([]);
                setDashboardPins({});
                setPositionsInDashboard({});
                setPositionsInWorkflow({});
            }

            setFitViewOnLoad(true);
            return prevNodes;
        });
    }

    const updateDefaultCode = (nodeId: string, content: string) => {
        console.log("updateDefaultCode");
        setNodes((prevNodes: Node[]) => updateNodeData(prevNodes, nodeId, (data: any) => ({ ...data, defaultCode: content })));
    }

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
    }

    const applyRemoveChanges = (changes: NodeRemoveChange[]) => {
        let allowedChanges: NodeRemoveChange[] = [];

        let edges = reactFlow.getEdges();

        for (const change of changes) {
            let allowed = true;

            for (const edge of edges) {
                if (
                    edge.source == change.id ||
                    edge.target == change.id
                ) {
                    alert(
                        "Connected boxes cannot be removed. Remove the edges first by selecting it and pressing backspace."
                    );
                    allowed = false;
                    break;
                }
            }

            if (allowed) allowedChanges.push(change);
        }

        onNodesDelete(allowedChanges);
        return onNodesChange(allowedChanges);
    };

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
    const acceptSuggestion = (nodeId: string) => {
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

                newBox(workflowNameRef.current, (node.type as string) + "-" + node.id);

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
    }

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
    };
}
