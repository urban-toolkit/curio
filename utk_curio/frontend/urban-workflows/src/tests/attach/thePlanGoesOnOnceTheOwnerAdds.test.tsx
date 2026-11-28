import React from "react";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";

/**
 * Step 5.6 of the agent chat plan, found by #1652's dev check: the owner's
 * Apply of an invited editor's pick ended the wait of the plan the pick
 * waited on and started nothing, so nothing built the loader. Now the plan
 * goes on as a direct pick's does: the listing's record of the pick says who
 * picked and how the plan goes on (`goesOn`, the answer a direct pick gives),
 * his tab takes it once (`claimGoesOn`) and goes on through the pick's own
 * switch. The owner's tab never does: her Apply approves adding the dataset,
 * not spending a build.
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
    claimGoesOn: jest.fn(),
    simulate: jest.fn(),
    validateNode: jest.fn(),
  },
}));

import { agentsApi, type AgentAttachment } from "../../services/agents";
import { AgentAttachmentsProvider, useAgentAttachmentsContext } from "../../providers/agents";
import { UserContext, type UserProviderProps } from "../../providers/userContext";

const api = agentsApi as unknown as jest.Mocked<typeof agentsApi> & { claimGoesOn: jest.Mock };

/** The editor who picked, and the dataflow's owner, by account id. */
const BOB = 2;
const ALICE = 1;

const base = {
  sessionId: "s1",
  revision: 1,
  hooks: [],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
};
const BUILDER = {
  ...base,
  attachmentId: "dfb",
  coord: "agent.curio.dataflow-builder@1",
  target: { kind: "canvas" },
  name: "Dataflow Builder",
  category: "canvas",
  capabilities: ["dataflow.orchestrate"],
} as AgentAttachment;

/** How the plan goes on, as a direct pick's answer says it. */
function goesOn(continueWith: "build" | "step" | "node") {
  return { status: "plan-waiting", attachmentId: "dfb", nodeId: "n1", ref: "load", continueWith, running: null };
}

/** The loader's Dataset Finder, whose record says Bob's pick resolved once the
 * owner added the dataset, and how the plan goes on. */
function finder(continueWith: "build" | "step" | "node" = "build") {
  return {
    ...base,
    attachmentId: "att-df",
    sessionId: "s2",
    coord: "agent.curio.dataset-finder@1",
    target: { kind: "node", targetId: "n1" },
    name: "Dataset Finder",
    category: "data",
    capabilities: ["dataset.discover", "dataset.select"],
    sourceRecord: {
      status: "resolved",
      recordedAt: "2026-11-28T04:11:41+00:00",
      pickedBy: String(BOB),
      goesOn: goesOn(continueWith),
    },
  } as AgentAttachment;
}

function signedInAs(id: number): UserProviderProps {
  return {
    user: { id, username: `user${id}`, name: `User ${id}` } as UserProviderProps["user"],
    loading: false,
    isAuthenticated: true,
    enableUserAuth: true,
    skipProjectPage: false,
    allowGuest: false,
    sharedGuestUsername: "guest_shared",
    isSharedGuest: false,
    signup: async () => null,
    signin: async () => null,
    signinGuest: async () => null,
    signout: async () => {},
    updateProfile: async () => {},
    updateTokens: async () => {},
    saveUserType: async () => {},
    logout: () => {},
  };
}

const Harness: React.FC = () => {
  const ctx = useAgentAttachmentsContext();
  if (!ctx) return null;
  return <button onClick={() => void ctx.reload()}>reload</button>;
};

function renderAs(id: number) {
  return render(
    <UserContext.Provider value={signedInAs(id)}>
      <AgentAttachmentsProvider>
        <Harness />
      </AgentAttachmentsProvider>
    </UserContext.Provider>,
  );
}

/** Lets the provider's chains of promises run out. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  api.listAttachments.mockResolvedValue({ attachments: [BUILDER, finder()] });
  api.getSession.mockImplementation(async (_pid: string, attachmentId: string) => ({
    attachmentId, sessionId: attachmentId === "dfb" ? "s1" : "s2", turns: [],
  }));
  api.followTurn.mockRejectedValue(Object.assign(new Error("no such ask"), { status: 404 }));
  api.simulate.mockResolvedValue({ status: "completed" });
  api.validateNode.mockResolvedValue({ verdict: "pass" });
  api.claimGoesOn.mockResolvedValue({ delegated: goesOn("build") });
});

describe("once the owner added the dataset an editor picked, the plan goes on from his tab", () => {
  it("takes the go-on once and goes on with Build & validate, as a direct pick does", async () => {
    renderAs(BOB);
    await waitFor(() => expect(api.claimGoesOn).toHaveBeenCalledWith("p1", "att-df"));
    await waitFor(() => expect(api.simulate).toHaveBeenCalledWith("p1", "dfb", "auto", expect.any(Function)));
    // The listing again, read before the server dropped the go-on: not twice.
    // (Build & validate reads the listing too, so the reads are counted from here.)
    const reads = api.listAttachments.mock.calls.length;
    fireEvent.click(screen.getByText("reload"));
    await waitFor(() => expect(api.listAttachments.mock.calls.length).toBeGreaterThan(reads));
    await settle();
    expect(api.claimGoesOn).toHaveBeenCalledTimes(1);
    expect(api.simulate).toHaveBeenCalledTimes(1);
    expect(api.validateNode).not.toHaveBeenCalled();
  });

  it("goes on with one Step when a Step left the loader waiting", async () => {
    api.listAttachments.mockResolvedValue({ attachments: [BUILDER, finder("step")] });
    api.claimGoesOn.mockResolvedValue({ delegated: goesOn("step") });
    renderAs(BOB);
    await waitFor(() => expect(api.simulate).toHaveBeenCalledWith("p1", "dfb", "step", expect.any(Function)));
    expect(api.simulate).toHaveBeenCalledTimes(1);
  });

  it("the owner's tab takes nothing and runs nothing", async () => {
    renderAs(ALICE);
    await waitFor(() => expect(api.listAttachments).toHaveBeenCalled());
    await settle();
    expect(api.claimGoesOn).not.toHaveBeenCalled();
    expect(api.simulate).not.toHaveBeenCalled();
    expect(api.validateNode).not.toHaveBeenCalled();
  });

  it("runs nothing when the server says the plan went on without it", async () => {
    api.claimGoesOn.mockResolvedValue({ delegated: null });
    renderAs(BOB);
    await waitFor(() => expect(api.claimGoesOn).toHaveBeenCalledTimes(1));
    await settle();
    expect(api.simulate).not.toHaveBeenCalled();
    expect(api.validateNode).not.toHaveBeenCalled();
  });
});
