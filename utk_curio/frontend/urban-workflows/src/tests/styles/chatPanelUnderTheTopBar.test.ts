import fs from "fs";
import path from "path";

/**
 * The agent chat opens under the top bar, as Define scenario does, instead of
 * covering the bar's right end from the window's top.
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot see which declarations a class carries.
 */
const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");
const PANEL_CSS = read("components/agents/attach/AgentChatPanel.module.css");

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("the agent chat panel's place", () => {
  it("starts where the top bar ends: both are the one token's height", () => {
    const panel = ruleBody(PANEL_CSS, ".panel") ?? "";
    expect(panel).toMatch(/\n\s*position:\s*fixed;/);
    expect(panel).toMatch(/\n\s*top:\s*var\(--curio-top-bar-height\);/);
    expect(panel).toMatch(/\n\s*right:\s*0;/);
    expect(panel).toMatch(/\n\s*bottom:\s*0;/);
    expect(ruleBody(read("components/layout/GlobalPageHeader.module.css"), ".header")).toMatch(
      /\n\s*height:\s*var\(--curio-top-bar-height\);/,
    );
    expect(read("styles/curioTokens.css")).toMatch(/--curio-top-bar-height:\s*\d+px;/);
  });

  it("puts the agents rail beside the chat's column", () => {
    expect(ruleBody(PANEL_CSS, ".panel")).toMatch(/\n\s*flex-direction:\s*row;/);
    const column = ruleBody(PANEL_CSS, ".column") ?? "";
    expect(column).toMatch(/\n\s*flex:\s*1;/);
    expect(column).toContain("min-width: 0;");
    expect(column).toMatch(/\n\s*flex-direction:\s*column;/);
  });

  it("draws Jump to latest in a row of its own above the composer, never over a message", () => {
    const jump = ruleBody(read("components/agents/attach/TranscriptJumpButton.module.css"), ".jump") ?? "";
    expect(jump).not.toMatch(/position:\s*absolute/);
    expect(ruleBody(PANEL_CSS, ".jumpRow")).toMatch(/\n\s*flex:\s*none;/);
  });

  it("gives its header one row, with no extra top padding to line it up with the bar", () => {
    const header = ruleBody(PANEL_CSS, ".header") ?? "";
    expect(header).toMatch(/\n\s*align-items:\s*center;/);
    expect(header).not.toMatch(/flex-direction:\s*column;/);
    const padding = /\n\s*padding:\s*([^;]+);/.exec(header)?.[1].trim().split(/\s+/) ?? [];
    expect(padding.length).toBeGreaterThan(0);
    // Its top padding is its bottom padding.
    expect(padding[0]).toBe(padding.length >= 3 ? padding[2] : padding[0]);
  });
});
