import { renderHook, act, waitFor } from "@testing-library/react";

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    attach: jest.fn(),
    detachAttachment: jest.fn(),
    runAttachment: jest.fn(),
  },
}));

import { agentsApi, useAgentAttachments, AGENT_DOCK_REFRESH_EVENT } from "../../services/agents";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

function att(id: string) {
  return {
    attachmentId: id,
    coord: "agent.test.my-explainer@1",
    target: { kind: "canvas" as const },
    sessionId: "s",
    revision: 1,
    intent: null,
    intentEdited: false,
    title: null,
    titleEdited: false,
    name: "My Explainer",
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
      await result.current.attach("agent.test.my-explainer@1", { kind: "canvas" });
    });
    expect(api.attach).toHaveBeenCalledWith("p1", "agent.test.my-explainer@1", { kind: "canvas" });
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled()); // dock-refresh → reload
  });

  it("run returns the reply", async () => {
    const { result } = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(result.current.attachments).toHaveLength(1));
    // `run` resolves the whole payload, not just the reply string.
    let reply: { reply: string } | undefined;
    await act(async () => {
      reply = await result.current.run("a1", "explain");
    });
    expect(api.runAttachment).toHaveBeenCalledWith("p1", "a1", "explain", undefined);
    // dev/53: the full payload - the stream fallback must lose no content parts.
    expect(reply?.reply).toBe("the reply");
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
    renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
    api.listAttachments.mockClear();
    act(() => {
      window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
    });
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
  });
});

/** Two reads can overlap, as the room's word at once and its word when a wait
 *  ends do. The newest read's answer is what the list shows, whichever lands
 *  last: an older answer, or an older read's failure, changes nothing. */
describe("useAgentAttachments with two reads out at once", () => {
  type Listing = Awaited<ReturnType<typeof api.listAttachments>>;

  /** Two dock refreshes whose reads the test answers: the older first held. */
  async function twoReadsOut() {
    const hook = renderHook(() => useAgentAttachments("p1"));
    await waitFor(() => expect(hook.result.current.attachments).toHaveLength(1));
    const older: { answer?: (listing: Listing) => void; fail?: (error: Error) => void } = {};
    let answerNewer!: (listing: Listing) => void;
    api.listAttachments
      .mockImplementationOnce(() => new Promise<Listing>((resolve, reject) => {
        older.answer = resolve;
        older.fail = reject;
      }))
      .mockImplementationOnce(() => new Promise<Listing>((resolve) => {
        answerNewer = resolve;
      }));
    act(() => {
      window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
    });
    act(() => {
      window.dispatchEvent(new Event(AGENT_DOCK_REFRESH_EVENT));
    });
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(3));
    await act(async () => {
      answerNewer({ attachments: [att("a1"), att("a2")] });
    });
    expect(hook.result.current.attachments.map((a) => a.attachmentId)).toEqual(["a1", "a2"]);
    return { hook, older };
  }

  it("keeps the newer read's answer when the older one lands last", async () => {
    const { hook, older } = await twoReadsOut();
    await act(async () => {
      older.answer?.({ attachments: [att("a1")] });
    });
    expect(hook.result.current.attachments.map((a) => a.attachmentId)).toEqual(["a1", "a2"]);
  });

  it("keeps the newer read's answer when the older read fails last", async () => {
    const { hook, older } = await twoReadsOut();
    await act(async () => {
      older.fail?.(new Error("the older read broke"));
    });
    expect(hook.result.current.attachments.map((a) => a.attachmentId)).toEqual(["a1", "a2"]);
    expect(hook.result.current.error).toBeNull();
  });
});
