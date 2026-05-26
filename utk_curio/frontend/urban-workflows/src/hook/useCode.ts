import { useCallback } from "react";
import { Node } from "reactflow";
import { v4 as uuid } from "uuid";

import { IInteraction, useFlowContext } from "../providers/FlowProvider";
import { useProvenanceContext } from "../providers/ProvenanceProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { JavaScriptInterpreter } from "../JavaScriptInterpreter";
import { TrillGenerator } from "../TrillGenerator";
import { usePosition } from "./usePosition";
import { AccessLevelType, EdgeType, CURIO_UNIVERSAL_NODE_TYPE } from "../constants";

// Module-level singletons so every node shares the same interpreter
// connection pool. Exported so collaboration's remote-graph handler can
// re-attach them to nodes that arrive over the socket (which strips
// non-serializable fields).
export const pythonInterpreter = new PythonInterpreter();
export const jsInterpreter = new JavaScriptInterpreter();

type CreateCodeNodeOptions = {
    nodeId?: string;
    code?: string;
    description?: string;
    templateId?: string;
    templateName?: string;
    accessLevel?: AccessLevelType;
    customTemplate?: boolean;
    position?: { x: number; y: number };
    suggestionType?: boolean;
    goal?: string;
    warnings?: string[];
    inType?: string;
    out?: string;
    keywords?: number[];
    nodeWidth?: number;
    nodeHeight?: number;
    dashboardPinned?: boolean;
    dashboardX?: number;
    dashboardY?: number;
    dashboardWidth?: number;
    dashboardHeight?: number;
};

interface IUseCode {
    createCodeNode: (nodeType: string, options?: CreateCodeNodeOptions) => void;
    loadTrill: (trill: any, suggestionType?: string) => void;
}

