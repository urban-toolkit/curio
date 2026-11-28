import React from "react";
import { render, screen } from "@testing-library/react";

import { AgentDatasetCandidatesCard } from "../../components/agents/content/AgentDatasetCandidatesCard";
import { VerificationChip } from "../../components/agents/content/verificationChip";
import type { AgentDatasetCandidatesPart } from "../../services/agents";

// Step 5.4 of the agent chat plan: a Dataset Finder's card says what each
// link answered, and draws first the lane that holds the row that can be used
// most directly. On dev (11-26) a portal's home page read "Verified ✓" beside
// the model's own guess, and an Overpass answer of 406 read "Unreachable ✗".
// The fields this step adds are cast, so the file type checks on main too.

describe("a candidate's link says what it answered", () => {
  const label = (verification: Record<string, unknown>) => {
    const { container } = render(<VerificationChip verification={verification as never} />);
    return container.textContent;
  };

  it("names an error answer by its status, never Unreachable", () => {
    expect(label({ status: "http-error", httpStatus: 406, detail: "the endpoint answered 406" })).toBe(
      "Answered 406 ✗",
    );
  });

  it("names a stored error answer by its status too", () => {
    expect(label({ status: "unreachable", httpStatus: 404, detail: "the endpoint answered 404" })).toBe(
      "Answered 404 ✗",
    );
  });

  it("keeps Unreachable for a link that never answered", () => {
    expect(label({ status: "unreachable", detail: "timed out" })).toBe("Unreachable ✗");
  });

  it("reads a web page as a web page, never as verified data", () => {
    expect(label({ status: "verified", httpStatus: 200, contentType: "text/html", webPage: true })).toBe(
      "Web page",
    );
  });

  it("keeps Verified for a link that answered data", () => {
    expect(label({ status: "verified", httpStatus: 200, contentType: "application/json" })).toBe("Verified ✓");
  });
});

// The card is one list since step 7.1 (board S04): it draws its rows in the
// server's order (`rowOrder`), and a card minted before that order draws the
// lane that holds the best row first, as the server ranked its lanes.
describe("the card draws first the row that can be used most directly", () => {
  const part = (laneOrder: string[], rowOrder?: [string, number][]) =>
    ({
      type: "datasetCandidates",
      laneOrder,
      ...(rowOrder ? { rowOrder } : {}),
      lanes: {
        external: [
          { name: "Portal page", sourceType: "portal", url: "https://data.example.org/portal" },
          { name: "Error answer", sourceType: "api", url: "https://data.example.org/gone" },
        ],
        catalog: [{ name: "Held", sourceType: "catalog", datasetId: "imported.held@1", installed: true }],
      },
    }) as unknown as AgentDatasetCandidatesPart;

  const rows = () => screen.getAllByRole("checkbox").map((box) => box.getAttribute("aria-label"));

  it("draws the Data Catalog's rows first when the server ranks its lane first", () => {
    render(<AgentDatasetCandidatesCard part={part(["catalog", "external"])} />);
    expect(rows()).toEqual(["Select Held", "Select Portal page", "Select Error answer"]);
  });

  it("draws the external rows first when the server ranks their lane first", () => {
    render(<AgentDatasetCandidatesCard part={part(["external", "catalog"])} />);
    expect(rows()).toEqual(["Select Portal page", "Select Error answer", "Select Held"]);
  });

  it("draws the rows in the server's order across both lanes when it gives one", () => {
    render(
      <AgentDatasetCandidatesCard
        part={part(["external", "catalog"], [["external", 0], ["catalog", 0], ["external", 1]])}
      />,
    );
    expect(rows()).toEqual(["Select Portal page", "Select Held", "Select Error answer"]);
  });

  it("draws a row the server's order leaves out after the rest, and passes over an entry that names no row", () => {
    render(
      <AgentDatasetCandidatesCard
        part={part(["external", "catalog"], [["catalog", 0], ["external", 7], ["external", 1]])}
      />,
    );
    expect(rows()).toEqual(["Select Held", "Select Error answer", "Select Portal page"]);
  });
});
