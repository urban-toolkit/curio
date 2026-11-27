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

describe("the card draws first the lane that holds the best row", () => {
  const part = (laneOrder: string[]) =>
    ({
      type: "datasetCandidates",
      laneOrder,
      lanes: {
        external: [{ name: "Portal page", sourceType: "portal", url: "https://data.example.org/portal" }],
        catalog: [{ name: "Held", sourceType: "catalog", datasetId: "imported.held@1", installed: true }],
      },
    }) as unknown as AgentDatasetCandidatesPart;

  const LANES = ["External sources", "From your Data Catalog"];
  const lanes = () =>
    screen
      .getAllByRole("group")
      .map((group) => group.getAttribute("aria-label"))
      .filter((name) => LANES.includes(name ?? ""));

  it("draws the Data Catalog first when the server ranks it first", () => {
    render(<AgentDatasetCandidatesCard part={part(["catalog", "external"])} />);
    expect(lanes()).toEqual(["From your Data Catalog", "External sources"]);
  });

  it("draws the external lane first when the server ranks it first", () => {
    render(<AgentDatasetCandidatesCard part={part(["external", "catalog"])} />);
    expect(lanes()).toEqual(["External sources", "From your Data Catalog"]);
  });
});
