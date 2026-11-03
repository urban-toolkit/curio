import React from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * The Skill Catalog page, /catalog/skills, lists the skills the agents read.
 *
 * Its rail counts All skills and, in its Skills section, the Core ones, and
 * its grid lists them, with the browse drawer, a right-click menu and a
 * details modal, as the Agent Catalog page lists its agents. A skill's card
 * and details say what it is for, what it serves (the node kinds of its
 * behaviors and the features it names), the agents that use it, its text
 * (collapsed, as an agent's prompts are) and its files. View details opens a
 * modal, never a page. A package's skill says it is from its package, and
 * nothing here changes it. The Agent Catalog page, /catalog/agents, lists
 * agents alone.
 */

const mockAgent = {
  dirName: "agent.curio.dataset-finder@1",
  id: "agent.curio.dataset-finder",
  name: "Dataset Finder",
  purpose: "Find datasets",
  category: "data",
  version: "1.0.0",
  capabilities: [],
  hooks: ["canvas"],
  tags: [],
  requiresAgents: [],
  imported: false,
  published: false,
  publishable: false,
  provenance: { publisher: "curio", trust: "built-in" },
};

const mockSkills = [
  {
    name: "widgets",
    description: "Use this skill when a node declares, places or changes a widget.",
    license: "MIT",
    compatibility: "Written for Curio's agents, their tools and node code.",
    author: "curio",
    version: "1.0.0",
    files: [],
    behaviors: ["code", "vega"],
    features: [],
    nodeKinds: ["Data Loading", "Python Computation", "Vega-Lite"],
    core: false,
    agents: [
      { id: "agent.curio.node-builder", name: "Node Builder", coord: "agent.curio.node-builder@1",
        card: true, added: false, always: false },
      { id: "agent.curio.dataset-finder", name: "Dataset Finder", coord: "agent.curio.dataset-finder@1",
        card: true, added: true, always: false },
    ],
  },
  {
    name: "nodes",
    description: "Use this skill to pick node types.",
    license: "MIT",
    compatibility: null,
    author: "curio",
    version: "1.0.0",
    files: [],
    behaviors: [],
    features: [],
    nodeKinds: [],
    core: true,
    agents: [
      { id: "agent.curio.node-builder", name: "Node Builder", coord: "agent.curio.node-builder@1",
        card: true, added: false, always: true },
    ],
  },
  {
    name: "scenarios",
    description: "Use this skill when a dataflow holds scenario boxes.",
    license: "MIT",
    compatibility: null,
    author: "curio",
    version: "1.0.0",
    files: ["references/colors.md"],
    behaviors: [],
    features: ["scenario-boxes"],
    nodeKinds: [],
    core: false,
    agents: [],
  },
];

const mockListImports = jest.fn(() => Promise.resolve({ agents: [] as unknown[] }));
const mockUploadImport = jest.fn();
jest.mock("../../services/agents/agentsApi", () => ({
  agentsApi: {
    catalog: jest.fn(() => Promise.resolve({ items: [mockAgent], agents: [mockAgent], facets: null })),
    listImports: () => mockListImports(),
    readDefinition: jest.fn(() => Promise.resolve({ manifest: {}, prompts: {} })),
    uploadImport: (...args: unknown[]) => mockUploadImport(...args),
  },
}));

const mockRead = jest.fn((name: string) =>
  Promise.resolve({
    name,
    text: `## ${name}\nThe body an agent reads.`,
    files: mockSkills.find((skill) => skill.name === name)?.files ?? [],
  }),
);
const mockList = jest.fn(() => Promise.resolve({ skills: mockSkills as unknown[], editable: true, reason: null }));
const mockRemoveOwn = jest.fn((name: string) => Promise.resolve({ name, removed: true, agents: [] }));
const mockCheckImport = jest.fn();
const mockImportSkill = jest.fn();
jest.mock("../../services/agents/skillsApi", () => ({
  skillsApi: {
    list: () => mockList(),
    read: (name: string) => mockRead(name),
    agentSkills: jest.fn(() => new Promise(() => {})),
    removeOwnSkill: (name: string) => mockRemoveOwn(name),
    checkImport: (...args: unknown[]) => mockCheckImport(...args),
    importSkill: (...args: unknown[]) => mockImportSkill(...args),
  },
}));

const mockCapabilities = jest.fn(() => Promise.resolve({ catalogPublish: false }));
jest.mock("../../services/packages/packagesApi", () => ({
  packagesApi: { factoryCapabilities: () => mockCapabilities() },
}));

jest.mock("../../providers/ToastProvider", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("../../api/llmConfigsApi", () => ({
  llmConfigsApi: { listing: jest.fn(() => new Promise(() => {})) },
}));

import { AgentCatalogBrowse } from "../../pages/agents/AgentCatalogBrowse";
import { SkillCatalogBrowse } from "../../pages/skills/SkillCatalogBrowse";

/** The rail row a section key and value name. */
const railRow = (section: string, value: string) =>
  document.querySelector(
    `[data-curio-rail-section="${section}"][data-curio-rail-value="${value}"]`,
  ) as HTMLElement;

/** The rail's first row, All skills, which counts every skill. */
const allSkills = () =>
  within(screen.getByRole("complementary", { name: "Filter skills" })).getByRole("button", { name: /^All skills/ });

/** /catalog/skills, once its grid holds *count* skills. */
async function renderPage(count = 3) {
  render(<SkillCatalogBrowse />);
  await waitFor(() => expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(count));
}

/** A read the test answers by hand, after the page has drawn what came
 *  before it, as a server's answer comes. */
function held<T>() {
  let answer: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => {
    answer = resolve;
  });
  return { promise, answer: (value: T) => answer(value) };
}

/** The value of the drawer's info row *label*. */
const drawerRow = (drawer: HTMLElement, label: string) =>
  Array.from(drawer.querySelectorAll(".infoRow"))
    .find((row) => row.querySelector(".infoRowLabel")?.textContent === label)
    ?.querySelector(".infoRowValue")?.textContent;

/** The value of the details' Skill info row *label*. */
const detailsRow = (dialog: HTMLElement, label: string) =>
  Array.from(dialog.querySelectorAll("dt")).find((dt) => dt.textContent === label)?.nextElementSibling?.textContent;

beforeEach(() => mockRead.mockClear());

describe("the rail", () => {
  it("counts every skill, then the core ones in its Skills section", async () => {
    await renderPage();
    const rail = screen.getByRole("complementary", { name: "Filter skills" });
    expect(within(rail).getByText("Skills")).toBeInTheDocument();
    expect(allSkills()).toHaveTextContent("All skills3");
    expect(railRow("skills", "core")).toHaveTextContent("Core1");
    // The page lists skills from its first view, and no agent.
    expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(3);
    expect(document.querySelectorAll("article[data-agent-coord]")).toHaveLength(0);
  });

  it("lists the skills in the grid, and All skills brings every one back after Core", async () => {
    await renderPage();
    expect(document.querySelectorAll("article[data-agent-coord]")).toHaveLength(0);
    expect(allSkills()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByPlaceholderText("Search skills…")).toBeInTheDocument();
    fireEvent.click(railRow("skills", "core"));
    await waitFor(() => expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(1));
    expect(allSkills()).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(allSkills());
    await waitFor(() => expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(3));
    expect(allSkills()).toHaveAttribute("aria-pressed", "true");
  });

  it("Core lists only the skills every call holds", async () => {
    await renderPage();
    fireEvent.click(railRow("skills", "core"));
    await waitFor(() =>
      expect(
        Array.from(document.querySelectorAll("article[data-skill-name]")).map((card) =>
          card.getAttribute("data-skill-name"),
        ),
      ).toEqual(["nodes"]),
    );
  });

  it("searches a skill by what it serves", async () => {
    await renderPage();
    fireEvent.change(screen.getByPlaceholderText("Search skills…"), { target: { value: "scenario boxes" } });
    await waitFor(() =>
      expect(
        Array.from(document.querySelectorAll("article[data-skill-name]")).map((card) =>
          card.getAttribute("data-skill-name"),
        ),
      ).toEqual(["scenarios"]),
    );
  });
});

describe("a skill's card and drawer", () => {
  it("says what the skill is for, what it serves and how many agents use it", async () => {
    await renderPage();
    const card = document.querySelector('article[data-skill-name="widgets"]') as HTMLElement;
    expect(card.querySelector("h2")?.textContent).toBe("widgets");
    expect(within(card).getByText(mockSkills[0].description)).toBeInTheDocument();
    expect(
      Array.from(card.querySelectorAll("[data-curio-tag-chip]")).map((chip) => chip.textContent),
    ).toEqual(["Data Loading", "Python Computation", "Vega-Lite"]);
    expect(within(card).getByText("2 agents")).toBeInTheDocument();
    expect(within(card).getByText("✓ Added by you")).toBeInTheDocument();
  });

  it("opens the drawer on the first skill by name, with the agents that use it", async () => {
    await renderPage();
    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    expect(within(drawer).getByText("Skill details")).toBeInTheDocument();
    // Sorted by name: nodes, scenarios, widgets.
    expect(within(drawer).getByRole("heading", { name: "nodes" })).toBeInTheDocument();
    fireEvent.click(document.querySelector('article[data-skill-name="widgets"]') as HTMLElement);
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "widgets" })).toBeInTheDocument());
    expect(within(drawer).getByText("Dataset Finder (added by you)")).toBeInTheDocument();
    expect(within(drawer).getByText("Node Builder")).toBeInTheDocument();
  });

  it("offers View details on right-click, as every catalog card does", async () => {
    await renderPage();
    fireEvent.contextMenu(document.querySelector('article[data-skill-name="scenarios"]') as HTMLElement);
    const menu = await screen.findByRole("menu", { name: "Skill actions" });
    expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["View details"]);
    fireEvent.click(within(menu).getByRole("menuitem", { name: "View details" }));
    expect(await screen.findByRole("dialog", { name: "Skill details" })).toBeInTheDocument();
  });
});

