import fs from "fs";
import path from "path";

/**
 * Badges sit on their row's centre line (#495, #520).
 *
 * Source-read, as in planEdgeNames.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const css = (rel: string) =>
  fs.readFileSync(path.resolve(__dirname, "../../components/packages", rel), "utf8");

function ruleBody(source: string, selector: string): string | null {
  const at = source.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = source.indexOf("{", at);
  return source.slice(open + 1, source.indexOf("}", open));
}

test("the agent card's version chip is centred, not stretched (#495)", () => {
  const card = css("publishing/PackageCard.module.css");
  expect(ruleBody(card, ".versionBadge")).toMatch(/align-self:\s*center;/);
});

describe("the Node settings heading row (#520)", () => {
  const modal = css("editing/NodeTemplateConfigModal.module.css");

  it("has no margin on the heading to push or lift the badge", () => {
    expect(ruleBody(modal, ".title")).toMatch(/margin:\s*0;/);
  });

  it("keeps the close button's room and the space below on the row", () => {
    const row = ruleBody(modal, ".titleRow") ?? "";
    expect(row).toMatch(/padding-right:\s*32px;/);
    expect(row).toMatch(/margin-bottom:\s*6px;/);
    expect(row).toMatch(/align-items:\s*center;/);
  });
});
