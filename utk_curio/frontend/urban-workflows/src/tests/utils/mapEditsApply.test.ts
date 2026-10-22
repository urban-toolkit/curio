/**
 * The Map Edits node's edit log applied in the browser, the one way it is
 * applied there: `applyFeatureEdits` (utils/editFeatures/applyEdits), which
 * the map the node feeds draws before Commit edits (`mapEditsPreview`), the
 * node's tools read (`layerModel.editedFeatures`) and its table and condition
 * count read (`applyEdits`). Every case of `editFeaturesApply.cases.json` goes
 * through it, and each must hand on the layer a run hands on:
 * `utk_curio/sandbox/tests/test_feature_edits_cases.py` runs the same cases
 * through `curio_edit_features`, so `expected` is the run's.
 */
import shared from "../../utils/editFeatures/editFeaturesApply.cases.json";
import { applyEdits, editedCollection } from "../../utils/editFeatures/applyEdits";
import { normalizeEditFeatures, type FeatureEdit } from "../../utils/editFeatures/editFeatures";
import { editedFeatures } from "../../utils/editFeatures/layerModel";

type Feature = { type: "Feature"; geometry: unknown; properties: Record<string, unknown> };
type Layer = { type: "FeatureCollection"; features: Feature[] };
type ApplyCase = { name: string; layer: string; key: string; edits: unknown[]; expected: Layer };

const layers = shared.layers as unknown as Record<string, Layer>;
const cases = shared.cases as unknown as ApplyCase[];

/** A case's edits as the node keeps them; every entry of a case is one it keeps. */
function editsOf(c: ApplyCase): FeatureEdit[] {
  const edits = normalizeEditFeatures({ key: c.key, edits: c.edits })?.edits ?? [];
  expect(edits).toHaveLength(c.edits.length);
  return edits;
}

describe("the browser applies the log as a run hands it on (applyFeatureEdits)", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const before = JSON.stringify(layers[c.layer]);
    expect(editedCollection(layers[c.layer], editsOf(c), c.key)).toEqual(c.expected);
    // The input is never changed.
    expect(JSON.stringify(layers[c.layer])).toBe(before);
  });
});

describe("what the node reads the log through hands on the same", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    // The node's tools: the features, shapes included, of the node's own layer.
    const drawn = editedFeatures(layers[c.layer], editsOf(c), c.key, null, null);
    expect({
      type: "FeatureCollection",
      features: drawn.map((feature) => ({ type: "Feature", geometry: feature.geometry, properties: feature.properties })),
    }).toEqual(c.expected);
    // The node's table: the features' properties.
    const rows = layers[c.layer].features.map((feature) => feature.properties);
    const { state } = applyEdits(rows, editsOf(c), c.key);
    expect(state.filter((row) => row !== null)).toEqual(c.expected.features.map((feature) => feature.properties));
  });
});
