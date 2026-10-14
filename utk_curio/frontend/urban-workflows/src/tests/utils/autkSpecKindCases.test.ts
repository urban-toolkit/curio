/**
 * The cases in utils/autkSpecKind.cases.json, run through the canvas's own
 * classifyAutkSpecString. backend/tests/test_runs/test_autk_spec_kind.py runs
 * the same file through execution/autk_spec_kind, so a run on the server sorts
 * an Autark node by the canvas's rule: a document that only loads data runs on
 * the server, one that draws is forwarded, and the rest wait for the browser.
 */
import fs from "fs";
import path from "path";

import { classifyAutkSpecString, type AutkSpecKind } from "../../utils/autkSpecKind";

interface KindCase {
  name: string;
  spec: string;
  kind: AutkSpecKind;
}

const CASES: KindCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/autkSpecKind.cases.json"), "utf8"),
).cases;

test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  expect(classifyAutkSpecString(c.spec)).toBe(c.kind);
});
