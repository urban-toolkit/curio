import { groupPalettePackages } from "../../../components/menus/nodes/toolsMenuPackagePalette/model";
import type { NodeDescriptor, NodePackageMeta } from "../../../registry/types";

function stubPackageDesc(meta: NodePackageMeta): NodeDescriptor {
  return { source: "package", package: meta } as unknown as NodeDescriptor;
}

describe("groupPalettePackages ordering", () => {
  test("orders by manifest createdAtMs descending (ties by coord)", () => {
    const newer: NodePackageMeta = {
      packageId: "package.new",
      major: 1,
      version: "1.0.0",
      createdAtMs: 200,
    };
    const older: NodePackageMeta = {
      packageId: "package.old",
      major: 1,
      version: "1.0.0",
      createdAtMs: 100,
    };
    const noTs: NodePackageMeta = { packageId: "package.nots", major: 1, version: "1.0.0" };

    const groups = groupPalettePackages([
      stubPackageDesc(older),
      stubPackageDesc(noTs),
      stubPackageDesc(newer),
    ]);

    expect(groups.map((g) => g.key)).toEqual(["package.new@1", "package.old@1", "package.nots@1"]);
  });

  test("uses strongest createdAtMs across templates in one package coordinate", () => {
    const base: Omit<NodePackageMeta, "createdAtMs"> = {
      packageId: "package.multi",
      major: 1,
      version: "1.0.0",
    };
    const other: NodePackageMeta = {
      packageId: "package.other",
      major: 1,
      version: "1.0.0",
      createdAtMs: 300,
    };
    const groups = groupPalettePackages([
      stubPackageDesc(other),
      stubPackageDesc({ ...base, createdAtMs: 50 } as NodePackageMeta),
      stubPackageDesc({ ...base, createdAtMs: 500 } as NodePackageMeta),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["package.multi@1", "package.other@1"]);
  });
});
