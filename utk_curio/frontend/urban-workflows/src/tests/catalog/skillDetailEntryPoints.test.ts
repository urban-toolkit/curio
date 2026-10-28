import fs from "fs";
import path from "path";

/**
 * A skill's two ways into its details, as an agent's are
 * (agentDetailEntryPoints.test.ts): the card click drives the side drawer,
 * "View details" opens a modal, and neither leaves the page.
 *
 * Read from disk, as that suite is: the claims are about what the page does
 * not do.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const BROWSE = "pages/agents/AgentCatalogBrowse.tsx";
const CARD = "pages/agents/SkillCatalogBrowseCard.tsx";
const DRAWER = "pages/agents/SkillCatalogBrowseDrawer.tsx";

describe("skill detail entry points", () => {
  it("uses the shared wording, with no arrow, on the card and in the drawer", () => {
    for (const file of [CARD, DRAWER]) {
      expect(read(file)).toContain("View details");
      expect(read(file)).not.toContain("View details ↗");
    }
  });

  it("routes the card and its View details to two different surfaces", () => {
    const browse = read(BROWSE);
    expect(browse).toContain("onSelect={() => skillBrowse.setSelectedName(skill.name)}");
    expect(browse).toContain("onViewDetails={() => setDetailSkillName(skill.name)}");
    expect(browse).not.toContain("onViewDetails={() => skillBrowse.setSelectedName(skill.name)}");
  });

  it("opens details as a modal, not a route", () => {
    const browse = read(BROWSE);
    expect(browse).toContain("<SkillDetailModal");
    expect(browse).not.toContain("useNavigate");
    expect(browse).not.toContain("/catalog/agents/");
    expect(browse).not.toContain("/catalog/skills");
    expect(read("components/agents/catalog/SkillDetailModal.tsx")).toContain("<ModalShell");
  });
});
