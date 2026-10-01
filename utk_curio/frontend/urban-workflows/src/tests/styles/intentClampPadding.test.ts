import fs from "fs";
import path from "path";

/**
 * The collapsed instruction bubble shows four lines and nothing of a fifth (#502).
 *
 * `.intentClamped` clamps the bubble to four lines with `overflow: hidden`,
 * and `.msgUser` gives the same element `padding: 8px 12px`. Overflow is
 * clipped at the padding box, so the fifth line drew through the bottom
 * padding, cut through its letters. The clamped bubble moves its vertical
 * padding into a transparent border, which sits outside the clip.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/AgentChatPanel.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

describe("clamped instruction bubble", () => {
  test("the clamp still clips", () => {
    expect(ruleBody(".intentClamped")).toMatch(/overflow:\s*hidden;/);
  });

  test("its vertical padding is a border, outside the clipped box", () => {
    const body = ruleBody(".msgUser.intentClamped");
    expect(body).not.toBeNull();
    expect(body).toMatch(/padding-top:\s*0;/);
    expect(body).toMatch(/padding-bottom:\s*0;/);
    expect(body).toMatch(/border-top:\s*8px solid transparent;/);
    expect(body).toMatch(/border-bottom:\s*8px solid transparent;/);
  });
});
