/**
 * The Raster Calculator starts with a call to Curio's raster algebra that
 * lists its operations, statistics among them, and keeps the code a saved
 * dataflow carries. Statistics are one of its operations, not a node of their
 * own. The node is SCOUT Rasters' (`scout.rasters@1`), and its template names
 * this behavior, so a package node drops with the same code.
 */
// The built-in behaviors pull in vega and vega-lite, whose ESM Jest's default
// transform skips; this suite never compiles a chart.
jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });

import * as fs from "fs";
import * as path from "path";
// The module the registry loads the icon from: curio.builtin@1 does not name it,
// so Curio does not bundle it.
import { faCalculator } from "@fortawesome/free-solid-svg-icons/faCalculator";
import * as rasterNodeBehaviors from "../../../adapters/node/rasterNodeBehaviors";
import * as rasterNodeCode from "../../../utils/raster/rasterNodeCode";
import { useRasterCalculatorBehavior } from "../../../adapters/node/rasterNodeBehaviors";
import { RASTER_CALCULATOR_CODE } from "../../../utils/raster/rasterNodeCode";
import { getBehavior } from "../../../registry/behaviorRegistry";
import "../../../registry/builtinBehaviors";
import { loadIconRefs } from "../../../registry/iconRegistry";
import { BUILTIN_PACKAGE_ID, registerPackageTemplates } from "../../../registry/packagesClient";
import { clearPackageNodes } from "../../../registry/nodeRegistry";

const fresh = { nodeId: "n1" } as never;
const saved = { nodeId: "n1", defaultCode: "return curio_raster_calculate(\"add\", [input_0, input_1])" } as never;
const state = {} as never;

const REPO_ROOT = path.resolve(__dirname, "../../../../../../..");

describe("raster node behaviors", () => {
  it("a dropped Raster Calculator starts with its call", () => {
    expect(useRasterCalculatorBehavior(fresh, state)).toEqual({ defaultValueOverride: RASTER_CALCULATOR_CODE });
    expect(RASTER_CALCULATOR_CODE.endsWith('\nreturn curio_raster_calculate("subtract", [input_0, input_1])\n')).toBe(true);
  });

  it("lists statistics among its operations, with a condition and a mask explained", () => {
    expect(RASTER_CALCULATOR_CODE).toContain("\n#   return curio_raster_statistics(input_0, mask=input_1)\n");
    expect(RASTER_CALCULATOR_CODE).toContain("as a table of one row");
    expect(RASTER_CALCULATOR_CODE).toContain("where=lambda value: value < 1.08");
    expect(RASTER_CALCULATOR_CODE).toContain("mask_values=[0]");
  });

  it("keeps the code a dataflow carries", () => {
    expect(useRasterCalculatorBehavior(saved, state)).toEqual({});
  });

  it("is the one raster node: statistics have no behavior or code of their own", () => {
    expect(getBehavior("raster-calculator")).toBe(useRasterCalculatorBehavior);
    expect(getBehavior("raster-statistics")).toBeUndefined();
    expect(rasterNodeBehaviors).not.toHaveProperty("useRasterStatisticsBehavior");
    expect(rasterNodeCode).not.toHaveProperty("RASTER_STATISTICS_CODE");
  });
});

describe("SCOUT Rasters' Raster Calculator", () => {
  beforeEach(() => clearPackageNodes());

  it("is a package node with this behavior, its icon and the PACKAGE pill, and no built-in one is left", async () => {
    const read = (dir: string) =>
      JSON.parse(fs.readFileSync(path.join(REPO_ROOT, "packages", dir, "manifest.json"), "utf-8"));
    const manifest = read("scout.rasters@1");
    const template = manifest.templates.find((t: { id: string }) => t.id === "raster-calculator");
    expect(template).toBeDefined();
    expect(template.source).toBeUndefined();
    expect(read(`${BUILTIN_PACKAGE_ID}@1`).templates.map((t: { id: string }) => t.id)).not.toContain("raster-calculator");

    // As the package loader does before it builds descriptors.
    await loadIconRefs([template.iconRef]);
    const [descriptor] = registerPackageTemplates([{
      packageId: manifest.id,
      major: 1,
      version: manifest.version,
      name: manifest.name,
      publisher: manifest.publisher,
      description: manifest.description,
      license: manifest.license,
      permissions: [],
      lineage: null,
      templates: [{
        id: `${manifest.id}/raster-calculator@1`,
        templateId: template.id,
        label: template.label,
        category: template.category,
        engine: template.engine,
        description: template.description,
        icon: null,
        iconRef: template.iconRef,
        behavior: template.behavior,
        paletteOrder: template.paletteOrder,
        editor: template.editor,
        hasCode: template.hasCode,
        hasWidgets: template.hasWidgets,
        hasGrammar: template.hasGrammar,
        grammarId: null,
        badge: null,
        inputPorts: template.inputPorts,
        outputPorts: template.outputPorts,
        source: null,
        bidirectional: false,
        containerStyle: null,
        hasProvenance: null,
      }],
    }]);
    expect(descriptor.package?.packageId).toBe("scout.rasters");
    expect(descriptor.package?.name).toBe("SCOUT Rasters");
    // No source of its own: the behavior writes the code, unwrapped.
    expect(descriptor.adapter.useNodeBehavior).toBe(useRasterCalculatorBehavior);
    expect(descriptor.adapter.useNodeBehavior(fresh, state)).toEqual({ defaultValueOverride: RASTER_CALCULATOR_CODE });
    expect(descriptor.icon).toBe(faCalculator);
    expect(descriptor.badge).toBe("PACKAGE");
    expect(descriptor.category).toBe("computation");
  });
});
