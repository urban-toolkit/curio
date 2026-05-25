import {
  comparePackageVersionDescending,
  findForkFamilyRootPackage,
  findForkFamilyRootPaletteGroup,
  forkFamilyKeyFromPaletteGroup,
  formatForkOfSubtitle,
  lineageCoordKey,
  packageCoordinateKey,
  partitionInstalledPackagesForWarehouseList,
  partitionPalettePackageGroups,
  partitionPackagesByForkFamily,
  referencedForkParentCoordinates,
} from "../../utils/forkPackageLineage";
import type { PackagePayload } from "../../api/packagesApi";
import type { NodePackageMeta } from "../../registry/types";

const lin = (
  fork: { packageId: string; major: number },
  root: { packageId: string; major: number },
) => ({ forkedFrom: fork, root });

describe("forkPackageLineage", () => {
  test("lineageCoordKey", () => {
    expect(lineageCoordKey({ packageId: "a.b.c", major: 1 })).toBe("a.b.c@1");
  });

  test("formatForkOfSubtitle includes root title when differs from fork parent", () => {
    const { text, title } = formatForkOfSubtitle(
      lin({ packageId: "curio.palette.f.x", major: 1 }, { packageId: "ai.root", major: 1 }),
    );
    expect(text).toContain("Fork of curio.palette.f.x@1");
    expect(title).toContain("family root ai.root@1");
  });

  test("comparePackageVersionDescending", () => {
    expect(comparePackageVersionDescending("2.0.0", "1.0.0")).toBeLessThan(0);
    expect(comparePackageVersionDescending("1.10.0", "1.2.0")).toBeLessThan(0);
  });

  test("partitionPackagesByForkFamily groups by root only when 2+ members", () => {
    const a = {
      dirName: "z.fork.a@1",
      version: "1.0.0",
      lineage: lin({ packageId: "x", major: 1 }, { packageId: "root", major: 1 }),
    } as PackagePayload;
    const b = {
      dirName: "z.fork.b@1",
      version: "1.0.0",
      lineage: lin({ packageId: "root", major: 1 }, { packageId: "root", major: 1 }),
    } as PackagePayload;
    const solo = {
      dirName: "solo.fork@1",
      version: "1.0.0",
      lineage: lin({ packageId: "y", major: 1 }, { packageId: "other", major: 1 }),
    } as PackagePayload;

    const { singletons, families } = partitionPackagesByForkFamily([a, b, solo]);

    expect(families).toHaveLength(1);
    expect(families[0]!.rootKey).toBe("root@1");
    expect(families[0]!.members.map((m) => m.dirName).sort()).toEqual(["z.fork.a@1", "z.fork.b@1"].sort());
    expect(singletons).toContain(solo);
    expect(singletons).toHaveLength(1);
  });

  test("partitionPalettePackageGroups merges same root preserving first label position", () => {
    const meta = (
      lineage: ReturnType<typeof lin> | undefined,
      version = "1.0.0",
    ): NodePackageMeta =>
      lineage
        ? {
            packageId: "fork",
            major: 1,
            version,
            lineage: { forkedFrom: lineage.forkedFrom, root: lineage.root },
          }
        : { packageId: "plain", major: 1, version };

    const zebra = {
      key: "z.a@1",
      label: "Zebra · z.a@1",
      descriptors: [{ package: meta(undefined, "9.9.9") }],
    };
    const famA = {
      key: "f.a@1",
      label: "FA",
      descriptors: [{ package: meta(lin({ packageId: "root", major: 1 }, { packageId: "root", major: 1 }), "2.0.0") }],
    };
    const famB = {
      key: "f.b@1",
      label: "FB",
      descriptors: [{ package: meta(lin({ packageId: "f.a", major: 1 }, { packageId: "root", major: 1 }), "3.0.0") }],
    };
    const groups = sortPaletteForkGroupsLike([famA, zebra, famB]);

    expect(forkFamilyKeyFromPaletteGroup(famA)).toBe("root@1");

    const rows = partitionPalettePackageGroups(groups);

    expect(rows.some((r) => r.kind === "singleton" && r.group.label === zebra.label)).toBe(true);

    const famRow = rows.find((r) => r.kind === "family") as Extract<
      (typeof rows)[number],
      { kind: "family" }
    > | undefined;
    expect(famRow).toBeTruthy();
    expect(famRow!.members).toHaveLength(2);
    expect(rows[0]!.kind).toBe("family");
    expect(rows.find((r) => r.kind === "singleton")?.kind).toBe("singleton");
  });

  test("findForkFamilyRootPaletteGroup prefers lineage-free root coordinate", () => {
    const root = {
      key: "root@1",
      label: "Root · root@1",
      descriptors: [{ package: { packageId: "root", major: 1, version: "1.0.0" } satisfies NodePackageMeta }],
    };
    const fork = {
      key: "fork@1",
      label: "Fork · fork@1",
      descriptors: [
        {
          package: {
            packageId: "fork",
            major: 1,
            version: "2.0.0",
            lineage: lin({ packageId: "root", major: 1 }, { packageId: "root", major: 1 }),
          } satisfies NodePackageMeta,
        },
      ],
    };
    expect(findForkFamilyRootPaletteGroup("root@1", [fork, root])?.key).toBe("root@1");
  });

  test("referencedForkParentCoordinates aggregates forkedFrom coords", () => {
    const packages = [
      { lineage: lin({ packageId: "parent.a", major: 1 }, { packageId: "root", major: 1 }) },
      { lineage: lin({ packageId: "parent.b", major: 2 }, { packageId: "root", major: 1 }) },
      { dirName: "solo@1" },
    ] as unknown as PackagePayload[];
    expect([...referencedForkParentCoordinates(packages)].sort()).toEqual(["parent.a@1", "parent.b@2"]);
  });

  test("packageCoordinateKey", () => {
    expect(packageCoordinateKey({ packageId: "curio.palette.fork", major: 1 })).toBe("curio.palette.fork@1");
  });

  test("findForkFamilyRootPackage matches dirName or packageId@major", () => {
    const root = {
      dirName: "root@1",
      packageId: "root",
      major: 1,
      lineage: null,
    } as PackagePayload;
    const fork = {
      dirName: "fork@1",
      packageId: "fork",
      major: 1,
      lineage: lin({ packageId: "root", major: 1 }, { packageId: "root", major: 1 }),
    } as PackagePayload;
    expect(findForkFamilyRootPackage("root@1", [root, fork])).toBe(root);
    expect(findForkFamilyRootPackage("root@1", [fork])).toBeUndefined();
  });

  test("partitionInstalledPackagesForWarehouseList groups forks under root header", () => {
    const root = {
      dirName: "root@1",
      packageId: "root",
      major: 1,
      name: "Root package",
      version: "1.0.0",
      lineage: null,
      templates: [{ id: "a" }],
    } as PackagePayload;
    const forkA = {
      dirName: "fork.a@1",
      packageId: "fork.a",
      major: 1,
      name: "Fork A",
      version: "1.0.0",
      lineage: lin({ packageId: "root", major: 1 }, { packageId: "root", major: 1 }),
      templates: [{ id: "b" }],
    } as PackagePayload;
    const forkB = {
      dirName: "fork.b@1",
      packageId: "fork.b",
      major: 1,
      name: "Fork B",
      version: "1.0.0",
      lineage: lin({ packageId: "fork.a", major: 1 }, { packageId: "root", major: 1 }),
      templates: [{ id: "c" }],
    } as PackagePayload;
    const solo = {
      dirName: "solo@1",
      packageId: "solo",
      major: 1,
      name: "Solo",
      version: "1.0.0",
      lineage: null,
      templates: [{ id: "d" }],
    } as PackagePayload;

    const rows = partitionInstalledPackagesForWarehouseList([root, forkA, forkB, solo]);

    expect(rows.filter((r) => r.kind === "singleton")).toHaveLength(1);
    expect(rows.find((r) => r.kind === "singleton")?.package.dirName).toBe("solo@1");

    const family = rows.find((r) => r.kind === "family");
    expect(family).toBeTruthy();
    if (family?.kind !== "family") throw new Error("expected family row");
    expect(family.rootKey).toBe("root@1");
    expect(family.rootPack?.dirName).toBe("root@1");
    expect(family.members.map((m) => m.dirName).sort()).toEqual(["fork.a@1", "fork.b@1"].sort());
  });
});

/** Deterministic alphabetical by label — mirrors hub sort for test input. */
function sortPaletteForkGroupsLike<G extends { label: string }>(g: G[]): G[] {
  return [...g].sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: "base" }));
}
