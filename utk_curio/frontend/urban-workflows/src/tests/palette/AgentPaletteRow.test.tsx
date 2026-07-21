import React from "react";
import { render, screen } from "@testing-library/react";
import { AgentPaletteRow } from "../../components/menus/nodes/agentsPalette/AgentPaletteRow";

function card(over: Partial<any> = {}): any {
  return {
    id: "agent.chat-agent",
    version: "1.0.0",
    dirName: "agent.chat-agent@1.0.0",
    name: "Chat",
    category: "node",
    purpose: "assistant for a node or the canvas",
    capabilities: ["conversation.respond"],
    hooks: ["node", "canvas"],
    provenance: { publisher: "curio", trust: "built-in" },
    imported: false,
    installedInProject: true,
    published: false,
    publishable: false,
    scope: "installed",
    ...over,
  };
}

describe("AgentPaletteRow compatible-target pills", () => {
  it("shows both Canvas and Node pills for a dual-compatible agent", () => {
    render(<AgentPaletteRow agent={card()} />);
    expect(screen.getByText("Node")).toBeInTheDocument();
    expect(screen.getByText("Canvas")).toBeInTheDocument();
  });

  it("shows a single pill for a single-target agent", () => {
    render(<AgentPaletteRow agent={card({ name: "Explainer", hooks: ["node"] })} />);
    expect(screen.getByText("Node")).toBeInTheDocument();
    expect(screen.queryByText("Canvas")).not.toBeInTheDocument();
  });

  it("shows a Canvas-only pill for a canvas agent", () => {
    render(<AgentPaletteRow agent={card({ name: "Planner", category: "canvas", hooks: ["canvas"] })} />);
    expect(screen.getByText("Canvas")).toBeInTheDocument();
    expect(screen.queryByText("Node")).not.toBeInTheDocument();
  });
});
