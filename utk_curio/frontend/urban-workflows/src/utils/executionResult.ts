/**
 * What a code node shows after a run, and the provenance the run records. One
 * rule for a run the browser sent (`PythonInterpreter`, `JavaScriptInterpreter`,
 * shown by `CodeEditor`) and a step of a run on the server (`useServerRun`).
 */
import type { NodeOutput } from "../hook/useNodeState";
import { formatDate, mapTypes } from "./formatters";

/** Show at most the last 4000 characters of stdout: a runaway log loop must not lock the panel. */
const STDOUT_CAP = 4000;

/**
 * Whether a run's reply carries an output. A run without one failed. Text on
 * stderr does not say so: a run that succeeds can write warnings there.
 */
function replyHasOutput(reply: any): boolean {
    return reply.output?.path !== "";
}

/**
 * The node's outcome from a run's reply, and the artifact it passes downstream
 * (``null`` when the run produced none, which is a failure).
 */
export function executionResultOutput(result: any): { shown: NodeOutput; artifact: any | null } {
    const hasOutput = replyHasOutput(result);

    // result.stdout is list[str] from the sandbox; join with newlines so
    // multi-line autkdb output is readable instead of comma-coerced. Cap at the
    // tail, since errors usually surface there.
    const stdoutLines: string[] = Array.isArray(result.stdout)
        ? result.stdout
        : (result.stdout ? [String(result.stdout)] : []);
    let stdoutText = stdoutLines.join("\n");
    let stdoutTruncated = false;
    if (stdoutText.length > STDOUT_CAP) {
        stdoutText = stdoutText.slice(-STDOUT_CAP);
        stdoutTruncated = true;
    }
    const stdoutBlock = stdoutText
        ? "stdout:\n" + (stdoutTruncated
            ? `... [truncated to last ${STDOUT_CAP} chars]\n` + stdoutText
            : stdoutText)
        : "";

    if (hasOutput) {
        let outputContent = stdoutBlock;
        if (result.stderr) {
            outputContent += (outputContent ? "\n" : "") + "stderr:\n" + result.stderr;
        }
        outputContent += (outputContent ? "\n" : "") + "Saved to file: " + result.output.path;
        return { shown: { code: "success", content: outputContent }, artifact: result.output };
    }
    let errorContent = "";
    if (stdoutBlock) errorContent += stdoutBlock + "\n";
    errorContent += result.stderr || "(no stderr)";
    // The traceback is unchanged; the missing-library notice rides alongside it (#299).
    return {
        shown: { code: "error", content: errorContent, missingModule: result.missingModule ?? null },
        artifact: null,
    };
}

/**
 * Record a node run in the provenance: its times, the kinds of data it read and
 * returned, and its code. A run that failed returned an error.
 */
export function recordExecProvenance(
    nodeExecProv: (...args: any[]) => void,
    run: {
        startedAt: Date;
        finishedAt: Date;
        workflowName: string;
        nodeId: string;
        /** The input the node ran on ("" for none). */
        input: unknown;
        reply: any;
        /** The node's code as written, before its references are resolved. */
        code: string;
    },
): void {
    const { reply } = run;
    // The reply names what the run read, and what it returned, by one
    // `dataType` each (backend/app/execution/node_exec.py).
    const typesInput = run.input != "" ? reply.input?.dataType : undefined;
    const typesOutput = replyHasOutput(reply) ? reply.output?.dataType : "error";
    nodeExecProv(
        formatDate(run.startedAt),
        formatDate(run.finishedAt),
        run.workflowName,
        run.nodeId,
        mapTypes(typesInput),
        mapTypes(typesOutput),
        run.code,
    );
}
