/**
 * Attaching an agent to a connection.
 *
 * The backend has accepted `target.kind === "connection"` all along: the
 * manifest parser lists it in `_TARGET_KINDS`, `attachments.attach` validates
 * the id against the spec's edges, and orphan pruning handles it. The palette
 * pill, the card tag, the "Attaches to: connection" line and the guide all
 * advertised the gesture. Only the frontend never produced one: the drop target
 * union stopped at node | canvas and the canvas hit-tested nodes only, so
 * dropping a connection agent on an edge silently attached it to the canvas and
 * reported success.
 */

import { pickEdgeAtPoint, type AgentDropTarget } from "../../utils/agentCatalogEvents";
import { attachAgentOnDrop } from "../../utils/agentDropAttach";
import { composeAgentRunContext } from "../../components/agents/attach/agentRunContext";

describe("pickEdgeAtPoint", () => {
  const atPoint = (el: Element | null) => {
    (document as any).elementFromPoint = jest.fn(() => el);
  };

  afterEach(() => {
    delete (document as any).elementFromPoint;
  });

  it("reads the edge id off a real React Flow 11 edge group", () => {
    // Hit-tested through the DOM because React Flow renders a wide invisible
    // interaction path over each curve; re-deriving bezier geometry here would
    // be a second, worse source of truth for where an edge is.
    //
    // The markup here is what @reactflow/core@11 actually renders: the edge
    // group gets `data-testid="rf__edge-<id>"` and NO `data-id` - only nodes
    // get that. An earlier version of this test hand-set `data-id` on the
    // group, which asserted the implementation's assumption rather than React
    // Flow's output, so it stayed green while dropping an agent on a connection
    // could never work in a browser.
    const group = document.createElement("div");
    group.className = "react-flow__edge";
    group.setAttribute("data-testid", "rf__edge-edge-42");
    const path = document.createElement("div");
    path.className = "react-flow__edge-interaction";
    group.appendChild(path);
    document.body.appendChild(group);
    atPoint(path);

    expect(pickEdgeAtPoint(10, 10)).toBe("edge-42");
    document.body.removeChild(group);
  });

  it("prefers data-id when a future React Flow provides one", () => {
    const group = document.createElement("div");
    group.className = "react-flow__edge";
    group.setAttribute("data-id", "edge-42");
    group.setAttribute("data-testid", "rf__edge-stale");
    document.body.appendChild(group);
    atPoint(group);

    expect(pickEdgeAtPoint(10, 10)).toBe("edge-42");
    document.body.removeChild(group);
  });

  it("is null over empty canvas", () => {
    atPoint(document.createElement("div"));
    expect(pickEdgeAtPoint(10, 10)).toBeNull();
  });

  it("is null when the element carries no edge id", () => {
    const group = document.createElement("div");
    group.className = "react-flow__edge";
    document.body.appendChild(group);
    atPoint(group);
    expect(pickEdgeAtPoint(10, 10)).toBeNull();
    document.body.removeChild(group);
  });
});

describe("attachAgentOnDrop with a connection target", () => {
  it("persists the graph first, like a node target", async () => {
    // The backend validates the target id against the SAVED spec, so a drop
    // onto a freshly drawn edge 400s without this flush.
    const saveProject = jest.fn().mockResolvedValue({ id: "p1" });
    const attach = jest.fn().mockResolvedValue(undefined);
    const target: AgentDropTarget = { kind: "connection", targetId: "edge-7" };

    await attachAgentOnDrop({
      projectId: null,
      target,
      agentCoord: "agent.connection-builder@1.0.0",
      saveProject,
      attach,
    });

    expect(saveProject).toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("p1", "agent.connection-builder@1.0.0", target);
  });

  it("still skips the flush for a canvas target", async () => {
    const saveProject = jest.fn();
    const attach = jest.fn().mockResolvedValue(undefined);

    await attachAgentOnDrop({
      projectId: "p1",
      target: { kind: "canvas" },
      agentCoord: "agent.chat-agent@1.0.0",
      saveProject,
      attach,
    });

    expect(saveProject).not.toHaveBeenCalled();
  });
});

describe("the connectionSide fragment", () => {
  it("names both ends in the vocabulary the prompt expects", () => {
    // new_connection_prompt.txt expects to be "informed if the nodes you are
    // suggesting will be connected into the input or output of the node", so
    // the fragment speaks in inputs and outputs rather than source/target.
    // Before edge attach existed, connectionSide had no producer at all and
    // Connection Builder's declared read composed to nothing.
    const attachment: any = {
      attachmentId: "att-1",
      coord: "agent.connection-builder@1.0.0",
      target: { kind: "connection", targetId: "edge-7" },
      reads: ["connectionSide"],
    };
    const canvas = {
      nodes: [],
      edges: [{ id: "edge-7", source: "node-a", target: "node-b" }],
      workflowName: "wf",
      workflowGoal: "",
    };

    const out = composeAgentRunContext(attachment, canvas as any);
    expect(out).toContain("the output of node node-a");
    expect(out).toContain("the input of node node-b");
  });

  it("composes nothing when the edge is gone", () => {
    const attachment: any = {
      attachmentId: "att-1",
      coord: "agent.connection-builder@1.0.0",
      target: { kind: "connection", targetId: "edge-missing" },
      reads: ["connectionSide"],
    };
    const canvas = { nodes: [], edges: [], workflowName: "wf", workflowGoal: "" };
    expect(composeAgentRunContext(attachment, canvas as any)).toBeNull();
  });
});
