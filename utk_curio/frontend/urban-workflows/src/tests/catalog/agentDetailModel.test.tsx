import React from "react";
import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";

/**
 * An agent's details name the configuration it runs on, read-only: the choice
 * is made in API Settings, which the link opens on that agent's row.
 *
 * They also say what the agent does in the docs' three words
 * (docs/AGENT-CATALOG.md, "The agents"): what you ask it in chat, the tools it
 * uses there, and its modes with who asks for each. Each prompt says when it
 * runs.
 */

let mockBundle: { manifest: Record<string, unknown>; prompts: Record<string, string> } = {
  manifest: {},
  prompts: {},
};
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: { readDefinition: jest.fn(() => Promise.resolve(mockBundle)) },
}));

let mockListing: Record<string, unknown> = {};
jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: { listing: jest.fn(() => Promise.resolve(mockListing)) },
}));

// The Skills section reads the agent's skills; agentSkillsSection.test.tsx
// covers it, so here it stays loading.
jest.mock("../../services/agents/skillsApi", () => ({
  skillsApi: { agentSkills: jest.fn(() => new Promise(() => {})) },
}));

import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";
import {
  API_SETTINGS_EVENT,
  type ApiSettingsFocus,
} from "../../components/apiSettings/apiSettingsRequest";

const AGENT = {
  id: "agent.curio.node-builder", version: "1.0.0", dirName: "agent.curio.node-builder@1",
  name: "Node Builder", category: "node", purpose: "Writes node content.",
  capabilities: ["node.content.generate"], hooks: ["node"],
  provenance: { publisher: "curio", trust: "built-in" }, imported: false,
  installedInProject: false, published: false, publishable: false, scope: "browse",
  requiresAgents: [], inCatalog: true,
} as never;

const listingWith = (editable: boolean) => ({
  editable,
  active: { source: "default", label: "Work", model: "gpt-4o-mini" },
  agents: [{
    id: "agent.curio.node-builder", name: "Node Builder", category: "node",
    choice: "llm-00000000000b",
    answers: { source: "assigned", label: "Local", model: "llama3" },
  }],
});

