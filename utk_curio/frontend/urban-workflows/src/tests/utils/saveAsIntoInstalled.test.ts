/**
 * #432: Save as package node into an existing package sends a draft of that
 * package, and the backend lays it over the installed copy.
 *
 * A template that ships no source of its own (curio.example-ui's Column
 * Filter is driven by its behavior bundle) must stay that way. The draft used
 * to invent `sources/<templateId>.py` for it, with placeholder code, so the
 * saved package gained a fake source file and the template a `source` it
 * never had.
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

function template(templateId: string, source: string | null): PackageTemplatePayload {
  return {
    id: `me.ui/${templateId}@1`, templateId, label: templateId, category: "computation",
    engine: "python", description: "", icon: null, iconRef: null, behavior: null,
    paletteOrder: null, editor: "code", hasCode: true, hasWidgets: false, hasGrammar: false,
    grammarId: null, badge: null, inputPorts: [], outputPorts: [], source,
    bidirectional: false, containerStyle: null, hasProvenance: null,
  };
}

const target: PackagePayload = {
  packageId: "me.ui", major: 1, version: "1.0.0", name: "UI", publisher: "t", description: "",
  license: "MIT", permissions: [], dependencies: { packages: {}, python: {}, js: {} },
  templates: [template("column-filter", null), template("loader", "sources/loader.py")],
  dirName: "me.ui@1", lineage: null, familyKey: "me.ui@1", channel: "stable",
};

test("a template with no source of its own is sent without one", () => {
  mockDesc = {
    id: "curio.builtin/computation-analysis" as NodeDescriptor["id"],
    label: "Station reader", category: "computation", editor: "code", hasCode: true,
    inputPorts: [], outputPorts: [], source: "package",
    package: { packageId: "curio.builtin", major: 1, version: "1.0.0" },
  } as Partial<NodeDescriptor>;
  const draft = buildSaveAsInstallDraft({
    canvasNode: { id: "n1", position: { x: 0, y: 0 }, data: { nodeType: mockDesc.id } } as any,
    target: { kind: "installed", package: target },
  });
  expect(draft).not.toBeNull();
  const payload = toApiPayload(draft!);
  const templates = payload.manifest.templates as Array<Record<string, unknown>>;
  const byId = Object.fromEntries(templates.map((t) => [t.id, t]));

  expect(byId["column-filter"].source).toBeUndefined();
  expect(payload.sources["column-filter"]).toBeUndefined();
  // The template that has a source keeps it, and the canvas node is added.
  expect(byId.loader.source).toBe("sources/loader.py");
  expect(templates).toHaveLength(3);
});
