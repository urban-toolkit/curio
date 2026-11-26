import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

/**
 * The handoff's provider side: after the user's pick on a candidates card, the
 * Dataflow Builder goes on with its plan by itself, and the chat that asked for
 * the candidates shows its Source recorded turn. The open chat is read again
 * when the listing says it waits on a node whose card it does not hold.
 */

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ projectId: "p1", dataflowDoc: null }),
}));
jest.mock("../../services/packages/packagesApi", () => ({ packagesApi: {} }));
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    listAttachments: jest.fn(),
    getSession: jest.fn(),
    followTurn: jest.fn(),
    recordDatasetSelection: jest.fn(),
    simulate: jest.fn(),
    validateNode: jest.fn(),
  },
}));

import { agentsApi, type AgentAttachment, type AgentDatasetSelection } from "../../services/agents";
import { AgentAttachmentsProvider, useAgentAttachmentsContext } from "../../providers/agents";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const base = {
  sessionId: "s1",
  revision: 1,
  hooks: [],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
};
const BUILDER: AgentAttachment = {
  ...base,
  attachmentId: "dfb",
  coord: "agent.curio.dataflow-builder@1",
  target: { kind: "canvas" },
  name: "Dataflow Builder",
  category: "canvas",
  capabilities: ["dataflow.orchestrate"],
};
const FINDER: AgentAttachment = {
  ...base,
  attachmentId: "att-df",
  sessionId: "s2",
  coord: "agent.curio.dataset-finder@1",
  target: { kind: "node", targetId: "n1" },
  name: "Dataset Finder",
  category: "data",
  capabilities: ["dataset.discover", "dataset.select"],
};
const URL = "https://data.example.org/areas.geojson";
const PICK_TURN = {
  role: "agent" as const,
  text: "**Load boundaries** needs a source. Its Dataset Finder found 1 candidate: pick one with Use this source.",
  content: [{
    type: "sourcePick" as const,
    finderAttachmentId: "att-df",
    nodeId: "n1",
    nodeLabel: "Load boundaries",
    lanes: { external: [{ name: "Chicago areas", sourceType: "portal" as const, url: URL }], catalog: [] },
  }],
};

const Harness: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;
  return (
    <div>
      <button
        onClick={() => void ctx.recordDatasetSelection("att-df", [{ lane: "external", key: URL }]).catch(() => undefined)}
      >
        pick
      </button>
      <button
        onClick={() =>
          void ctx.recordDatasetSelection("att-df", [{ lane: "external", key: URL }], "d2").catch(() => undefined)
        }
      >
        pick-on-d2
      </button>
      <button onClick={() => ctx.openChat("dfb")}>open-builder</button>
      <button onClick={() => void ctx.reload()}>reload</button>
      <div data-testid="builder-turns">{(ctx.transcripts["dfb"] ?? []).map((t) => t.text).join("|")}</div>
    </div>
  );
};

function renderProvider() {
  return render(
    <AgentAttachmentsProvider>
      <Harness />
    </AgentAttachmentsProvider>,
  );
}

/** The selection the server answers a pick with. */
function answer(delegated: AgentDatasetSelection["delegated"], askedBy = "dfb"): AgentDatasetSelection {
  return { attachmentId: "att-df", nodeId: "n1", status: "resolved", picks: [], delegated, askedBy };
}