describe("a skill's details", () => {
  async function openDetails(name: string) {
    await renderPage();
    const card = document.querySelector(`article[data-skill-name="${name}"]`) as HTMLElement;
    fireEvent.click(within(card).getByRole("button", { name: "View details" }));
    return screen.findByRole("dialog", { name: "Skill details" });
  }

  /** The section a level-3 heading titles, in the details window. */
  const section = (dialog: HTMLElement, title: string) =>
    within(within(dialog).getByRole("heading", { name: title, level: 3 }).closest("section") as HTMLElement);

  it("is a modal, with its description, what it serves, its users, its text and its files", async () => {
    const dialog = await openDetails("widgets");
    expect(within(dialog).getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual([
      "Description", "Serves", "Used by", "Skill info", "Text", "Files",
    ]);
    expect(section(dialog, "Description").getByText(mockSkills[0].description)).toBeInTheDocument();
    expect(section(dialog, "Serves").getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Data Loading", "Python Computation", "Vega-Lite",
    ]);
    expect(section(dialog, "Used by").getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Node Builder", "Dataset Finder (added by you)",
    ]);
    expect(section(dialog, "Files").getByText("None besides SKILL.md")).toBeInTheDocument();
    // The text is read when the window opens, and arrives collapsed.
    await waitFor(() => expect(mockRead).toHaveBeenCalledWith("widgets"));
    const text = await waitFor(() => {
      const details = dialog.querySelector("details");
      expect(details).not.toBeNull();
      return details as HTMLDetailsElement;
    });
    expect(text.open).toBe(false);
    expect(text.querySelector("summary")?.textContent).toBe("What an agent reads · SKILL.md");
    expect(text.querySelector("pre")?.textContent).toBe("## widgets\nThe body an agent reads.");
  });

  it("names a feature it serves in plain words, and its files", async () => {
    const dialog = await openDetails("scenarios");
    expect(section(dialog, "Serves").getByText("Dataflows with scenario boxes")).toBeInTheDocument();
    expect(section(dialog, "Used by").getByText("No agent")).toBeInTheDocument();
    await waitFor(() => expect(mockRead).toHaveBeenCalledWith("scenarios"));
    await act(async () => {});
    expect(section(dialog, "Files").getByText("references/colors.md")).toBeInTheDocument();
    expect(section(dialog, "Files").queryByText("None besides SKILL.md")).toBeNull();
  });

  it("says a core skill serves every call", async () => {
    const dialog = await openDetails("nodes");
    expect(section(dialog, "Serves").getByText("Every call of every agent: the preamble holds it.")).toBeInTheDocument();
  });

  it("exports the skill from its header, as an agent's details export the agent", async () => {
    const dialog = await openDetails("widgets");
    expect(within(dialog).getByRole("button", { name: "Export" })).toBeEnabled();
  });
});

