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
    expect(screen.getByText(/3 runs used today/)).toBeInTheDocument();
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
    expect(screen.getByText(/inactive until both a budget and an estimate/i)).toBeInTheDocument();
    expect(screen.getByText(/actual cost is not available in v1/i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText(/daily budget/i), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).not.toHaveBeenCalled(); // dirty + declined confirm
    confirmSpy.mockRestore();
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
