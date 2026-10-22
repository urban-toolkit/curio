import {
  installLabel,
  installTitle,
  matchesAgentSearch,
  missingRequiredAgents,
  sortAgentCards,
  type AgentCard,
} from "../../services/agents";

function card(over: Partial<AgentCard> = {}): AgentCard {
  return {
    id: "agent.test.my-explainer",
    version: "1.0.0",
    dirName: "agent.test.my-explainer@1",
    name: "My Explainer",
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
    expect(matchesAgentSearch(card(), "agent.my-")).toBe(true); // id
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
  const b = card({ name: "beta", dirName: "agent.test.beta@1" });
  const a = card({ name: "Alpha", dirName: "agent.test.alpha@1" });
  const c = card({ name: "charlie", dirName: "agent.test.charlie@1" });

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
  const nodeBuilder = { id: "agent.curio.node-builder", name: "Node Builder", coord: "agent.curio.node-builder@1", visible: true, installedInProject: false };

  it("a leaf card installs plainly", () => {
    expect(missingRequiredAgents(card())).toEqual([]);
    expect(installLabel(card())).toBe("Add to project");
    expect(installTitle(card())).toBeUndefined();
  });

  it("tolerates a payload without the field", () => {
    const legacy = card();
    delete (legacy as Partial<AgentCard>).requiresAgents;
    expect(installLabel(legacy)).toBe("Add to project");
  });

  it("names what the click adds when a dependency is missing", () => {
    const c = card({ requiresAgents: [nodeBuilder] });
    expect(installLabel(c)).toBe("Add to project (+1 required)");
    expect(installTitle(c)).toBe("Also adds Node Builder (required)");
  });

  it("a satisfied dependency counts as a plain Add to project", () => {
    const c = card({ requiresAgents: [{ ...nodeBuilder, installedInProject: true }] });
    expect(installLabel(c)).toBe("Add to project");
  });

  it("an unresolvable dependency is called out (the server will refuse)", () => {
    const c = card({ requiresAgents: [{ ...nodeBuilder, id: "agent.test.ghost", name: "agent.test.ghost", coord: null, visible: false }] });
    expect(installLabel(c)).toBe("Add to project (+1 required)");
    expect(installTitle(c)).toContain("Cannot add: requires agent.test.ghost");
  });
});
