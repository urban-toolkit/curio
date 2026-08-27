import type { AgentCard } from "../../api/agentsApi";
import {
  installLabel,
  installTitle,
  matchesAgentSearch,
  missingRequiredAgents,
  sortAgentCards,
} from "../../components/agents/catalog/agentListUtils";

function card(over: Partial<AgentCard> = {}): AgentCard {
  return {
    id: "agent.node-explainer",
    version: "1.0.0",
    dirName: "agent.node-explainer@1.0.0",
    name: "Node Explainer",
    category: "node",
    purpose: "explains what a node / flow does",
    capabilities: ["node.explain"],
    hooks: ["node"],
    provenance: { publisher: "curio", trust: "built-in" },
    imported: false,
    installedInProject: false,
    published: false,
    publishable: false,
    requiresAgents: [],
    scope: "browse",
    ...over,
  };
}

describe("matchesAgentSearch", () => {
  it("passes every card for an empty or whitespace-only query", () => {
    expect(matchesAgentSearch(card(), "")).toBe(true);
    expect(matchesAgentSearch(card(), "   ")).toBe(true);
  });

  it("matches each promised field, case-insensitively", () => {
    expect(matchesAgentSearch(card(), "EXPLAINER")).toBe(true); // name
    expect(matchesAgentSearch(card(), "agent.node-")).toBe(true); // id
    expect(matchesAgentSearch(card(), "flow does")).toBe(true); // purpose
    expect(matchesAgentSearch(card({ category: "evaluate" }), "Evaluate")).toBe(true); // category
    expect(matchesAgentSearch(card(), "node.explain")).toBe(true); // capability
    expect(matchesAgentSearch(card({ hooks: ["canvas"] }), "canvas")).toBe(true); // hook
    expect(matchesAgentSearch(card(), "curio")).toBe(true); // publisher
  });

  it("rejects a card matching no field", () => {
    expect(matchesAgentSearch(card(), "dataset finder")).toBe(false);
  });

  it("trims the query before matching", () => {
    expect(matchesAgentSearch(card(), "  explainer  ")).toBe(true);
  });
});

describe("sortAgentCards", () => {
  const b = card({ name: "beta", dirName: "agent.beta@1.0.0" });
  const a = card({ name: "Alpha", dirName: "agent.alpha@1.0.0" });
  const c = card({ name: "charlie", dirName: "agent.charlie@1.0.0" });

  it('"name" sorts alphabetically, case-insensitively', () => {
    expect(sortAgentCards([b, c, a], "name").map((x) => x.name)).toEqual([
      "Alpha",
      "beta",
      "charlie",
    ]);
  });

  it('"new" preserves the server roster order (AgentCard has no timestamp)', () => {
    expect(sortAgentCards([b, c, a], "new").map((x) => x.name)).toEqual([
      "beta",
      "charlie",
      "Alpha",
    ]);
  });

  it("returns a copy, never mutating the input", () => {
    const input = [b, c, a];
    const out = sortAgentCards(input, "name");
    expect(out).not.toBe(input);
    expect(input.map((x) => x.name)).toEqual(["beta", "charlie", "Alpha"]);
  });
});

describe("requiresAgents helpers (dev/106)", () => {
  const ncb = { id: "agent.node-content-builder", name: "Node Content Builder", coord: "agent.node-content-builder@1.0.0", visible: true, installedInProject: false };

  it("a leaf card installs plainly", () => {
    expect(missingRequiredAgents(card())).toEqual([]);
    expect(installLabel(card())).toBe("Add to dataflow");
    expect(installTitle(card())).toBeUndefined();
  });

  it("tolerates a payload without the field", () => {
    const legacy = card();
    delete (legacy as Partial<AgentCard>).requiresAgents;
    expect(installLabel(legacy)).toBe("Add to dataflow");
  });

  it("names what the click adds when a dependency is missing", () => {
    const c = card({ requiresAgents: [ncb] });
    expect(installLabel(c)).toBe("Add to dataflow (+1 required)");
    expect(installTitle(c)).toBe("Also adds Node Content Builder (required)");
  });

  it("a satisfied dependency counts as a plain Add to dataflow", () => {
    const c = card({ requiresAgents: [{ ...ncb, installedInProject: true }] });
    expect(installLabel(c)).toBe("Add to dataflow");
  });

  it("an unresolvable dependency is called out (the server will refuse)", () => {
    const c = card({ requiresAgents: [{ ...ncb, id: "agent.ghost", name: "agent.ghost", coord: null, visible: false }] });
    expect(installLabel(c)).toBe("Add to dataflow (+1 required)");
    expect(installTitle(c)).toContain("Cannot add: requires agent.ghost");
  });
});
