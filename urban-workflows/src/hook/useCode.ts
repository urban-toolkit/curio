import { useCallback } from "react";
import { Node } from "reactflow";
import { v4 as uuid } from "uuid";

import { IInteraction, IOutput, useFlowContext } from "../providers/FlowProvider";
import { PythonInterpreter } from "../PythonInterpreter";
import { usePosition } from "./usePosition";
import { Template } from "../providers/TemplateProvider";
import { AccessLevelType } from "../constants";

const pythonInterpreter = new PythonInterpreter();

interface IUseCode {
    createCodeNode: (boxType: string, template: Template | null, id: string, code: string, saveProvDB: boolean, position:any) => void;
}

export function useCode(): IUseCode {
    const { addNode, setOutputs, setInteractions, applyNewPropagation, applyNewOutput } = useFlowContext();
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

    const createCodeNode = useCallback((boxType: string, template: Template | null = null, id = "", code = "", saveProvDB = true, position = getPosition()) => {
        let nodeId;
        if (id === "") {
            nodeId = uuid();
        } else {
            nodeId = id;
        }

        let node: Node;

        if(code == null){
            code = "";
        }

        console.log(position)

        if(template != null){
           node = {
                id: nodeId,
                type: boxType,
                position: position,
                data: {
                    nodeId: nodeId,
                    pythonInterpreter: pythonInterpreter,
                    defaultCode: template.code,
                    description: template.description,
                    templateId: template.id,
                    templateName: template.name,
                    accessLevel: template.accessLevel,
                    hidden: false,
                    nodeType: boxType,
                    customTemplate: template.custom,
                    input: "",
                    outputCallback,
                    interactionsCallback,
                    propagationCallback: applyNewPropagation,
                },
            };
        }else{
            node = {
                id: nodeId,
                type: boxType,
                position: position,
                data: {
                    nodeId: nodeId,
                    pythonInterpreter: pythonInterpreter,
                    defaultCode: code.split(' ').join(' '), 
                    description: '',
                    templateId: '',
                    templateName: '',
                    accessLevel: '',
                    hidden: false,
                    nodeType: boxType,
                    customTemplate: true,
                    input: "",
                    outputCallback,
                    interactionsCallback,
                    propagationCallback: applyNewPropagation,
                },
            };
            
        }

    addNode(node,saveProvDB);

    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode };
}
