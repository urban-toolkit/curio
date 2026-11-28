import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

import { AgentDatasetCandidatesCard } from "../../components/agents/content/AgentDatasetCandidatesCard";
import { DatasetDetailsContext } from "../../components/datasets/catalog/datasetDetailsContext";
import type { AgentDatasetCandidatesPart, AgentDatasetSourceRecord } from "../../services/agents";

/**
 * The Sources card as the signed-off board S04 draws it (step 7.1 of the
 * owner's agent chat plan, part 2): one list of rows, best first, each its
 * name, where it comes from, why it fits the node and at most one warning; a
 * portal download's How to get it; one link per row; None fits? to the
 * Finder's chat; and, once picked, Recorded with what comes of the pick
 * (board S05). The fields this part adds are cast, so the file type checks on
 * the branch before it.
 */

// The board's rows: a portal page the probe read as a web page, whose portal
// did not confirm its dataset id; an Overpass query that answered 406; an
// endpoint code can fetch; and a dataset the dataflow holds.
const PORTAL = {
  name: "Chicago Public Library locations, hours and contact info",
  sourceType: "portal",
  url: "https://data.cityofchicago.org/d/x8fc-8rcq",
  provider: "Chicago Data Portal",
  format: "CSV, GeoJSON",
  fit: {
    score: 90,
    rationale: "The city's list of CPL branches with name, address and lat/long: the fields this node loads.",
  },
  access: "manual-download",
  accessWhy: "the data URL answered with a web page",
  downloadSteps: [
    "Open the portal page in your browser: https://data.cityofchicago.org/d/x8fc-8rcq",
    "Save the CSV file the portal offers.",
  ],
  sourceId: "source.cityofchicago.data-portal@1",
  resourceId: "x8fc-8rcq",
  verification: { status: "verified", httpStatus: 200, contentType: "text/html", webPage: true },
};
const OVERPASS = {
  name: "Chicago libraries in OpenStreetMap",
  sourceType: "api",
  url: "https://overpass-api.de/api/interpreter?data=libraries",
  provider: "OpenStreetMap, through Overpass",
  format: "JSON",
  fit: { score: 60, rationale: "Library points and footprints; branch names and addresses are less reliable." },
  verification: { status: "http-error", httpStatus: 406, detail: "the endpoint answered 406" },
};
const ENDPOINT = {
  name: "Branch endpoint",
  sourceType: "api",
  url: "https://data.example.org/branches.json",
  format: "JSON",
  access: "fetchable",
  fit: { score: 70, rationale: "Branch points as JSON." },
  verification: { status: "verified", httpStatus: 200, contentType: "application/json" },
};
const HELD = {
  name: "Chicago Neighborhoods",
  sourceType: "catalog",
  datasetId: "imported.neighborhoods@1",
  installed: true,
  format: "GeoJSON",
  fit: { score: 55, rationale: "Neighborhood outlines, with no branches." },
};

/** The card as the server ranks it: one list across both lanes, which puts
 * the dataset the dataflow holds between two external rows. */
const PART = {
  type: "datasetCandidates",
  lanes: { external: [ENDPOINT, PORTAL, OVERPASS], catalog: [HELD] },
  laneOrder: ["external", "catalog"],
  rowOrder: [["external", 0], ["catalog", 0], ["external", 1], ["external", 2]],
} as unknown as AgentDatasetCandidatesPart;

/** The row of the card that names *name*. */
const rowOf = (name: string): HTMLElement =>
  screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement;

describe("the Sources card is one list, best first (board S04)", () => {
  it("draws its rows in the server's order across both lanes, with no lane of its own", () => {
    render(<AgentDatasetCandidatesCard part={PART} nodeLabel="CPL branches" onRecordSelection={jest.fn()} />);
    expect(screen.getAllByRole("checkbox").map((box) => box.getAttribute("aria-label"))).toEqual([
      "Select Branch endpoint",
      "Select Chicago Neighborhoods",
      `Select ${PORTAL.name}`,
      `Select ${OVERPASS.name}`,
    ]);
    expect(screen.queryByRole("group", { name: "External sources" })).toBeNull();
    expect(screen.queryByRole("group", { name: "From your Data Catalog" })).toBeNull();
  });
});

