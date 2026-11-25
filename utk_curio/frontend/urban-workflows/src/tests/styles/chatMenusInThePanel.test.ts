import fs from "fs";
import path from "path";

/**
 * The chat's menus as their stylesheets draw them.
 *
 * - A rail group's list is never taller than the panel, less a margin above
 *   and below; the rail places it inside the panel (AgentChatPanel.test.tsx,
 *   "keeps a group's list inside the panel").
 * - More's Tokens used pulses while a running reply can still add to it, as
 *   the counter beside the composer did, and holds still for reduced motion.
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot see which rules apply.
 */
const ATTACH = path.resolve(__dirname, "../../components/agents/attach");
const RAIL = fs.readFileSync(path.join(ATTACH, "chat/AgentRail.module.css"), "utf8");
const PANEL = fs.readFileSync(path.join(ATTACH, "AgentChatPanel.module.css"), "utf8");

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("a rail group's list", () => {
  test("is at most the panel's height, less a margin above and below", () => {
    expect(ruleBody(RAIL, ".flyout")).toMatch(/max-height:\s*min\(320px,\s*calc\(100% - 16px\)\);/);
    expect(ruleBody(RAIL, ".flyout")).toMatch(/overflow-y:\s*auto;/);
  });
});

describe("More's Tokens used", () => {
  test("pulses while live", () => {
    const live = ruleBody(PANEL, ".menuTokensLive");
    expect(live).toMatch(/animation:\s*chatTokensPulse\s/);
    expect(PANEL).toMatch(/@keyframes chatTokensPulse\s*\{/);
  });

  test("holds still for reduced motion", () => {
    expect(PANEL).toMatch(
      /@media \(prefers-reduced-motion: reduce\) \{\s*\.menuTokensLive \{\s*animation: none;\s*\}\s*\}/,
    );
  });
});
