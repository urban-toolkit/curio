import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

/**
 * An agent's details list its skills beside In chat, Tools and Modes.
 *
 * The rows are this account's: the core skills its preamble holds, then its
 * own, then those its chat or a mode of it always holds. Add skill picks one
 * of the skills it does not hold, Remove drops one, and Restore brings back
 * the list it ships with, each through the agent's skills routes. The core
 * skills and those its instruction or a mode names as its own show no Remove,
 * and an account that may change nothing (a hosted guest) sees the list
 * alone. A skill's name opens its details, the Skill Catalog's, over the
 * agent's, and Escape closes the skill's alone.
 */

jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: { readDefinition: jest.fn(() => Promise.resolve({ manifest: {}, prompts: {} })) },
}));

jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: { listing: jest.fn(() => new Promise(() => {})) },
}));

const mockAgentSkills = jest.fn();
const mockAddSkill = jest.fn();
const mockRemoveSkill = jest.fn();
const mockRestoreSkills = jest.fn();
const mockCard = jest.fn();
const mockRead = jest.fn((name: string) => Promise.resolve({ name, text: `## ${name}`, files: [] }));
jest.mock("../../services/agents/skillsApi", () => ({
  skillsApi: {
    agentSkills: (coord: string) => mockAgentSkills(coord),
    addSkill: (coord: string, name: string) => mockAddSkill(coord, name),
    removeSkill: (coord: string, name: string) => mockRemoveSkill(coord, name),
    restoreSkills: (coord: string) => mockRestoreSkills(coord),
    card: (name: string) => mockCard(name),
    read: (name: string) => mockRead(name),
  },
}));

import { AgentDetailModal } from "../../components/agents/catalog/AgentDetailModal";

const COORD = "agent.curio.dataset-finder@1";
const AGENT = {
  id: "agent.curio.dataset-finder", version: "1.0.0", dirName: COORD,
  name: "Dataset Finder", category: "data", purpose: "Find datasets in catalogs and portals.",
  capabilities: ["dataset.discover"], hooks: ["canvas"],
  provenance: { publisher: "curio", trust: "built-in" }, imported: false,
  installedInProject: false, published: false, publishable: false, scope: "browse",
  requiresAgents: [], inCatalog: true, tools: [], modes: [],
} as never;

const row = (name: string, extra: Record<string, unknown> = {}) => ({
  name, description: `When to use ${name}.`, core: false, added: false, chat: false, modes: [], asked: false,
  removable: true, ...extra,
});

/** The Dataset Finder's skills as the server lists them, before any change. */
const SHIPPED = {
  coord: COORD,
  agentId: "agent.curio.dataset-finder",
  skills: [
    row("compatibility", { core: true, removable: false }),
    row("node-control", { core: true, removable: false }),
    row("nodes", { core: true, removable: false }),
    row("catalogs", { modes: ["Find datasets"], removable: false }),
  ],
  addable: [
    { name: "widgets", description: "Use this skill when a node declares a widget." },
    { name: "provenance", description: "Use this skill to read a node's history." },
  ],
  changed: false,
  editable: true,
  reason: null,
};

/** After Add skill picked widgets. */
const WITH_WIDGETS = {
  ...SHIPPED,
  skills: [...SHIPPED.skills, row("widgets", { added: true })],
  addable: [SHIPPED.addable[1]],
  changed: true,
};

/** widgets as the Skill Catalog's listing sends its card. */
const WIDGETS_CARD = {
  name: "widgets", description: "Use this skill when a node declares a widget.", license: "MIT",
  compatibility: null, author: "curio", version: "1.0.0", files: [], behaviors: ["code"], features: [],
  nodeKinds: ["Python Computation"], core: false, source: "curio",
  agents: [{ id: "agent.curio.dataset-finder", name: "Dataset Finder", coord: COORD, card: true, added: true,
             always: false }],
};

const skillsSection = () =>
  within(screen.getByRole("heading", { name: "Skills", level: 3 }).closest("section") as HTMLElement);

