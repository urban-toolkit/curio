import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: {
    getAgentSettings: jest.fn(),
    updateAgentSettings: jest.fn(),
    getProjectAgentDefaults: jest.fn(),
    updateProjectAgentDefaults: jest.fn(),
  },
}));

import { agentsApi } from "../../api/agentsApi";
import { AgentSettingsModal } from "../../components/agents/settings/AgentSettingsModal";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const effective = {
  quotas: { runsPerDay: { value: 100, source: "deployment" as const, usedToday: 3 } },
  cost: {
    dailyBudgetUsd: { value: null, source: null },
    estimatedCostPerRunUsd: { value: null, source: null },
    configured: false,
    estimatedSpendTodayUsd: null,
  },
  resources: { maxOutputTokens: { value: 4096, source: "deployment" as const } },
};

const accountPayload = {
  revision: 1,
  settings: {},
  effective,
  ceilings: { quotas: { runsPerDay: 100 }, resources: { maxOutputTokens: 4096 }, cost: {} },
  usedToday: 3,
  usageToday: { inputTokens: 120, outputTokens: 45 },
};

const projectPayload = {
  coord: "agent.chat-agent@1.0.0",
  name: "Chat",
  revision: 1,
  settings: {},
  effective,
};

beforeEach(() => {
  jest.clearAllMocks();
  api.getAgentSettings.mockResolvedValue(accountPayload as any);
  api.updateAgentSettings.mockResolvedValue({
    ...accountPayload,
    revision: 2,
    settings: { quotas: { runsPerDay: 30 } },
    effective: {
      ...effective,
      quotas: { runsPerDay: { value: 30, source: "account", usedToday: 3 } },
    },
  } as any);
  api.getProjectAgentDefaults.mockResolvedValue(projectPayload as any);
  api.updateProjectAgentDefaults.mockResolvedValue({
    ...projectPayload,
    revision: 2,
    settings: {},
  } as any);
});

describe("AgentSettingsModal — account scope", () => {
  it("shows the scope, effective values with sources, ceilings, and usage", async () => {
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    expect(screen.getByText(/effective 100 · from deployment/)).toBeInTheDocument();
    expect(screen.getByText(/≤ 100/)).toBeInTheDocument();
    // Actual tokens next to the run count (memo dev/37) — never an estimate.
    expect(
      screen.getByText(/3 runs · 120 in \/ 45 out tokens today \(actual\)/),
    ).toBeInTheDocument();
  });

  it("shows zero usage when the server payload predates usage capture", async () => {
    const { usageToday: _dropped, ...legacy } = accountPayload;
    api.getAgentSettings.mockResolvedValue(legacy as any);
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    expect(
      screen.getByText(/3 runs · 0 in \/ 0 out tokens today \(actual\)/),
    ).toBeInTheDocument();
  });

  it("saves a draft with the revision and applies the response", async () => {
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled(); // not dirty
    fireEvent.change(screen.getByLabelText(/runs per day/i), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.updateAgentSettings).toHaveBeenCalledWith(1, { quotas: { runsPerDay: 30 } }),
    );
    await waitFor(() =>
      expect(screen.getByText(/effective 30 · from account/)).toBeInTheDocument(),
    );
  });

  it("a stale-revision 409 reloads and asks to reapply", async () => {
    api.updateAgentSettings.mockRejectedValue(
      Object.assign(new Error("changed"), { status: 409 }),
    );
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/runs per day/i), { target: { value: "30" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.getByText(/changed elsewhere — reloaded/i)).toBeInTheDocument(),
    );
    expect(api.getAgentSettings).toHaveBeenCalledTimes(2);
  });

  it("a validation 400 shows the server's field message", async () => {
    api.updateAgentSettings.mockRejectedValue(
      Object.assign(new Error("quotas.runsPerDay may not exceed the inherited limit (100)"), {
        status: 400,
      }),
    );
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/runs per day/i), { target: { value: "500" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(screen.getByText(/may not exceed the inherited limit/)).toBeInTheDocument(),
    );
  });

  it("guards dirty close and shows the honest cost note", async () => {
    const onClose = jest.fn();
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(false);
    render(<AgentSettingsModal scope="account" onClose={onClose} />);
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cost"));
    expect(screen.getByText(/inactive until a daily budget is set/i)).toBeInTheDocument();
    // Honest Actual line (memos dev/11/37/40): tokens are real; without a
    // deployment price the missing USD is named, never faked.
    expect(
      screen.getByText(/Actual: 120 in \/ 45 out tokens today — no USD price configured/),
    ).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/daily budget/i), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled(); // dirty + declined confirm
    confirmSpy.mockRestore();
  });
});

