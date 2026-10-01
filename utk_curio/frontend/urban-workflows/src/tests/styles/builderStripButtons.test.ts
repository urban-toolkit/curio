import fs from "fs";
import path from "path";

/**
 * The builder strip's buttons keep their labels on one line (#505).
 *
 * `.actions` was a flex row with no wrapping and the buttons could shrink, so a
 * full row squeezed "Solve this node" and "Build & validate plan" down to
 * their longest word and broke the labels over two or three lines.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/AgentBuilderStrip.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

describe("builder strip button rows", () => {
  test("a full row wraps its buttons to a new line", () => {
    expect(ruleBody(".actions")).toMatch(/flex-wrap:\s*wrap;/);
  });

  test("a button neither shrinks nor wraps its label", () => {
    const body = ruleBody(".solve,\n.run");
    expect(body).toMatch(/white-space:\s*nowrap;/);
    expect(body).toMatch(/flex-shrink:\s*0;/);
  });

  test("a hint beside a button is what wraps", () => {
    const body = ruleBody(".actions > .hint");
    expect(body).toMatch(/flex:\s*1 1 0;/);
    expect(body).toMatch(/min-width:\s*0;/);
  });
});
