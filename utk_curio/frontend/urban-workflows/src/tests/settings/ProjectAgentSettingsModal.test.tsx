import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: { getProjectAgentDefaults: jest.fn() },
}));

import { agentsApi } from "../../api/agentsApi";
import { ProjectAgentSettingsModal } from "../../components/agents/settings/ProjectAgentSettingsModal";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const defaults = {
  coord: "agent.chat-agent@1.0.0",
  name: "Chat",
  revision: 1,
  settings: {},
  effective: {
    quotas: { runsPerDay: { value: 200, usedToday: 3, source: "account" } },
    cost: { configured: false, source: "account" },
    resources: { source: "account", provider: "openai_compatible", model: "llama4-nim" },
  },
};

beforeEach(() => {
  jest.clearAllMocks();
  api.getProjectAgentDefaults.mockResolvedValue(defaults);
});

describe("ProjectAgentSettingsModal", () => {
  it("shows the scope, effective values, and their provenance", async () => {
    render(
      <ProjectAgentSettingsModal projectId="p1" coord={defaults.coord} onClose={jest.fn()} />,
    );
    expect(screen.getByText(/loading settings/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
    expect(screen.getByText("Project agent default")).toBeInTheDocument();
    expect(screen.getByText(/3 used today/)).toBeInTheDocument();
    expect(screen.getByText("200")).toBeInTheDocument();
    expect(screen.getByText(/no project budget set/i)).toBeInTheDocument();
    expect(screen.getByText(/openai_compatible · llama4-nim/)).toBeInTheDocument();
    expect(screen.getAllByText("Inherited from account")).toHaveLength(3);
    expect(api.getProjectAgentDefaults).toHaveBeenCalledWith("p1", defaults.coord);
  });

  it("is read-only: no Publish/Release/Share or edit controls", async () => {
    render(
      <ProjectAgentSettingsModal projectId="p1" coord={defaults.coord} onClose={jest.fn()} />,
    );
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
    for (const name of [/publish/i, /release/i, /share/i, /save/i, /edit/i]) {
      expect(screen.queryByRole("button", { name })).not.toBeInTheDocument();
    }
    expect(screen.getByText(/become editable with the cost, quotas/i)).toBeInTheDocument();
  });

  it("surfaces a load failure with retry", async () => {
    api.getProjectAgentDefaults.mockRejectedValueOnce(new Error("boom"));
    render(
      <ProjectAgentSettingsModal projectId="p1" coord={defaults.coord} onClose={jest.fn()} />,
    );
    await waitFor(() => expect(screen.getByText(/boom/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
  });

  it("closes via the shell close button", async () => {
    const onClose = jest.fn();
    render(<ProjectAgentSettingsModal projectId="p1" coord={defaults.coord} onClose={onClose} />);
    await waitFor(() => expect(screen.getByText("Chat")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalled();
  });
});
