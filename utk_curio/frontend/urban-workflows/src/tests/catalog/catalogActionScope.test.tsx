/**
 * Where each catalog's ACTIONS live, and who is allowed to see them.
 *
 * Six changes are held here, all of them answers to the same complaint: a
 * catalog surface was showing a control that either did nothing, said the same
 * thing twice, or offered a write the viewer had no business making.
 *
 *   1. The publish control appears only when there is something to do.
 *   2. Publish and Unpublish are ONE control, not a badge plus a button.
 *   3. The Node browse card carries no account-wide write.
 *   4. The account-level agent import has one name, not three.
 *   5. The agent import picker accumulates across dialogs.
 *   6. Two projects that share a name are distinguishable.
 *
 * The source-level claims are read from disk. That is the established pattern
 * in this directory: several of them are claims about what a file does NOT
 * contain, and a render assertion can only show what a rendered tree does.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

import { shouldShowPublishPill } from "../../components/packages/CatalogPublishPill";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

// ── 1. The publish control appears only when actionable ──────────────────────

describe("the publish control appears only when there is something to do", () => {
  // It used to be `isPublished === true || (allowPublish && canPublish)`, so
  // anything already published rendered a static "Published" badge regardless
  // of who was looking. The standalone catalog pages list the shared catalog,
  // which means EVERY card on them is published - so every card carried a badge
  // announcing that the catalog contains the item you are looking at in the
  // catalog.
  test("a published item the viewer cannot act on shows nothing", () => {
    expect(
      shouldShowPublishPill({ isPublished: true, allowPublish: true, canPublish: false }),
    ).toBe(false);
  });

  test("a published item the viewer CAN act on shows the control", () => {
    expect(
      shouldShowPublishPill({ isPublished: true, allowPublish: true, canPublish: true }),
    ).toBe(true);
  });

  test("an unpublished item the viewer can act on shows the control", () => {
    expect(
      shouldShowPublishPill({ isPublished: false, allowPublish: true, canPublish: true }),
    ).toBe(true);
  });

  test("the operator's publish switch still wins over everything", () => {
    expect(
      shouldShowPublishPill({ isPublished: false, allowPublish: false, canPublish: true }),
    ).toBe(false);
  });

  test("a dataset that came from the shared catalog offers neither half", () => {
    // The reported case: after "Add to project", a shipped dataset the user
    // never published (Chicago Green Roofs) offered to Unpublish it, because
    // installing flips `origin` hub -> imported while `isPublished` stays true.
    // `isUserOwnedDataset` reads the store folder instead, which does not move.
    //
    // The gate has moved with the control. It was on the CARD; publishing is a
    // decision about the item, not about the project the card sits in, so it
    // now lives in the Data Catalog page's right-hand drawer - and the drawer
    // is where the gate has to be right, because that drawer had
    // `canPublish: true` and no ownership test whatsoever.
    const drawer = read("pages/dataHub/DataCatalogBrowseDrawer.tsx");
    // Anchor the end AFTER the start: this file has a wrapper component with
    // its own earlier `return (`, so a bare indexOf produced an empty slice
    // that vacuously passed nothing.
    const gateStart = drawer.indexOf("const showPublishPill");
    const gate = drawer.slice(gateStart, drawer.indexOf("return (", gateStart));
    expect(gate).toContain("isUserOwnedDataset(dataset)");
    expect(gate).not.toContain("canPublish: true");
    // And the card is out of it entirely.
    expect(read("components/datasets/catalog/DatasetCard.tsx")).not.toContain(
      "CatalogPublishPill",
    );
  });
});

// ── 2. One control for the published state ───────────────────────────────────

describe("Publish and Unpublish are one control", () => {
  const CARDS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetCard.tsx"],
    ["package", "components/packages/publishing/PackageCard.tsx"],
  ];

  test.each(CARDS)("the %s card offers no publish control at all", (_kind, rel) => {
    // This once asserted "one control, not two" ON the card. The card now has
    // neither: publishing is an account-level decision about the item, and it
    // belongs on the catalog page's detail drawer, not on a tile in a scrolling
    // grid one stray click from a browse gesture.
    const src = read(rel);
    expect(/>\s*Unpublish\s*</.test(src)).toBe(false);
    expect(src).not.toContain("CatalogPublishPill");
    expect(src).not.toContain("onUnpublish");
  });

  test("the pill renders the state as the action, and asks first", () => {
    const pill = read("components/packages/CatalogPublishPill.tsx");
    expect(pill).toContain('{busy ? "…" : "Unpublish"}');
    expect(pill).toContain('{busy ? "…" : "Publish"}');
    // Both are confirmed, and both from inside a drawer, so both need the
    // overlay layer or the dialog paints under it.
    expect(pill.match(/layer="overlay"/g)?.length).toBe(2);
  });
});

// ── 3. The Node browse card carries no account-wide write ────────────────────

describe("the browse cards are informational, and the drawer acts", () => {
  test("the Node card no longer installs to every project from the grid", () => {
    const card = read("pages/catalog/PackageBrowseCard.tsx");
    // As rendered text, not as any mention: the comment recording why the
    // button left names the label it removed.
    expect(/>\s*Add to all projects\s*</.test(card)).toBe(false);
    expect(card).not.toContain("onInstall");
    // It says where it is, once, in the strip - not again down in the actions.
    expect(card).toContain("In all projects");
    expect(/>\s*In defaults\s*</.test(card)).toBe(false);
  });

  test("the drawer still carries both the add and the update", () => {
    const drawer = read("pages/catalog/PackageBrowseDrawer.tsx");
    expect(drawer).toContain("Add to all projects");
    expect(drawer).toContain("onInstall");
  });

  test.each([
    ["data", "pages/dataHub/DataCatalogBrowseCard.tsx"],
    ["node", "pages/catalog/PackageBrowseCard.tsx"],
    ["agent", "pages/agents/AgentCatalogBrowseCard.tsx"],
  ])("the %s card offers View details and a status, the same shape", (_kind, rel) => {
    const src = read(rel);
    expect(src).toContain("View details");
    expect(src).toMatch(/stripBadgePopular/);
  });
});

// ── 4. One name for the account-level agent import ───────────────────────────

describe("the account-level agent import has one name", () => {
  test("the drawer row says what the browse page says", () => {
    // `state.importAgent` is `agentsApi.import`, the same call the browse page
    // makes. The drawer labelled it a bare "Import" while the page labelled it
    // "Add to my account" - and the drawer's FOOTER has an "Import agent"
    // button that uploads a definition, an unrelated operation. Two "Import"s
    // in one panel, meaning different things.
    // The row button is gone from the drawer altogether - an account-level add
    // is not a per-project action and does not belong on a canvas card - so
    // what is asserted now is that neither of the colliding names came back,
    // and that the account-level control lives on the browse page instead.
    const drawer = read("components/agents/catalog/AgentCatalogDrawer.tsx");
    expect(/>\s*Import\s*</.test(drawer)).toBe(false);
    expect(drawer).not.toContain("state.importAgent");
    expect(read("pages/agents/AgentCatalogBrowseDrawer.tsx")).toContain(
      "Add to all projects",
    );
  });

  test("the footer's upload keeps its own, distinct name", () => {
    // It is genuinely a different operation (POST /api/agents/imports/upload,
    // which writes definition bytes), so it keeps a distinct label rather than
    // being folded into the one above.
    expect(read("components/agents/catalog/AgentCatalogDrawer.tsx")).toContain("Import agent");
  });
});

// ── 5. The agent import picker accumulates ───────────────────────────────────

jest.mock("../../api/agentsApi", () => ({
  agentsApi: { uploadImport: jest.fn() },
}));

describe("the agent import picker can assemble a real package", () => {
  test("a second selection adds to the first instead of replacing it", async () => {
    // An agent package is `<id>@<version>/manifest.json` plus
    // `<id>@<version>/prompts/*.txt` - two directories - and one OS file dialog
    // cannot span two directories. `pick` used to `setFiles(read)`, so the
    // second dialog discarded the manifest picked in the first and the flow
    // could never be completed against the documented layout.
    const { AgentImportModal } = await import(
      "../../components/agents/catalog/AgentImportModal"
    );
    render(<AgentImportModal onClose={() => {}} onImported={() => {}} />);
    const input = screen.getByLabelText("Package files") as HTMLInputElement;
    // Read the running tally, not the page: the hint above the picker also
    // says "manifest.json", so a text query matches two nodes.
    const summary = () => document.querySelector(".summary")?.textContent ?? "";

    const manifest = new File(['{"id":"a"}'], "manifest.json", { type: "application/json" });
    await userEvent.upload(input, manifest);
    await waitFor(() => expect(summary()).toContain("manifest.json"));
    expect(summary()).toContain("0 prompt file");

    const prompt = new File(["hello"], "explain.txt", { type: "text/plain" });
    await userEvent.upload(input, prompt);
    await waitFor(() => expect(summary()).toContain("1 prompt file"));
    // The manifest survived the second dialog. This is the whole point.
    expect(summary()).toContain("manifest.json");
  });

  test("Clear empties an accumulating selection", async () => {
    const { AgentImportModal } = await import(
      "../../components/agents/catalog/AgentImportModal"
    );
    render(<AgentImportModal onClose={() => {}} onImported={() => {}} />);
    const input = screen.getByLabelText("Package files") as HTMLInputElement;
    await userEvent.upload(
      input,
      new File(['{"id":"a"}'], "manifest.json", { type: "application/json" }),
    );
    await userEvent.click(await screen.findByRole("button", { name: "Clear" }));
    // The whole tally goes, not just its text.
    await waitFor(() => expect(document.querySelector(".summary")).toBeNull());
  });
});

// ── 6. Two projects sharing a name are distinguishable ───────────────────────

jest.mock("../../services/datasetCatalog", () => ({
  datasetCatalogApi: { datasetUsage: jest.fn() },
}));

jest.mock("../../services/datasetLineage", () => ({
  formatNodeTypeLabel: (t?: string) => t ?? "node",
}));

describe("the usage list never looks like it repeats itself", () => {
  async function renderUsage(usage: Array<Record<string, unknown>>) {
    const { datasetCatalogApi } = await import("../../services/datasetCatalog");
    (datasetCatalogApi.datasetUsage as jest.Mock).mockResolvedValue(usage);
    const { DatasetDataflowUsageSection } = await import(
      "../../components/datasets/catalog/DatasetDataflowUsage"
    );
    render(
      <MemoryRouter>
        <DatasetDataflowUsageSection datasetId="d1" />
      </MemoryRouter>,
    );
    return within(await screen.findByRole("region", { name: "Projects using this dataset" }));
  }

  test("two different projects with the same name are told apart", async () => {
    // Both rows are truthful and link to different projects. The row showed
    // nothing but the name, so "Used in projects (2)" read as one project
    // listed twice.
    const usage = await renderUsage([
      { dataflowId: "aaaaaaaa-1111", dataflowName: "Traffic study", nodeCount: 1, nodes: [] },
      { dataflowId: "bbbbbbbb-2222", dataflowName: "Traffic study", nodeCount: 1, nodes: [] },
    ]);
    expect(usage.getByText("Used in projects (2)")).toBeInTheDocument();
    expect(usage.getByText("aaaaaaaa")).toBeInTheDocument();
    expect(usage.getByText("bbbbbbbb")).toBeInTheDocument();
  });

  test("distinct names stay clean, with no id noise", async () => {
    const usage = await renderUsage([
      { dataflowId: "aaaaaaaa-1111", dataflowName: "Traffic study", nodeCount: 1, nodes: [] },
      { dataflowId: "bbbbbbbb-2222", dataflowName: "Green roofs", nodeCount: 1, nodes: [] },
    ]);
    expect(usage.queryByText("aaaaaaaa")).not.toBeInTheDocument();
    expect(usage.queryByText("bbbbbbbb")).not.toBeInTheDocument();
  });

  test("a repeated id collapses to one row, and the count agrees", async () => {
    const usage = await renderUsage([
      { dataflowId: "aaaaaaaa-1111", dataflowName: "Traffic study", nodeCount: 1, nodes: [] },
      { dataflowId: "aaaaaaaa-1111", dataflowName: "Traffic study", nodeCount: 1, nodes: [] },
    ]);
    expect(usage.getByText("Used in projects (1)")).toBeInTheDocument();
  });
});

// ── Every tab is a real content scope ────────────────────────────────────────

describe("no catalog drawer keeps a curation tab it cannot fill", () => {
  test("the Data drawer's Featured tab is gone", () => {
    // It was `hub || installed`, sliced to 6 - no curation behind it, nothing
    // could ever become featured, and it sat first so it was what the drawer
    // opened on. The Node drawer lost Featured and Updates for the same reason.
    const types = read("components/datasets/catalog/datasetCatalogDrawerTypes.ts");
    // The union itself, not any mention: the comment above it records what left.
    expect(types).toContain('export type DrawerTab = "browse" | "installed" | "computed";');
    expect(types).not.toContain('featured: "Featured"');
    const drawer = read("components/datasets/catalog/DatasetCatalogDrawer.tsx");
    expect(/>\s*Featured\s*</.test(drawer)).toBe(false);
    // The dead filter branch went with it, not just the button.
    expect(read("components/datasets/catalog/useDatasetCatalogDrawer.ts")).not.toContain(
      'tab === "featured"',
    );
  });

  test("what remains in each drawer is a scope, not a mood", () => {
    // Everything / in this project, plus one kind-specific scope where the
    // catalog genuinely has one: datasets produced by nodes, agent definitions
    // the user wrote.
    expect(read("components/packages/publishing/DrawerTabs.tsx")).toContain("In project");
    expect(read("components/datasets/catalog/datasetCatalogDrawerTypes.ts")).toContain(
      'computed: "Computed"',
    );
    expect(read("components/agents/catalog/AgentCatalogDrawer.tsx")).toContain('"My imports"');
  });
});

// ── Every catalog page can import, next to its search box ──────────────────

describe("the catalog pages import, not just the drawers", () => {
  const PAGES: [string, string, string][] = [
    ["data", "pages/dataHub/DataCatalogBrowse.tsx", "Import dataset"],
    ["node", "pages/catalog/NodeCatalogBrowse.tsx", "Import package"],
    ["agent", "pages/agents/AgentCatalogBrowse.tsx", "Import agent"],
  ];

  test.each(PAGES)("the %s page has an import control", (_k, rel, label) => {
    // Each drawer has had an import in its sticky footer all along; the pages
    // had none, so the only route from a downloaded file into the product was
    // to open a dataflow and use that dataflow's drawer - even though two of
    // the three imports are not dataflow-scoped at all.
    const src = read(rel);
    expect(src).toContain("CatalogHeaderImport");
    expect(src).toContain(`label="${label}"`);
  });

  test.each(PAGES)("the %s page puts it in the header tools row", (_k, rel) => {
    // Beside the search box, the arrangement the Projects page already used.
    const src = read(rel);
    const tools = src.slice(src.indexOf("headerTools"), src.indexOf("filterBar"));
    expect(tools).toContain("hubSearch");
    expect(tools).toContain("CatalogHeaderImport");
    // Search first, import second.
    expect(tools.indexOf("CatalogHeaderImport")).toBeGreaterThan(tools.indexOf("hubSearch"));
  });

  test("it borrows the Projects page's secondary treatment, not the primary one", () => {
    // `publishButton` is the light fill the Projects page gives "Import Jupyter
    // notebook". Import must not compete with a page's primary action.
    const comp = read("pages/catalog/CatalogHeaderImport.tsx");
    expect(comp).toContain("styles.publishButton");
    expect(comp).not.toContain("primaryHeaderButton");
    expect(read("pages/projects/ProjectsList.tsx")).toContain("Import Jupyter notebook");
  });

  test("the file variant clears its input so the same file can be picked twice", () => {
    // Without the reset, re-picking the same file fires no change event and the
    // second import silently does nothing.
    expect(read("pages/catalog/CatalogHeaderImport.tsx")).toContain(
      'fileInputRef.current.value = ""',
    );
  });

  test("the page and the drawer import through ONE pathway each", () => {
    // The pages' imports were briefly second copies of the drawers': same
    // upload call, same refresh, same reload, free to drift from then on. Each
    // pair now shares a hook, so changing how a file is taken in changes both
    // surfaces at once.
    const PAIRS: [string, string, string][] = [
      [
        "usePackageArchiveImport",
        "components/packages/publishing/NodeCatalogDrawer.tsx",
        "pages/catalog/useNodeCatalogBrowse.ts",
      ],
      [
        "useDatasetImport",
        "components/datasets/catalog/useDatasetCatalogDrawer.ts",
        "pages/dataHub/DataCatalogBrowse.tsx",
      ],
      [
        "AgentImportModal",
        "components/agents/catalog/AgentCatalogDrawer.tsx",
        "pages/agents/AgentCatalogBrowse.tsx",
      ],
    ];
    for (const [shared, drawer, page] of PAIRS) {
      expect(read(drawer)).toContain(shared);
      expect(read(page)).toContain(shared);
    }
  });

  test("neither page calls the upload API behind its shared hook's back", () => {
    // The tell that a copy has grown back.
    expect(read("pages/catalog/useNodeCatalogBrowse.ts")).not.toContain("uploadArchive");
    expect(read("pages/dataHub/DataCatalogBrowse.tsx")).not.toContain("importDataset(file)");
  });

  test("the agent import is a modal, not a file dialog", () => {
    // An agent package is a manifest plus its prompt files across two
    // directories; one file input cannot express that.
    const page = read("pages/agents/AgentCatalogBrowse.tsx");
    const tools = page.slice(page.indexOf("headerTools"), page.indexOf("filterBar"));
    expect(tools).not.toContain("accept=");
    expect(page).toContain("AgentImportModal");
  });
});

// ── Datasets reach every project too ─────────────────────────────────────────

describe("the Data catalog has the all-projects scope its peers had", () => {
  test("the page offers the account-level action the drawer had nowhere to put", () => {
    const drawer = read("pages/dataHub/DataCatalogBrowseDrawer.tsx");
    expect(drawer).toContain("Add to all projects");
    expect(drawer).toContain("Remove from all projects");
    // Dark to add, light to take away: the same vocabulary as its peers.
    expect(drawer).toContain("styles.addToPaletteBtn");
    expect(drawer).toContain("styles.destructiveBtn");
  });

  test("View details survives the primary slot being taken", () => {
    // The drawer's primary action USED to be "View details"; the account-level
    // action displaced it rather than deleting it.
    const drawer = read("pages/dataHub/DataCatalogBrowseDrawer.tsx");
    expect(drawer).toContain("View details");
    expect(drawer).toContain("secondaryAction");
    // And it takes neither of the two loaded treatments, because it is neither
    // an action nor a destructive one.
    expect(drawer).toContain("styles.drawerLinkButton");
  });

  test("the card states the wider scope and does not also state the narrower", () => {
    const card = read("pages/dataHub/DataCatalogBrowseCard.tsx");
    expect(card).toContain("In all projects");
    // A dataset in every project is also in this one; saying both is a
    // tautology plus a narrowing.
    expect(card).toContain("inAllProjects ?");
  });

  test("the page can filter by the account scope, like the Node page", () => {
    const page = read("pages/dataHub/DataCatalogBrowse.tsx");
    expect(page).toContain("In all projects");
    expect(page).toContain('scope === "defaults"');
  });

  test("membership is its own fetch, not a field on each row", () => {
    // Same shape as GET /api/packages/defaults: it is a property of the
    // account, and the same dataset row is served to every user.
    const api = read("services/datasetCatalog/datasetCatalogApi.ts");
    expect(api).toContain("listDatasetDefaults");
    expect(api).toContain("addDatasetToDefaults");
    expect(api).toContain("removeDatasetFromDefaults");
    expect(api).toContain("/api/datasets/defaults");
  });
});

// ── Every details view is the same shape ─────────────────────────────────────

describe("all three catalogs have a details view, and it is the same shape", () => {
  const MODALS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetDetailModal.tsx"],
    ["agent", "components/agents/catalog/AgentDetailModal.tsx"],
    ["package", "components/packages/publishing/PackageDetailModal.tsx"],
  ];

  test.each(MODALS)("the %s details view fills the panel, not a small box", (_k, rel) => {
    // The Data one was `xlarge` and the other two were `large`, so the same
    // affordance opened a half-page panel in one catalog and a small centred
    // dialog in the others.
    expect(read(rel)).toContain('size="xlarge"');
  });

  test("the Node catalog has a details view at all", () => {
    // It was the only one of the three with none: its card's "View details"
    // called `onSelect`, so on a card whose drawer was already open the click
    // did nothing, and below 1100px (where the drawer column is display:none)
    // there was no way to read a package's contents on any screen.
    const page = read("pages/catalog/NodeCatalogBrowse.tsx");
    expect(page).toContain("PackageDetailModal");
    expect(page).toContain("setDetailDirName");
    // And it is NOT wired to the same setter as the drawer - that is the bug
    // (#189) that made the Agent page's own "View details" a no-op.
    expect(page).toContain("const [detailDirName");
  });

  test.each([
    ["agent", "components/agents/catalog/AgentDetailModal.tsx"],
    ["package", "components/packages/publishing/PackageDetailModal.tsx"],
  ])("the %s details view can export", (_k, rel) => {
    const src = read(rel);
    expect(src).toContain("Export");
    expect(src).toContain("styles.exportButton");
  });

  test("the agent details view shows the prompts, which ARE the agent", () => {
    // `AgentCard` is a summary and carries no prompt text, so the details
    // screen described an agent's behaviour without showing the prompts that
    // define it. It reads the definition instead.
    const src = read("components/agents/catalog/AgentDetailModal.tsx");
    expect(src).toContain("readDefinition");
    expect(src).toContain("Prompts");
    // Collapsed: a prompt runs to hundreds of lines.
    expect(src).toContain("<details");
  });

  test("agents can now round-trip: what Export writes, Import accepts", () => {
    // The product had an agent IMPORT with no export, so a definition could go
    // into a Curio and never come back out. And the import wanted a manifest
    // plus loose prompt files from two different directories, which one file
    // dialog cannot span. The export writes one bundle; the payload builder
    // takes that bundle.
    expect(read("components/agents/catalog/AgentDetailModal.tsx")).toContain(
      "curio-agent.json",
    );
    expect(read("components/agents/catalog/buildUploadPayload.ts")).toContain(
      "curio-agent.json",
    );
  });

  test("the download helper is a leaf, not the package API", () => {
    // Importing it from `api/packagesApi` dragged the whole node-package
    // registry into any component that only wanted to save bytes to a file,
    // and killed unrelated test suites on a registry mock before their first
    // assertion.
    expect(read("components/agents/catalog/AgentDetailModal.tsx")).toContain(
      'from "../../../utils/triggerBlobDownload"',
    );
  });
});

// ── The agent drawer is per-project, and only per-project ────────────────────

describe("the agent drawer stopped speaking about the account", () => {
  test("there is no My imports scope", () => {
    // It listed the ACCOUNT's imported definitions inside a per-dataflow panel,
    // and its row button was the only thing in the product that wrote a
    // built-in into that list - which is how "Dataflow builder" and
    // "Connection builder" came to report themselves as the user's own imports.
    const hook = read("components/agents/catalog/useAgentCatalogDrawer.ts");
    expect(hook).toContain('export type AgentScope = "browse" | "installed";');
    // Not "never calls listImports": it does, as the no-project fallback for
    // the "In project" scope, because a dataflow has no project until its first
    // save and the scope would otherwise render empty. What must not come back
    // is the SCOPE - an account-level tab inside a per-dataflow panel.
    // The comment above the type records what left, so assert on the scope
    // MACHINERY rather than on any mention of the word.
    expect(hook).not.toMatch(/s === "imports"/);
    expect(hook).not.toMatch(/ALL_SCOPES.*imports/);
    const drawer = read("components/agents/catalog/AgentCatalogDrawer.tsx");
    expect(/>\s*My imports\s*</.test(drawer)).toBe(false);
  });

  test("the account-level control lives on the page instead", () => {
    expect(read("pages/agents/AgentCatalogBrowseDrawer.tsx")).toContain(
      "Add to all projects",
    );
  });
});

// ── An unsaved dataflow still shows the all-projects agents ─────────────────

describe("the agents palette in a dataflow that has no project yet", () => {
  test("falls back to the account's agents instead of showing nothing", () => {
    // A dataflow you have just created has no project - it is created on the
    // first save - so `listProjectAgents` had nothing to read and the palette
    // did `setAgents([])`. The reported symptom was agents marked "In all
    // projects" being absent from a new dataflow; they were absent from the
    // palette specifically because the project did not exist yet, and
    // `save_project` seeds them the moment it does.
    const src = read(
      "components/menus/nodes/agentsPalette/AgentsPaletteDropdown.tsx",
    );
    expect(src).toContain("agentsApi.listImports()");
    // The bare bail-out is gone.
    expect(src).not.toMatch(/if \(!projectId\) \{\s*setAgents\(\[\]\);/);
  });

  test("a saved dataflow still reads its own lockfile", () => {
    // The fallback must not replace the per-project read: once the project
    // exists, its lockfile is the truth, and the account list would show agents
    // the user removed from THIS dataflow.
    expect(
      read("components/menus/nodes/agentsPalette/AgentsPaletteDropdown.tsx"),
    ).toContain("agentsApi.listProjectAgents(projectId)");
  });
});

// ── One details header, not three ────────────────────────────────────────────

describe("every details view opens with the same header", () => {
  const VIEWS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetDetailPanel.tsx"],
    ["agent", "components/agents/catalog/AgentDetailModal.tsx"],
    ["package", "components/packages/publishing/PackageDetailModal.tsx"],
  ];

  test.each(VIEWS)("the %s view renders the shared header", (_k, rel) => {
    // There were two stylesheets and three results: two title sizes, three
    // paddings, and the action in a different place in each. Lining them up
    // meant editing whichever file you happened to be in, so they came apart
    // again immediately. One component now.
    expect(read(rel)).toContain("CatalogDetailHeader");
  });

  test.each(VIEWS)("the %s view builds no header of its own", (_k, rel) => {
    const src = read(rel);
    expect(src).not.toContain("styles.headerMain");
    expect(src).not.toMatch(/<div className=\{styles\.header\}>/);
  });

  test("the shared header clears the modal's close button", () => {
    // ModalShell's `.closeX` is absolutely positioned at top/right 16px, and
    // the header's action rendered underneath it.
    const css = read("components/catalog/CatalogDetailHeader.module.css");
    expect(css).toMatch(/padding:\s*24px\s+68px/);
  });

  test("the data view drops the breadcrumb that restated its own title", () => {
    // "DATA CATALOG / <name>" sat directly above a header showing <name>, and
    // none of it was a link. Its two peers never had one.
    expect(read("components/datasets/catalog/DatasetDetailPanel.tsx")).not.toContain(
      "<span>DATA CATALOG</span>",
    );
  });
});

// ── An unsaved dataflow shows what it will contain ───────────────────────────

describe("a dataflow with no project yet is not reported as empty", () => {
  test("the datasets palette and drawer count the all-projects datasets", () => {
    // `installed` is derived from ONE dataflow's spec refs, so before the first
    // save it is false for everything and both surfaces rendered empty - even
    // for a dataset the user had just added to every project.
    const helper = read("services/datasetCatalog/datasetCatalogTypes.ts");
    expect(helper).toContain("export function isInThisDataflow");
    expect(read("components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx")).toContain(
      "isInThisDataflow",
    );
    expect(read("components/datasets/catalog/useDatasetCatalogDrawer.ts")).toContain(
      "isInThisDataflow",
    );
  });

  test("the fallback applies only when there is no project", () => {
    // Once the dataflow exists its own refs are the truth again - the account
    // list would otherwise show datasets the user removed from THIS dataflow.
    expect(read("services/datasetCatalog/datasetCatalogTypes.ts")).toContain(
      "return !hasProject && dataset.inAllProjects === true;",
    );
  });

  test("the right bar drops the per-dataset usage walk", () => {
    // It fired a `/usage` request that walks every project's spec, from a panel
    // that opens on the first card the moment the page loads.
    expect(read("pages/dataHub/DataCatalogBrowseDrawer.tsx")).not.toContain(
      "DatasetDataflowUsageSection",
    );
  });
});

// ── The left rail leads the same way on all three pages ─────────────────────

describe("every catalog page's rail opens with the same section", () => {
  const PAGES: [string, string][] = [
    ["node", "pages/catalog/NodeCatalogBrowse.tsx"],
    ["agent", "pages/agents/AgentCatalogBrowse.tsx"],
    ["data", "pages/dataHub/DataCatalogBrowse.tsx"],
  ];

  test.each(PAGES)("the %s rail has a By status section", (_k, rel) => {
    // The Data rail opened straight into "By format". Its account-level scope
    // existed only as a chip down in the filter bar, so the three catalogs
    // disagreed about where you look for the same kind of filter.
    expect(read(rel)).toContain("By status");
  });

  test.each(PAGES)("the %s rail's status section is first", (_k, rel) => {
    const src = read(rel);
    const rail = src.slice(src.indexOf("categoryRail"));
    const status = rail.indexOf("By status");
    expect(status).toBeGreaterThan(-1);
    // No other rail heading precedes it.
    const firstLabel = rail.indexOf("railLabel}>");
    expect(rail.slice(firstLabel, firstLabel + 40)).toContain("By status");
  });

  test.each(PAGES)("the %s rail offers the all-projects scope", (_k, rel) => {
    expect(read(rel)).toContain("In all projects");
  });

  test("the data rail does not label two buttons 'All datasets'", () => {
    // The format section's reset used that name too; it only clears the format
    // facet, so it says so.
    const src = read("pages/dataHub/DataCatalogBrowse.tsx");
    expect(src.match(/<span>All datasets<\/span>/g) ?? []).toHaveLength(1);
    expect(src).toContain("<span>All formats</span>");
  });
});

// ── The left palette and the right drawer agree ─────────────────────────────

describe("a catalog's palette and its drawer describe the same dataflow", () => {
  test("the datasets palette queries the same listing branch as the drawer", () => {
    // `includeHub` is not a narrower view of one dataset - it takes a different
    // branch server-side (`listing.py`): with no `dataflowId`, `false` skips
    // `user_store.list_items()` entirely, so the account's datasets were absent
    // from the palette's response and nothing could mark them. The drawer asked
    // with `true` and saw them. Same dataflow, two answers - which is exactly
    // what "the left side does not match the right side" was.
    const palette = read(
      "components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx",
    );
    const drawer = read("components/datasets/catalog/useDatasetCatalogDrawer.ts");
    expect(palette).toContain("includeHub: true");
    expect(drawer).toContain("includeHub: true");
    expect(palette).not.toContain("includeHub: false");
  });

  test("both decide membership with the same helper", () => {
    // Not two hand-rolled predicates that drift.
    for (const rel of [
      "components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx",
      "components/datasets/catalog/useDatasetCatalogDrawer.ts",
    ]) {
      expect(read(rel)).toContain("isInThisDataflow");
    }
  });

  test("the agents palette and drawer share the same no-project fallback", () => {
    for (const rel of [
      "components/menus/nodes/agentsPalette/AgentsPaletteDropdown.tsx",
      "components/agents/catalog/useAgentCatalogDrawer.ts",
    ]) {
      expect(read(rel)).toContain("agentsApi.listImports()");
    }
  });
});

// ── Every drawer counts its dataflow the same way ───────────────────────────

describe("all three drawers put a count on their In project tab", () => {
  test("the data drawer does", () => {
    expect(read("components/datasets/catalog/DatasetCatalogDrawer.tsx")).toContain(
      "tabInstalledCount",
    );
  });

  test("the node drawer does", () => {
    expect(read("components/packages/publishing/DrawerTabs.tsx")).toContain(
      "installedCount",
    );
  });

  test("the agent drawer does too, which it did not", () => {
    // It was the only one of the three with no number on that tab, so the
    // drawers reported the dataflow's contents in two different ways.
    const drawer = read("components/agents/catalog/AgentCatalogDrawer.tsx");
    expect(drawer).toContain("c.installedCount");
    expect(drawer).toContain("tabStyles.tabBadge");
  });

  test("the agent count does not wait for its own tab to be opened", () => {
    // Counting only the VISIBLE scope would read 0 until you clicked the tab
    // the number describes.
    expect(read("components/agents/catalog/useAgentCatalogDrawer.ts")).toContain(
      'fetchScope("installed")',
    );
  });
});

// ── The palettes say the same thing, and offer the same controls ────────────

describe("the three palettes are one design", () => {
  const PALETTES: [string, string][] = [
    ["data", "components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx"],
    ["agent", "components/menus/nodes/agentsPalette/AgentsPaletteDropdown.tsx"],
    ["node", "components/menus/nodes/toolsMenuPackagePalette/PackagesPaletteDropdown.tsx"],
  ];

  test.each(PALETTES)("the %s palette tells you the rows are draggable", (_k, rel) => {
    // Every palette lists draggable rows and only the Agent one said so - in a
    // source comment, which is the wrong audience entirely.
    expect(read(rel)).toContain("PaletteDragHint");
  });

  test("the hint is one component, not three strings", () => {
    const hint = read("components/menus/nodes/PaletteDragHint.tsx");
    expect(hint).toContain("onto a node or the canvas to attach it");
    // "a dataset" / "an agent": the article the word actually takes.
    expect(hint).toContain("aOrAn");
  });

  test("the data palette has no sort toggle its peers lack", () => {
    const src = read("components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx");
    expect(src).not.toContain("styles.sortToggle");
    expect(src).not.toContain("setSortKey");
  });
});

// ── The node drawer knows what a new dataflow will contain ──────────────────

describe("the Node drawer's In project tab in an unsaved dataflow", () => {
  test("falls back to the account defaults", () => {
    // `projectPackages` is empty until the first save, so this read "No
    // packages added to this dataflow yet" while the account's defaults
    // (curio.builtin, the examples, uhvi) were seeded into it the moment it
    // saved. Its two peers already did this.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).toMatch(/packagesApi\s*\.getDefaults\(\)/);
    expect(src).toContain("projectId ? projectPackages : accountDefaults");
  });

  test("the count comes from the same set as the list", () => {
    // One source, so the badge cannot disagree with the rows under it.
    const src = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(src).toContain("installedCount={projectInstalledDirs.size}");
    expect(src).toContain("projectInstalledDirs.has(p.dirName)");
  });
});

// ── An agent is in a dataflow, or it is not ─────────────────────────────────

describe("the agent drawer states membership once", () => {
  test("membership decides which single control the card offers", () => {
    // The reported bug: an agent appeared under "In project" AND under
    // "Browse all" offering "Add to project" - the same agent, twice, saying
    // two different things. Before the first save a dataflow has no project,
    // so `installedInProject` is false for EVERYTHING, which is what made the
    // browse card offer to add something the dataflow already had.
    const drawer = read("components/agents/catalog/AgentCatalogDrawer.tsx");
    expect(drawer).toContain("const inThisDataflow");
    expect(drawer).toContain("!hasProject && card.imported === true");
    // One ternary on that predicate: Remove when in, Add when not. Never both,
    // and never Add for something already there.
    expect(drawer).toContain("{inThisDataflow ? (");
  });

  test("in the dataflow means Remove, not Add", () => {
    const drawer = read("components/agents/catalog/AgentCatalogDrawer.tsx");
    const block = drawer.slice(drawer.indexOf("{inThisDataflow ? ("));
    const remove = block.indexOf("Remove from project");
    const add = block.indexOf("installLabel(card)");
    expect(remove).toBeGreaterThan(-1);
    expect(add).toBeGreaterThan(remove);
  });
});

// ── One card shape per drawer, in every tab ─────────────────────────────────

describe("a drawer renders the same card in both of its tabs", () => {
  test("the Node drawer's In project tab uses PackageCard, not a second list", () => {
    // It rendered `MyPackagesList` - a compact dot-and-row list with its own
    // actions - so one drawer showed its two tabs in two visual languages, and
    // neither matched the Data or Agent drawer.
    // The import, not any mention: two comments record what this replaced.
    const drawer = read("components/packages/publishing/NodeCatalogDrawer.tsx");
    expect(drawer).not.toMatch(/import \{ MyPackagesList \}/);
    expect(drawer).not.toMatch(/<MyPackagesList/);
    // Both branches render the card into the same list container.
    expect((drawer.match(/<PackageCard/g) ?? []).length).toBe(2);
    expect((drawer.match(/shell\.cardList/g) ?? []).length).toBe(2);
  });

  test("an installed package offers Remove, never Add", () => {
    const card = read("components/packages/publishing/PackageCard.tsx");
    expect(card).toContain("{!isInstalled ? (");
    expect(card).toContain("const showUninstall = isInstalled");
  });
});

// ── One card body, the Agent drawer's, in all three ─────────────────────────

describe("the In-project cards share one body shape", () => {
  const CARDS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetCard.tsx"],
    ["package", "components/packages/publishing/PackageCard.tsx"],
    ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
  ];

  test.each(CARDS)("the %s card has a title and one meta row", (_k, rel) => {
    const src = read(rel);
    expect(src).toMatch(/cardTitle\}/);
    expect(src).toMatch(/cardMetaRow\}/);
  });

  test.each(CARDS)("the %s card carries no row-header strip", (_k, rel) => {
    // The Agent card - the baseline - never had one. The other two stacked it
    // above their meta row AND a tag row: three rows of chrome around a name.
    expect(read(rel)).not.toContain("<CatalogItemRowHeader");
  });

  test.each(CARDS)("the %s card carries no tag row", (_k, rel) => {
    expect(read(rel)).not.toMatch(/className=\{styles\.tagRow\}/);
  });

  test("re-siting the chips dropped no information", () => {
    // Everything the chips said now reads as meta text.
    const pkg = read("components/packages/publishing/PackageCard.tsx");
    expect(pkg).toContain("pkg.templates.length");
    expect(pkg).toContain("pkg.channel");
    const data = read("components/datasets/catalog/DatasetCard.tsx");
    expect(data).toContain("DATASET_FORMAT_LABEL[dataset.format]");
    expect(data).toContain("version");
  });

  test("live state stays a badge, description does not", () => {
    // The package's update chip and the dataset's connection badge are state,
    // not description, so they keep their own treatment inside the meta row.
    expect(read("components/packages/publishing/PackageCard.tsx")).toContain("tagUpdate");
    expect(read("components/datasets/catalog/DatasetCard.tsx")).toContain(
      "DatasetConnectionBadge",
    );
  });
});

// ── The drag hint says what each kind can actually do ───────────────────────

describe("the palette hint is accurate per kind, not merely uniform", () => {
  test("only agents are described as attaching to a node", () => {
    // An agent IS a thing bound to a node's hook. A dataset or a package
    // dropped on a node does nothing - both become new nodes on the canvas -
    // so one shared sentence would have been consistent and wrong for two of
    // the three.
    expect(read("components/menus/nodes/agentsPalette/AgentsPaletteDropdown.tsx")).toContain(
      "attachesToNode",
    );
    for (const rel of [
      "components/menus/nodes/datasetPalette/DatasetsPaletteDropdown.tsx",
      "components/menus/nodes/toolsMenuPackagePalette/PackagesPaletteDropdown.tsx",
    ]) {
      expect(read(rel)).not.toContain("attachesToNode");
    }
  });

  test("both wordings live in the one component", () => {
    const hint = read("components/menus/nodes/PaletteDragHint.tsx");
    expect(hint).toContain("onto a node or the canvas to attach it");
    expect(hint).toContain("onto the canvas to add it");
  });
});

// ── Every drawer can take a thing back out ──────────────────────────────────

describe("Remove from project is in all three drawers", () => {
  const CARDS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetCard.tsx"],
    ["package", "components/packages/publishing/PackageCard.tsx"],
    ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
  ];

  test.each(CARDS)("the %s card offers it", (_k, rel) => {
    expect(read(rel)).toContain("Remove from project");
  });

  test.each(CARDS)("the %s card keeps it visible without a project", (_k, rel) => {
    // Three behaviours before this: Data and Node dropped the handler when
    // `projectId` was null and rendered no button at all, while the Agent card
    // rendered it disabled. So an item listed under "In project" in an unsaved
    // dataflow had no way back out on two of the three surfaces - and the card
    // changed shape depending on whether you had saved.
    const src = read(rel);
    expect(src).toMatch(/!hasProject/);
  });

  test("the drawers pass the handler unconditionally", () => {
    for (const rel of [
      "components/datasets/catalog/DatasetCatalogDrawer.tsx",
      "components/packages/publishing/NodeCatalogDrawer.tsx",
    ]) {
      const src = read(rel);
      expect(src).toContain("hasProject={Boolean(projectId)}");
      expect(src).not.toMatch(/onUninstall=\{projectId \?/);
    }
  });
});

// ── Each drawer renders one card, in every tab ──────────────────────────────

describe("no drawer keeps a second list component for its In-project tab", () => {
  test("the Data drawer dropped InstalledDatasetsList", () => {
    // Same split the Node drawer had: "In project" rendered a compact row list
    // with its own actions while the tab beside it rendered cards, so one
    // drawer spoke two visual languages and neither matched the Agent drawer.
    const drawer = read("components/datasets/catalog/DatasetCatalogDrawer.tsx");
    expect(drawer).not.toMatch(/import \{ InstalledDatasetsList \}/);
    expect(drawer).not.toMatch(/<InstalledDatasetsList/);
  });

  test("the card's installed state agrees with the tab that listed it", () => {
    // A bare `dataset.installed` disagreed: before the first save nothing is
    // installed, so a dataset listed under "In project" was handed a card
    // offering "Add to project". Listed as in, told it was out.
    expect(read("components/datasets/catalog/DatasetCatalogDrawer.tsx")).toContain(
      "isInThisDataflow(dataset, Boolean(projectId))",
    );
  });
});

// ── One import glyph across the drawers ─────────────────────────────────────

describe("every drawer's import wears the same icon", () => {
  test("the shared footer renders it, rather than each caller passing one", () => {
    // The Data drawer passed its own and the Node drawer passed none, so two
    // footers built from the very same component still looked different.
    const footer = read("components/packages/publishing/DrawerFooter.tsx");
    expect(footer).toContain("faFileImport");
    expect(read("components/datasets/catalog/DatasetCatalogDrawer.tsx")).not.toContain(
      "faFileImport",
    );
  });

  test("the Agent footer, which is its own element, carries it too", () => {
    expect(read("components/agents/catalog/AgentCatalogDrawer.tsx")).toContain(
      "faFileImport",
    );
  });
});

// ── Every card action explains itself ───────────────────────────────────────

describe("the drawer cards' Add and Remove both carry tooltips", () => {
  const CARDS: [string, string][] = [
    ["dataset", "components/datasets/catalog/DatasetCard.tsx"],
    ["package", "components/packages/publishing/PackageCard.tsx"],
    ["agent", "components/agents/catalog/AgentCatalogDrawer.tsx"],
  ];

  test.each(CARDS)("the %s card's Remove explains both of its states", (_k, rel) => {
    // The Agent one had no `title` at all, in either state - so the disabled
    // case in an unsaved dataflow said nothing about why it was disabled.
    const src = read(rel);
    expect(src).toContain("from this project`");
    expect(src).toContain("There is no project to remove it from yet.");
  });

  test.each(CARDS)("the %s card's Add has one too", (_k, rel) => {
    // The inverse gap: the Agent card had an Add tooltip and the other two did
    // not. Three buttons, two conventions, in both directions.
    const src = read(rel);
    expect(src).toMatch(/title=\{(`Add |installTitle\()/);
  });
});

// ── One type size for the same button ───────────────────────────────────────

describe("Remove from project looks the same in every drawer", () => {
  test("no drawer overrides the shared secondary button's type", () => {
    // The Agent drawer dropped it to 10px with the padding trimmed, so the very
    // same control was visibly smaller there than on the Data and Node cards.
    const css = read("components/agents/catalog/AgentCatalogDrawer.module.css");
    const rule = css.slice(css.indexOf("button.secondaryBtn"));
    const body = rule.slice(0, rule.indexOf("}"));
    expect(body).not.toContain("font-size");
    expect(body).not.toContain("padding");
  });

  test("the shared rule is the only one setting it", () => {
    const shared = read("components/packages/publishing/PackageCard.module.css");
    const rule = shared.slice(shared.indexOf(".btnSecondary"));
    expect(rule.slice(0, rule.indexOf("}"))).toContain("font-size");
  });
});

// ── No dashes in the copy ───────────────────────────────────────────────────

describe("user-facing catalog copy uses sentences, not dashes", () => {
  const SURFACES = [
    "components/datasets/catalog/DatasetCard.tsx",
    "components/packages/publishing/PackageCard.tsx",
    "components/agents/catalog/AgentCatalogDrawer.tsx",
    "components/datasets/catalog/DatasetCatalogDrawer.tsx",
    "components/menus/nodes/PaletteDragHint.tsx",
  ];

  test.each(SURFACES)("%s has no dash inside a quoted tooltip or label", (rel) => {
    const src = read(rel);
    // Quoted strings only: the surrounding prose comments explain the history
    // and legitimately use dashes.
    const strings = src.match(/"[^"\r\n]{8,}"/g) ?? [];
    const dashed = strings.filter(
      (str) => / - /.test(str) || /[—–]/.test(str),
    );
    expect(dashed).toEqual([]);
  });
});

// ── The four page intros say the same kind of thing ──────────────────────────

describe("the four browse pages introduce themselves the same way", () => {
  const INTROS: [string, string, string][] = [
    ["projects", "pages/projects/ProjectsList.tsx", "Your projects."],
    ["node", "pages/catalog/NodeCatalogBrowse.tsx", "Node packages in the shared catalog."],
    ["data", "pages/dataHub/DataCatalogBrowse.tsx", "Datasets in the shared catalog."],
    ["agent", "pages/agents/AgentCatalogBrowse.tsx", "Agents in the shared catalog."],
  ];

  test.each(INTROS)("the %s page opens by naming what is on it", (_k, rel, opening) => {
    expect(read(rel)).toContain(opening);
  });

  test.each(INTROS)("the %s page uses the project vocabulary, not dataflow", (_k, rel) => {
    const src = read(rel);
    const intro = src.slice(src.indexOf("pageIntro"), src.indexOf("headerTools"));
    expect(intro).not.toMatch(/dataflow/i);
  });

  test("all three catalogs claim to reach every project, and all three can", () => {
    // Data could not, and said so, until it grew the defaults list that its
    // peers already had: `datasets/defaults.py`, the eager install walk, and
    // the seed in `save_project`. The claim is only allowed here because all
    // three halves exist - a page that says "all your projects" while nothing
    // seeds new ones is simply lying to the user.
    for (const rel of [
      "pages/catalog/NodeCatalogBrowse.tsx",
      "pages/agents/AgentCatalogBrowse.tsx",
      "pages/dataHub/DataCatalogBrowse.tsx",
    ]) {
      expect(read(rel)).toContain("all your projects");
    }
  });
});
