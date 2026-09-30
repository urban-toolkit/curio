import fs from "fs";
import path from "path";

/**
 * A plan review connection row shows its whole name pair (#511).
 *
 * `.planEdgeNames` was one line with an ellipsis, so the target and the
 * `[handle]` suffix were cut off beside the Connect button, and rows to
 * different targets read the same.
 *
 * Source-read, as in bundlePreviewScroll.test.ts: jest maps CSS modules to
 * `identity-obj-proxy`, so a rendered assertion cannot see which rules apply.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/content/AgentReviewCard.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

test("the names wrap instead of being cut off", () => {
  const body = ruleBody(".planEdgeNames") ?? "";
  expect(body).toMatch(/white-space:\s*normal;/);
  expect(body).toMatch(/overflow-wrap:\s*anywhere;/);
  expect(body).toMatch(/min-width:\s*0;/);
  expect(body).not.toMatch(/text-overflow:\s*ellipsis/);
});
