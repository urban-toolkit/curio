import React from "react";
import { render, screen, fireEvent, act, within } from "@testing-library/react";

import {
  AgentDatasetCandidatesCard,
  composeConfirmationPrompt,
  rowProvenance,
} from "../../components/agents/content/AgentDatasetCandidatesCard";
import type { AgentDatasetCandidatesPart } from "../../services/agents";
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

describe("AgentDatasetCandidatesCard (dev/50, the Sources card of board S04)", () => {
  it("renders one list of informational rows: where each comes from, why it fits, and its warning", () => {
    render(<AgentDatasetCandidatesCard part={PART} />);
    // One list: the lanes are no groups of their own (board S04).
    expect(screen.queryByRole("group", { name: "External sources" })).toBeNull();
    expect(screen.queryByRole("group", { name: "From your Data Catalog" })).toBeNull();
    expect(screen.getAllByRole("listitem").map((row) => row.querySelector("input")?.getAttribute("aria-label"))).toEqual([
      "Select NOAA Climate Data API",
      "Select Cities",
      "Select Roads",
    ]);
    expect(screen.getByText("NOAA Climate Data API")).toBeInTheDocument();
    expect(screen.getByText("NOAA · json")).toBeInTheDocument();
    // Why it fits, with no score.
    expect(screen.getByText("direct match")).toBeInTheDocument();
    expect(screen.queryByText(/Fit 90\/100/)).toBeNull();
    // What it needs is its one warning, a sentence.
    expect(screen.getByText("API token required.")).toBeInTheDocument();
    // No chip says whether a dataset is installed: a pick adds it.
    expect(screen.queryByText("Installed")).toBeNull();
    expect(screen.queryByText("Not installed")).toBeNull();
    expect(screen.getAllByText("Data Catalog")).toHaveLength(2);
  });

  it("selection is the only action a row takes (docs/06)", () => {
    render(<AgentDatasetCandidatesCard part={PART} />);
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    // A row's buttons open what it names, read-only: the link the runtime did
    // not vouch for, as plain text, and each catalog row's details; nothing
    // here applies, installs or downloads.
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual(["How to get it", "View details", "View details"]);
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
          { name: "Downloadable", sourceType: "discovery", url: "https://source.example/r",
            acquirable: true, sourceId: "source.a", resourceId: "r" },
          { name: "Model claim", sourceType: "api", url: "https://claimed.example/y" },
          { name: "Bad scheme", sourceType: "api", url: "javascript:alert(1)",
            verification: { status: "verified" } } as any,
        ],
        catalog: [],
      },
    };
    render(<AgentDatasetCandidatesCard part={part} />);
    const links = screen.getAllByRole("link", { name: "Portal ↗" });
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://ok.example/x",
      "https://source.example/r",
    ]);
    links.forEach((a) => expect(a).toHaveAttribute("rel", expect.stringContaining("noopener")));
    // Unvouched URLs stay plain text, under their row's How to get it.
    for (const [name, url] of [
      ["Model claim", "https://claimed.example/y"],
      ["Bad scheme", "javascript:alert(1)"],
    ]) {
      const row = screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement;
      expect(within(row).queryByText(url)).toBeNull();
      fireEvent.click(within(row).getByRole("button", { name: "How to get it" }));
      expect(within(row).getByText(url).tagName).toBe("SPAN");
      expect(within(row).queryByRole("link")).toBeNull();
    }
    expect(screen.getAllByRole("link")).toHaveLength(2);
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
    render(<AgentDatasetCandidatesCard part={PART} onComposePrompt={onComposePrompt} handoffName="Node Builder" />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Cities" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Confirm my selection. Install from the Data Catalog: Cities (imported.abc@1).",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Confirm my selection. Install from the Data Catalog: Cities (imported.abc@1); " +
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
  // Board S04: a row carries a warning, never a chip, so a link that answered
  // data says nothing more, and every other verdict is its row's warning, in
  // the words of the one label table.
  it("says the runtime's verdict of each external row that gave no data, loud, and nothing of one that did", () => {
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
              {
                name: "Down API", sourceType: "endpoint",
                url: "https://down.example.gov/data.json",
                verification: { status: "unreachable", detail: "timed out" },
              },
            ],
            catalog: [],
          },
        }}
        onComposePrompt={jest.fn()}
      />,
    );
    const warningOf = (name: string) =>
      (screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement).querySelector(".warning");
    expect(warningOf("Chicago Heat")).toBeNull();
    expect(screen.queryByText("Verified ✓")).toBeNull();
    expect(warningOf("Guessed Portal")).toHaveTextContent(/^Unverified: never checked\.$/);
    // An error answer says what it answered (step 5.4); Unreachable is for a
    // link that gave no answer. Neither is usable as offered.
    expect(warningOf("Dead API")).toHaveTextContent(/^Answered 404: not usable as offered\.$/);
    expect(warningOf("Down API")).toHaveTextContent(/^Unreachable: not usable as offered\.$/);
    // What the probe saw is on the warning's tooltip.
    expect(warningOf("Dead API")).toHaveAttribute("data-tooltip", "the endpoint answered 404");
  });
});