export function useCode(): IUseCode {
    const { addNode, setOutputs, setInteractions, applyNewPropagation, applyNewOutput, loadParsedTrill } = useFlowContext();
    const { loadNodeProvenance } = useProvenanceContext();
    const { getPosition } = usePosition();

    const outputCallback = useCallback(
        (nodeId: string, output: string) => {
            applyNewOutput({nodeId: nodeId, output: output});
        },
        [setOutputs]
    );

    const interactionsCallback = useCallback((interactions: any, nodeId: string) => {
        setInteractions((prevInteractions: IInteraction[]) => {
            let newInteractions: IInteraction[] = [];
            let newNode = true;

            for(const interaction of prevInteractions){
                if(interaction.nodeId == nodeId){
                    newInteractions.push({nodeId: nodeId, details: interactions, priority: 1});
                    newNode = false;
                }else{
                    newInteractions.push({...interaction, priority: 0});
                }
            }

            if(newNode)
                newInteractions.push({nodeId: nodeId, details: interactions, priority: 1});

            return newInteractions;
        })
    }, [setInteractions]);

    // suggestionType: "workflow" | "connection" | "none"
    const loadTrill = (trill: any, suggestionType?: string, fromProvenance?: boolean) => {

        let nodes = [];
        let edges = [];

        for(const node of trill.dataflow.nodes){
            let x = node.x;
            let y = node.y;
            const parsedWidth =
                typeof node.width === "number"
                    ? node.width
                    : typeof node.nodeWidth === "number"
                        ? node.nodeWidth
                        : typeof node.metadata?.width === "number"
                            ? node.metadata.width
                            : typeof node.metadata?.nodeWidth === "number"
                                ? node.metadata.nodeWidth
                                : undefined;
            const parsedHeight =
                typeof node.height === "number"
                    ? node.height
                    : typeof node.nodeHeight === "number"
                        ? node.nodeHeight
                        : typeof node.metadata?.height === "number"
                            ? node.metadata.height
                            : typeof node.metadata?.nodeHeight === "number"
                                ? node.metadata.nodeHeight
                                : undefined;

            if(x == undefined || y == undefined){
                let position = getPosition();
                x = position.x + 800;
                y = position.y;
            }

            let nodeMeta: any = {
                nodeId: node.id, 
                code: node.content, 
                position: {x: x, y: y}
            }

            if(node.goal != undefined)
                nodeMeta.goal = node.goal;

            if(node.in != undefined)
                nodeMeta.inType = node.in;

            if(node.out != undefined)
                nodeMeta.out = node.out;

            if(node.warnings != undefined)
                nodeMeta.warnings = node.warnings;

            if(node.metadata != undefined && node.metadata.keywords != undefined)
                nodeMeta.keywords = node.metadata.keywords;

            if(typeof parsedWidth === "number")
                nodeMeta.nodeWidth = parsedWidth;

            if(typeof parsedHeight === "number")
                nodeMeta.nodeHeight = parsedHeight;

            if(node.dashboardPinned)
                nodeMeta.dashboardPinned = true;

            if(typeof node.dashboardX === "number"){
                nodeMeta.dashboardX = node.dashboardX;
                nodeMeta.dashboardY = node.dashboardY;
            }

            if(typeof node.dashboardWidth === "number"){
                nodeMeta.dashboardWidth = node.dashboardWidth;
                nodeMeta.dashboardHeight = node.dashboardHeight;
            }

            if(suggestionType != undefined)
                nodeMeta.suggestionType = suggestionType;

            nodes.push(generateCodeNode(node.type, nodeMeta));

        }

        for(const edge of trill.dataflow.edges){

            let targetHandle = "in";

            for(let i = 0; i < 5; i++){
                if(edge.id && edge.id.includes("in_"+i))
                    targetHandle = "in_"+i;
            }

            let add_edge: any = {
                id: edge.id,
                type: EdgeType.UNIDIRECTIONAL_EDGE,
                markerEnd: {type: "arrow"},
                source: edge.source,
                sourceHandle: "out",
                target: edge.target,
                targetHandle
            }

            add_edge.data = {}

            if(suggestionType != undefined)
                add_edge.data.suggestionType = suggestionType;

            if(edge.metadata != undefined && edge.metadata.keywords != undefined)
                add_edge.data.keywords = edge.metadata.keywords;

            if(edge.type == "Interaction"){
                add_edge.markerStart = {type: "arrow"};
                add_edge.sourceHandle = "in/out";
                add_edge.targetHandle = "in/out";
                add_edge.type = EdgeType.BIDIRECTIONAL_EDGE;
            }

            edges.push(add_edge);
        }

        if (fromProvenance) {
            // Reverting to a historical version: preserve the current provenance graph.
            // latestTrill was already set to the target version by switchProvenanceTrill.
            const savedProv = TrillGenerator.getSerializableDataflowProvenance();
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, false, trill.dataflow.packages || [], trill.dataflow.description || "");
            TrillGenerator.loadDataflowProvenance(savedProv);
        } else if(suggestionType == undefined) {
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, true, false, trill.dataflow.packages || [], trill.dataflow.description || "");
            if (trill.nodeProvenance) loadNodeProvenance(trill.nodeProvenance);
            if (trill.dataflowProvenance) TrillGenerator.loadDataflowProvenance(trill.dataflowProvenance);
        } else {
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, true, undefined, trill.dataflow.description || "");
        }

    }

    const generateCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}) => {
        const {
            nodeId = uuid(),
            code = undefined,
            description = undefined,
            templateId = undefined,
            templateName = undefined,
            accessLevel = undefined,
            customTemplate = undefined,
            position = getPosition(),
            suggestionType = "none",
            warnings = [],
            goal = "",
            inType = "DEFAULT",
            out = "DEFAULT",
            keywords = [],
            nodeWidth = undefined,
            nodeHeight = undefined,
            dashboardPinned = undefined,
            dashboardX = undefined,
            dashboardY = undefined,
            dashboardWidth = undefined,
            dashboardHeight = undefined,
        } = options;

        const node: Node = {
            id: nodeId,
            type: CURIO_UNIVERSAL_NODE_TYPE,
            position,
            data: {
                nodeId: nodeId,
                pythonInterpreter: pythonInterpreter,
                jsInterpreter: jsInterpreter,
                defaultCode: code,
                description,
                templateId,
                templateName,
                accessLevel,
                warnings,
                hidden: false,
                nodeType: nodeType,
                customTemplate,
                suggestionType,
                goal,
                in: inType,
                out,
                nodeWidth,
                nodeHeight,
                dashboardPinned,
                dashboardX,
                dashboardY,
                dashboardWidth,
                dashboardHeight,
                input: "",
                inputTypes: [],
                keywords,
                outputCallback,
                interactionsCallback,
                propagationCallback: applyNewPropagation,
            },
        };

        return node;

    }, [addNode, outputCallback, getPosition]);

    const createCodeNode = useCallback((nodeType: string, options: CreateCodeNodeOptions = {}) => {
        let node = generateCodeNode(nodeType, options);
        addNode(node, undefined, true);
    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode, loadTrill };
}
