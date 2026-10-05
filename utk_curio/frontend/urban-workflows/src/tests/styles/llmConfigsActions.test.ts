import fs from "fs";
import path from "path";

/**
 * The API Settings body does not scroll sideways (#510).
 *
 * The LLM configurations table is `width: 100%`, but a nowrap Actions cell
 * kept "Edit Duplicate Remove" on one line, so the table was about 451 px wide
 * in a 409 px body. Source-read, as in planEdgeNames.test.ts: jest maps CSS
 * modules to `identity-obj-proxy`, and jsdom has no table layout to measure.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/llmConfigs/LlmConfigs.module.css"),
  "utf8",
);

test("the Actions cell may wrap", () => {
  expect(CSS).not.toMatch(/\n\.actions \{[^}]*white-space:\s*nowrap/);
});

test("each action keeps its label on one line", () => {
  expect(CSS).toMatch(/\n\.actions > \.actionBtn \{[^}]*white-space:\s*nowrap;/);
});