describe("AgentDatasetCandidatesCard — dev/114 the Node Builder chat variant", () => {
  it("composes the build request instead of the hand-off in a Node Builder chat", () => {
    const onComposePrompt = jest.fn();
    render(<AgentDatasetCandidatesCard part={PART} onComposePrompt={onComposePrompt} variant="builder" />);
    fireEvent.click(screen.getByRole("checkbox", { name: "Select NOAA Climate Data API" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Build the data-loading node. Fetch from: NOAA Climate Data API (https://api.noaa.gov).",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Cities" }));
    expect(onComposePrompt).toHaveBeenLastCalledWith(
      "Build the data-loading node. Load from the Data Catalog: Cities (imported.abc@1); " +
        "fetch from: NOAA Climate Data API (https://api.noaa.gov).",
    );
    // Still only the read-only buttons, How to get it and View details; the
    // prompt stays the vehicle (docs/06).
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual([
      "How to get it",
      "View details",
      "View details",
    ]);
  });

  it("the finder variant is the default and unchanged", () => {
    expect(composeConfirmationPrompt([], [PART.lanes.external[0]], undefined, "Node Builder")).toBe(
      "Confirm my selection. Hand off to Node Builder: NOAA Climate Data API.",
    );
    expect(composeConfirmationPrompt([], [PART.lanes.external[0]], "builder")).toBe(
      "Build the data-loading node. Fetch from: NOAA Climate Data API (https://api.noaa.gov).",
    );
  });
});

describe("AgentDatasetCandidatesCard — dev/132 the portal download and its Import", () => {
  const MANUAL: AgentDatasetCandidatesPart = {
    type: "datasetCandidates",
    lanes: {
      external: [
        {
          name: "Setores GeoSampa",
          sourceType: "portal",
          url: "https://geosampa.example.gov.br/downloads",
          format: "Shapefile (zip)",
          access: "manual-download",
          accessWhy: 'the data URL answered with a web page titled "Downloads"',
          downloadSteps: [
            "Open the portal page in your browser: https://geosampa.example.gov.br/downloads",
            "Save the Shapefile (zip) file the portal offers.",
            "Then use Import dataset below: it registers the file in this project's Data Catalog, and the node is built from it.",
          ],
        },
        {
          name: "NOAA Climate Data API",
          sourceType: "api",
          url: "https://api.noaa.gov",
          access: "fetchable",
          accessWhy: "the endpoint answered 200 with application/json",
        },
      ],
      catalog: [],
    },
  };

  /** Opens the How to get it of the row named *name*. */
  const openHowTo = (name: string) => {
    const row = screen.getByRole("checkbox", { name: `Select ${name}` }).closest("li") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "How to get it" }));
    return row;
  };

  it("teaches the download only for the row that needs it", () => {
    render(<AgentDatasetCandidatesCard part={MANUAL} />);
    expect(
      screen.getByText('Manual download: the data URL answered with a web page titled "Downloads".'),
    ).toBeInTheDocument();
    // The portal's steps are under its How to get it.
    const row = openHowTo("Setores GeoSampa");
    expect(within(row).getByText(/Open the portal page in your browser/)).toBeInTheDocument();
    // The fetchable row teaches nothing: its code is written for it.
    expect(screen.getAllByText(/^Manual download/)).toHaveLength(1);
    expect(screen.getAllByText(/Open the portal page in your browser/)).toHaveLength(1);
    // No Import control without the host's import (a canvas-level chat).
    expect(screen.queryByText("Import dataset")).toBeNull();
  });

  it("imports the downloaded file and confirms it as the node's source", async () => {
    const onImportDataset = jest.fn().mockResolvedValue("imported.x99@1");
    const onRecordSelection = jest.fn().mockResolvedValue({
      attachmentId: "att-df",
      nodeId: "n1",
      status: "resolved",
      picks: [],
      delegated: { status: "delegating", nodeId: "n1" },
    });
    const { container } = render(
      <AgentDatasetCandidatesCard
        part={MANUAL}
        onImportDataset={onImportDataset}
        onRecordSelection={onRecordSelection}
      />,
    );
    openHowTo("Setores GeoSampa");
    expect(screen.getByText("Import dataset")).toBeInTheDocument();
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["a,b\n1,2\n"], "setores.zip", { type: "application/zip" });
    await act(async () => {
      fireEvent.change(input, { target: { files: [file] } });
    });
    // The file carries where it came from: the row's link, recorded with it.
    expect(onImportDataset).toHaveBeenCalledWith(file, {
      resourceUrl: "https://geosampa.example.gov.br/downloads",
    });
    // The just-imported dataset IS the node's source — one catalog pick.
    expect(onRecordSelection).toHaveBeenCalledWith([
      { lane: "catalog", key: "imported.x99@1" },
    ]);
    // And the card says the builder took over from there.
    expect(screen.getByRole("status")).toHaveTextContent(
      /^Source recorded: its builder is writing the loader from it now\.$/,
    );
  });

  it("a failed import records nothing", async () => {
    const onImportDataset = jest.fn().mockResolvedValue(null);
    const onRecordSelection = jest.fn();
    const { container } = render(
      <AgentDatasetCandidatesCard
        part={MANUAL}
        onImportDataset={onImportDataset}
        onRecordSelection={onRecordSelection}
      />,
    );
    openHowTo("Setores GeoSampa");
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    await act(async () => {
      fireEvent.change(input, {
        target: { files: [new File(["x"], "broken.zip")] },
      });
    });
    expect(onRecordSelection).not.toHaveBeenCalled();
  });

  it("a confirmed fetchable row says the session will pick the node up", async () => {
    const onRecordSelection = jest.fn().mockResolvedValue({
      attachmentId: "att-df",
      nodeId: "n1",
      status: "resolved",
      picks: [],
      delegated: {
        status: "session-running",
        reason: "the running Solve session picks this node up on its next pass",
      },
    });
    render(
      <AgentDatasetCandidatesCard part={MANUAL} onRecordSelection={onRecordSelection} />,
    );
    fireEvent.click(screen.getByLabelText("Select NOAA Climate Data API"));
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: /Use this source/ }),
      );
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      /^Source recorded: the running Solve session builds its loader on its next pass\.$/,
    );
  });
});

