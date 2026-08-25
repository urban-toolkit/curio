import { TrillGenerator } from "../../../TrillGenerator";
import type { AgentAttachment } from "../../../api/agentsApi";

/**
 * The live-canvas grounded-context composer (memo dev/44).
 *
 * Attachment runs carry the inputs their manifests declare (`inputs.reads`,
 * dev/38) exactly as the legacy call sites pushed them — composed from the
 * LIVE ReactFlow state on every send, so unsaved/new nodes are covered and
 * stale values are structurally impossible. The result rides the run
 * request's ephemeral `context` field: never persisted, never replayed.
 *
 * Node Content Builder reproduces the legacy Get Code framing byte-for-byte
 * (`clickGenerateContentNode` in styles.tsx): the Trill with the target
 * node's content blanked, then Node ID / Subtask / Task. Every other agent
 * assembles generic per-read fragments (canonical labels from its legacy
 * site) in the manifest's declared order. Reads with no chat-time source
 * (`connectionSide`, `keywords`, `currentTask`, `userMessage` — the user's
 * message carries the intent) are omitted, per the dev/44 audit table.
 */

export interface AgentCanvasState {
  nodes: unknown[];
  edges: unknown[];
  workflowName: string;
  workflowGoal: string;
}

type TrillNode = { id?: string; content?: string; type?: string; goal?: string };

function liveTrill(canvas: AgentCanvasState): { dataflow?: { nodes?: TrillNode[] } } {
  return TrillGenerator.generateTrill(
    canvas.nodes,
    canvas.edges,
    canvas.workflowName,
    canvas.workflowGoal,
  );
}

function targetNodeId(attachment: AgentAttachment): string | null {
  return attachment.target.kind === "node" ? (attachment.target.targetId ?? null) : null;
}

function findTrillNode(trill: ReturnType<typeof liveTrill>, nodeId: string | null): TrillNode | null {
  if (!nodeId) return null;
  return trill.dataflow?.nodes?.find((n) => n.id === nodeId) ?? null;
}

/** Legacy Get Code framing (styles.tsx `generateContentNode`), byte-faithful:
 * the target node's content is blanked in the Trill before it is sent. */
function nodeContentBuilderContext(
  attachment: AgentAttachment,
  canvas: AgentCanvasState,
): string | null {
  const nodeId = targetNodeId(attachment);
  if (!nodeId) return null;
  const trill = liveTrill(canvas);
  let subtask = "";
  for (const node of trill.dataflow?.nodes ?? []) {
    if (node.id === nodeId) {
      subtask = node.goal ?? "";
      node.content = ""; // legacy parity: regenerate fresh, never echo old code
    }
  }
  return (
    "Current Trill: " + JSON.stringify(trill) + "\n" +
    " Node ID: " + nodeId + "\n" +
    "Subtask: " + subtask + " Task: " + "\n" + canvas.workflowGoal
  );
}

/** Generic per-read fragments (canonical labels from the legacy call sites). */
function readFragment(
  read: string,
  attachment: AgentAttachment,
  canvas: AgentCanvasState,
): string | null {
  const nodeId = targetNodeId(attachment);
  switch (read) {
    case "dataflowContext":
      return "Current Trill: " + JSON.stringify(liveTrill(canvas));
    case "nodeId":
      return nodeId ? "Node ID: " + nodeId : null;
    case "subtask": {
      const node = findTrillNode(liveTrill(canvas), nodeId);
      return node?.goal ? "Subtask: " + node.goal : null;
    }
    case "workflowGoal":
      return canvas.workflowGoal ? "Task: " + canvas.workflowGoal : null;
    case "nodeContext": {
      const node = findTrillNode(liveTrill(canvas), nodeId);
      if (!node) return null;
      // Legacy NodeExplanation payload shape; in/out empty when unexecuted.
      return JSON.stringify({
        id: node.id,
        type: node.type ?? "",
        content: node.content ?? "",
        current_input: "",
        current_output: "",
      });
    }
    case "codeContext":
    case "nodeContent": {
      const node = findTrillNode(liveTrill(canvas), nodeId);
      return node?.content ? "Node content: " + node.content : null;
    }
    case "nodeType": {
      const node = findTrillNode(liveTrill(canvas), nodeId);
      return node?.type ? "Node type: " + node.type : null;
    }
    // dev/67-2: the P5 composites' declared reads finally have producers —
    // before this, all three composed `null` and ran context-blind ("I don't
    // have the full dataflow edges" was literally true).
    case "graphContext":
      // The builder's full live-canvas view: nodes AND edges, unsaved included.
      return "Current Trill: " + JSON.stringify(liveTrill(canvas));
    case "mission": {
      const parts = [
        canvas.workflowName ? "Workflow: " + canvas.workflowName : null,
        canvas.workflowGoal ? "Mission: " + canvas.workflowGoal : null,
      ].filter((p): p is string => p != null);
      return parts.length ? parts.join("\n") : null;
    }
    case "installedTemplates":
      // RETIRED (memo dev/93 D3/commit 4). This used to compose "Installed
      // node templates" from the client registry's palette — and the server
      // already appends the authoritative "Available node templates" roster to
      // the same run. Two lists, two headings, two spellings (the client keys
      // descriptors VERSIONED, the server's roster is unversioned) and two
      // scopes: the palette can name templates this PROJECT cannot
      // instantiate. A Dataflow Builder quoted `curio.builtin/data-loading@1`
      // from this list, was refused by the plan validator, and looped. The
      // server block is now gated on every grant that declares this read, so
      // dropping the producer removes the contradiction without leaving any
      // agent roster-less. The declared read stays on the manifests (no
      // manifest churn); it simply composes nothing.
      return null;
    case "nodeIntent": {
      const node = findTrillNode(liveTrill(canvas), nodeId);
      return node?.goal ? "Node intent: " + node.goal : null;
    }
    case "targetContext": {
      // Node target → that node's snapshot; canvas target → the whole graph.
      if (nodeId) {
        const node = findTrillNode(liveTrill(canvas), nodeId);
        if (!node) return null;
        return (
          "Target node: " +
          JSON.stringify({
            id: node.id,
            type: node.type ?? "",
            goal: node.goal ?? "",
            content: node.content ?? "",
          })
        );
      }
      return "Current Trill: " + JSON.stringify(liveTrill(canvas));
    }
    default:
      // connectionSide / keywords / currentTask / userMessage /
      // externalSelection (arrives via the confirmation prompt) / catalog
      // (tool-served — catalog.search is the truth): no chat-time source;
      // dev/44 audit table + dev/67-2 §3.
      return null;
  }
}

/**
 * Compose the run's grounded context for one attachment, or `null` when the
 * agent declares nothing composable (e.g. the chat agent).
 */
export function composeAgentRunContext(
  attachment: AgentAttachment,
  canvas: AgentCanvasState,
): string | null {
  if (attachment.coord.startsWith("agent.node-content-builder@")) {
    return nodeContentBuilderContext(attachment, canvas);
  }
  const reads = attachment.reads ?? [];
  const fragments = reads
    .map((read) => readFragment(read, attachment, canvas))
    .filter((f): f is string => f != null);
  return fragments.length ? fragments.join("\n") : null;
}
