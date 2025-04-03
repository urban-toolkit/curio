import { useCallback } from "react";
import { Node } from "reactflow";
import { v4 as uuid } from "uuid";

import { IInteraction, IOutput, useFlowContext } from "../providers/FlowProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { usePosition } from "./usePosition";
import { Template } from "../providers/TemplateProvider";
import { AccessLevelType, BoxType, EdgeType } from "../constants";

const pythonInterpreter = new PythonInterpreter();

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
};

interface IUseCode {
    createCodeNode: (boxType: string, options?: CreateCodeNodeOptions) => void;
    loadTrill: (trill: any, suggestionType?: string) => void;
}

export function useCode(): IUseCode {
    const { addNode, setOutputs, setInteractions, applyNewPropagation, applyNewOutput, loadParsedTrill } = useFlowContext();
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
    const loadTrill = (trill: any, suggestionType?: string) => {

        let nodes = [];
        let edges = [];

        for(const node of trill.dataflow.nodes){
            let x = node.x;
            let y = node.y;

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

            if(suggestionType != undefined)
                nodeMeta.suggestionType = suggestionType;

            nodes.push(generateCodeNode(node.type, nodeMeta));

        }

        for(const edge of trill.dataflow.edges){

            let add_edge: any = {
                id: edge.id,
                type: EdgeType.UNIDIRECTIONAL_EDGE,
                markerEnd: {type: "arrow"},
                source: edge.source,
                sourceHandle: "out",
                target: edge.target,
                targetHandle: "in"
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

        if(suggestionType == undefined)
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, true, false); 
        else if(suggestionType == "workflow")
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, true); // if loading as suggestion deactivate provenance and merge
        else
            loadParsedTrill(trill.dataflow.name, trill.dataflow.task, nodes, edges, false, true); 

    }

    const generateCodeNode = useCallback((boxType: string, options: CreateCodeNodeOptions = {}) => {
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
            keywords = []
        } = options;

        const node: Node = {
            id: nodeId,
            type: boxType,
            position,
            data: {
                nodeId: nodeId,
                pythonInterpreter: pythonInterpreter,
                defaultCode: code,
                description,
                templateId,
                templateName,
                accessLevel,
                warnings,
                hidden: false,
                nodeType: boxType,
                customTemplate,
                suggestionType,
                goal,
                in: inType,
                out,
                input: "",
                keywords,
                outputCallback,
                interactionsCallback,
                propagationCallback: applyNewPropagation,
            },
        };

        return node;

    }, [addNode, outputCallback, getPosition]);

    const createCodeNode = useCallback((boxType: string, options: CreateCodeNodeOptions = {}) => {
        let node = generateCodeNode(boxType, options);
        addNode(node, undefined, true);
    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode, loadTrill };
}
