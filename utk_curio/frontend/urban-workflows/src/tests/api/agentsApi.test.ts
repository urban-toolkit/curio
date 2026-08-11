/**
 * Unit tests for the /api/agents client. `apiFetch` is mocked so each method's
 * URL / verb / body / param-escaping is asserted without a real request.
 */

jest.mock("../../utils/authApi", () => ({
  apiFetch: jest.fn(() => Promise.resolve({ agents: [] })),
  getToken: jest.fn(),
}));

import { apiFetch } from "../../utils/authApi";
import { agentsApi } from "../../api/agentsApi";

const mockFetch = apiFetch as jest.Mock;

beforeEach(() => mockFetch.mockClear());

describe("agentsApi", () => {
  it("catalog() hits the global catalog, with optional projectId", () => {
    agentsApi.catalog();
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/catalog");
    agentsApi.catalog("proj 1");
    expect(mockFetch).toHaveBeenLastCalledWith("/api/agents/catalog?projectId=proj%201");
  });

  it("listImports() GETs the My Imports scope", () => {
    agentsApi.listImports();
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/imports");
  });

  it("import() POSTs the coord", () => {
    agentsApi.import("agent.node-explainer@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/imports", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.node-explainer@1.0.0" }),
    });
  });

  it("removeImport() DELETEs an escaped coord", () => {
    agentsApi.removeImport("agent.node-explainer@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/imports/agent.node-explainer%401.0.0",
      { method: "DELETE" },
    );
  });

  it("listProjectAgents() GETs the project scope", () => {
    agentsApi.listProjectAgents("p1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1");
  });

  it("installToProject() POSTs the coord to the install path", () => {
    agentsApi.installToProject("p1", "agent.chat-agent@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/install", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.chat-agent@1.0.0" }),
    });
  });

  it("uninstallFromProject() DELETEs the escaped coord under the project", () => {
    agentsApi.uninstallFromProject("p1", "agent.chat-agent@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/agent.chat-agent%401.0.0",
      { method: "DELETE" },
    );
  });

  it("publish() POSTs the coord to publications", () => {
    agentsApi.publish("agent.my-custom@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/publications", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.my-custom@1.0.0" }),
    });
  });

  it("unpublish() DELETEs the escaped coord under publications", () => {
    agentsApi.unpublish("agent.my-custom@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/publications/agent.my-custom%401.0.0", {
      method: "DELETE",
    });
  });

  it("listAttachments() GETs the project attachments", () => {
    agentsApi.listAttachments("p1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments");
  });

  it("attach() POSTs coord + target", () => {
    agentsApi.attach("p1", "agent.node-explainer@1.0.0", { kind: "canvas" });
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments", {
      method: "POST",
      body: JSON.stringify({ coord: "agent.node-explainer@1.0.0", target: { kind: "canvas" } }),
    });
  });

  it("detachAttachment() DELETEs the attachment", () => {
    agentsApi.detachAttachment("p1", "att-1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1", {
      method: "DELETE",
    });
  });

  it("runAttachment() POSTs the message to /run", () => {
    agentsApi.runAttachment("p1", "att-1", "hi");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1/run", {
      method: "POST",
      body: JSON.stringify({ message: "hi" }),
    });
  });

  it("updateAttachmentIntent() PATCHes the intent (null clears)", () => {
    agentsApi.updateAttachmentIntent("p1", "att-1", "focus on cost");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1", {
      method: "PATCH",
      body: JSON.stringify({ intent: "focus on cost" }),
    });
    agentsApi.updateAttachmentIntent("p1", "att-1", null);
    expect(mockFetch).toHaveBeenLastCalledWith("/api/agents/projects/p1/attachments/att-1", {
      method: "PATCH",
      body: JSON.stringify({ intent: null }),
    });
  });

  it("updateAttachmentTitle() PATCHes the manual conversation title (memo dev/25)", () => {
    agentsApi.updateAttachmentTitle("p1", "att-1", "Dataset Import Help");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1", {
      method: "PATCH",
      body: JSON.stringify({ title: "Dataset Import Help" }),
    });
  });

  it("getSession() GETs the attachment's transcript", () => {
    agentsApi.getSession("p1", "att-1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1/session");
  });

  it("clearSession() DELETEs the transcript", () => {
    agentsApi.clearSession("p1", "att-1");
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/projects/p1/attachments/att-1/session", {
      method: "DELETE",
    });
  });

  it("applyProposal() POSTs the apply action; dismissProposal() DELETEs (memo dev/41)", () => {
    agentsApi.applyProposal("p1", "att-1", "prop-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1/apply",
      { method: "POST" },
    );
    agentsApi.dismissProposal("p1", "att-1", "prop-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1",
      { method: "DELETE" },
    );
  });

  describe("runAttachmentStream()", () => {
    const realFetch = global.fetch;
    afterEach(() => {
      global.fetch = realFetch;
    });

    function streamResponse(frames: string[], ok = true, status = 200, body: unknown = {}) {
      const encoder = new TextEncoder();
      const chunks = frames.map((f) => encoder.encode(f));
      let i = 0;
      return {
        ok,
        status,
        json: () => Promise.resolve(body),
        body: {
          getReader: () => ({
            read: () =>
              Promise.resolve(
                i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined },
              ),
          }),
        },
      } as unknown as Response;
    }

    it("parses delta/done frames and resolves the full reply", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: delta\ndata: {"text": "he"}\n\n',
          'event: delta\ndata: {"text": "llo"}\n\nevent: done\ndata: {"reply": "hello"}\n\n',
        ]),
      );
      const deltas: string[] = [];
      const result = await agentsApi.runAttachmentStream("p1", "att-1", "hi", (t) => deltas.push(t));
      expect(deltas).toEqual(["he", "llo"]);
      expect(result.reply).toBe("hello");
      // An old server's plain done frame leaves the dev/37 fields absent.
      expect(result.executionId).toBeUndefined();
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/agents/projects/p1/attachments/att-1/run/stream"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ message: "hi" }) }),
      );
    });

    it("parses the execution event and the enriched done payload (memo dev/37)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: execution\ndata: {"executionId": "e1"}\n\n',
          'event: delta\ndata: {"text": "hello"}\n\n',
          'event: done\ndata: {"reply": "hello", "executionId": "e1", "usage": {"inputTokens": 7, "outputTokens": 9}}\n\n',
        ]),
      );
      const result = await agentsApi.runAttachmentStream("p1", "att-1", "hi", () => undefined);
      expect(result).toEqual({
        reply: "hello",
        executionId: "e1",
        usage: { inputTokens: 7, outputTokens: 9 },
      });
    });

    it("parses the content event and the done content field (memo dev/39)", async () => {
      const parts = [
        { type: "suggestedPrompts", primary: "Next", alternatives: ["Alt"] },
      ];
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: execution\ndata: {"executionId": "e1"}\n\n',
          'event: delta\ndata: {"text": "hi"}\n\n',
          `event: content\ndata: ${JSON.stringify({ parts })}\n\n`,
          `event: done\ndata: ${JSON.stringify({ reply: "hi", executionId: "e1", usage: null, content: parts })}\n\n`,
        ]),
      );
      const result = await agentsApi.runAttachmentStream("p1", "att-1", "hi", () => undefined);
      expect(result.content).toEqual(parts);
      expect(result.reply).toBe("hi");
    });

    it("takes content from the content event when done omits it (old-server shape)", async () => {
      const parts = [{ type: "card", kind: "result", title: "T", lines: [] }];
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          `event: content\ndata: ${JSON.stringify({ parts })}\n\nevent: done\ndata: {"reply": "hi"}\n\n`,
        ]),
      );
      const result = await agentsApi.runAttachmentStream("p1", "att-1", "hi", () => undefined);
      expect(result.content).toEqual(parts);
    });

    it("routes tool/review events to onEvent (memo dev/41)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: tool_requested\ndata: {"tool": "node.read"}\n\n',
          'event: tool_started\ndata: {"tool": "node.read"}\n\n',
          'event: tool_result\ndata: {"tool": "node.read", "status": "ok"}\n\n',
          'event: review_required\ndata: {"proposalId": "p1", "tool": "node.content.write", "summary": "s"}\n\n',
          'event: delta\ndata: {"text": "hi"}\n\nevent: done\ndata: {"reply": "hi"}\n\n',
        ]),
      );
      const seen: Array<[string, unknown]> = [];
      const result = await agentsApi.runAttachmentStream(
        "p1", "att-1", "hi", () => undefined, (name, payload) => seen.push([name, payload]),
      );
      expect(seen.map(([n]) => n)).toEqual([
        "tool_requested", "tool_started", "tool_result", "review_required",
      ]);
      expect(seen[2][1]).toEqual({ tool: "node.read", status: "ok" });
      expect(result.reply).toBe("hi");
    });

    it("skips unknown event names (forward tolerance)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: card\ndata: {"kind": "preview"}\n\n', // a T2 event this client predates
          'event: delta\ndata: {"text": "hello"}\n\nevent: done\ndata: {"reply": "hello"}\n\n',
        ]),
      );
      const deltas: string[] = [];
      const result = await agentsApi.runAttachmentStream("p1", "att-1", "hi", (t) => deltas.push(t));
      expect(deltas).toEqual(["hello"]);
      expect(result.reply).toBe("hello");
    });

    it("throws with status/body on a pre-stream HTTP error (quota 429)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([], false, 429, { error: "daily agent-run limit reached (2/day)", quota: true }),
      );
      await expect(
        agentsApi.runAttachmentStream("p1", "att-1", "hi", () => undefined),
      ).rejects.toMatchObject({ status: 429, message: expect.stringContaining("limit") });
    });

    it("throws on a mid-stream error event", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse(['event: delta\ndata: {"text": "par"}\n\nevent: error\ndata: {"error": "boom"}\n\n']),
      );
      await expect(
        agentsApi.runAttachmentStream("p1", "att-1", "hi", () => undefined),
      ).rejects.toThrow("boom");
    });
  });

  describe("solveAttachmentStream() (dev/63)", () => {
    const realFetch = global.fetch;
    afterEach(() => {
      global.fetch = realFetch;
    });

    function streamResponse(frames: string[]) {
      const encoder = new TextEncoder();
      const chunks = frames.map((f) => encoder.encode(f));
      let i = 0;
      return {
        ok: true,
        status: 200,
        json: () => Promise.resolve({}),
        body: {
          getReader: () => ({
            read: () =>
              Promise.resolve(
                i < chunks.length ? { done: false, value: chunks[i++] } : { done: true, value: undefined },
              ),
          }),
        },
      } as unknown as Response;
    }

    it("dispatches per-node lifecycle events and resolves with the done payload", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: solve_started\ndata: {"executionId": "e1", "targets": ["n1"]}\n\n',
          'event: node_started\ndata: {"nodeId": "n1"}\n\n',
          'event: node_result\ndata: {"nodeId": "n1", "status": "solved", "content": "code"}\n\n',
          'event: done\ndata: {"attachmentId": "a1", "executionId": "e1", "results": {"n1": {"status": "solved"}}, "appliedContents": [], "builderSession": {"phase": "ready"}, "cancelled": false, "notAttempted": []}\n\n',
        ]),
      );
      const seen: Array<[string, unknown]> = [];
      const result = await agentsApi.solveAttachmentStream("p1", "att-1", (n, p) => seen.push([n, p]));
      expect(seen.map(([n]) => n)).toEqual(["solve_started", "node_started", "node_result"]);
      expect(seen[2][1]).toEqual({ nodeId: "n1", status: "solved", content: "code" });
      expect(result.cancelled).toBe(false);
      expect(result.builderSession.phase).toBe("ready");
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/agents/projects/p1/attachments/att-1/solve/stream"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({}) }),
      );
    });



    it("validateNode streams lifecycle events and resolves on done (dev/67-7)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: validation_started\ndata: {"nodeId": "n1", "executionId": "e1"}\n\n',
          'event: generation_round\ndata: {"round": 1}\n\n',
          'event: node_executed\ndata: {"nodeId": "up1", "index": 0, "total": 2}\n\n',
          'event: round_verdict\ndata: {"round": 1, "verdict": "pass"}\n\n',
          'event: done\ndata: {"verdict": "pass", "rounds": 1, "proposalId": "vp1", "nodeId": "n1"}\n\n',
        ]),
      );
      const seen: string[] = [];
      const result = await agentsApi.validateNode("p1", "att-1", { ref: "ra" }, (n) => seen.push(n));
      expect(seen).toEqual(["validation_started", "generation_round", "node_executed", "round_verdict"]);
      expect(result).toMatchObject({ verdict: "pass", proposalId: "vp1" });
      expect(global.fetch).toHaveBeenCalledWith(
        expect.stringContaining("/attachments/att-1/validate-node"),
        expect.objectContaining({ method: "POST", body: JSON.stringify({ ref: "ra" }) }),
      );
    });

    it("posts propose mode when given (dev/67-6)", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: solve_started\ndata: {"executionId": "e1", "targets": ["n1"]}\n\n',
          'event: node_result\ndata: {"nodeId": "n1", "status": "proposed", "proposalId": "cp1"}\n\n',
          'event: done\ndata: {"attachmentId": "a1", "executionId": "e1", "results": {}, "appliedContents": [], "builderSession": {"phase": "simulating"}, "mode": "propose"}\n\n',
        ]),
      );
      const seen: Array<[string, unknown]> = [];
      await agentsApi.solveAttachmentStream(
        "p1", "att-1", (n, p) => seen.push([n, p]), ["n1"], undefined, "propose",
      );
      expect(seen[1][1]).toEqual({ nodeId: "n1", status: "proposed", proposalId: "cp1" });
      expect(global.fetch).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ body: JSON.stringify({ nodeIds: ["n1"], mode: "propose" }) }),
      );
    });

    it("posts the retry subset and throws on a mid-stream error event", async () => {
      global.fetch = jest.fn().mockResolvedValue(
        streamResponse([
          'event: solve_started\ndata: {"executionId": "e1", "targets": ["n1"]}\n\n',
          'event: error\ndata: {"error": "boom"}\n\n',
        ]),
      );
      await expect(
        agentsApi.solveAttachmentStream("p1", "att-1", () => undefined, ["n1"]),
      ).rejects.toThrow("boom");
      expect(global.fetch).toHaveBeenCalledWith(
        expect.anything(),
        expect.objectContaining({ body: JSON.stringify({ nodeIds: ["n1"] }) }),
      );
    });
  });

  it("cancelSolve() posts the cancel endpoint (dev/63)", () => {
    agentsApi.cancelSolve("p1", "att-1");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/solve/cancel",
      { method: "POST" },
    );
  });

  it("getProjectAgentDefaults() GETs the escaped defaults path", () => {
    agentsApi.getProjectAgentDefaults("p1", "agent.chat-agent@1.0.0");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/defaults/agent.chat-agent%401.0.0",
    );
  });

  it("agent settings: GET/PATCH account + PATCH project defaults", () => {
    agentsApi.getAgentSettings();
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/settings");
    agentsApi.updateAgentSettings(3, { quotas: { runsPerDay: 10 } });
    expect(mockFetch).toHaveBeenLastCalledWith("/api/agents/settings", {
      method: "PATCH",
      body: JSON.stringify({ revision: 3, settings: { quotas: { runsPerDay: 10 } } }),
    });
    agentsApi.updateProjectAgentDefaults("p1", "agent.chat-agent@1.0.0", 2, {});
    expect(mockFetch).toHaveBeenLastCalledWith(
      "/api/agents/projects/p1/defaults/agent.chat-agent%401.0.0",
      { method: "PATCH", body: JSON.stringify({ revision: 2, settings: {} }) },
    );
  });

  it("uploadImport() POSTs the manifest + prompt texts (dev/36)", () => {
    agentsApi.uploadImport({ id: "agent.x" }, { "prompts/i.txt": "text" });
    expect(mockFetch).toHaveBeenCalledWith("/api/agents/imports/upload", {
      method: "POST",
      body: JSON.stringify({ manifest: { id: "agent.x" }, prompts: { "prompts/i.txt": "text" } }),
    });
  });



  it("applyPlanEdges() posts the indices to the apply-edges path (dev/67-8)", () => {
    agentsApi.applyPlanEdges("p1", "att-1", "prop-1", [0, 2]);
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1/apply-edges",
      { method: "POST", body: JSON.stringify({ edges: [0, 2] }) },
    );
    agentsApi.applyPlanEdges("p1", "att-1", "prop-1");
    expect(mockFetch).toHaveBeenLastCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1/apply-edges",
      { method: "POST", body: JSON.stringify({}) },
    );
  });

  it("applyPlanNode() posts the ref to the apply-node path (dev/67-5)", () => {
    agentsApi.applyPlanNode("p1", "att-1", "prop-1", "ra");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1/apply-node",
      { method: "POST", body: JSON.stringify({ ref: "ra" }) },
    );
  });

  it("savePlanGoal() PATCHes the plan-goals path (dev/67-5)", () => {
    agentsApi.savePlanGoal("p1", "att-1", "prop-1", "ra", "better goal");
    expect(mockFetch).toHaveBeenCalledWith(
      "/api/agents/projects/p1/attachments/att-1/proposals/prop-1/plan-goals",
      { method: "PATCH", body: JSON.stringify({ ref: "ra", goal: "better goal" }) },
    );
  });
});