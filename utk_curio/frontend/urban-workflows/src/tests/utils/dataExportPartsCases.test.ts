/**
 * The cases in utils/dataExportParts.cases.json, run through the canvas's own
 * exportParts, which labels the parts of a Data Export node's input for its
 * Part dropdown. backend/tests/test_datasets/test_data_export_parts_cases.py
 * runs the same file through the sandbox's bundle_zip.parts_of, which names
 * the zip's files, so the dropdown and the zip never disagree. And the value a
 * pick writes names that one part, as curio_export finds it.
 */
import fs from "fs";
import path from "path";

import { exportParts, kindLabel, partNamed, partValue } from "../../utils/dataExportParts";

interface PartsCase {
  name: string;
  envelope: unknown;
  labels: string[] | null;
}

const CASES: PartsCase[] = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../utils/dataExportParts.cases.json"), "utf8"),
).cases;

test.each(CASES.map((c) => [c.name, c] as const))("%s", (_name, c) => {
  const parts = exportParts(c.envelope);
  expect(parts === null ? null : parts.map((part) => part.label)).toEqual(c.labels);
  if (parts) expect(parts.map((part) => part.index)).toEqual(parts.map((_part, index) => index));
});

test("a part's kind and place name it as the zip does", () => {
  expect(kindLabel(0, "dataframe")).toBe("Table · part 1");
  expect(kindLabel(2, "geodataframe")).toBe("Geo table · part 3");
  expect(kindLabel(1, "outputs")).toBe("Outputs · part 2");
});

test("a pick writes a part's label when no other part has it, else its position, and finds it again", () => {
  const caseNamed = (name: string) => CASES.find((c) => c.name.startsWith(name))!;
  const chicago = exportParts(caseNamed("the Chicago Loop Layers").envelope)!;
  expect(partValue(chicago, chicago[2])).toBe("Trees (OpenStreetMap)");
  expect(partNamed(chicago, "Trees (OpenStreetMap)")).toBe(chicago[2]);

  const twice = exportParts(caseNamed("two tables that carry one label").envelope)!;
  expect(twice.map((part) => partValue(twice, part))).toEqual(["0", "1"]);
  expect(partNamed(twice, "1")).toBe(twice[1]);

  // A dict's part is found by its key too, and empty names no one part.
  const keyed = exportParts(caseNamed("a dict").envelope)!;
  expect(partNamed(keyed, "roads")).toBe(keyed[0]);
  expect(partNamed(keyed, "")).toBeNull();
  expect(partNamed(keyed, "Bridges")).toBeNull();
  expect(partNamed(keyed, "3")).toBeNull();
});
