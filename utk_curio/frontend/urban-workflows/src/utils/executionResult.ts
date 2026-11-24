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
 * When the result a run reused was made (`reused.madeAt`), for a node whose
 * key held what its maker's last run kept, so it ran nothing, as a dashboard
 * visitor's step does; null for a result its run made.
 */
function reusedMadeAt(reply: any): string | null {
    const madeAt = reply?.reused?.madeAt;
    return typeof madeAt === "string" && madeAt ? madeAt : null;
}

/** What a node whose run reused a kept result shows in place of its logs. */
export function reusedLine(madeAt: string): string {
    const when = new Date(madeAt).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
    return `Reused the result of ${when}: same code, inputs and datasets, so the node did not run. ` +
        "Play the node to run it again.";
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
        const reused = reusedMadeAt(result);
        // A reused result printed nothing this time: say what it is instead.
        let outputContent = reused ? reusedLine(reused) : stdoutBlock;
        if (!reused && result.stderr) {
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
    // A reused result is no run: the run that made it was recorded then.
    if (reusedMadeAt(reply)) return;
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