describe("AgentSettingsModal — Actual USD states (memo dev/40)", () => {
  it("priced deployments show Actual USD, tokens, and the effective date", async () => {
    api.getAgentSettings.mockResolvedValue({
      ...accountPayload,
      actualSpendTodayUsd: 4.5,
      pricing: {
        provider: "anthropic",
        model: "claude-sonnet-5",
        priced: true,
        effectiveDate: "2026-07-01",
      },
    } as any);
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cost"));
    expect(
      screen.getByText(/Actual: \$4\.5000 today · 120 in \/ 45 out tokens \(provider-reported\) · pricing effective 2026-07-01/),
    ).toBeInTheDocument();
  });

  it("unpriced deployments name the missing price for the provider · model", async () => {
    api.getAgentSettings.mockResolvedValue({
      ...accountPayload,
      actualSpendTodayUsd: null,
      pricing: {
        provider: "openai_compatible",
        model: "gemma4",
        priced: false,
        effectiveDate: null,
      },
    } as any);
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cost"));
    expect(
      screen.getByText(/no USD price configured for openai_compatible · gemma4/),
    ).toBeInTheDocument();
  });

  it("a budget with neither estimate nor price shows the fail-closed state", async () => {
    api.getAgentSettings.mockResolvedValue({
      ...accountPayload,
      effective: {
        ...effective,
        cost: {
          ...effective.cost,
          dailyBudgetUsd: { value: 5, source: "account" },
        },
      },
      pricing: {
        provider: "openai_compatible",
        model: "gemma4",
        priced: false,
        effectiveDate: null,
      },
    } as any);
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cost"));
    expect(screen.getByText(/runs are blocked until one is provided/)).toBeInTheDocument();
  });

  it("a budget with a price gates on actual spend", async () => {
    api.getAgentSettings.mockResolvedValue({
      ...accountPayload,
      actualSpendTodayUsd: 0,
      effective: {
        ...effective,
        cost: {
          ...effective.cost,
          dailyBudgetUsd: { value: 5, source: "account" },
        },
      },
      pricing: { provider: "anthropic", model: "m", priced: true, effectiveDate: null },
    } as any);
    render(<AgentSettingsModal scope="account" onClose={jest.fn()} />);
    await waitFor(() => expect(screen.getByText("Account policy")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Cost"));
    expect(
      screen.getByText(/budget gate is active on actual provider-priced spend/),
    ).toBeInTheDocument();
  });
});

describe("AgentSettingsModal — project scope", () => {
  const renderProject = () =>
    render(
      <AgentSettingsModal
        scope="project"
        projectId="p1"
        coord={projectPayload.coord}
        onClose={jest.fn()}
      />,
    );

  it("shows the project scope and the account-only estimate as read-only", async () => {
    renderProject();
    await waitFor(() => expect(screen.getByText("Project agent default")).toBeInTheDocument());
    expect(screen.getByText("Chat")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Cost"));
    expect(screen.queryByLabelText(/estimated cost per run/i)).not.toBeInTheDocument();
    expect(screen.getByText(/account-scope setting/)).toBeInTheDocument();
  });

  it("saves against the project defaults and resets to agent default", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    renderProject();
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/runs per day/i), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.updateProjectAgentDefaults).toHaveBeenCalledWith(
        "p1",
        projectPayload.coord,
        1,
        { quotas: { runsPerDay: 5 } },
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Reset to agent default" }));
    await waitFor(() =>
      expect(api.updateProjectAgentDefaults).toHaveBeenLastCalledWith(
        "p1",
        projectPayload.coord,
        2,
        {},
      ),
    );
    confirmSpy.mockRestore();
  });

  it("has no Publish/Release/Share controls", async () => {
    renderProject();
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
    for (const name of [/publish/i, /release/i, /share/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });
});

describe("AgentSettingsModal — attachment scope (memo dev/42)", () => {
  const attachmentPayload = {
    attachmentId: "att-1",
    coord: "agent.chat-agent@1.0.0",
    name: "Chat",
    revision: 1,
    settings: {},
    effective,
  };

  beforeEach(() => {
    (api as any).getAttachmentSettings = jest
      .fn()
      .mockResolvedValue(attachmentPayload as any);
    (api as any).updateAttachmentSettings = jest.fn().mockResolvedValue({
      ...attachmentPayload,
      revision: 2,
      settings: { quotas: { runsPerDay: 3 } },
      effective: {
        ...effective,
        quotas: { runsPerDay: { value: 3, source: "attachment", usedToday: 0 } },
      },
    } as any);
  });

  const renderAttachment = () =>
    render(
      <AgentSettingsModal
        scope="attachment"
        projectId="p1"
        attachmentId="att-1"
        onClose={jest.fn()}
      />,
    );

  it("shows the Attached instance banner and the estimate as read-only", async () => {
    renderAttachment();
    await waitFor(() => expect(screen.getByText("Attached instance")).toBeInTheDocument());
    expect(screen.getByText("Chat")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Cost"));
    expect(screen.queryByLabelText(/estimated cost per run/i)).not.toBeInTheDocument();
    expect(screen.getByText(/account-scope setting/)).toBeInTheDocument();
  });

  it("saves against the attachment settings and shows the attachment source", async () => {
    renderAttachment();
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/runs per day/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect((api as any).updateAttachmentSettings).toHaveBeenCalledWith(
        "p1", "att-1", 1, { quotas: { runsPerDay: 3 } },
      ),
    );
    await waitFor(() =>
      expect(screen.getByText(/effective 3 · from attachment/)).toBeInTheDocument(),
    );
  });

  it("Clear overrides PATCHes an empty settings object", async () => {
    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValue(true);
    renderAttachment();
    await waitFor(() => expect(screen.getByLabelText(/runs per day/i)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Clear overrides" }));
    await waitFor(() =>
      expect((api as any).updateAttachmentSettings).toHaveBeenCalledWith("p1", "att-1", 1, {}),
    );
    confirmSpy.mockRestore();
  });

  it("carries no Publish/Release/Share controls", async () => {
    renderAttachment();
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
    for (const name of [/publish/i, /release/i, /share/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
  });
});