// The card in the Dataset Finder's chat, and the same card in the chat that
// asked for it: the source its Finder recorded, as the listing has it.
describe("AgentDatasetCandidatesCard: the source recorded for its node", () => {
  const ROADS = { name: "Roads", sourceType: "catalog" as const, datasetId: "imported.def@1", installed: true };

  it("names the node it finds a source for, and its pick button reads Use this source", () => {
    render(<AgentDatasetCandidatesCard part={PART} nodeLabel="Load buildings" onRecordSelection={jest.fn()} />);
    const card = screen.getByRole("group", { name: "Sources for Load buildings" });
    expect(card).toHaveTextContent("Sources for Load buildings");
    expect(within(card).getByRole("button", { name: "Use this source" })).toBeDisabled();
  });

  it("says Recorded with what was picked, where it comes from and what comes of it, in place of its rows and Use this source", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        nodeLabel="Load buildings"
        onRecordSelection={jest.fn()}
        record={{
          status: "resolved",
          picks: [{ ...ROADS, provider: "City of Chicago" }],
          next: "The Dataflow Builder builds Load buildings from it.",
        }}
        waitsForPick={false}
      />,
    );
    const card = screen.getByRole("group", { name: "Sources for Load buildings" });
    // What comes of the pick is the record's, as the server said it (board
    // S05): the Source recorded turns are the agents' alone, so the chat says
    // it once, here.
    expect(within(card).getByRole("status")).toHaveTextContent(
      /^Recorded: Roads \(City of Chicago\)\. The Dataflow Builder builds Load buildings from it\.$/,
    );
    expect(within(card).queryByRole("button", { name: "Use this source" })).toBeNull();
    expect(within(card).queryAllByRole("checkbox")).toHaveLength(0);
  });

  it("says Recorded with what was picked alone when the server said nothing of what comes next", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        onRecordSelection={jest.fn()}
        record={{ status: "resolved", picks: [{ ...ROADS, provider: "City of Chicago" }] }}
        waitsForPick={false}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent(/^Recorded: Roads \(City of Chicago\)\.$/);
  });

  it("says a picked source that downloads for a paused plan is Recorded, from the Data Catalog, and to press Resume once it lands", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        onRecordSelection={jest.fn()}
        record={{
          status: "awaiting-install",
          picks: [{ ...ROADS, installed: false, acquiring: { jobId: "j1" } }],
          next: "It is downloading into the Data Catalog: once it lands, press Resume in the Dataflow Builder's chat to build the loader.",
        }}
        waitsForPick={false}
      />,
    );
    // A catalog pick with no provider comes from the Data Catalog.
    expect(screen.getByRole("status")).toHaveTextContent(
      /^Recorded: Roads \(Data Catalog\)\. It is downloading into the Data Catalog: once it lands, press Resume in the Dataflow Builder's chat to build the loader\.$/,
    );
  });

  it("keeps its rows while the node still waits for the user's pick", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        onRecordSelection={jest.fn()}
        record={{ status: "candidates-pending", candidates: 3 }}
        waitsForPick
      />,
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Use this source" })).toBeInTheDocument();
    expect(screen.queryByText(/^Recorded:/)).toBeNull();
  });
});

