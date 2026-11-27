/**
 * What the agents' cards say, in whole words that name what they mean (step
 * 5.1 of the owner's agent chat plan):
 *
 * - a candidates card's note, once its pick is recorded, names the node, as
 *   the Source recorded turns do ("Source recorded for Load pedestrians: ...");
 * - the card's download line, the message a selection composes and the
 *   verification chip say with a colon or a full stop what a dash said;
 * - a chart's or a map's change card says its document was validated
 *   against its grammar: the sandbox does not run one, and nothing failed.
 */
import React from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";

import {
  AgentDatasetCandidatesCard,
  composeConfirmationPrompt,
} from "../../components/agents/content/AgentDatasetCandidatesCard";
import { ValidationBlock } from "../../components/agents/content/reviewCard/ValidationBlock";
import { verificationLabel } from "../../components/agents/content/verificationChip";
import type { AgentDatasetCandidatesPart } from "../../services/agents";

const NODE = "Load pedestrians";

const PART: AgentDatasetCandidatesPart = {
  type: "datasetCandidates",
  lanes: {
    external: [{ name: "NOAA Climate Data API", sourceType: "api", url: "https://api.noaa.gov" }],
    catalog: [{ name: "Cities", sourceType: "catalog", datasetId: "imported.abc@1", installed: true }],
  },
};

/** What the card's note says once the pick answered *answer*, on a card
 * named for *nodeLabel*. */
