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
    createCodeNode: (boxType: string, template: Template | null, searching: boolean, id: string, code: string) => void;
}

export function useCode(): IUseCode {
    const { addNode, setOutputs, setInteractions, applyNewPropagation, applyNewOutput } = useFlowContext();
    const { getPosition } = usePosition();

    const outputCallback = useCallback(
        (nodeId: string, output: string) => {
            applyNewOutput({ nodeId: nodeId, output: output });
        },
        [setOutputs]
    );

    const interactionsCallback = useCallback((interactions: any, nodeId: string) => {
        setInteractions((prevInteractions: IInteraction[]) => {
            let newInteractions: IInteraction[] = [];
            let newNode = true;

            for (const interaction of prevInteractions) {
                if (interaction.nodeId == nodeId) {
                    newInteractions.push({ nodeId: nodeId, details: interactions, priority: 1 });
                    newNode = false;
                } else {
                    newInteractions.push({ ...interaction, priority: 0 });
                }
            }

            if (newNode)
                newInteractions.push({ nodeId: nodeId, details: interactions, priority: 1 });

            return newInteractions;
        })
    }, [setInteractions]);

    const createCodeNode = useCallback((boxType: string, template: Template | null = null, searching = false, id = "", code ="") => {
        console.log(boxType, id);
    
        let nodeId;
        if (id === "") {
            nodeId = uuid();
        } else {
            nodeId = id;
        }
    
        let node: Node;
    
        if (template != null) {
            // Caso template não seja nulo, usamos o código do template
            node = {
                id: nodeId,
                type: boxType,
                position: getPosition(),
                data: {
                    nodeId: nodeId,
                    pythonInterpreter: pythonInterpreter,
                    defaultCode: template.code, // O código do template será utilizado
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
        } else {



            console.log(code.split(' ').join(' '));
            // Caso template seja nulo, usamos o código padrão
            node = {
                id: nodeId,
                type: boxType,
                position: getPosition(),
                data: {
                    nodeId: nodeId,
                    pythonInterpreter: pythonInterpreter,
//                     defaultCode: `import pandas as pd

// d = {'a': ["A", "B", "C", "D", "E", "F", "G", "H", "I"], 'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}
// df = pd.DataFrame(data=d)

// return df`, // Código padrão
                    defaultCode: code.split(' ').join(' '), // Código padrão
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
    
        // Adiciona o nó
        addNode(node);
    
        if (!searching) {
            fetch('http://localhost:5002/registerProjectItem', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    id: nodeId,
                    name: template?.name || 'Test',
                    dependency: '',
                    code: template?.code || 'print(\'Hello World\')', // Envia o código editável
                    boxType: boxType,
                }),
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .catch((error) => {
                console.error('Erro ao registrar item do projeto:', error);
            });
        }
    }, [addNode, outputCallback, getPosition]);

    return { createCodeNode };
}