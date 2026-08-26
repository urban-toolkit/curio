import fs from "fs";
import path from "path";

/**
 * One way into an agent's details, from one page.
 *
 * The Data Catalog learned this the hard way: it once offered two routes to the
 * same screen, a card's "View details ↗" that navigated and a drawer button
 * that opened a modal, so one screen had two names, two containers and an arrow
 * promising a navigation the other path did not make.
 *
 * `/catalog/agents` is built to that conclusion rather than rediscovering it -
 * the card and the drawer share one selection, the page never navigates, and
 * the label is the same word the other two catalogs use. Asserted here so a
 * later "quick link to a detail page" cannot quietly reintroduce the split.
 *
 * Read from disk rather than rendered: these are claims about what the page
 * does *not* do, and a component test can only show what a rendered tree does.
 * Same approach as datasetDetailEntryPoints.test.ts.
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

  it("routes the card and its View details to one selection", () => {
    // Both set the selected coordinate; neither opens a second surface. If a
    // detail route is ever added, it should stay a deep link the UI does not
    // walk you into - the way /catalog/data/:datasetId does.
    const browse = read(BROWSE);
    expect(browse).toContain("onSelect={() => setSelectedCoord(agent.dirName)}");
    expect(browse).toContain("onViewDetails={() => setSelectedCoord(agent.dirName)}");
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
    expect(drawer).not.toMatch(/req\.installedInProject/);
  });

  it("claims no freshness it cannot measure", () => {
    // An agent card carries no timestamp. `fresh` drives a green/grey dot, and
    // a green one here would be inventing recency.
    expect(read(DRAWER)).toContain("fresh={false}");
  });
});

describe("the account-scope CTA says what the click does", () => {
  it("adds to the account, not to every project", () => {
    // The Node Catalog page says "Add to all projects" because installing
    // there really does reach every project. An agent import does not - it
    // makes the agent available to install - so borrowing that label would
    // overstate it.
    const drawer = read(DRAWER);
    expect(drawer).toContain("Add to my account");
    expect(drawer).toContain("Remove from my account");
    expect(drawer).not.toContain("Add to all projects");
    expect(drawer).not.toContain("Add to dataflow");
  });

  it("never says Install", () => {
    // The word the catalogs retired: it described neither scope.
    for (const file of [BROWSE, CARD, DRAWER]) {
      expect(read(file)).not.toMatch(/>\s*Install\s*</);
    }
  });
});