describe("the account's own skills", () => {
  const own = {
    ...mockSkills[2],
    name: "street-trees",
    description: "Use this skill when a dataflow counts street trees.",
    license: null,
    author: null,
    version: null,
    core: false,
    source: "yours",
    published: false,
    publishedByYou: false,
    publishable: true,
    removable: true,
    agents: [],
  };

  beforeEach(() => {
    mockList.mockClear();
    mockRemoveOwn.mockClear();
  });

  it("are imported from the page's own Import skill, and the page imports no agent", async () => {
    await renderPage();
    expect(screen.queryByRole("button", { name: "Import agent" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Import skill" }));
    expect(await screen.findByRole("heading", { name: "Import skill" })).toBeInTheDocument();
    expect(screen.getByLabelText("Skill folder")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Import skill" })).toBeNull());
    expect(screen.getByRole("button", { name: "Import skill" })).toBeInTheDocument();
  });

  it("say whose they are, and one held is removed from the account's skills from its drawer", async () => {
    mockList.mockResolvedValueOnce({ skills: [...mockSkills, own], editable: true, reason: null });
    await renderPage(4);
    const card = document.querySelector('article[data-skill-name="street-trees"]') as HTMLElement;
    expect(within(card).getByText("you")).toBeInTheDocument();
    expect(within(card).getByText("yours")).toBeInTheDocument();
    fireEvent.click(card);
    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "street-trees" })).toBeInTheDocument());
    expect(within(drawer).getByText("✓ In your skills")).toBeInTheDocument();
    expect(within(drawer).getByText("You imported it")).toBeInTheDocument();
    // It names no license, so its meta row draws no dot with nothing beside it.
    const meta = drawer.querySelector(".drawerMeta") as HTMLElement;
    expect(meta.textContent).toBe("street-trees");
    expect(meta.querySelector(".liveDot")).toBeNull();
    fireEvent.click(within(drawer).getByRole("button", { name: "Remove from your skills" }));
    await waitFor(() => expect(mockRemoveOwn).toHaveBeenCalledWith("street-trees"));
    // The skills are read again, without it.
    await waitFor(() => expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(3));
  });

  it("offer no removal for a skill Curio ships", async () => {
    await renderPage();
    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    expect(within(drawer).queryByRole("button", { name: "Remove from your skills" })).toBeNull();
    expect(within(drawer).getByText("Curio")).toBeInTheDocument();
    // Its license sits beside the meta row's dot.
    const meta = drawer.querySelector(".drawerMeta") as HTMLElement;
    expect(meta.textContent).toBe("nodesMIT");
    expect(meta.querySelector(".liveDot")).not.toBeNull();
  });

  it("open in the drawer once imported, after the skills are read again", async () => {
    mockCheckImport.mockResolvedValueOnce({
      name: own.name, givenName: own.name, description: own.description, warnings: [], leftOut: [], files: [],
      problem: null, rename: false, replaces: false, agents: [],
    });
    mockImportSkill.mockResolvedValueOnce({ skill: own, agents: [], replaced: false });
    await renderPage();
    // The read after the import is the first to hold it, and it answers once
    // the page has drawn the closed review, as a server's answer comes.
    const read = held<{ skills: unknown[]; editable: boolean; reason: null }>();
    mockList.mockImplementationOnce(() => read.promise);
    fireEvent.click(screen.getByRole("button", { name: "Import skill" }));
    fireEvent.change(await screen.findByLabelText("Skill files"), {
      target: { files: [new File(["---\nname: street-trees\n---\n"], "SKILL.md")] },
    });
    const importButton = await screen.findByRole("button", { name: "Import" });
    await waitFor(() => expect(importButton).toBeEnabled());
    fireEvent.click(importButton);
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Import skill" })).toBeNull());
    await act(async () => {});
    await act(async () => read.answer({ skills: [...mockSkills, own], editable: true, reason: null }));
    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    await waitFor(() => expect(within(drawer).queryByRole("heading", { name: "street-trees" })).not.toBeNull());
    expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(4);
  });
});

