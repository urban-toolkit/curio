import fs from "fs";
import path from "path";

import type { AgentDropTarget } from "../../services/agents";
import { attachAgentOnDrop } from "../../utils/agentDropAttach";

describe("attachAgentOnDrop", () => {
  it("waits for the server to hold the graph before attaching to a node, using the dataflow's id", async () => {
    const calls: string[] = [];
    const keepDataflow = jest.fn(async () => {
      calls.push("keep");
      return "proj-9";
    });
    const attach = jest.fn(async () => {
      calls.push("attach");
    });
    await attachAgentOnDrop({
      projectId: "proj-9",
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });
    // The wait runs BEFORE attach, so the node is the server's when validated.
    expect(calls).toEqual(["keep", "attach"]);
    expect(attach).toHaveBeenCalledWith("proj-9", "agent.test.x@1", { kind: "node", targetId: "n1" });
  });

  it("an invited editor's drop on a node or a connection makes nothing, and waits for the editor's last change", async () => {
    // The editor's tab makes no dataflow: its canvas is bound to the
    // dataflow's doc on the server, which the attach reads, so the node the
    // editor just added reaches the server first, as the owner's does.
    for (const target of [
      { kind: "node" as const, targetId: "n1" },
      { kind: "connection" as const, targetId: "e1" },
    ]) {
      const calls: string[] = [];
      const keepDataflow = jest.fn(async () => "owners-proj");
      const whenKept = jest.fn(async () => {
        calls.push("kept");
        return true;
      });
      const attach = jest.fn(async () => {
        calls.push("attach");
      });
      await attachAgentOnDrop({
        projectId: "owners-proj",
        target,
        agentCoord: "agent.test.x@1",
        keepDataflow,
        attach,
        savesHere: false,
        whenKept,
      });
      expect(keepDataflow).not.toHaveBeenCalled();
      expect(calls).toEqual(["kept", "attach"]);
      expect(attach).toHaveBeenCalledWith("owners-proj", "agent.test.x@1", target);
    }
  });

  it("an invited editor's drop on the canvas waits for nothing", async () => {
    const whenKept = jest.fn(async () => true);
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: "owners-proj",
      target: { kind: "canvas" },
      agentCoord: "agent.test.x@1",
      keepDataflow: jest.fn(),
      attach,
      savesHere: false,
      whenKept,
    });
    expect(whenKept).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("owners-proj", "agent.test.x@1", { kind: "canvas" });
  });

  it("attaches to a node of a never-saved project using the id of the dataflow made for it", async () => {
    const keepDataflow = jest.fn(async () => "new-proj");
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: undefined,
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });
    expect(keepDataflow).toHaveBeenCalledTimes(1);
    expect(attach).toHaveBeenCalledWith("new-proj", "agent.test.x@1", { kind: "node", targetId: "n1" });
  });

  it("falls back to the existing projectId when the wait returns no id", async () => {
    const keepDataflow = jest.fn(async () => null);
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: "proj-1",
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.test.x@1", { kind: "node", targetId: "n1" });
  });

  it("does NOT wait for a canvas target", async () => {
    const keepDataflow = jest.fn(async () => "proj-1");
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: "proj-1",
      target: { kind: "canvas" },
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });
    expect(keepDataflow).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.test.x@1", { kind: "canvas" });
  });

  it("throws (without attaching) when no project id is resolvable for a canvas drop", async () => {
    const attach = jest.fn(async () => undefined);
    await expect(
      attachAgentOnDrop({
        projectId: undefined,
        target: { kind: "canvas" },
        agentCoord: "agent.test.x@1",
        keepDataflow: jest.fn(),
        attach,
      }),
    ).rejects.toThrow(/Save the project/i);
    expect(attach).not.toHaveBeenCalled();
  });

  it("propagates a failure of the wait and does not attach", async () => {
    const attach = jest.fn(async () => undefined);
    await expect(
      attachAgentOnDrop({
        projectId: "proj-1",
        target: { kind: "node", targetId: "n1" },
        agentCoord: "agent.test.x@1",
        keepDataflow: jest.fn(async () => {
          throw new Error("Guest users cannot save projects");
        }),
        attach,
      }),
    ).rejects.toThrow(/cannot save/i);
    expect(attach).not.toHaveBeenCalled();
  });

  it("is handed the canvas's wait for the server, never a save", () => {
    const src = fs.readFileSync(path.resolve(__dirname, "../../components/MainCanvas.tsx"), "utf8");
    expect(src).toMatch(/attachAgentOnDrop\(\{[^}]*\bkeepDataflow:\s*ensureProjectId\b[^}]*\}\)/);
    // An editor's drop waits for the editor's last change the same way.
    expect(src).toMatch(/attachAgentOnDrop\(\{[^}]*\bwhenKept:\s*whenChangesKept\b[^}]*\}\)/);
    expect(src).not.toMatch(/requestProjectSave/);
  });
});

/**
 * A drop on a canvas whose dataflow has no id yet, as File > New's canvas has
 * until its first action that needs one: the dataflow is made first
 * (`keepDataflow`, `ensureProjectId`), then the agent is attached to it, on a
 * node, a connection or the canvas alike. A hosted guest (`isHostedGuest`: a
 * guest on a Curio started with --deploy) drops as an account does: the
 * dataflow made for it is its own, kept until the server starts again, and
 * nothing tells it to sign in.
 */
describe("attachAgentOnDrop on a dataflow not saved yet", () => {
  it.each([
    ["a node", { kind: "node", targetId: "n1" }],
    ["a connection", { kind: "connection", targetId: "e1" }],
    ["the canvas", { kind: "canvas" }],
  ])("makes the dataflow first when it drops on %s, then attaches to it", async (_where, target) => {
    const calls: string[] = [];
    const keepDataflow = jest.fn(async () => {
      calls.push("keep");
      return "proj-new";
    });
    const attach = jest.fn(async () => {
      calls.push("attach");
    });

    await attachAgentOnDrop({
      projectId: undefined,
      target: target as AgentDropTarget,
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });

    // The dataflow is made BEFORE the attach, which names it.
    expect(calls).toEqual(["keep", "attach"]);
    expect(keepDataflow).toHaveBeenCalledTimes(1);
    expect(attach).toHaveBeenCalledWith("proj-new", "agent.test.x@1", target);
  });

  it("attaches to the canvas of a dataflow it has at once", async () => {
    const keepDataflow = jest.fn(async () => "proj-1");
    const attach = jest.fn(async () => undefined);

    await attachAgentOnDrop({
      projectId: "proj-1",
      target: { kind: "canvas" },
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
    });

    expect(keepDataflow).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.test.x@1", { kind: "canvas" });
  });

  it("tells no one to sign in: the canvas hands the drop no viewer, and its failure shows as an error", () => {
    const helper = fs.readFileSync(path.resolve(__dirname, "../../utils/agentDropAttach.ts"), "utf8");
    expect(helper).not.toMatch(/hostedGuest|Sign in/);
    const src = fs.readFileSync(path.resolve(__dirname, "../../components/MainCanvas.tsx"), "utf8");
    expect(src).toMatch(/attachAgentOnDrop\(\{[^}]*\bkeepDataflow:\s*ensureProjectId\b[^}]*\}\)/);
    expect(src).not.toMatch(/attachAgentOnDrop\(\{[^}]*\bhostedGuest\b[^}]*\}\)/);
    expect(src).toMatch(/"Attach failed\."\s*,\s*"error"/);
  });
});
