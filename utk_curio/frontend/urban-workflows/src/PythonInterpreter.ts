import { NodeTemplateId } from "./registry/types";
import { recordExecProvenance } from "./utils/executionResult";
import { executionInputRef } from "./utils/flowOutputRef";
import { runNodeOnBackend } from "./utils/nodeRunRequest";

/**
 * A node's code as Play posts it: each line indented by four spaces and ended
 * with a newline. A run on the server sends it so too (`run_engine.play_indent`),
 * and the cases both sides read are in `providers/flow/playCode.cases.json`.
 */
export function playIndent(code: string): string {
    let posted = "";
    for (const line of code.split("\n")) {
        posted += "    " + line + "\n";
    }
    return posted;
}

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

        const unifiedLines = playIndent(userCode);

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
