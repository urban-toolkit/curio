import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("../../api/agentsApi", () => ({
  agentsApi: { catalogSettings: jest.fn(), updateCatalogSettings: jest.fn() },
}));

import { agentsApi, type CatalogSettingsResponse } from "../../api/agentsApi";
import {
  AgentCatalogSettingsModal,
  fromRows,
  itemSchema,
} from "../../components/agents/catalog/AgentCatalogSettingsModal";

const api = agentsApi as jest.Mocked<typeof agentsApi>;

const SCHEMA = {
  type: "array",
  items: {
    type: "object",
    required: ["name", "description"],
    properties: {
      name: { type: "string" },
      description: { type: "string" },
      examples: { type: "array", items: { type: "string" } },
    },
  },
};

const DEFAULT = [
  { name: "Action", description: "a verb.", examples: ["Load", "Filter"] },
  { name: "None", description: "anything else." },
];

function response(overrides: Partial<CatalogSettingsResponse> = {}, value: unknown = DEFAULT) {
  return {
    editable: true,
    reason: null,
    settings: [
      {
        key: "keywordTypes",
        label: "Keyword types",
        description: "The types a keyword can take.",
        schema: SCHEMA,
        default: DEFAULT,
        value,
        isDefault: value === DEFAULT,
        readBy: [
          {
            agentId: "agent.dataflow-planner",
            agentName: "Dataflow Planner",
            capability: "workflow.keywords.extract",
            internal: true,
          },
          {
            agentId: "agent.dataflow-planner",
            agentName: "Dataflow Planner",
            capability: "workflow.keyword.bind",
            internal: true,
          },
        ],
      },
    ],
    ...overrides,
  } as CatalogSettingsResponse;
}

beforeEach(() => jest.resetAllMocks());

describe("the entry editor", () => {
  it("reads its fields from the setting's schema", () => {
    const item = itemSchema(SCHEMA)!;
    expect(item.fields).toEqual([
      { name: "name", list: false },
      { name: "description", list: false },
      { name: "examples", list: true },
    ]);
    expect(itemSchema({ type: "string" })).toBeNull();
  });

  it("turns rows back into the value, leaving out empty optional fields", () => {
    const item = itemSchema(SCHEMA)!;
    expect(
      fromRows(
        [
          { name: " Hazard ", description: "a hazard.", examples: "flood, heat wave ," },
          { name: "Asset", description: "what it damages.", examples: "" },
        ],
        item
      )
    ).toEqual([
      { name: "Hazard", description: "a hazard.", examples: ["flood", "heat wave"] },
      { name: "Asset", description: "what it damages." },
    ]);
  });
});

describe("AgentCatalogSettingsModal", () => {
  it("shows the value and which agents read it", async () => {
    api.catalogSettings.mockResolvedValue(response());
    render(<AgentCatalogSettingsModal onClose={jest.fn()} />);
    expect(await screen.findByDisplayValue("Action")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Load, Filter")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Read by Dataflow Planner (workflow.keywords.extract, workflow.keyword.bind)."
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Default")).toBeInTheDocument();
    // Nothing to restore while the value is the default.
    expect(screen.getByRole("button", { name: "Restore default" })).toBeDisabled();
  });

  it("saves the edited rows", async () => {
    const saved = [{ name: "Hazard", description: "a verb.", examples: ["Load", "Filter"] }];
    api.catalogSettings.mockResolvedValue(response());
    api.updateCatalogSettings.mockResolvedValue(response({}, saved));
    render(<AgentCatalogSettingsModal onClose={jest.fn()} />);
    fireEvent.change(await screen.findByLabelText("Name 1"), { target: { value: "Hazard" } });
    fireEvent.click(screen.getByRole("button", { name: "Remove None" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.updateCatalogSettings).toHaveBeenCalledWith({ keywordTypes: saved })
    );
    expect(await screen.findByText("Saved")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("None")).not.toBeInTheDocument();
  });

  it("adds a row, and restores the default with null", async () => {
    const edited = [{ name: "Hazard", description: "a hazard." }];
    api.catalogSettings.mockResolvedValue(response({}, edited));
    api.updateCatalogSettings.mockResolvedValue(response());
    render(<AgentCatalogSettingsModal onClose={jest.fn()} />);
    await screen.findByDisplayValue("Hazard");
    fireEvent.click(screen.getByRole("button", { name: "Add row" }));
    expect(screen.getByLabelText("Name 2")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Restore default" }));
    await waitFor(() =>
      expect(api.updateCatalogSettings).toHaveBeenCalledWith({ keywordTypes: null })
    );
    expect(await screen.findByDisplayValue("Action")).toBeInTheDocument();
  });

  it("shows the server's refusal and keeps the edit", async () => {
    api.catalogSettings.mockResolvedValue(response());
    api.updateCatalogSettings.mockRejectedValue(
      new Error("keywordTypes[0][name]: '' should be non-empty")
    );
    render(<AgentCatalogSettingsModal onClose={jest.fn()} />);
    fireEvent.change(await screen.findByLabelText("Name 1"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("should be non-empty");
    expect(screen.getByLabelText("Name 1")).toHaveValue("");
  });

  it("is read-only for an account that may not change settings", async () => {
    api.catalogSettings.mockResolvedValue(
      response({ editable: false, reason: "Guests share one account." })
    );
    render(<AgentCatalogSettingsModal onClose={jest.fn()} />);
    expect(await screen.findByText("Guests share one account.")).toBeInTheDocument();
    expect(screen.getByLabelText("Name 1")).toHaveAttribute("readonly");
    expect(screen.queryByRole("button", { name: "Save" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add row" })).not.toBeInTheDocument();
  });
});
