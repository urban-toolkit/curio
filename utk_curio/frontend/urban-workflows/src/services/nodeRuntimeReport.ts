import { getToken } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";
import type { EMPTY_RENDER_KIND } from "../generated/renderCauses";

/**
 * Report a node's own execution outcome to the runtime journal (memo dev/135).
 *
 * `DEC-052`'s journal had three writers and all three were the sandbox, so
 * every kind that runs in the BROWSER or through its own service — a Vega-Lite
 * chart, an AUTK map, a Data Pool, a Merge Flow, a Simple View, a Spatial Join,
 * a Data Export, and any node that trips the render boundary — left no trace,
 * and every agent reading the journal was told `never-executed` about a node
 * the user had just watched fail (the owner's `a29d1ad8`).
 *
 * Three properties this module exists to keep:
 *
 * - **Fire and forget.** A render must never be delayed, failed or visibly
 *   changed by its journal. Nothing here throws, nothing here is awaited by a
 *   caller, and a failed report is silent (it is logged at debug level only).
 * - **Deduplicated.** The same outcome re-rendered (a re-mount, a resize, a
 *   parent state change) reports once. The key is the node plus the outcome
 *   itself, so a real change always reports and a repeat never does.
 * - **The content is never sent.** A status, a short message, and a declared
 *   output type — the same rule `nodeRuntimeSummary` keeps for the chat path.
 */

/** The statuses the route accepts (the journal's own allowlist). */
export type NodeRuntimeStatus = "ok" | "error" | "running";

export interface NodeRuntimeReport {
  dataflowId: string;
  nodeId: string;
  status: NodeRuntimeStatus;
  /** A render error, a compile failure, a service reason — bounded here too. */
  message?: string;
  /** What the node says it produced, when it can say (never the data). */
  outputType?: string;
  durationMs?: number;
  /** The content that ran, so the repair loop can digest-match it (dev/129). */
  code?: string;
  /**
   * What KIND of outcome this is, when the node can say (dev/136).
   * ``empty-render`` is the one that matters: a render that failed is not the
   * same problem as a render that drew nothing, and the corrections differ —
   * so the harness must not have to match prose to tell them apart.
   */
  kind?: typeof EMPTY_RENDER_KIND | string;
}

const MESSAGE_CHARS = 2000;

/** Last reported outcome per node, so a repeat costs nothing. */
const lastReported = new Map<string, string>();

function fingerprint(report: NodeRuntimeReport): string {
  return `${report.status}::${(report.message ?? "").slice(0, MESSAGE_CHARS)}::${
    report.outputType ?? ""
  }::${report.kind ?? ""}`;
}

/** Forget a node's last report (a new project, or a deliberate re-report). */
export function resetNodeRuntimeReports(nodeId?: string): void {
  if (nodeId) lastReported.delete(nodeId);
  else lastReported.clear();
}

/**
 * Post one outcome. Returns whether it was sent (false = deduplicated, or the
 * report had no identity to write against). Never rejects.
 */
export async function reportNodeRuntime(report: NodeRuntimeReport): Promise<boolean> {
  const { dataflowId, nodeId, status } = report;
  // An unsaved canvas has no project to journal against — the server would
  // no-op anyway, so do not spend the request.
  if (!dataflowId || !nodeId || !status) return false;
  const key = `${dataflowId}::${nodeId}`;
  const mark = fingerprint(report);
  if (lastReported.get(key) === mark) return false;
  lastReported.set(key, mark);
  try {
    const token = getToken();
    await fetch(`${backendUrl()}/nodeRuntime`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        dataflowId,
        nodeId,
        status,
        message: (report.message ?? "").slice(0, MESSAGE_CHARS),
        outputType: report.outputType ?? "",
        durationMs: report.durationMs ?? 0,
        code: report.code ?? "",
        kind: report.kind ?? "",
      }),
      // A node's outcome is worth reporting even if the user navigates away
      // in the same tick; the payload is small enough for the keepalive cap.
      keepalive: true,
    });
    return true;
  } catch (error) {
    // Observational by contract: a journal write can never be a user-visible
    // failure. The next real change re-reports, since the fingerprint moved.
    console.debug("[nodeRuntimeReport] could not report outcome", error);
    return true;
  }
}

/**
 * The `NodeOutput` a node instance carries → a report, or null when there is
 * nothing settled to say.
 *
 * `exec` is the transient "running" state a play sets before the result
 * arrives; it is deliberately NOT reported, because a render in flight is not
 * an outcome and the record would immediately be overwritten.
 */
export function reportFromNodeOutput(
  output: {
    code?: string;
    content?: unknown;
    outputType?: string;
    dataType?: string;
    /** dev/136: set by a renderer that knows WHY it produced nothing. */
    kind?: string;
  } | undefined,
  identity: { dataflowId: string; nodeId: string; code?: string },
): NodeRuntimeReport | null {
  const code = typeof output?.code === "string" ? output.code : "";
  if (code !== "success" && code !== "error") return null;
  const message =
    code === "error"
      ? typeof output?.content === "string" && output.content.trim()
        ? output.content
        : "This node reported an error without a message."
      : "";
  return {
    dataflowId: identity.dataflowId,
    nodeId: identity.nodeId,
    status: code === "error" ? "error" : "ok",
    message,
    outputType: output?.outputType || output?.dataType || "",
    code: identity.code ?? "",
    // dev/136: an empty render travels as itself. The renderer stamps the
    // kind; a plain failure carries none, and the harness reads the difference
    // instead of matching the message's prose.
    ...(output?.kind ? { kind: String(output.kind) } : {}),
  };
}
