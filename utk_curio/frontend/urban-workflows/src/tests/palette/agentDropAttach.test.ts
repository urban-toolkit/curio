import fs from "fs";
import path from "path";

import { attachAgentOnDrop } from "../../utils/agentDropAttach";

describe("attachAgentOnDrop", () => {
  it("saves the graph before attaching to a node, using the saved project id", async () => {
    const calls: string[] = [];
    const saveProject = jest.fn(async () => {
      calls.push("save");
      return { id: "proj-9" };
    });
    const attach = jest.fn(async () => {
      calls.push("attach");
    });
    await attachAgentOnDrop({
      projectId: "proj-9",
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
    });
    // Save must run BEFORE attach so the node is on disk when validated.
    expect(calls).toEqual(["save", "attach"]);
    expect(attach).toHaveBeenCalledWith("proj-9", "agent.x@1.0.0", { kind: "node", targetId: "n1" });
  });

  it("attaches to a node of a never-saved project using the id from the save", async () => {
    const saveProject = jest.fn(async () => ({ id: "new-proj" }));
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: undefined,
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
    });
    expect(saveProject).toHaveBeenCalledTimes(1);
    expect(attach).toHaveBeenCalledWith("new-proj", "agent.x@1.0.0", { kind: "node", targetId: "n1" });
  });

  it("falls back to the existing projectId when the save returns no id", async () => {
    const saveProject = jest.fn(async () => null);
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: "proj-1",
      target: { kind: "node", targetId: "n1" },
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
    });
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.x@1.0.0", { kind: "node", targetId: "n1" });
  });

  it("does NOT pre-save for a canvas target", async () => {
    const saveProject = jest.fn(async () => ({ id: "proj-1" }));
    const attach = jest.fn(async () => undefined);
    await attachAgentOnDrop({
      projectId: "proj-1",
      target: { kind: "canvas" },
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
    });
    expect(saveProject).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.x@1.0.0", { kind: "canvas" });
  });

  it("throws (without attaching) when no project id is resolvable for a canvas drop", async () => {
    const attach = jest.fn(async () => undefined);
    await expect(
      attachAgentOnDrop({
        projectId: undefined,
        target: { kind: "canvas" },
        agentCoord: "agent.x@1.0.0",
        saveProject: jest.fn(),
        attach,
      }),
    ).rejects.toThrow(/Save the project/i);
    expect(attach).not.toHaveBeenCalled();
  });

  it("propagates a save failure and does not attach", async () => {
    const attach = jest.fn(async () => undefined);
    await expect(
      attachAgentOnDrop({
        projectId: "proj-1",
        target: { kind: "node", targetId: "n1" },
        agentCoord: "agent.x@1.0.0",
        saveProject: jest.fn(async () => {
          throw new Error("Guest users cannot save projects");
        }),
        attach,
      }),
    ).rejects.toThrow(/cannot save/i);
    expect(attach).not.toHaveBeenCalled();
  });
});

/**
 * A hosted guest (`isHostedGuest`: a guest on a Curio started with --deploy)
 * cannot save the dataflow. A drop on a node or a connection saves first, on
 * a saved dataflow too, and a drop on the canvas needs a dataflow that was
 * saved, so those drops tell it to sign in, before any save or attach. A drop
 * on the canvas of a dataflow it has attaches as before. The deps are built
 * as variables so the hostedGuest field type-checks before it exists.
 */
describe("attachAgentOnDrop for a hosted guest", () => {
  const SIGN_IN = "Sign in to attach agents.";

  it.each([
    ["a node", { kind: "node", targetId: "n1" }],
    ["a connection", { kind: "connection", edgeId: "e1" }],
  ])("is told to sign in when it drops on %s, and nothing is saved or attached", async (_where, target) => {
    const saveProject = jest.fn(async () => ({ id: "proj-1" }));
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: "proj-1",
      target: target as never,
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toThrow(SIGN_IN);
    expect(saveProject).not.toHaveBeenCalled();
    expect(attach).not.toHaveBeenCalled();
  });

  it("is told to sign in when it drops on the canvas of a dataflow it never saved", async () => {
    const saveProject = jest.fn(async () => ({ id: "proj-1" }));
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: undefined,
      target: { kind: "canvas" } as never,
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toThrow(SIGN_IN);
    expect(saveProject).not.toHaveBeenCalled();
    expect(attach).not.toHaveBeenCalled();
  });

  it("attaches to the canvas of a dataflow it has, as before", async () => {
    const saveProject = jest.fn(async () => ({ id: "proj-1" }));
    const attach = jest.fn(async () => undefined);
    const deps = {
      projectId: "proj-1",
      target: { kind: "canvas" } as never,
      agentCoord: "agent.x@1.0.0",
      saveProject,
      attach,
      hostedGuest: true,
    };

    await attachAgentOnDrop(deps);

    expect(saveProject).not.toHaveBeenCalled();
    expect(attach).toHaveBeenCalledWith("proj-1", "agent.x@1.0.0", { kind: "canvas" });
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
      agentCoord: "agent.x@1.0.0",
      saveProject: jest.fn(async () => ({ id: "proj-1" })),
      attach: jest.fn(async () => undefined),
      hostedGuest: true,
    };

    await expect(attachAgentOnDrop(deps)).rejects.toMatchObject({ message: SIGN_IN, toastVariant: "warning" });
    // The canvas shows a drop's failure with the kind the failure carries.
    const src = fs.readFileSync(path.resolve(__dirname, "../../components/MainCanvas.tsx"), "utf8");
    expect(src).toMatch(/"Attach failed\."\s*,\s*e\?\.toastVariant\s*\?\?\s*"error"/);
  });
});
