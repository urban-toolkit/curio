import { NodeType } from "./constants";
import { NodeTemplateId } from "./registry/types";
import { recordExecProvenance } from "./utils/executionResult";
import { executionInputRef } from "./utils/flowOutputRef";
import { runNodeOnBackend } from "./utils/nodeRunRequest";

export class PythonInterpreter {
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

        let lines = userCode.split("\n");

        let unifiedLines = "";
        for (const line of lines) {
            unifiedLines += "    " + line + "\n";
        }

        const startedAt = new Date();

        console.log("unifiedLines", unifiedLines);

        // Diagnostic: surface what the frontend is actually sending as the
        // node's input. Useful when chasing "input_0 is None" bugs in package /
        // several-input scenarios: the most common cause is `data.input`
        // never being updated by `applyNewOutput` before Run fires.
        // Strip large blobs so the console stays readable.
        try {
            const preview = JSON.stringify(input, (_k, v) =>
                typeof v === 'string' && v.length > 200 ? `${v.slice(0, 200)}…[${v.length} chars]` : v,
            );
            console.log(`[PythonInterpreter] node=${nodeType} id=${nodeId} input=${preview}`);
        } catch {
            console.log(`[PythonInterpreter] node=${nodeType} id=${nodeId} input=<unserializable>`);
        }

        runNodeOnBackend(
            "/processPythonCode",
            {
                code: unifiedLines,
                input: executionInputRef(input), // new
                inputTypes: inputTypes, // new
                nodeType: nodeType, // new
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
