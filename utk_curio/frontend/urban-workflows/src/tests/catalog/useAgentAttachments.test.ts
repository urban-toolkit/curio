import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    attach: jest.fn(),
    detachAttachment: jest.fn(),
    runAttachment: jest.fn(),
  },
}));

import { agentsApi } from "../../api/agentsApi";
import { useAgentAttachments } from "../../components/agents/attach/useAgentAttachments";
import { AGENT_DOCK_REFRESH_EVENT } from "../../utils/agentsPaletteEvents";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

function att(id: string) {
  return {
    attachmentId: id,
    coord: "agent.node-explainer@1.0.0",
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "Node Explainer",
    category: "node",
    hooks: ["node"],
  };
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listAttachments.mockResolvedValue({ attachments: [att("a1")] });
  api.attach.mockResolvedValue(att("a2"));
  api.detachAttachment.mockResolvedValue({ attachmentId: "a1", detached: true });
  api.runAttachment.mockResolvedValue({ attachmentId: "a1", coord: "c", reply: "the reply" });
});

describe("useAgentAttachments", () => {
  it("loads attachments for the project", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(result.current.attachments).toHaveLength(1));
    expect(api.listAttachments).toHaveBeenCalledWith("p1");
  });

  it("null project → no fetch, empty list", async () => {
    const { result } = renderHook(() => useAgentAttachments(null));
    await new Promise((r) => setTimeout(r, 10));
    expect(api.listAttachments).not.toHaveBeenCalled();
    expect(result.current.attachments).toEqual([]);
  });

  it("attach calls the endpoint and reloads via the dock event", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(result.current.attachments).toHaveLength(1));
    api.listAttachments.mockClear();
    await act(async () => {
      await result.current.attach("agent.node-explainer@1.0.0", { kind: "canvas" });
    });
    expect(api.attach).toHaveBeenCalledWith("p1", "agent.node-explainer@1.0.0", { kind: "canvas" });
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled()); // dock-refresh → reload
  });

  it("run returns the reply", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(result.current.attachments).toHaveLength(1));
    let reply = "";
    await act(async () => {
      reply = await result.current.run("a1", "explain");
    });
    expect(api.runAttachment).toHaveBeenCalledWith("p1", "a1", "explain", undefined);
    expect(reply).toBe("the reply");
  });

  it("detach calls the endpoint", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(result.current.attachments).toHaveLength(1));
    await act(async () => {
      await result.current.detach("a1");
    });
    expect(api.detachAttachment).toHaveBeenCalledWith("p1", "a1");
  });

  it("reloads on the dock-refresh event", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
    api.listAttachments.mockClear();
    act(() => {
      window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
    });
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
  });
});