describe("a package's skill", () => {
  /** Scout's skill as the listing sends it: its metadata names curio as its author. */
  const scout = {
    ...mockSkills[2],
    name: "scout",
    description: "Use this skill when a dataflow uses Scout's nodes.",
    author: "curio",
    files: [],
    features: [],
    nodeKinds: ["Raster Calculator", "Bars"],
    source: "package",
    published: false,
    publishedByYou: false,
    publishable: false,
    removable: false,
    agents: [],
    package: { id: "curio.scout@1", name: "Scout" },
  };
  /** A skill the account imported, which may be published. */
  const mine = {
    ...mockSkills[2],
    name: "street-trees",
    description: "Use this skill when a dataflow counts street trees.",
    author: null,
    source: "yours",
    publishable: true,
    removable: true,
    agents: [],
  };

  beforeEach(() => {
    mockCapabilities.mockClear();
    mockList.mockClear();
  });

  it("says From Scout on its card, in its drawer and in its details, whatever its author, and nothing changes it", async () => {
    // Publishing is on, so a pill that does not show is the skill's, not the switch's.
    mockCapabilities.mockResolvedValueOnce({ catalogPublish: true });
    mockList.mockResolvedValueOnce({ skills: [...mockSkills, mine, scout], editable: true, reason: null });
    await renderPage(5);
    await waitFor(() => expect(mockCapabilities).toHaveBeenCalled());
    const card = document.querySelector('article[data-skill-name="scout"]') as HTMLElement;
    expect(within(card).getByText("From Scout")).toBeInTheDocument();
    expect(within(card).getByText("package")).toBeInTheDocument();
    expect(card.querySelector(".publisher")?.textContent).toBe("Scout · v1.0.0");
    // No agent is counted for it, and its author does not stand for whose it is.
    expect(within(card).queryByText(/\d+ agents?$/)).toBeNull();
    expect(within(card).queryByText(/curio/)).toBeNull();
    expect(
      Array.from(card.querySelectorAll("[data-curio-tag-chip]")).map((chip) => chip.textContent),
    ).toEqual(["Raster Calculator", "Bars"]);

    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    fireEvent.click(document.querySelector('article[data-skill-name="street-trees"]') as HTMLElement);
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "street-trees" })).toBeInTheDocument());
    expect(await within(drawer).findByRole("button", { name: "Publish" })).toBeInTheDocument();
    fireEvent.click(card);
    await waitFor(() => expect(within(drawer).getByRole("heading", { name: "scout" })).toBeInTheDocument());
    expect(drawerRow(drawer, "From")).toBe("Scout");
    expect(within(drawer).getByText("Scout · v1.0.0")).toBeInTheDocument();
    expect(within(drawer).getByText("Agents on a dataflow that uses Scout")).toBeInTheDocument();
    expect(within(drawer).queryByText("No agent")).toBeNull();
    expect(within(drawer).queryByText("✓ In your skills")).toBeNull();
    expect(within(drawer).queryByRole("button", { name: "Remove from your skills" })).toBeNull();
    expect(within(drawer).queryByRole("button", { name: "Publish" })).toBeNull();

    fireEvent.click(within(card).getByRole("button", { name: "View details" }));
    const dialog = await screen.findByRole("dialog", { name: "Skill details" });
    expect(within(dialog).getByText("Scout · v1.0.0")).toBeInTheDocument();
    expect(detailsRow(dialog, "From")).toBe("Scout");
    // Its author is a fact of its details, beside whose it is.
    expect(detailsRow(dialog, "Author")).toBe("curio");
    const usedBy = within(within(dialog).getByRole("heading", { name: "Used by", level: 3 }).closest("section") as HTMLElement);
    expect(usedBy.getByText("Agents on a dataflow that uses Scout")).toBeInTheDocument();
    expect(usedBy.queryByText("No agent")).toBeNull();
    expect(within(dialog).queryByRole("button", { name: "Export" })).toBeNull();
    // Its text is read as any skill's is.
    await waitFor(() => expect(mockRead).toHaveBeenCalledWith("scout"));
  });
});