// The Recorded line names the pick and where it comes from, then what comes
// of it in the server's words (the record's `next`, board S05), and none of
// its own: the server never promises a build nobody starts, and neither does
// the line. The Source recorded turns are the agents' alone, so the chat says
// it once, here.
describe("AgentDatasetCandidatesCard: the Recorded line says what comes next as the server said it", () => {
  const ROADS = { name: "Roads", sourceType: "catalog" as const, datasetId: "imported.def@1", installed: true };

  it("a download no plan waits on says Recorded, then to Solve the node once it lands, and that no build comes by itself", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        onRecordSelection={jest.fn()}
        record={{
          status: "awaiting-install",
          picks: [{ ...ROADS, installed: false, acquiring: { jobId: "j1" } }],
          next: "It is downloading into the Data Catalog: Solve the node once it lands.",
        }}
        waitsForPick={false}
      />,
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(
      /^Recorded: Roads \(Data Catalog\)\. It is downloading into the Data Catalog: Solve the node once it lands\.$/,
    );
    expect(status).not.toHaveTextContent("the loader is built from it once it lands");
  });

  it("a pick no builder takes says Recorded, then what the user must do, and promises no build", () => {
    render(
      <AgentDatasetCandidatesCard
        part={PART}
        onRecordSelection={jest.fn()}
        record={{
          status: "resolved",
          picks: [ROADS],
          next: "No builder is attached to this node: Solve the node, or attach a Node Builder to it.",
        }}
        waitsForPick={false}
      />,
    );
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent(
      /^Recorded: Roads \(Data Catalog\)\. No builder is attached to this node: Solve the node, or attach a Node Builder to it\.$/,
    );
    expect(status).not.toHaveTextContent("The loader is built from this source");
  });
});

