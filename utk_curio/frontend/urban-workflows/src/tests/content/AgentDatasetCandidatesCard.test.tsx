import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import {
  AgentDatasetCandidatesCard,
  composeConfirmationPrompt,
} from "../../components/agents/content/AgentDatasetCandidatesCard";
import type { AgentDatasetCandidatesPart } from "../../api/agentsApi";
import { DatasetDetailsContext } from "../../components/datasets/catalog/datasetDetailsContext";

const PART: AgentDatasetCandidatesPart = {
  type: "datasetCandidates",
  lanes: {
    external: [
      {
        name: "NOAA Climate Data API",
        sourceType: "api",
        url: "https://api.noaa.gov",
        provider: "NOAA",
        format: "json",
        fit: { score: 90, rationale: "direct match" },
        requirement: "API token required",
      },
    ],
    catalog: [
      { name: "Cities", sourceType: "catalog", datasetId: "imported.abc@1", installed: false },
      { name: "Roads", sourceType: "catalog", datasetId: "imported.def@1", installed: true },
    ],
  },
};

describe("AgentDatasetCandidatesCard (dev/50 — the docs/06 two-lane surface)", () => {
  it("renders both labeled lanes with informational rows and installed chips", () => {
    render(<AgentDatasetCandidatesCard part={PART} />);
    expect(screen.getByRole("group", { name: "External sources" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "From your Data Catalog" })).toBeInTheDocument();
    expect(screen.getByText("NOAA Climate Data API")).toBeInTheDocument();
    expect(screen.getByText("Fit 90/100 — direct match")).toBeInTheDocument();
    expect(screen.getByText("API token required")).toBeInTheDocument();
    expect(screen.getByText("Installed")).toBeInTheDocument();
    expect(screen.getAllByText("Not installed")).toHaveLength(1);
  });

  it("selection is the only action a row takes (docs/06)", () => {
    render(<AgentDatasetCandidatesCard part={PART} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    // The one button per catalog row opens what it names, read-only; nothing
    // here applies, installs or downloads.
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["View details", "View details"]);
  });

  it("a catalog row opens the dataset's details, like the same row anywhere else", () => {
    const openDatasetDetails = jest.fn();
    const onComposePrompt = jest.fn();
    render(
      <DatasetDetailsContext.Provider value={{ openDatasetDetails }}>
        <AgentDatasetCandidatesCard part={PART} onComposePrompt={onComposePrompt} />
      </DatasetDetailsContext.Provider>,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "View details" })[0]);
    expect(openDatasetDetails).toHaveBeenCalledWith("imported.abc@1");
    // Opening details is not a selection.
    expect(onComposePrompt).not.toHaveBeenCalled();
    expect(screen.getByRole("checkbox", { name: "Select Cities" })).not.toBeChecked();
  });

  it("links an external row to its portal only when the runtime vouched for the URL", () => {
    const part: AgentDatasetCandidatesPart = {
      type: "datasetCandidates",
      lanes: {
        external: [
          { name: "Verified", sourceType: "api", url: "https://ok.example/x",
            verification: { status: "verified" } } as any,
          { name: "Downloadable", sourceType: "lake", url: "https://lake.example/r",
            acquirable: true, sourceId: "lake.a", resourceId: "r" },
          { name: "Model claim", sourceType: "api", url: "https://claimed.example/y" },
          { name: "Bad scheme", sourceType: "api", url: "javascript:alert(1)",
            verification: { status: "verified" } } as any,
        ],
        catalog: [],
      },
    };
    render(<AgentDatasetCandidatesCard part={part} />);
    const links = screen.getAllByRole("link", { name: "View on the portal ↗" });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://ok.example/x",
      "https://lake.example/r",
    ]);
    links.forEach((a) => expect(a).toHaveAttribute("rel", expect.stringContaining("noopener")));
    // Unvouched URLs stay plain text, as before.
    expect(screen.getByText("https://claimed.example/y")).toBeInTheDocument();
    expect(screen.getByText("javascript:alert(1)")).toBeInTheDocument();
  });

  it("hostile metadata renders inert as plain text", () => {
    const hostile: AgentDatasetCandidatesPart = {
      type: "datasetCandidates",
      lanes: {
        external: [
          {
            name: '<img src=x onerror="window.__candPwned=true">',
            sourceType: "portal",
          },
        ],
        catalog: [],
      },
    };
    const { container } = render(<AgentDatasetCandidatesCard part={hostile} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x");
    expect((window as unknown as { __candPwned?: boolean }).__candPwned).toBeUndefined();
  });

  it("toggling selection composes the lane-correct confirmation prompt", () => {
    const onComposePrompt = jest.fn();
    render(<AgentDatasetCandidatesCard part={PART} onComposePrompt={onComposePrompt} />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Cities" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Confirm my selection — install from the Data Catalog: Cities (imported.abc@1).",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Confirm my selection — install from the Data Catalog: Cities (imported.abc@1); " +
        "hand off to Node Builder: NOAA Climate Data API.",
    );
    // Deselecting empties the composition back out.
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Cities" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith("");
  });

  it("composeConfirmationPrompt is empty with no selection", () => {
    expect(composeConfirmationPrompt([], [])).toBe("");
  });
});

describe("AgentDatasetCandidatesCard — dev/67-4 verification verdicts", () => {
  it("renders the runtime's verdict per external row — verified or loud", () => {
    render(
      <AgentDatasetCandidatesCard
        part={{
          type: "datasetCandidates",
          lanes: {
            external: [
              {
                name: "Chicago Heat", sourceType: "api",
                url: "https://data.cityofchicago.org/resource/abcd-1234.json",
                verification: { status: "verified", datasetName: "Chicago Heat Deaths 2024" },
              },
              {
                name: "Guessed Portal", sourceType: "portal",
                verification: { status: "unverified", detail: "no probeable URL — the identifier was never checked" },
              },
              {
                name: "Dead API", sourceType: "endpoint",
                url: "https://data.example.gov/gone.json",
                verification: { status: "unreachable", httpStatus: 404, detail: "the endpoint answered 404" },
              },
            ],
            catalog: [],
          },
        }}
        onComposePrompt={jest.fn()}
      />,
    );
    expect(screen.getByText("Verified ✓")).toBeInTheDocument();
    expect(screen.getByText("Unverified — never checked")).toBeInTheDocument();
    expect(screen.getByText("Unreachable ✗")).toBeInTheDocument();
  });
});
