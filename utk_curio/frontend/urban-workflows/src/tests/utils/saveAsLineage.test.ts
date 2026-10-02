/**
 * #435: Save as package node, New package..., records where the node came
 * from.
 *
 * The Node Catalog groups a package with its forks by `lineage.root`
 * (PaletteForkFamily, backend catalog_family). A new package made from an
 * installed package's node started from `makeDraft()`, whose lineage is null,
 * so it never joined its source's family.
 *
 * A node of the built-in palette is not a fork of anything: every Save As
 * starts from one, and a palette family shows one member at a time, so
 * recording `curio.builtin` would hide unrelated packages behind each other.
 */
import type { NodeDescriptor } from "../../registry/types";

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

function descriptor(pkg: NodeDescriptor["package"]): Partial<NodeDescriptor> {
  return {
    id: `${pkg!.packageId}/station-reader` as NodeDescriptor["id"],
    label: "Station reader",
    category: "computation",
    editor: "code",
    hasCode: true,
    inputPorts: [],
    outputPorts: [],
    source: "package",
    package: pkg,
  } as Partial<NodeDescriptor>;
}

function saveAsNewPackage() {
  const draft = buildSaveAsInstallDraft({
    canvasNode: { id: "n1", position: { x: 0, y: 0 }, data: { nodeType: mockDesc.id } } as any,
    target: { kind: "new" },
  });
  expect(draft).not.toBeNull();
  return toApiPayload(draft!).manifest as { lineage?: unknown };
}

test("a node of an installed package is recorded as a fork of it", () => {
  mockDesc = descriptor({ packageId: "curio.weather", major: 1, version: "1.0.2" });
  expect(saveAsNewPackage().lineage).toEqual({
    forkedFrom: { packageId: "curio.weather", major: 1 },
    root: { packageId: "curio.weather", major: 1 },
  });
});

test("a node of a fork keeps the fork's root", () => {
  mockDesc = descriptor({
    packageId: "me.weather-tweaks",
    major: 2,
    version: "2.0.0",
    lineage: {
      forkedFrom: { packageId: "curio.weather", major: 1 },
      root: { packageId: "curio.weather", major: 1 },
    },
  });
  expect(saveAsNewPackage().lineage).toEqual({
    forkedFrom: { packageId: "me.weather-tweaks", major: 2 },
    root: { packageId: "curio.weather", major: 1 },
  });
});

test("a node of the built-in palette records no lineage", () => {
  mockDesc = descriptor({ packageId: "curio.builtin", major: 1, version: "1.0.0" });
  expect(saveAsNewPackage().lineage).toBeUndefined();
});
