import React from "react";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

/**
 * A loader's Dataset Finder's chat as the signed-off board S08 draws it (step
 * 7.1 of the owner's agent chat plan, part 2): the Finder's reply in its own
 * words, without the candidates it printed, which its card shows; a reply
 * that was only those candidates takes no place; and its card names no other
 * chat. The agents read the reply whole.
 */

jest.mock("../../providers/FlowProvider", () => ({
  useFlowContext: () => ({ playAllNodes: jest.fn(), projectDirty: false }),
}));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { catalog: jest.fn(), listInstalled: jest.fn(), resolve: jest.fn() },
}));

import { AgentChatPanel } from "../../components/agents/attach/AgentChatPanel";
import type { AgentAttachment, AgentSessionTurn } from "../../services/agents";

const FINDER = {
  attachmentId: "att-df",
  coord: "agent.curio.dataset-finder@1",
  target: { kind: "node", targetId: "n1" },
  sessionId: "s2",
  revision: 1,
  name: "Dataset Finder",
  category: "data",
  hooks: [],
  intent: null,
  intentEdited: false,
  title: null,
  titleEdited: false,
  capabilities: ["dataset.discover", "dataset.select"],
  waitsForYou: ["n1"],
  sourceRecord: { status: "candidates-pending", candidates: 1, askedBy: "dfb", askers: ["dfb"] },
  solvesNodes: false,
} as unknown as AgentAttachment;

const LANES = {
  external: [{ name: "Chicago areas", sourceType: "portal", url: "https://data.example.org/areas.geojson" }],
  catalog: [],
};
/** The candidates as the Finder printed them. */
const BLOCK = JSON.stringify({ datasetCandidates: { lanes: LANES } }, null, 2);
const PROSE =
  "The project's Data Catalog holds no Chicago community area dataset, so the external lane offers the boundaries.";

/** The task another agent asked of the Finder, drawn as one quiet line. */
const ASKED = {
  role: "user",
  text: "[Delegated by Dataflow Builder] dataset.discover: find candidates for the node",
  asked: { by: "Dataflow Builder", task: "find a source for Load boundaries" },
} as unknown as AgentSessionTurn;
/** The Finder's reply, with the card of its run's trace. */
const reply = (text: string) =>
  ({
    role: "agent",
    text,
    content: [{ type: "card", kind: "result", title: "Delegated task · ok", lines: ["dataset.discover · ok"], runDetails: true }],
  }) as unknown as AgentSessionTurn;
/** The card of those candidates. */
const FOUND = {
  role: "agent",
  text: "I found 1 candidate for Load boundaries. Pick one with Use this source.",
  content: [{ type: "datasetCandidates", lanes: LANES }],
} as unknown as AgentSessionTurn;

function renderFinder(turns: AgentSessionTurn[], overrides: Partial<React.ComponentProps<typeof AgentChatPanel>> = {}) {
  return render(
    <AgentChatPanel
      attachment={FINDER}
      turns={turns}
      onSend={jest.fn().mockResolvedValue(undefined)}
      onClose={jest.fn()}
      targetName="Load boundaries"
      {...overrides}
    />,
    { wrapper: MemoryRouter },
  );
}

/** The agent turns the chat draws. */
const agentRows = () => document.querySelectorAll(".agentRow");

describe("the Finder's reply is drawn without the candidates its card shows", () => {
  it("draws its words, not the candidates it printed in a fence", () => {
    renderFinder([ASKED, reply(`${PROSE}\n\n\`\`\`curio.v1\n${BLOCK}\n\`\`\``), FOUND]);
    expect(screen.getByText(PROSE)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("datasetCandidates");
    expect(screen.getByRole("group", { name: "Sources for Load boundaries" })).toBeInTheDocument();
  });

  it("draws its words, not the candidates the chat cut short", () => {
    // The chat keeps a delegated reply's first 2,000 characters.
    const cut = `${PROSE}\n\n\`\`\`curio.v1\n${BLOCK.slice(0, 40)}`;
    renderFinder([ASKED, reply(cut), FOUND]);
    expect(screen.getByText(PROSE)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("datasetCandidates");
  });

  it("draws no turn for a reply that was only its candidates", () => {
    renderFinder([ASKED, reply(BLOCK), FOUND]);
    expect(document.body.textContent).not.toContain("datasetCandidates");
    // The card's turn alone.
    expect(agentRows()).toHaveLength(1);
    expect(screen.getByText("Asked by the Dataflow Builder: find a source for Load boundaries.")).toBeInTheDocument();
  });

  it("draws any other JSON as it is", () => {
    const other = '```json\n{"columns": ["area", "geometry"]}\n```';
    renderFinder([reply(`${PROSE}\n\n${other}`)]);
    expect(document.body.textContent).toContain('"columns"');
  });
});

describe("the Finder's own card names no other chat", () => {
  it("offers Use this source, and says nothing of the chat that asked", () => {
    renderFinder([FOUND], {
      onRecordDatasetSelection: jest.fn(),
      agentNameOf: (id: string) => (id === "dfb" ? "Dataflow Builder" : null),
    });
    const own = screen.getByRole("group", { name: "Sources for Load boundaries" });
    expect(within(own).getByRole("button", { name: "Use this source" })).toBeInTheDocument();
    expect(own).not.toHaveTextContent("The same card is in");
    expect(own).not.toHaveTextContent("Dataflow Builder");
  });
});