async function noteAfterThePick(answer: object, nodeLabel: string | null = NODE): Promise<string> {
  const onRecordSelection = jest.fn().mockResolvedValue({ attachmentId: "att-df", nodeId: "n1", picks: [], ...answer });
  render(<AgentDatasetCandidatesCard part={PART} nodeLabel={nodeLabel} onRecordSelection={onRecordSelection} />);
  fireEvent.click(screen.getByRole("checkbox", { name: "Select Cities" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Use this source" }));
  });
  return (await screen.findByRole("status")).textContent ?? "";
}

describe("a candidates card's note names the node its pick is recorded for", () => {
  it("names it when the source is recorded and the node is to be solved", async () => {
    expect(await noteAfterThePick({ status: "resolved" })).toBe(
      `Source recorded for ${NODE}: Solve it to build its loader from this source.`,
    );
  });

  it("names it, and the builder writing its loader", async () => {
    expect(
      await noteAfterThePick({ status: "resolved", delegated: { status: "delegating", nodeId: "n1", name: "Node Builder" } }),
    ).toBe(`Source recorded for ${NODE}: its Node Builder is writing the loader from it now.`);
  });

  it("names it, and the running Solve that builds its loader", async () => {
    expect(
      await noteAfterThePick({
        status: "resolved",
        delegated: { status: "session-running", reason: "the running Solve session picks this node up on its next pass" },
      }),
    ).toBe(`Source recorded for ${NODE}: the running Solve session builds its loader on its next pass.`);
  });

  it("names it, and says the server's reason as a sentence of its own", async () => {
    expect(
      await noteAfterThePick({
        status: "resolved",
        delegated: {
          status: "manual-download",
          reason: "this source is a portal download: follow the steps on the card and use Import dataset",
        },
      }),
    ).toBe(`Source recorded for ${NODE}. This source is a portal download: follow the steps on the card and use Import dataset.`);
  });

  it("names it when its dataset waits for its install", async () => {
    expect(await noteAfterThePick({ status: "awaiting-install" })).toBe(
      `Source recorded for ${NODE}: install the dataset from the Data Catalog, then Solve it.`,
    );
  });

  it("says no 'this node' on a card that does not know its node's name", async () => {
    expect(await noteAfterThePick({ status: "resolved" }, null)).toBe(
      "Source recorded: Solve it to build its loader from this source.",
    );
  });
});

describe("the candidates card's lines say with no dash what a dash said", () => {
  it("says why a row is a portal download after a colon", () => {
    const part: AgentDatasetCandidatesPart = {
      type: "datasetCandidates",
      lanes: {
        external: [
          {
            name: "Setores GeoSampa",
            sourceType: "portal",
            url: "https://geosampa.example.gov.br/downloads",
            access: "manual-download",
            accessWhy: 'the data URL answered with a web page titled "Downloads"',
          },
        ],
        catalog: [],
      },
    };
    render(<AgentDatasetCandidatesCard part={part} />);
    const row = screen.getByRole("group", { name: "External sources" });
    expect(within(row).getByText(/^Download it from the portal/)).toHaveTextContent(
      'Download it from the portal: the data URL answered with a web page titled "Downloads"',
    );
  });

  it("composes a selection's message as two sentences", () => {
    const [noaa] = PART.lanes.external;
    const [cities] = PART.lanes.catalog;
    expect(composeConfirmationPrompt([cities], [noaa], "finder", "Node Builder")).toBe(
      "Confirm my selection. Install from the Data Catalog: Cities (imported.abc@1); " +
        "hand off to Node Builder: NOAA Climate Data API.",
    );
    expect(composeConfirmationPrompt([cities], [noaa], "builder")).toBe(
      "Build the data-loading node. Load from the Data Catalog: Cities (imported.abc@1); " +
        "fetch from: NOAA Climate Data API (https://api.noaa.gov).",
    );
  });

  it("says an unchecked source was never checked after a colon", () => {
    expect(verificationLabel("unverified")).toBe("Unverified: never checked");
    expect(verificationLabel(undefined)).toBe("Unverified: never checked");
  });
});

describe("a chart's change card says its document was validated against its grammar", () => {
  // Read from a variable: the evidence a chart's validation carries.
  const evidence = { kind: "not-executable", documentValidated: "vis-vega" };
  // A round as the loop records it: the runner's reason, cut at 120
  // characters, and the document the round checked.
  const reason =
    "node 'map' (curio.builtin/vis-vega) has no code the sandbox could run, as it works in the browser or through its own s";
  const document = '{"mark": "bar", "encoding": {"x": {"field": "a"}}}';
  const attempts = [{ round: 1, verdict: "not-executable", kind: "not-executable", detail: reason, code: document }];

  it("as a passed check, never a failure", () => {
    render(<ValidationBlock validation={{ verdict: "not-executable", rounds: 1, evidence, attempts }} />);
    const block = screen.getByRole("status", { name: "Validated against its grammar" });
    expect(block).toHaveTextContent(/^VALID/);
    expect(block).toHaveTextContent("Validated against its grammar, not executed");
    expect(block).toHaveTextContent("Round 1 · validated against its grammar, not executed");
    expect(block).not.toHaveTextContent(/FAIL|failed|not executable|no code the sandbox could run|this attempt ran/);
    // The document the round validated stays in the chat, under words of a check that passed.
    const shown = within(block).getByText("The document this round validated").closest("details");
    expect(shown).not.toBeNull();
    expect(shown).toHaveTextContent(document);
  });

  it("while a corrected chart's failed round keeps its error and the document it checked", () => {
    const refused = "the document's encoding.x needs a type";
    const corrected = [
      { round: 1, verdict: "fail", kind: "document-invalid", detail: refused, code: '{"mark": "bar"}' },
      ...attempts.map((attempt) => ({ ...attempt, round: 2 })),
    ];
    render(<ValidationBlock validation={{ verdict: "not-executable", rounds: 2, evidence, attempts: corrected }} />);
    const block = screen.getByRole("status", { name: "Validated against its grammar" });
    expect(block).toHaveTextContent(refused);
    expect(block).toHaveTextContent("The code this attempt ran");
    expect(block).not.toHaveTextContent(/no code the sandbox could run/);
    expect(block).toHaveTextContent("Round 2 · validated against its grammar, not executed");
  });

  it("while a node with no document to check still says it ran nothing", () => {
    render(
      <ValidationBlock
        validation={{ verdict: "not-executable", rounds: 1, evidence: { kind: "not-executable" }, attempts }}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Round 1 · not executable: no code to run, nothing ran");
  });
});
