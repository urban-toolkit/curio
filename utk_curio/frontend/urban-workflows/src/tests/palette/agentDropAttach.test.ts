import fs from "fs";
import path from "path";

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
    expect(src).not.toMatch(/requestProjectSave/);
  });
});

/**
 * A hosted guest (`isHostedGuest`: a guest on a Curio started with --deploy)
 * cannot save the dataflow. A drop on a node or a connection needs the server
 * to hold the graph, on a saved dataflow too, and a drop on the canvas needs a
 * dataflow that was saved, so those drops tell it to sign in, before anything
 * is sent. A drop on the canvas of a dataflow it has attaches as before. The
 * deps are built as variables so the hostedGuest field type-checks before it
 * exists.
 */
describe("attachAgentOnDrop for a hosted guest", () => {
  const SIGN_IN = "Sign in to attach agents.";

  it.each([
    ["a node", { kind: "node", targetId: "n1" }],
    ["a connection", { kind: "connection", edgeId: "e1" }],
  ])("is told to sign in when it drops on %s, and nothing is sent or attached", async (_where, target) => {
    const keepDataflow = jest.fn(async () => "proj-1");
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: "proj-1",
      target: target as never,
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toThrow(SIGN_IN);
    expect(keepDataflow).not.toHaveBeenCalled();
    expect(attach).not.toHaveBeenCalled();
  });

  it("is told to sign in when it drops on the canvas of a dataflow it never saved", async () => {
    const keepDataflow = jest.fn(async () => "proj-1");
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: undefined,
      target: { kind: "canvas" } as never,
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toThrow(SIGN_IN);
    expect(keepDataflow).not.toHaveBeenCalled();
    expect(attach).not.toHaveBeenCalled();
  });

  it("attaches to the canvas of a dataflow it has, as before", async () => {
    const keepDataflow = jest.fn(async () => "proj-1");
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: "proj-1",
      target: { kind: "canvas" } as never,
      agentCoord: "agent.test.x@1",
      keepDataflow,
      attach,
      hostedGuest: true,
    };

    await attachAgentOnDrop(deps);

    expect(keepDataflow).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.test.x@1", { kind: "canvas" });
  });

  it("is what the canvas's agent drop is told about who drops", () => {
    // The canvas knows the viewer; the drop above only knows what it is handed.
    const src = fs.readFileSync(path.resolve(__dirname, "../../components/MainCanvas.tsx"), "utf8");
    expect(src).toMatch(/attachAgentOnDrop\(\{[^}]*\bhostedGuest\b[^}]*\}\)/);
  });

  it("is a note, shown with the toast kind the other sign-in notes use", async () => {
    const deps = {
      projectId: "proj-1",
      target: { kind: "node", targetId: "n1" } as never,
      agentCoord: "agent.test.x@1",
      keepDataflow: jest.fn(async () => "proj-1"),
      attach: jest.fn(async () => undefined),
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toMatchObject({ message: SIGN_IN, toastVariant: "warning" });
    // The canvas shows a drop's failure with the kind the failure carries.
    const src = fs.readFileSync(path.resolve(__dirname, "../../components/MainCanvas.tsx"), "utf8");
    expect(src).toMatch(/"Attach failed\."\s*,\s*e\?\.toastVariant\s*\?\?\s*"error"/);
  });
});
