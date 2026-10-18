import { NodeTemplateId } from "./registry/types";
import { recordExecProvenance } from "./utils/executionResult";
import { executionInputRef } from "./utils/flowOutputRef";
import { runNodeOnBackend } from "./utils/nodeRunRequest";

export class JavaScriptInterpreter {
    public interpretCode(
        unresolvedUserCode: string,
        userCode: string,
        input: string,
        inputTypes: string[],
        callback: any,
        nodeType: NodeTemplateId,
        nodeId: string,
        workflow_name: string,
        nodeExecProv: any,
        dataflowId?: string | null,
        saveOutputDataset = false,
        nodeName?: string,
        inputSlots?: number[],
    ) {
        const callbackError = (message: string) => {
            callback({
                stdout: [],
                stderr: message,
                output: { path: "", dataType: "str" },
            });
        };

        const startedAt = new Date();

        runNodeOnBackend(
            "/processJavaScriptCode",
            {
                code: userCode,
                input: executionInputRef(input),
                inputTypes: inputTypes,
                nodeType: nodeType,
                nodeId: nodeId,
                ...(dataflowId ? { dataflowId } : {}),
                ...(nodeName ? { nodeName } : {}),
                // The wired circles: the value on circle k is the code's input_k.
                ...(inputSlots && inputSlots.length > 0 ? { inputSlots } : {}),
                saveOutputDataset,
            },
            nodeId,
            (json) => {
                recordExecProvenance(nodeExecProv, {
                    startedAt,
                    finishedAt: new Date(),
                    workflowName: workflow_name,
                    nodeId,
                    input,
                    reply: json,
                    code: unresolvedUserCode,
                });

                callback(json);
            },
            callbackError,
        );
    }
}
