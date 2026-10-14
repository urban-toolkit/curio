// The calls `useServerRun` makes, for a visitor running a published dashboard.
//
// A start sends the values the dashboard's widgets show now, for the inputs the
// link lets a visitor set, and the run that answers is followed as an owner's
// run on the server is: its steps' outputs reach the tiles, read through the
// run's key (publishedArtifacts). Nothing is reported back or listed: a visitor
// has no runs of their own.
import type { Node } from "reactflow";
import type { ServerRunApi } from "../../providers/flow/useServerRun";
import type { Run } from "../runs/runsApi";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";
import { publishedApi, type PublishedInput } from "./publishedApi";
import { notePublishedArtifacts, setPublishedRun } from "./publishedArtifacts";

/** The values the dashboard's widgets show, for the inputs the link lets a visitor set. */
export function inputsFromNodes(
    nodes: readonly Node[],
    allowed: readonly Pick<PublishedInput, "nodeId" | "name">[],
): Record<string, Record<string, unknown>> {
    const wanted = new Set(allowed.map((input) => `${input.nodeId}\u0000${input.name}`));
    const inputs: Record<string, Record<string, unknown>> = {};
    for (const node of nodes) {
        for (const widget of normalizeWidgets(node.data?.widgets)) {
            if (!wanted.has(`${node.id}\u0000${widget.name}`)) continue;
            const value = "value" in widget && widget.value !== undefined ? widget.value : widget.default;
            (inputs[node.id] ??= {})[widget.name] = value;
        }
    }
    return inputs;
}

/** A published run's record, in the shape the hook reads. */
function asRun(raw: any, runId: string): Run {
    return {
        id: runId,
        projectId: "",
        projectName: null,
        trigger: "all",
        targetNodeId: null,
        wholeDataflow: true,
        rerunOf: null,
        specRevision: null,
        status: raw?.status ?? "queued",
        createdAt: null,
        startedAt: null,
        finishedAt: null,
        counts: { ok: 0, failed: 0, skipped: 0, waiting: 0 },
        error: null,
        live: true,
        steps: (raw?.steps ?? []).map((step: any) => ({
            nodeId: step.nodeId,
            label: step.label ?? null,
            nodeType: null,
            level: null,
            role: step.role,
            status: step.status,
            startedAt: null,
            finishedAt: null,
            durationMs: null,
            outputPath: null,
            outputType: null,
            installedDatasetId: null,
            codeSha256: null,
            stdoutTail: null,
            stderrTail: null,
            skipReason: null,
        })),
    };
}

/**
 * The run calls for the link *token*; *nodes* reads the dashboard's nodes at
 * the moment Run is pressed.
 */
export function publishedRunApi(token: string, nodes: () => readonly Node[]): ServerRunApi {
    const keys = new Map<string, string>();
    const keyOf = (runId: string) => keys.get(runId) ?? "";

    return {
        async start() {
            const { inputs: allowed } = await publishedApi.describe(token);
            const started = await publishedApi.startRun(token, inputsFromNodes(nodes(), allowed));
            keys.set(started.runId, started.key);
            setPublishedRun(started.runId, started.key);
            return asRun(await publishedApi.getRun(started.runId, started.key), started.runId);
        },
        async get(runId: string) {
            return asRun(await publishedApi.getRun(runId, keyOf(runId)), runId);
        },
        follow(runId, onEvent, signal) {
            return publishedApi.follow(runId, keyOf(runId), (event) => {
                // The names a step produced may be read with the run's key.
                if (event.kind === "step_finished") {
                    notePublishedArtifacts((event as any).output);
                    notePublishedArtifacts((event as any).reply);
                }
                onEvent(event);
            }, signal);
        },
        async cancel(runId: string) {
            return asRun(await publishedApi.cancel(runId, keyOf(runId)), runId);
        },
        async reportStep(runId: string) {
            return asRun({}, runId);
        },
        async listForProject() {
            return [];
        },
    };
}