it("names what the agent runs on and opens API Settings on its row", async () => {
  mockListing = listingWith(true);
  const onClose = jest.fn();
  const asked: ApiSettingsFocus[] = [];
  const listener = (event: Event) => asked.push((event as CustomEvent<ApiSettingsFocus>).detail);
  window.addEventListener(API_SETTINGS_EVENT, listener);
  render(<AgentDetailModal agent={AGENT} onClose={onClose} />);
  expect(await screen.findByText("Local · llama3")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Change in API Settings" }));
  await waitFor(() => expect(asked).toEqual([{ section: "agent-models", agentId: "agent.curio.node-builder" }]));
  expect(onClose).toHaveBeenCalled();
  window.removeEventListener(API_SETTINGS_EVENT, listener);
});

it("offers no change when this account cannot choose one", async () => {
  mockListing = listingWith(false);
  render(<AgentDetailModal agent={AGENT} onClose={jest.fn()} />);
  expect(await screen.findByText("Local · llama3")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Change in API Settings" })).toBeNull();
});

/** The Node Builder as the catalog lists it, cut down: its chat, three of its
 *  tools and two of its modes, in the words the server sends. */
const NODE_BUILDER = {
  ...(AGENT as object),
  purpose: "Create a node, or rewrite a node's content, as a proposal you review.",
  capabilities: [
    "node.build", "node.content.generate", "package.build", "package.extend", "node.kind.author",
  ],
  tools: [
    { id: "dataflow.read", label: "Read the dataflow" },
    { id: "node.runtime.read", label: "Read a node's last run" },
    { id: "node.create", label: "Propose a node" },
  ],
  modes: [
    {
      label: "Write a node's content",
      capabilities: ["node.content.generate"],
      prompt: "prompts/new_content_prompt.md",
      askedBy: ["Node Builder", "Dataflow Builder", "Solve"],
    },
    {
      label: "Write a package",
      capabilities: ["package.build", "package.extend", "node.kind.author"],
      prompt: "prompts/package_build_instruction.md",
      askedBy: ["Node Builder", "Researcher", "Dataflow Builder"],
    },
  ],
  promptRuns: [
    { path: "prompts/default_preamble.md", runs: ["every call"] },
    { path: "prompts/node_build_instruction.md", runs: ["a message you type"] },
    { path: "prompts/new_content_prompt.md", runs: ["Write a node's content"] },
    { path: "prompts/package_build_instruction.md", runs: ["Write a package"] },
  ],
} as never;

/** The section a level-3 heading titles. */
const section = (title: string) =>
  within(
    screen.getByRole("heading", { name: title, level: 3 }).closest("section") as HTMLElement,
  );

describe("the details say what the agent does in the docs' three words", () => {
  beforeEach(() => {
    mockListing = listingWith(true);
    mockBundle = { manifest: {}, prompts: {} };
  });

  it("opens with In chat, Tools and Modes (who asks), and no flat capability list", async () => {
    render(<AgentDetailModal agent={NODE_BUILDER} onClose={jest.fn()} />);
    await screen.findByText("Local · llama3");
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(titles.slice(0, 3)).toEqual(["In chat", "Tools", "Modes (who asks)"]);
    expect(titles).not.toContain("Capabilities");
    expect(
      section("In chat").getByText(
        "Create a node, or rewrite a node's content, as a proposal you review.",
      ),
    ).toBeInTheDocument();
  });

  it("names each tool in plain words", async () => {
    render(<AgentDetailModal agent={NODE_BUILDER} onClose={jest.fn()} />);
    await screen.findByText("Local · llama3");
    expect(section("Tools").getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Read the dataflow",
      "Read a node's last run",
      "Propose a node",
    ]);
  });

  it("says who asks for each mode, with the mode's capability ids beneath it", async () => {
    render(<AgentDetailModal agent={NODE_BUILDER} onClose={jest.fn()} />);
    await screen.findByText("Local · llama3");
    const modes = section("Modes (who asks)");
    const items = modes.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(
      within(items[0]).getByText(
        "Write a node's content: asked by Node Builder, Dataflow Builder, Solve",
      ),
    ).toBeInTheDocument();
    expect(within(items[0]).getByText("node.content.generate")).toBeInTheDocument();
    expect(
      within(items[1]).getByText(
        "Write a package: asked by Node Builder, Researcher, Dataflow Builder",
      ),
    ).toBeInTheDocument();
    expect(
      within(items[1]).getByText("package.build, package.extend, node.kind.author"),
    ).toBeInTheDocument();
    // A capability that is no mode is not listed anywhere: the ids stay only
    // under the mode they belong to.
    expect(screen.queryByText("node.build")).toBeNull();
  });

  it("says so when an agent has no tools or no modes, and when no agent asks for a mode", async () => {
    const quiet = {
      ...(NODE_BUILDER as object),
      tools: [],
      modes: [
        {
          label: "Extract the keywords of a description",
          capabilities: ["workflow.keywords.extract"],
          prompt: "prompts/syntax_analysis_prompt.md",
          askedBy: [],
        },
      ],
    } as never;
    const { unmount } = render(<AgentDetailModal agent={quiet} onClose={jest.fn()} />);
    await screen.findByText("Local · llama3");
    expect(section("Tools").getByText("None")).toBeInTheDocument();
    expect(
      section("Modes (who asks)").getByText(
        "Extract the keywords of a description: no agent asks for this",
      ),
    ).toBeInTheDocument();
    unmount();

    render(
      <AgentDetailModal
        agent={{ ...(NODE_BUILDER as object), modes: [] } as never}
        onClose={jest.fn()}
      />,
    );
    await screen.findByText("Local · llama3");
    expect(section("Modes (who asks)").getByText("None")).toBeInTheDocument();
  });

  it("labels each prompt by when it runs, in that order", async () => {
    // Flask sends the bundle's prompts sorted by path; the window follows the
    // card's order: every call, a message you type, then each mode.
    mockBundle = {
      manifest: {},
      prompts: {
        "prompts/default_preamble.md": "You are part of Curio.",
        "prompts/new_content_prompt.md": "Write the content.",
        "prompts/node_build_instruction.md": "Build a node.",
        "prompts/package_build_instruction.md": "Write the package.",
      },
    };
    render(<AgentDetailModal agent={NODE_BUILDER} onClose={jest.fn()} />);
    // The window is a portal into the document body, not the render
    // container: read the Prompts section where the user sees it.
    const heading = await screen.findByRole("heading", { name: "Prompts (4)", level: 3 });
    const prompts = heading.closest("section") as HTMLElement;
    expect(Array.from(prompts.querySelectorAll("summary")).map((s) => s.textContent)).toEqual([
      "every call · prompts/default_preamble.md",
      "a message you type · prompts/node_build_instruction.md",
      "Write a node's content · prompts/new_content_prompt.md",
      "Write a package · prompts/package_build_instruction.md",
    ]);
  });
});
