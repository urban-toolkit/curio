/**
 * Choosing a starter Autark document from the shape of the incoming data.
 *
 * The Autark counterpart of `vegaDefaultSpec.ts`, offered the same way
 * (hook/useStarterSpec): a node with no input stays empty, and once an input
 * arrives, while the editor is still empty, it fills with a complete, readable
 * document chosen from the input's layers and their column roles
 * (utils/starterSpec). Explicit and complete: every field the document relies
 * on is written out, so it reads as a lesson in the grammar rather than a
 * minimal one that works by magic.
 *
 * A layer is only offered when it has geometry to draw: an Autark map cannot
 * draw a table without it, so an input with none leaves the editor empty and
 * the node's body says why.
 *
 * Pure, with no autk import, so it is testable under jest.
 */
import { AUTK_STARTER_LADDER, type AutkStarterRuleId } from "../generated/visDefaults";
import { autkTableName } from "./autkInput";
import { resolveGeometryField } from "./geometryField";
import type { GrammarFrame, GrammarInput } from "./grammarInput";
import { toRows } from "./rowSource";
import {
  classifyColumns,
  groupColumns,
  inRange,
  meetsRoles,
  type ColumnRole,
} from "./starterSpec";

/** A drawable layer of the input, as the ladder sees it. */
export type StarterLayer = {
  /** The table the document names it by. */
  name: string;
  /** Its columns, grouped by role. */
  columns: Record<ColumnRole, string[]>;
};

export interface AutkStarterRule {
  /** Stable id, asserted in tests and named in docs/USAGE.md. */
  id: string;
  when: (layers: StarterLayer[]) => boolean;
  build: (layers: StarterLayer[]) => Record<string, unknown>;
}

/**
 * Each rule's document past its family key, by rule id. The rule itself (its
 * place in the ladder, the layers and columns it needs and the family it
 * writes) is generated into `AUTK_STARTER_LADDER`, which the agents' shared
 * preamble states too.
 */
export const AUTK_STARTER_BUILDERS: Record<
  AutkStarterRuleId,
  (layers: StarterLayer[]) => Record<string, unknown>
> = {
  layers: (layers) => ({ layerRefs: layers.map((layer) => ({ dataRef: layer.name })) }),
  "geometry+quantitative": ([layer]) => ({
    layerRefs: [{
      dataRef: layer.name,
      getFnv: layer.columns.quantitative[0],
      getFnvType: "quantitative",
      colorMapInterpolator: "interpolateViridis",
    }],
  }),
  "geometry+nominal": ([layer]) => ({
    layerRefs: [{
      dataRef: layer.name,
      getFnv: layer.columns.nominal[0],
      getFnvType: "categorical",
      colorMapInterpolator: "schemeTableau10",
    }],
  }),
  geometry: ([layer]) => ({ layerRefs: [{ dataRef: layer.name }] }),
};

/**
 * The ladder: first match wins, in the generated order. A rule holds when the
 * input has as many layers as it needs and every layer has the columns it
 * needs. The prose counterpart is the table in `docs/USAGE.md`; adding or
 * reordering a rule trips `autkDefaultSpec.test.ts`.
 */
export const AUTK_STARTER_RULES: AutkStarterRule[] = AUTK_STARTER_LADDER.map(
  (rule): AutkStarterRule => ({
    id: rule.id,
    when: (layers) =>
      inRange(layers.length, rule.layers) &&
      layers.every((layer) => meetsRoles(layer.columns, rule.columns)),
    build: (layers) => ({ [rule.produces]: AUTK_STARTER_BUILDERS[rule.id](layers) }),
  }),
);

/** The document for these layers, or `null` when there is nothing to draw. */
export function chooseAutkStarter(layers: StarterLayer[]): Record<string, unknown> | null {
  const rule = AUTK_STARTER_RULES.find((r) => r.when(layers));
  return rule ? rule.build(layers) : null;
}

/** A frame as a drawable layer, or `null` when it has no geometry or no rows. */
export function starterLayer(frame: GrammarFrame): StarterLayer | null {
  const name = autkTableName(frame);
  if (frame.dataType === "geodataframe") {
    const features: any[] = frame.payload?.features ?? [];
    if (!features.some((f) => f?.geometry != null)) return null;
    const rows = features.map((f) => f?.properties ?? {});
    return { name, columns: groupColumns(classifyColumns(frame.schema, rows, frame.geometryName)) };
  }
  // A DataFrame: its geometry column, found by value as the input path finds it.
  const rows = toRows({ data: frame.payload });
  const field = resolveGeometryField(rows, null).field;
  if (!field || rows.length === 0) return null;
  return { name, columns: groupColumns(classifyColumns(frame.schema, rows, field)) };
}

/** The chosen document as the JSON text the editor should hold, or null. */
export function autkStarterText(read: GrammarInput): string | null {
  const layers = read.frames.map(starterLayer).filter((layer): layer is StarterLayer => layer != null);
  const doc = chooseAutkStarter(layers);
  return doc ? JSON.stringify(doc, null, 2) : null;
}
