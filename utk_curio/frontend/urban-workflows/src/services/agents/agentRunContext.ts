import { TrillGenerator } from "../../TrillGenerator";
import type { Scenario } from "../../utils/scenarios/scenarioModel";
import type { AgentAttachment } from "./types";
import { incomingSourceIds } from "../../utils/nodeEmptyState";
import {
  type Feeder,
  storeOutputFor,
  summarizeNodeInput,
  summarizeNodeOutput,
} from "../../utils/nodeRuntimeSummary";

/**
 * The live-canvas grounded-context composer (memo dev/44).
 *
 * Attachment runs carry the inputs their manifests declare (`inputs.reads`,
 * dev/38) exactly as the legacy call sites pushed them — composed from the
 * LIVE ReactFlow state on every send, so unsaved/new nodes are covered and
 * stale values are structurally impossible. The result rides the run
 * request's ephemeral `context` field: never persisted, never replayed.
 *
 * Every agent assembles generic per-read fragments (canonical labels from its
 * legacy site) in the manifest's declared order. Reads with no chat-time source
 * (`connectionSide`, `keywords`, `currentTask`, `userMessage` — the user's
 * message carries the intent) are omitted, per the dev/44 audit table.
 */

export interface AgentCanvasState {
  nodes: unknown[];
  edges: unknown[];
  workflowName: string;
  workflowGoal: string;
  /** dev/129 (porting dev/111): the FlowProvider's produced artifacts, so
   *  `current_output` can name one. Optional — every other caller is
   *  unchanged. */
  outputs?: Array<{ nodeId?: string; output?: unknown }>;
  /** #662: the dataflow's scenarios, which an agent's view carries only when
   *  there are some. */
  scenarios?: Scenario[];
}

type TrillNode = { id?: string; content?: string; type?: string; goal?: string };

function liveTrill(canvas: AgentCanvasState): { dataflow?: { nodes?: TrillNode[] } } {
  return TrillGenerator.generateTrill(
    canvas.nodes,
    canvas.edges,
    canvas.workflowName,
    canvas.workflowGoal,
    undefined,
    undefined,
    undefined,
    undefined,
    canvas.scenarios && canvas.scenarios.length > 0 ? canvas.scenarios : undefined,
  );
}

/** The LIVE ReactFlow node (its `data` carries input/output state), or null. */
function findLiveNode(
  nodes: unknown[],
  nodeId: string,
): { data?: Record<string, unknown> } | null {
  if (!Array.isArray(nodes)) return null;
  const found = nodes.find(
    (n) => (n as { id?: string } | null)?.id === nodeId,
  ) as { data?: Record<string, unknown> } | undefined;
  return found ?? null;
}

function targetNodeId(attachment: AgentAttachment): string | null {
  return attachment.target.kind === "node" ? (attachment.target.targetId ?? null) : null;
}

function findTrillNode(trill: ReturnType<typeof liveTrill>, nodeId: string | null): TrillNode | null {
  if (!nodeId) return null;
  return trill.dataflow?.nodes?.find((n) => n.id === nodeId) ?? null;
}

/**
 * The nodes feeding *nodeId*, as its body asks when it has nothing to show
 * (`incomingSourceIds`: data edges only, once each in the canvas's order),
 * with the ids and types the Trill gives them and their live state. With
 * them, a node with no input yet says what it waits for, not that nothing
 * feeds it.
 */
function feedersOf(
  trill: ReturnType<typeof liveTrill>,
  canvas: AgentCanvasState,
  nodeId: string,
): Feeder[] {
  const edges = (Array.isArray(canvas.edges) ? canvas.edges : []) as Parameters<typeof incomingSourceIds>[0];
  return incomingSourceIds(edges, nodeId).flatMap((id) => {
    const node = findTrillNode(trill, id);
    if (!node) return [];
    return [{
      id,
      type: node.type ?? "",
      data: findLiveNode(canvas.nodes, id)?.data,
      storeOutput: storeOutputFor(canvas.outputs, id),
    }];
  });
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
    case "connectionSide": {
      // Only an agent attached to a connection has a side. The Node Builder's
      // chat suggests nodes for the input side or the output side of a node,
      // so name both ends in those terms rather than inventing a
      // source/target framing the prompt does not use.
      if (attachment.target.kind !== "connection") return null;
      const edge = (canvas.edges as { id?: string; source?: string; target?: string }[])
        .find((e) => e?.id === attachment.target.targetId);
      if (!edge?.source || !edge?.target) return null;
      return (
        "Connection: the output of node " + edge.source +
        " into the input of node " + edge.target
      );
    }
    case "nodeContext": {
      const trill = liveTrill(canvas);
      const node = findTrillNode(trill, nodeId);
      if (!node) return null;
      // dev/111, ported here by dev/129: these two were sent EMPTY, so every
      // agent asked about a node was told nothing about what it received or
      // produced. They now carry a bounded, truthful runtime summary — never
      // the output's content.
      const live = nodeId ? findLiveNode(canvas.nodes, nodeId) : null;
      return JSON.stringify({
        id: node.id,
        type: node.type ?? "",
        content: node.content ?? "",
        current_input: live ? summarizeNodeInput(live.data, feedersOf(trill, canvas, nodeId ?? "")) : "",
        current_output: live
          ? summarizeNodeOutput(live.data, storeOutputFor(canvas.outputs, nodeId ?? ""))
          : "",
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
        const trill = liveTrill(canvas);
        const node = findTrillNode(trill, nodeId);
        if (!node) return null;
        // dev/135: the snapshot used to be {id, type, goal, content} — no
        // runtime state at all — so the Node Builder attached to a node that
        // was visibly RED replied "since the node has never been executed…"
        // (the owner's `a29d1ad8`). It was an accurate report of an empty
        // context. The live summary rides both node reads now, in the same
        // words `nodeContext` and the server's own composer use.
        const live = findLiveNode(canvas.nodes, nodeId);
        return (
          "Target node: " +
          JSON.stringify({
            id: node.id,
            type: node.type ?? "",
            goal: node.goal ?? "",
            content: node.content ?? "",
            current_input: live ? summarizeNodeInput(live.data, feedersOf(trill, canvas, nodeId)) : "",
            current_output: live
              ? summarizeNodeOutput(live.data, storeOutputFor(canvas.outputs, nodeId))
              : "",
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
 * agent declares nothing composable (e.g. only `userMessage`).
 *
 * An attachment that reads both `targetContext` and `dataflowContext` (the
 * Researcher) gets the whole dataflow once: away from a node, `targetContext`
 * already IS the live Trill, so `dataflowContext` composes nothing there. On a
 * node, `targetContext` is that node's snapshot and both compose.
 */
export function composeAgentRunContext(
  attachment: AgentAttachment,
  canvas: AgentCanvasState,
): string | null {
  const reads = attachment.reads ?? [];
  const targetIsTheDataflow = reads.includes("targetContext") && targetNodeId(attachment) == null;
  const fragments = reads
    .filter((read) => !(read === "dataflowContext" && targetIsTheDataflow))
    .map((read) => readFragment(read, attachment, canvas))
    .filter((f): f is string => f != null);
  return fragments.length ? fragments.join("\n") : null;
}
