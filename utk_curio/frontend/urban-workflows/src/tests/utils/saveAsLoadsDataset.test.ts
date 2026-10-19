/**
 * Save as package node keeps the `loadsDataset` flag of the node's template.
 *
 * The Data Catalog's lineage, the canvas and the agents take a node for a
 * loader when its template declares `loadsDataset` (registry/declaredNodes).
 * A copy of Data Loading saved into a package of your own declares it too, so
 * it stays a loader; a copy of any other node declares nothing. Saving into
 * an installed package keeps the flag of the templates already there.
 */
import type { NodeDescriptor } from "../../registry/types";
import type { PackagePayload, PackageTemplatePayload } from "../../services/packages";

let mockDesc: Partial<NodeDescriptor>;

jest.mock("../../registry/packageRegistryBootstrap", () => ({
  refreshPackageRegistry: jest.fn(),
}));
jest.mock("../../registry/nodeRegistry", () => ({
  tryGetNodeDescriptor: () => mockDesc,
}));
jest.mock("../../utils/flowNodeCanonicalType", () => ({
  getFlowNodeCanonicalType: () => mockDesc.id,
}));

import { buildSaveAsInstallDraft } from "../../utils/palettePackageFactoryDraft";
import { toApiPayload } from "../../services/packages";

const DATAFRAME = { types: ["DATAFRAME"], cardinality: "1" } as const;

function builtinDescriptor(templateId: string, fields: Record<string, unknown>): Partial<NodeDescriptor> {
  return {
    id: `curio.builtin/${templateId}@1`,
    label: templateId,
    category: "computation",
    editor: "code",
    hasCode: true,
    inputPorts: [],
    outputPorts: [DATAFRAME],
    source: "package",
    package: { packageId: "curio.builtin", major: 1, version: "1.0.0" },
    ...fields,
  } as unknown as Partial<NodeDescriptor>;
}

function savedTemplates(target: Parameters<typeof buildSaveAsInstallDraft>[0]["target"]) {
  const draft = buildSaveAsInstallDraft({
    canvasNode: { id: "n1", position: { x: 0, y: 0 }, data: { nodeType: mockDesc.id } } as any,
    target,
  });
  expect(draft).not.toBeNull();
  return toApiPayload(draft!).manifest.templates as Array<Record<string, unknown>>;
}

test("a copy of Data Loading in a new package declares loadsDataset", () => {
  mockDesc = builtinDescriptor("data-loading", { category: "data", loadsDataset: true });
  const [template] = savedTemplates({ kind: "new" });
  expect(template.loadsDataset).toBe(true);
});

test("a copy of a node whose template declares no loader declares nothing", () => {
  mockDesc = builtinDescriptor("computation-analysis", { inputPorts: [DATAFRAME] });
  const [template] = savedTemplates({ kind: "new" });
  expect(template).not.toHaveProperty("loadsDataset");
});

test("saving into an installed package keeps the flag of its loader", () => {
  const loader = {
    id: "me.loaders/fetch-parcels@1", templateId: "fetch-parcels", label: "Fetch parcels",
    category: "data", engine: "python", description: "", icon: null, iconRef: null, behavior: "code",
    paletteOrder: null, editor: "code", hasCode: true, hasWidgets: false, hasGrammar: false,
    grammarId: null, badge: null, inputPorts: [], outputPorts: [DATAFRAME], source: "sources/fetch-parcels.py",
    bidirectional: false, containerStyle: null, hasProvenance: null, loadsDataset: true,
  } as unknown as PackageTemplatePayload;
  const target = {
    packageId: "me.loaders", major: 1, version: "1.0.0", name: "Loaders", publisher: "t", description: "",
    license: "MIT", permissions: [], dependencies: { packages: {}, python: {}, js: {} },
    templates: [loader], dirName: "me.loaders@1", lineage: null, familyKey: "me.loaders@1", channel: "stable",
  } as unknown as PackagePayload;
  mockDesc = builtinDescriptor("computation-analysis", { inputPorts: [DATAFRAME] });

  const byId = Object.fromEntries(savedTemplates({ kind: "installed", package: target }).map((t) => [t.id, t]));
  expect(byId["fetch-parcels"].loadsDataset).toBe(true);
  expect(byId["computation-analysis"]).not.toHaveProperty("loadsDataset");
});