describe("a row says where it comes from, why it fits and what keeps it from being used", () => {
  it("says why it fits the node with no score, and where it comes from", () => {
    render(<AgentDatasetCandidatesCard part={PART} nodeLabel="CPL branches" onRecordSelection={jest.fn()} />);
    expect(within(rowOf(PORTAL.name)).getByText(PORTAL.fit.rationale)).toBeInTheDocument();
    expect(screen.queryByText(/Fit \d+\/100/)).toBeNull();
    expect(within(rowOf(PORTAL.name)).getByText("Chicago Data Portal · CSV, GeoJSON")).toBeInTheDocument();
    // A dataset with no provider comes from the Data Catalog.
    expect(within(rowOf(HELD.name)).getByText("Data Catalog · GeoJSON")).toBeInTheDocument();
  });

  it("carries at most one warning, in words, and no chip", () => {
    render(<AgentDatasetCandidatesCard part={PART} nodeLabel="CPL branches" onRecordSelection={jest.fn()} />);
    expect(
      within(rowOf(PORTAL.name)).getByText(
        "Manual download: the data URL answered with a web page, and its dataset id is not confirmed.",
      ),
    ).toBeInTheDocument();
    // What the probe saw is the warning's tooltip.
    expect(within(rowOf(OVERPASS.name)).getByText("Answered 406: not usable as offered.")).toHaveAttribute(
      "data-tooltip",
      "the endpoint answered 406",
    );
    // A link that answered data, and a dataset the dataflow holds, carry none.
    expect(rowOf(ENDPOINT.name).querySelectorAll(".warning")).toHaveLength(0);
    expect(rowOf(HELD.name).querySelectorAll(".warning")).toHaveLength(0);
    for (const chip of ["Installed", "Not installed", "Downloadable", "Verified ✓", "Web page", "Answered 406 ✗", "api", "portal", "catalog"]) {
      expect(screen.queryByText(chip)).toBeNull();
    }
  });

  it("opens a portal download's steps and its Import dataset with How to get it, which picks nothing", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        nodeLabel="CPL branches"
        onRecordSelection={jest.fn()}
        onImportDataset={jest.fn()}
      />,
    );
    const row = rowOf(PORTAL.name);
    expect(within(row).queryByText(/Open the portal page in your browser/)).toBeNull();
    expect(within(row).queryByText("Import dataset")).toBeNull();
    fireEvent.click(within(row).getByRole("button", { name: "How to get it" }));
    expect(within(row).getByText(/Open the portal page in your browser/)).toBeInTheDocument();
    expect(within(row).getByText("Import dataset")).toBeInTheDocument();
    expect(within(row).getByRole("checkbox")).not.toBeChecked();
    // A link code can fetch, and one that answered an error, have nothing to
    // get by hand.
    expect(within(rowOf(ENDPOINT.name)).queryByRole("button", { name: "How to get it" })).toBeNull();
    expect(within(rowOf(OVERPASS.name)).queryByRole("button", { name: "How to get it" })).toBeNull();
  });

  it("has one link: Portal for a link the runtime vouched for, View details for a dataset", () => {
    const openDatasetDetails = jest.fn();
    render(
      <DatasetDetailsContext.Provider value={{ openDatasetDetails }}>
        <AgentDatasetCandidatesCard part={PART} nodeLabel="CPL branches" onRecordSelection={jest.fn()} />
      </DatasetDetailsContext.Provider>,
    );
    expect(within(rowOf(PORTAL.name)).getByRole("link", { name: "Portal ↗" })).toHaveAttribute("href", PORTAL.url);
    expect(within(rowOf(ENDPOINT.name)).getByRole("link", { name: "Portal ↗" })).toHaveAttribute("href", ENDPOINT.url);
    // A link that answered an error is no link.
    expect(within(rowOf(OVERPASS.name)).queryByRole("link")).toBeNull();
    fireEvent.click(within(rowOf(HELD.name)).getByRole("button", { name: "View details" }));
    expect(openDatasetDetails).toHaveBeenCalledWith("imported.neighborhoods@1");
    expect(within(rowOf(HELD.name)).getByRole("checkbox")).not.toBeChecked();
  });
});

describe("the card's foot and its Recorded line", () => {
  it("asks the node's Dataset Finder when none fits, from the chat that asked", () => {
    const onOpen = jest.fn();
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        nodeLabel="CPL branches"
        onRecordSelection={jest.fn()}
        finderChat={{ name: "Dataset Finder", onOpen }}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "None fits? Ask its Dataset Finder" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("says Recorded with the pick, where it comes from and what comes of it (board S05)", () => {
    const record = {
      status: "resolved",
      picks: [HELD],
      next: "The Dataflow Builder builds CPL branches from it.",
    } as unknown as AgentDatasetSourceRecord;
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        nodeLabel="CPL branches"
        onRecordSelection={jest.fn()}
        record={record}
        waitsForPick={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      /^Recorded: Chicago Neighborhoods \(Data Catalog\)\. The Dataflow Builder builds CPL branches from it\.$/,
    );
  });

  // Dev check of #1652 (11-28): a portal row the pick downloaded read "(Data
  // Catalog)". The server keeps the portal on the pick it becomes.
  it("names a pick Curio downloaded by the portal it came from, not the Data Catalog it lands in", () => {
    const record = {
      status: "resolved",
      picks: [
        {
          name: "Libraries - Locations, Contact Information, and Usual Hours of Operation",
          sourceType: "catalog",
          datasetId: "imported.xefd08dde184e",
          imported: true,
          provider: "City of Chicago Data Portal",
          discoverySource: { sourceId: "source.cityofchicago.data-portal@1", resourceId: "x8fc-8rcq" },
        },
      ],
      next: "The Dataflow Builder builds CPL branches from it.",
    } as unknown as AgentDatasetSourceRecord;
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        nodeLabel="CPL branches"
        onRecordSelection={jest.fn()}
        record={record}
        waitsForPick={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      /^Recorded: Libraries - Locations, Contact Information, and Usual Hours of Operation \(City of Chicago Data Portal\)\. The Dataflow Builder builds CPL branches from it\.$/,
    );
  });

  it("says nothing of how to confirm it on a card with no pick of its own", () => {
    render(<AgentDatasetCandidatesCard part={PART} onComposePrompt={jest.fn()} />);
    expect(screen.queryByText(/select & confirm in chat/i)).toBeNull();
    // Selecting still writes the confirmation into the message box.
    expect(screen.getAllByRole("checkbox")).toHaveLength(4);
  });
});