/** The agent's details, open on *skills*; answers what closes them. */
async function openDetails(skills: unknown) {
  mockAgentSkills.mockResolvedValue(skills);
  const onClose = jest.fn();
  render(<AgentDetailModal agent={AGENT} onClose={onClose} />);
  await waitFor(() => expect(document.querySelectorAll("[data-curio-skill-row]").length).toBeGreaterThan(0));
  return onClose;
}

beforeEach(() => {
  mockAgentSkills.mockReset();
  mockAddSkill.mockReset();
  mockRemoveSkill.mockReset();
  mockRestoreSkills.mockReset();
  mockCard.mockReset();
  mockRead.mockClear();
});

it("lists Skills after In chat, Tools and Modes, read for this agent", async () => {
  await openDetails(SHIPPED);
  const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
  expect(titles.slice(0, 4)).toEqual(["In chat", "Tools", "Modes (who asks)", "Skills"]);
  expect(mockAgentSkills).toHaveBeenCalledWith(COORD);
  expect(
    Array.from(document.querySelectorAll("[data-curio-skill-row]")).map((li) => li.getAttribute("data-curio-skill-row")),
  ).toEqual(["compatibility", "node-control", "nodes", "catalogs"]);
});

it("offers no Remove for the core skills or a mode's own, and says why", async () => {
  await openDetails(SHIPPED);
  const section = skillsSection();
  expect(section.queryByRole("button", { name: /^Remove / })).toBeNull();
  expect(section.getAllByText("Every call")).toHaveLength(3);
  expect(section.getByText("Always for Find datasets")).toBeInTheDocument();
  // Nothing changed yet, so there is nothing to restore.
  expect(section.queryByRole("button", { name: "Restore" })).toBeNull();
});

it("offers no Remove for what its chat or a call of it always holds, and says which", async () => {
  await openDetails({
    ...SHIPPED,
    skills: [
      ...SHIPPED.skills,
      row("reuse-first", { chat: true, modes: ["Recommend packages", "Write a package"], removable: false }),
      row("research-notes", { chat: true, removable: false }),
      row("widgets", { asked: true, removable: false }),
      row("data-sources", { chat: true, asked: true, removable: false }),
      row("provenance"),
    ],
  });
  const section = skillsSection();
  expect(section.getByText("Always in chat and for Recommend packages, Write a package")).toBeInTheDocument();
  expect(section.getByText("Always in chat")).toBeInTheDocument();
  // A call another agent asks for is none of its modes, so it is never named by an id.
  expect(section.getByText("Always when another agent asks")).toBeInTheDocument();
  expect(section.getByText("Always in chat and when another agent asks")).toBeInTheDocument();
  expect(section.getAllByRole("button", { name: /^Remove / }).map((b) => b.getAttribute("aria-label"))).toEqual([
    "Remove provenance from Dataset Finder",
  ]);
});

it("adds a skill picked from the ones it does not hold", async () => {
  await openDetails(SHIPPED);
  mockAddSkill.mockResolvedValue(WITH_WIDGETS);
  const section = skillsSection();
  fireEvent.click(section.getByRole("button", { name: "Add skill" }));
  const picker = section.getByRole("list", { name: "Skills to add to Dataset Finder" });
  expect(within(picker).getAllByRole("button").map((b) => b.querySelector("span")?.textContent)).toEqual([
    "widgets", "provenance",
  ]);
  fireEvent.click(within(picker).getByRole("button", { name: /^widgets/ }));
  await waitFor(() => expect(mockAddSkill).toHaveBeenCalledWith(COORD, "widgets"));
  await waitFor(() => expect(document.querySelector('[data-curio-skill-row="widgets"]')).not.toBeNull());
  expect(section.getByText("Added by you")).toBeInTheDocument();
  // The picker closes once the skill is added.
  expect(section.queryByRole("list", { name: "Skills to add to Dataset Finder" })).toBeNull();
});

it("removes a skill it holds", async () => {
  await openDetails(WITH_WIDGETS);
  const section = skillsSection();
  // Only the row this account may change offers Remove.
  expect(section.getAllByRole("button", { name: /^Remove / })).toHaveLength(1);
  mockRemoveSkill.mockResolvedValue(SHIPPED);
  fireEvent.click(section.getByRole("button", { name: "Remove widgets from Dataset Finder" }));
  await waitFor(() => expect(mockRemoveSkill).toHaveBeenCalledWith(COORD, "widgets"));
  await waitFor(() => expect(document.querySelector('[data-curio-skill-row="widgets"]')).toBeNull());
});

