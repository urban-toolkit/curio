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
