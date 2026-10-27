/**
 * The built-in Data Loading node, as its shipped manifest declares it: a Data
 * widget where a file or a Data Catalog dataset is dropped, which the node opens
 * on (opensOnWidgets), and a starter whose code loads what the widget holds.
 */
import fs from "fs";
import path from "path";

import { shippedManifest } from "../_support/categoryDescriptors";
import { datasetWidgetReadBy, firstDatasetWidget } from "../../utils/widgets/datasetWidgets";
import { normalizeWidgets } from "../../utils/widgets/widgetModel";
import { resolveReferences } from "../../utils/references/codeReferences";

const BUILTIN = path.resolve(__dirname, "../../../../../../packages/curio.builtin@1");

function dataLoading(): Record<string, any> {
  const manifest = shippedManifest("curio.builtin@1") as unknown as { templates: Array<Record<string, any>> };
  const template = manifest.templates.find((t) => t.id === "data-loading");
  if (!template) throw new Error("curio.builtin@1 has no data-loading template");
  return template;
}

test("its Data widget is a dataset widget, which the node opens on", () => {
  const template = dataLoading();
  expect(template.opensOnWidgets).toBe(true);
  expect(template.hasWidgets).toBe(true);
  expect(normalizeWidgets(template.widgets)).toEqual([
    { name: "data", type: "dataset", label: "Data", default: "" },
  ]);
});

test("its starter loads what the Data widget holds", () => {
  const template = dataLoading();
  const starter = fs.readFileSync(path.join(BUILTIN, template.source), "utf8");
  expect(datasetWidgetReadBy(template.widgets, starter)?.name).toBe("data");

  const held = normalizeWidgets(template.widgets).map((w) => ({ ...w, value: "data.utk.trees" }));
  const { code, problems } = resolveReferences(starter, { widgets: held, inputs: [] }, "python");
  expect(problems).toEqual([]);
  expect(code).toBe('data = curio_load_data("data.utk.trees")\nreturn data\n');
});

test("its integrity file names the starter", () => {
  const integrity = JSON.parse(fs.readFileSync(path.join(BUILTIN, "integrity.json"), "utf8"));
  expect(Object.keys(integrity.sha256)).toContain(dataLoading().source);
  expect(firstDatasetWidget(dataLoading().widgets)?.name).toBe("data");
});
