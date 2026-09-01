import fs from "fs";
import path from "path";

/**
 * The two ways into an agent's details, and the one that is forbidden.
 *
 * The Data Catalog learned this the hard way: it once offered a card's
 * "View details ↗" that NAVIGATED alongside a drawer button that opened a
 * modal, so one screen had two names, two containers, and an arrow promising a
 * navigation the other path did not make. The conclusion was not "one entry
 * point" - it was "one screen per surface, and no navigation".
 *
 * `/catalog/agents` reads that way now: the card click drives the side drawer,
 * "View details" opens a modal, and neither leaves the page. Routing both to
 * the SAME setter (which this file used to assert) made the button a no-op -
 * the drawer is already open on the first card when the page loads, so there
 * was nothing left for it to change, and below 1100px the drawer column is
 * `display: none` and the click did nothing on any card at all (issue 189).
 *
 * Read from disk rather than rendered: the load-bearing claims are about what
 * the page does *not* do, and a component test can only show what a rendered
 * tree does. Same approach as datasetDetailEntryPoints.test.ts.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const BROWSE = "pages/agents/AgentCatalogBrowse.tsx";
const CARD = "pages/agents/AgentCatalogBrowseCard.tsx";
const DRAWER = "pages/agents/AgentCatalogBrowseDrawer.tsx";

describe("agent detail entry points", () => {
  it("uses the shared wording, with no arrow", () => {
    expect(read(CARD)).toContain("View details");
    // The arrow said "this leaves the page", which it does not.
    expect(read(CARD)).not.toContain("View details ↗");
  });

  it("does not navigate away from the browse page", () => {
    const browse = read(BROWSE);
    expect(browse).not.toContain("useNavigate");
    expect(browse).not.toContain("/catalog/agents/");
  });

  it("routes the card and its View details to two different surfaces", () => {
    // The card click drives the side drawer; View details opens the modal. They
    // must not share a setter: the drawer is already open on the first card
    // when the page loads, so a View details wired to `setSelectedCoord` has
    // nothing to change and reads as a dead control.
    const browse = read(BROWSE);
    expect(browse).toContain("onSelect={() => setSelectedCoord(agent.dirName)}");
    expect(browse).toContain("onViewDetails={() => setDetailCoord(agent.dirName)}");
    expect(browse).not.toContain("onViewDetails={() => setSelectedCoord(agent.dirName)}");
  });

  it("opens details as a modal, not a route", () => {
    // The modal is what makes the control work below 1100px, where
    // CatalogBrowseLayout hides the drawer column outright.
    const browse = read(BROWSE);
    expect(browse).toContain("AgentDetailModal");
    expect(read("components/agents/catalog/AgentDetailModal.tsx")).toContain("ModalShell");
  });
});

describe("the agent browse page reports only what it can know", () => {
  it("asks for no project when listing", () => {
    // Account scope: the page has no open dataflow, so requesting
    // `installedInProject` would mark rows against whichever one happened to
    // be open last.
    const hook = read("pages/agents/useAgentCatalogBrowse.ts");
    expect(hook).toContain("agentsApi.catalog()");
    expect(hook).not.toMatch(/agentsApi\.catalog\([^)]+\)/);
  });

  it("shows requirement resolvability, not per-project install state", () => {
    const drawer = read(DRAWER);
    expect(drawer).toContain("req.visible");
    // The field, not the word: the comment above the list explains why it is
    // deliberately unread, so a bare substring match would hit that instead.
    expect(drawer).not.toMatch(/\breq\.installedInProject\b/);
  });

  it("claims no freshness it cannot measure", () => {
    // An agent card carries no timestamp. `fresh` drives a green/grey dot, and
    // a green one here would be inventing recency.
    expect(read(DRAWER)).toContain("fresh={false}");
  });
});

describe("the account-scope CTA says what the click does", () => {
  it("uses one all-projects wording, shared with the Node Catalog", () => {
    // This deliberately read "Add to my account" while the Node Catalog page
    // read "Add to all projects", because the two writes are not identical: a
    // node install really does reach every project, whereas an agent import
    // makes the agent AVAILABLE to every project - it is not attached to any
    // one of them until you add it there.
    //
    // One vocabulary across the three catalogs was judged worth more than that
    // distinction, so both now read "Add to all projects"; the page intro
    // carries the nuance ("makes it available to all your projects") instead of
    // the button. The drawer's per-row button separately said a bare "Import"
    // for this same call, which made three names for one operation - and put
    // an unrelated "Import agent" (upload your own definition) in the same
    // panel.
    const drawer = read(DRAWER);
    expect(drawer).toContain("Add to all projects");
    expect(drawer).toContain("Remove from all projects");
    // The retired names. None of them may come back.
    expect(drawer).not.toContain("Add to my account");
    expect(drawer).not.toContain("Remove from my account");
    expect(drawer).not.toContain("Add to dataflow");
  });

  it("never says Install, anywhere on an agent surface", () => {
    // The word the catalogs retired: it described neither scope.
    //
    // This case used to read only the three browse-page files, which is
    // exactly why `agentListUtils.installLabel` kept rendering an "Install"
    // button through the entire terminology pass - the e2e caught it, this
    // suite did not. It now walks every agent component. Comment lines are
    // skipped so the explanation of why the word is banned may still name it.
    const dirs = [
      "components/agents",
      "pages/agents",
      "components/menus/nodes/agentsPalette",
    ];
    const files: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (/\.tsx?$/.test(entry.name)) files.push(full);
      }
    };
    for (const d of dirs) walk(path.join(SRC, d));
    // A guard on the guard: a moved directory would pass vacuously.
    expect(files.length).toBeGreaterThan(20);

    const commentLine = /^\s*(\/\*|\*|\/\/)/;
    const bareInstall = /["'>]\s*Install(ing)?\s*[…"'<]/;
    const offenders: string[] = [];
    for (const file of files) {
      for (const line of fs.readFileSync(file, "utf8").split("\n")) {
        if (commentLine.test(line)) continue;
        if (bareInstall.test(line)) {
          offenders.push(`${path.relative(SRC, file)}: ${line.trim()}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });
});