/** Lets the provider's chains of promises run out. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, FINDER] });
  api.getSession.mockImplementation(async (_pid: string, attachmentId: string) => ({
    attachmentId, sessionId: attachmentId === "dfb" ? "s1" : "s2", turns: [],
  }));
  api.followTurn.mockRejectedValue(Object.assign(new Error("no such ask"), { status: 404 }));
  api.simulate.mockResolvedValue({ status: "completed" });
  api.validateNode.mockResolvedValue({ verdict: "pass" });
});

describe("after the user's pick, the Dataflow Builder goes on by itself", () => {
  it("goes on with Build & validate when Build & validate paused on the loader", async () => {
    api.recordDatasetSelection.mockResolvedValue(
      answer({ status: "plan-waiting", attachmentId: "dfb", nodeId: "n1", ref: "load", continueWith: "build", running: null }),
    );
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick"));
    await waitFor(() => expect(api.simulate).toHaveBeenCalledWith("p1", "dfb", "auto", expect.any(Function)));
    expect(api.simulate).toHaveBeenCalledTimes(1);
    expect(api.validateNode).not.toHaveBeenCalled();
  });

  it("goes on with that row's Solve when a plan row's Solve left the loader waiting", async () => {
    api.recordDatasetSelection.mockResolvedValue(
      answer({ status: "plan-waiting", attachmentId: "dfb", nodeId: "n1", ref: "load", continueWith: "node", running: null }),
    );
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick"));
    await waitFor(() =>
      expect(api.validateNode).toHaveBeenCalledWith("p1", "dfb", { ref: "load" }, expect.any(Function)),
    );
    expect(api.simulate).not.toHaveBeenCalled();
  });

  it.each<[string, AgentDatasetSelection["delegated"]]>([
    ["a Build & validate running now builds it", { status: "plan-waiting", attachmentId: "dfb", nodeId: "n1", ref: "load", running: "auto" }],
    ["a pick no plan waited on starts the node's own builder on the server", { status: "delegating", attachmentId: "nb1", nodeId: "n1" }],
  ])("starts nothing more when %s", async (_why, delegated) => {
    api.recordDatasetSelection.mockResolvedValue(answer(delegated));
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick"));
    await waitFor(() => expect(api.recordDatasetSelection).toHaveBeenCalled());
    await settle();
    expect(api.simulate).not.toHaveBeenCalled();
    expect(api.validateNode).not.toHaveBeenCalled();
  });

  it("reads the chat that asked again, which says the source is recorded too", async () => {
    api.recordDatasetSelection.mockResolvedValue(answer({ status: "delegating", attachmentId: "nb1", nodeId: "n1" }));
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick"));
    await waitFor(() => expect(api.getSession).toHaveBeenCalledWith("p1", "dfb"));
    expect(api.getSession).toHaveBeenCalledWith("p1", "att-df");
  });
});

describe("the open chat is read again when the listing says it waits on a node whose card it does not hold", () => {
  it("reads it once more, and not again while its card is there", async () => {
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("open-builder"));
    await waitFor(() => expect(api.getSession).toHaveBeenCalledTimes(1));
    // A Build & validate in another tab asked the loader's Finder: the
    // listing names the loader among the Builder's waits, and its chat holds
    // the card on the server.
    api.listAttachments.mockResolvedValue({ attachments: [{ ...BUILDER, waitsForYou: ["n1"] }, FINDER] });
    api.getSession.mockResolvedValue({ attachmentId: "dfb", sessionId: "s1", turns: [PICK_TURN] });
    fireEvent.click(screen.getByText("reload"));
    await waitFor(() => expect(screen.getByTestId("builder-turns")).toHaveTextContent("needs a source"));
    expect(api.getSession).toHaveBeenCalledTimes(2);
    // The listing again, the card already in the chat: no further read.
    fireEvent.click(screen.getByText("reload"));
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(3));
    await settle();
    expect(api.getSession).toHaveBeenCalledTimes(2);
  });

  it("reads it again for the card of newer candidates, though it holds the card of an older search", async () => {
    const older = { ...PICK_TURN, content: [{ ...PICK_TURN.content[0], discoveryId: "d1" }] };
    api.getSession.mockImplementation(async (_pid: string, attachmentId: string) => ({
      attachmentId, sessionId: attachmentId === "dfb" ? "s1" : "s2", turns: attachmentId === "dfb" ? [older] : [],
    }));
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByText("open-builder"));
    await waitFor(() => expect(screen.getByTestId("builder-turns")).toHaveTextContent("needs a source"));
    const readsOfTheBuilder = () => api.getSession.mock.calls.filter(([, id]) => id === "dfb").length;
    const before = readsOfTheBuilder();
    // Another tab's Build & validate asked the loader's Finder again: its
    // record names the newer candidates, whose card the Builder's chat holds on
    // the server.
    api.listAttachments.mockResolvedValue({
      attachments: [
        { ...BUILDER, waitsForYou: ["n1"] },
        {
          ...FINDER,
          waitsForYou: ["n1"],
          sourceRecord: { status: "candidates-pending", candidates: 1, discoveryId: "d2", askedBy: "dfb", askers: ["dfb"] },
        },
      ],
    });
    fireEvent.click(screen.getByText("reload"));
    await waitFor(() => expect(readsOfTheBuilder()).toBe(before + 1));
  });
});

describe("a pick goes on as the user was going, and names its card", () => {
  it("goes on with one Step when a Step paused on the loader", async () => {
    api.recordDatasetSelection.mockResolvedValue(
      answer({ status: "plan-waiting", attachmentId: "dfb", nodeId: "n1", ref: "load", continueWith: "step", running: null }),
    );
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick"));
    await waitFor(() => expect(api.simulate).toHaveBeenCalledWith("p1", "dfb", "step", expect.any(Function)));
    expect(api.simulate).toHaveBeenCalledTimes(1);
    expect(api.validateNode).not.toHaveBeenCalled();
  });

  it("sends the id of the card the pick was made on", async () => {
    api.recordDatasetSelection.mockResolvedValue(answer({ status: "delegating", attachmentId: "nb1", nodeId: "n1" }));
    renderProvider();
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    fireEvent.click(screen.getByText("pick-on-d2"));
    await waitFor(() =>
      expect(api.recordDatasetSelection).toHaveBeenCalledWith("p1", "att-df", [{ lane: "external", key: URL }], "d2"),
    );
  });
});
