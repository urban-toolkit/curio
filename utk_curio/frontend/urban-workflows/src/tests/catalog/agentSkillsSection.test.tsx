import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

/**
 * An agent's details list its skills beside In chat, Tools and Modes.
 *
 * The rows are this account's: the core skills its preamble holds, then its
 * own, then those a mode of it always holds. Add skill picks one of the skills
 * it does not hold, Remove drops one, and Restore brings back the list it
 * ships with, each through the agent's skills routes. The core skills and a
 * mode's own show no Remove, and an account that may change nothing (a hosted
 * guest) sees the list alone.
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
jest.mock("../../services/agents/skillsApi", () => ({
  skillsApi: {
    agentSkills: (coord: string) => mockAgentSkills(coord),
    addSkill: (coord: string, name: string) => mockAddSkill(coord, name),
    removeSkill: (coord: string, name: string) => mockRemoveSkill(coord, name),
    restoreSkills: (coord: string) => mockRestoreSkills(coord),
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
  name, description: `When to use ${name}.`, core: false, added: false, modes: [], removable: true, ...extra,
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

const skillsSection = () =>
  within(screen.getByRole("heading", { name: "Skills", level: 3 }).closest("section") as HTMLElement);

async function openDetails(skills: unknown) {
  mockAgentSkills.mockResolvedValue(skills);
  render(<AgentDetailModal agent={AGENT} onClose={jest.fn()} />);
  await waitFor(() => expect(document.querySelectorAll("[data-curio-skill-row]").length).toBeGreaterThan(0));
}

beforeEach(() => {
  mockAgentSkills.mockReset();
  mockAddSkill.mockReset();
  mockRemoveSkill.mockReset();
  mockRestoreSkills.mockReset();
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
  expect(section.queryByRole("button")).toBeNull();
  expect(document.querySelector('[data-curio-skill-row="widgets"]')).not.toBeNull();
});