describe("/catalog/agents, the Agent Catalog page", () => {
  const mine = {
    ...mockAgent,
    dirName: "agent.test.my-agent@1",
    id: "agent.test.my-agent",
    name: "My Agent",
    imported: true,
    publishable: true,
    provenance: { publisher: "me", trust: "imported" },
  };

  /** /catalog/agents, once its grid holds the agents. */
  async function renderAgentsPage() {
    render(<AgentCatalogBrowse />);
    await screen.findAllByText("Dataset Finder");
  }

  beforeEach(() => {
    mockList.mockClear();
    mockListImports.mockClear();
    mockUploadImport.mockReset();
  });

  it("shows no Skills rail section and no skill, and imports agents alone", async () => {
    await renderAgentsPage();
    expect(document.querySelectorAll("article[data-agent-coord]")).toHaveLength(1);
    expect(document.querySelector('[data-curio-rail-section="skills"]')).toBeNull();
    const rail = screen.getByRole("complementary", { name: "Filter agents" });
    expect(within(rail).queryByText("Skills")).toBeNull();
    expect(within(rail).queryByRole("button", { name: /^All skills/ })).toBeNull();
    expect(document.querySelectorAll("article[data-skill-name]")).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Import agent" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Import skill" })).toBeNull();
    // It reads no skill at all: the Skill Catalog's page does.
    expect(mockList).not.toHaveBeenCalled();
  });

  it("opens an imported agent in the drawer once the roster is read again and holds it, as an imported skill does", async () => {
    mockUploadImport.mockResolvedValueOnce(mine);
    await renderAgentsPage();
    // The read after the upload is the first to hold it, and it answers once
    // the page has drawn the closed modal, as a server's answer comes.
    const read = held<{ agents: unknown[] }>();
    mockListImports.mockImplementationOnce(() => read.promise);
    fireEvent.click(screen.getByRole("button", { name: "Import agent" }));
    fireEvent.change(await screen.findByLabelText("Package files"), {
      target: { files: [new File([JSON.stringify({ id: mine.id, version: "1.0.0" })], "manifest.json")] },
    });
    const importButton = await screen.findByRole("button", { name: "Import" });
    await waitFor(() => expect(importButton).toBeEnabled());
    fireEvent.click(importButton);
    await waitFor(() => expect(mockUploadImport).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Import agent package" })).toBeNull());
    await act(async () => {});
    await act(async () => read.answer({ agents: [mine] }));
    const drawer = document.querySelector('[data-curio-browse-drawer="true"]') as HTMLElement;
    await waitFor(() => expect(within(drawer).queryByRole("heading", { name: "My Agent" })).not.toBeNull());
  });
});
