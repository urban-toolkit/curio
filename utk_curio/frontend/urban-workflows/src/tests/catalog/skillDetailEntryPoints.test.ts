import fs from "fs";
import path from "path";

/**
 * A skill's two ways into its details, as an agent's are
 * (agentDetailEntryPoints.test.ts): the card click drives the side drawer,
 * "View details" opens a modal, and neither leaves the page.
 *
 * Read from disk, as that suite is: the claims are about what the page does
 * not do. The skills have their own page, the Skill Catalog's, and the Agent
 * Catalog page holds none of their surfaces.
 */

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const BROWSE = "pages/skills/SkillCatalogBrowse.tsx";
const CARD = "pages/skills/SkillCatalogBrowseCard.tsx";
const DRAWER = "pages/skills/SkillCatalogBrowseDrawer.tsx";
const AGENT_BROWSE = "pages/agents/AgentCatalogBrowse.tsx";

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
    expect(read("components/skills/catalog/SkillDetailModal.tsx")).toContain("<ModalShell");
    // The page's one route takes no skill's name.
    expect(read("index.tsx")).toContain('<Route path="skills" element={<SkillCatalogBrowse />} />');
    expect(read("index.tsx")).not.toMatch(/path="skills\//);
  });

  it("leaves the Agent Catalog page no skill card, drawer or modal", () => {
    const agents = read(AGENT_BROWSE);
    for (const name of [
      "SkillCatalogBrowseCard",
      "SkillCatalogBrowseDrawer",
      "SkillDetailModal",
      "SkillImportModal",
      "showSkills",
    ]) {
      expect(agents).not.toContain(name);
    }
  });
});