it("restores the list Curio gives an agent it ships", async () => {
  await openDetails(WITH_WIDGETS);
  mockRestoreSkills.mockResolvedValue(SHIPPED);
  const restore = skillsSection().getByRole("button", { name: "Restore" });
  expect(restore).toHaveAttribute("data-tooltip", "Back to the skills Curio gives this agent");
  fireEvent.click(restore);
  await waitFor(() => expect(mockRestoreSkills).toHaveBeenCalledWith(COORD));
  await waitFor(() => expect(document.querySelector('[data-curio-skill-row="widgets"]')).toBeNull());
  expect(skillsSection().queryByRole("button", { name: "Restore" })).toBeNull();
});

it("shows a refused change beside the list, which stays", async () => {
  await openDetails(WITH_WIDGETS);
  mockRemoveSkill.mockRejectedValue(new Error("widgets is always held by Find datasets"));
  fireEvent.click(skillsSection().getByRole("button", { name: "Remove widgets from Dataset Finder" }));
  expect(await skillsSection().findByRole("alert")).toHaveTextContent("widgets is always held by Find datasets");
  expect(document.querySelector('[data-curio-skill-row="widgets"]')).not.toBeNull();
});

it("shows the list alone to an account that may change nothing", async () => {
  await openDetails({
    ...WITH_WIDGETS,
    skills: WITH_WIDGETS.skills.map((skill) => ({ ...skill, removable: false })),
    addable: [],
    editable: false,
    reason: "Changing an agent's skills is not available for guest users.",
  });
  const section = skillsSection();
  // Its only buttons are the skills' names, which open their details: reading
  // them changes nothing, and no button changes the list.
  expect(section.getAllByRole("button").map((button) => button.textContent)).toEqual(
    WITH_WIDGETS.skills.map((skill) => skill.name),
  );
  expect(document.querySelector('[data-curio-skill-row="widgets"]')).not.toBeNull();
});

it("opens a skill's details over the agent's from its name, and Escape closes the skill's alone", async () => {
  const onClose = await openDetails(WITH_WIDGETS);
  mockCard.mockResolvedValue(WIDGETS_CARD);
  const name = skillsSection().getByRole("button", { name: "widgets" });
  // The name keeps the skill's description as its hover text.
  expect(name).toHaveAttribute("data-tooltip", "When to use widgets.");
  fireEvent.click(name);
  await waitFor(() => expect(mockCard).toHaveBeenCalledWith("widgets"));
  const skill = await screen.findByRole("dialog", { name: "Skill details" });
  expect(within(skill).getByRole("heading", { name: "widgets", level: 2 })).toBeInTheDocument();
  expect(within(skill).getByText("Dataset Finder (added by you)")).toBeInTheDocument();
  await waitFor(() => expect(mockRead).toHaveBeenCalledWith("widgets"));
  // Stacked: the agent's details stay open beneath, the skill's on top.
  const shells = document.querySelectorAll('[data-curio-modal-shell="true"]');
  expect(shells).toHaveLength(2);
  expect(shells[shells.length - 1]).toBe(skill);
  expect(screen.getByRole("dialog", { name: "Agent details" })).toBeInTheDocument();

  fireEvent.keyDown(window, { key: "Escape" });
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Skill details" })).toBeNull());
  expect(screen.getByRole("dialog", { name: "Agent details" })).toBeInTheDocument();
  expect(onClose).not.toHaveBeenCalled();
  // The next Escape is the agent's.
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);
});

it("says so beside the list when a skill's details cannot be read, and opens no window", async () => {
  await openDetails(WITH_WIDGETS);
  mockCard.mockResolvedValue(null);
  fireEvent.click(skillsSection().getByRole("button", { name: "widgets" }));
  expect(await skillsSection().findByRole("alert")).toHaveTextContent("The details of widgets are not available.");
  expect(screen.queryByRole("dialog", { name: "Skill details" })).toBeNull();
  expect(document.querySelector('[data-curio-skill-row="widgets"]')).not.toBeNull();
});
