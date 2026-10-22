/**
 * The Interaction node's edit log applied in the browser, both ways it is
 * applied there: `applyEdits`, which the node's table and its condition count
 * read, and `layerModel.editedFeatures`, which the linked map draws before
 * Commit edits (`mapLayerEdits.editSources`) and the node's tools read. Every
 * case of `editFeaturesApply.cases.json` goes through both, and each must hand
 * on the layer a run hands on: `utk_curio/sandbox/tests/test_feature_edits_cases.py`
 * runs the same cases through `curio_edit_features`, so `expected` is the run's.
 */
import shared from "../../utils/editFeatures/editFeaturesApply.cases.json";
import { applyEdits } from "../../utils/editFeatures/applyEdits";
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

describe("the node's table (applyEdits) hands on what a run hands on", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    const rows = layers[c.layer].features.map((feature) => feature.properties);
    const { state } = applyEdits(rows, editsOf(c), c.key);
    // The table reads the features' properties; their shapes are the map's.
    expect(state.filter((row) => row !== null)).toEqual(c.expected.features.map((feature) => feature.properties));
  });
});

describe("the map before Commit edits (layerModel.editedFeatures) draws what a run hands on", () => {
  test.each(cases.map((c) => [c.name, c] as const))("%s", (_name, c) => {
    // The node's own layer: no edit names another.
    const drawn = editedFeatures(layers[c.layer], editsOf(c), c.key, null, null);
    expect({
      type: "FeatureCollection",
      features: drawn.map((feature) => ({ type: "Feature", geometry: feature.geometry, properties: feature.properties })),
    }).toEqual(c.expected);
  });
});