describe("AgentDatasetCandidatesCard — a row Curio downloads", () => {
  const DISCOVERY: AgentDatasetCandidatesPart = {
    type: "datasetCandidates",
    lanes: {
      external: [
        {
          // A connector row whose landing page is a portal: the probe says a
          // person would download it, but Curio downloads it itself.
          name: "Chicago community areas",
          sourceType: "discovery",
          url: "https://data.cityofchicago.org/d/cauq-8yn6",
          sourceId: "source.cityofchicago.data-portal@1",
          resourceId: "cauq-8yn6",
          acquirable: true,
          access: "manual-download",
          accessWhy: "the data URL answered with a web page",
          downloadSteps: ["Open the portal page in your browser: https://data.cityofchicago.org"],
        },
        {
          name: "Chicago wards",
          sourceType: "discovery",
          sourceId: "source.cityofchicago.data-portal@1",
          resourceId: "sp34-6z76",
          acquirable: true,
        },
      ],
      catalog: [],
    },
  };

  it("offers only the download, never the portal steps", () => {
    render(<AgentDatasetCandidatesCard part={DISCOVERY} onImportDataset={jest.fn()} />);
    expect(screen.getAllByRole("button", { name: "Download" })).toHaveLength(2);
    // No warning of a portal download, and nothing to get by hand.
    expect(screen.queryByText(/Manual download/)).toBeNull();
    expect(screen.queryByRole("button", { name: "How to get it" })).toBeNull();
    expect(screen.queryByText(/Open the portal page in your browser/)).toBeNull();
    expect(screen.queryByText("Import dataset")).toBeNull();
  });

  it("confirms a row with no url by its coordinate and says it is downloading", async () => {
    const onRecordSelection = jest.fn().mockResolvedValue({
      attachmentId: "att-df",
      nodeId: "n1",
      status: "awaiting-install",
      picks: [],
      delegated: {
        status: "acquiring",
        reason: "Chicago wards is downloading into your Data Catalog; Solve the node once it lands",
      },
    });
    render(<AgentDatasetCandidatesCard part={DISCOVERY} onRecordSelection={onRecordSelection} />);
    fireEvent.click(screen.getByLabelText("Select Chicago wards"));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /Use this source/ }));
    });
    expect(onRecordSelection).toHaveBeenCalledWith([
      { lane: "external", key: "source.cityofchicago.data-portal@1/sp34-6z76" },
    ]);
    expect(screen.getByText(/downloading into your Data Catalog/)).toBeInTheDocument();
  });
});

describe("rowProvenance", () => {
  it("states a row's coordinate and link, and nothing for a row with neither", () => {
    expect(rowProvenance({
      name: "a", sourceType: "discovery", url: "https://x.example/a.csv",
      sourceId: "source.a.b@1", resourceId: "r1",
    })).toEqual({ sourceId: "source.a.b@1", resourceId: "r1", resourceUrl: "https://x.example/a.csv" });
    expect(rowProvenance({ name: "a", sourceType: "document" })).toBeUndefined();
  });
});
