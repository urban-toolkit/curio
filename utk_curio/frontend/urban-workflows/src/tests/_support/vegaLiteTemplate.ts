/**
 * A package template that draws with the Vega-Lite grammar (`grammarId:
 * "vega-lite"`), as the SCOUT Comparison package's charts do, registered as
 * `packagesClient` registers one. Suites that check a rule keyed on the
 * Vega-Lite node run it for such a template too: it draws with the node's own
 * behavior, so it must be drawn, saved and walked the same way.
 */
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";

/** One of SCOUT Comparison's charts, versioned as a palette drop writes it. */
export const VEGA_LITE_TEMPLATE = "scout.comparison/donuts@1";

/** Registers {@link VEGA_LITE_TEMPLATE}; undo it with {@link clearVegaLiteTemplate}. */
export function registerVegaLiteTemplate(id: string = VEGA_LITE_TEMPLATE): void {
  const descriptor = {
    id,
    source: "package",
    package: { packageId: id.split("/")[0], major: 1, version: "1.0.0", name: "SCOUT Comparison", publisher: "Curio" },
    category: "vis_grammar",
    label: "Donuts",
    icon: {},
    inputPorts: [{ types: ["DATAFRAME", "GEODATAFRAME"], cardinality: "1" }],
    outputPorts: [{ types: ["DATAFRAME", "GEODATAFRAME"], cardinality: "1" }],
    editor: "grammar",
    grammarId: "vega-lite",
    badge: "VEGA",
    inPalette: true,
    description: "",
    hasCode: false,
    hasWidgets: true,
    hasGrammar: true,
    adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
  } as unknown as NodeDescriptor;
  registerNode(descriptor);
}

/** Drops every package template a suite registered. */
export function clearVegaLiteTemplate(): void {
  clearPackageNodes();
}
