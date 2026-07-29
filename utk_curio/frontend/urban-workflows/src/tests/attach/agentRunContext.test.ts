import { TrillGenerator } from "../../TrillGenerator";
import { composeAgentRunContext } from "../../components/agents/attach/agentRunContext";
import type { AgentAttachment } from "../../api/agentsApi";

/**
 * Grounded-context composer parity tests (memo dev/44): the Node Content
 * Builder framing must match the legacy Get Code flow
 * (`clickGenerateContentNode` in styles.tsx) byte-for-byte.
 */

const attachment = (over: Partial<AgentAttachment>): AgentAttachment => ({
  attachmentId: "a1",
  coord: "agent.chat-agent@1.0.0",
  target: { kind: "canvas" },
  sessionId: "s1",
  revision: 1,
  name: "X",
  category: "node",
  hooks: [],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
  ...over,
});

// Minimal live ReactFlow-shaped nodes — including an UNSAVED node (present on
// the canvas only, never persisted): the composer must still see it.
const nodes = [
  {
    id: "n1",
    type: "CODE",
    position: { x: 0, y: 0 },
    data: { nodeId: "n1", nodeType: "CODE", code: "print('old')", goal: "load the data" },
  },
  {
    id: "n2-unsaved",
    type: "CODE",
    position: { x: 10, y: 10 },
    data: { nodeId: "n2-unsaved", nodeType: "CODE", code: "", goal: "brand new" },
  },
];
const canvas = { nodes, edges: [], workflowName: "wf", workflowGoal: "analyze heat risk" };

// TrillGenerator stamps Date.now() into every spec — pin it so two
// independently generated trills compare byte-for-byte.
beforeEach(() => jest.spyOn(Date, "now").mockReturnValue(1_700_000_000_000));
afterEach(() => jest.restoreAllMocks());

describe("composeAgentRunContext (memo dev/44)", () => {
  it("Node Content Builder matches the legacy Get Code framing byte-for-byte", () => {
    const att = attachment({
      coord: "agent.node-content-builder@1.0.0",
      target: { kind: "node", targetId: "n1" },
      reads: ["dataflowContext", "nodeId", "subtask", "workflowGoal"],
    });
    const context = composeAgentRunContext(att, canvas);
    // Reproduce the legacy composition independently (styles.tsx:477-493).
    const trill = TrillGenerator.generateTrill(nodes, [], "wf", "analyze heat risk");
    let goal = "";
    for (const node of trill.dataflow.nodes) {
      if (node.id === "n1") {
        goal = node.goal ?? "";
        node.content = ""; // legacy blanks the target's content
      }
    }
    const legacy =
      "Current Trill: " + JSON.stringify(trill) + "\n" +
      " Node ID: n1\n" +
      "Subtask: " + goal + " Task: " + "\n" + "analyze heat risk";
    expect(context).toBe(legacy);
    // The blanking is real: the target's old code never reaches the model…
    expect(context).not.toContain("print('old')");
    // …and the unsaved canvas-only node IS included.
    expect(context).toContain("n2-unsaved");
  });

  it("generic reads compose labeled fragments in declared order", () => {
    const att = attachment({
      coord: "agent.workflow-suggester@1.0.0",
      reads: ["dataflowContext", "workflowGoal"],
    });
    const context = composeAgentRunContext(att, canvas)!;
    expect(context.startsWith("Current Trill: ")).toBe(true);
    expect(context).toContain("\nTask: analyze heat risk");
  });

  it("node-scoped reads resolve from the attached node", () => {
    const att = attachment({
      coord: "agent.node-explainer@1.0.0",
      target: { kind: "node", targetId: "n1" },
      reads: ["nodeContext"],
    });
    const context = composeAgentRunContext(att, canvas)!;
    const payload = JSON.parse(context);
    expect(payload.id).toBe("n1");
    expect(payload).toHaveProperty("current_input");
    expect(payload).toHaveProperty("current_output");
  });

  it("node-scoped reads are omitted for canvas attachments", () => {
    const att = attachment({
      coord: "agent.execution-subtask-planner@1.0.0",
      target: { kind: "canvas" },
      reads: ["nodeContent", "nodeType", "currentTask"],
    });
    // currentTask has no chat-time source; node fields need a node target.
    expect(composeAgentRunContext(att, canvas)).toBeNull();
  });

  it("agents with no composable reads yield null (chat agent)", () => {
    const att = attachment({ reads: ["userMessage"] });
    expect(composeAgentRunContext(att, canvas)).toBeNull();
  });
});
