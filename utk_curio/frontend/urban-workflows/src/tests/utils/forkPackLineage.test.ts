import {
  areForkPaletteParentsRevealedInDock,
  comparePackVersionDescending,
  filterForkParentHiddenPalettePackGroups,
  findForkFamilyRootPack,
  forkFamilyKeyFromPaletteGroup,
  formatForkOfSubtitle,
  lineageCoordKey,
  packCoordinateKey,
  partitionInstalledPacksForWarehouseList,
  partitionPalettePackGroups,
  partitionPacksByForkFamily,
  referencedForkParentCoordinates,
} from "../../utils/forkPackLineage";
import type { PackPayload } from "../../api/packsApi";
import type { NodePackMeta } from "../../registry/types";

const lin = (
  fork: { packId: string; major: number },
  root: { packId: string; major: number },
) => ({ forkedFrom: fork, root });

describe("forkPackLineage", () => {
  test("lineageCoordKey", () => {
    expect(lineageCoordKey({ packId: "a.b.c", major: 1 })).toBe("a.b.c@1");
  });

  test("formatForkOfSubtitle includes root title when differs from fork parent", () => {
    const { text, title } = formatForkOfSubtitle(
      lin({ packId: "curio.palette.f.x", major: 1 }, { packId: "ai.root", major: 1 }),
    );
    expect(text).toContain("Fork of curio.palette.f.x@1");
    expect(title).toContain("family root ai.root@1");
  });

  test("comparePackVersionDescending", () => {
    expect(comparePackVersionDescending("2.0.0", "1.0.0")).toBeLessThan(0);
    expect(comparePackVersionDescending("1.10.0", "1.2.0")).toBeLessThan(0);
  });

  test("partitionPacksByForkFamily groups by root only when 2+ members", () => {
    const a = {
      dirName: "z.fork.a@1",
      version: "1.0.0",
      lineage: lin({ packId: "x", major: 1 }, { packId: "root", major: 1 }),
    } as PackPayload;
    const b = {
      dirName: "z.fork.b@1",
      version: "1.0.0",
      lineage: lin({ packId: "root", major: 1 }, { packId: "root", major: 1 }),
    } as PackPayload;
    const solo = {
      dirName: "solo.fork@1",
      version: "1.0.0",
      lineage: lin({ packId: "y", major: 1 }, { packId: "other", major: 1 }),
    } as PackPayload;

    const { singletons, families } = partitionPacksByForkFamily([a, b, solo]);

    expect(families).toHaveLength(1);
    expect(families[0]!.rootKey).toBe("root@1");
    expect(families[0]!.members.map((m) => m.dirName).sort()).toEqual(["z.fork.a@1", "z.fork.b@1"].sort());
    expect(singletons).toContain(solo);
    expect(singletons).toHaveLength(1);
  });

  test("partitionPalettePackGroups merges same root preserving first label position", () => {
    const meta = (
      lineage: ReturnType<typeof lin> | undefined,
      version = "1.0.0",
    ): NodePackMeta =>
      lineage
        ? {
            packId: "fork",
            major: 1,
            version,
            lineage: { forkedFrom: lineage.forkedFrom, root: lineage.root },
          }
        : { packId: "plain", major: 1, version };

    const zebra = {
      key: "z.a@1",
      label: "Zebra · z.a@1",
      descriptors: [{ pack: meta(undefined, "9.9.9") }],
    };
    const famA = {
      key: "f.a@1",
      label: "FA",
      descriptors: [{ pack: meta(lin({ packId: "root", major: 1 }, { packId: "root", major: 1 }), "2.0.0") }],
    };
    const famB = {
      key: "f.b@1",
      label: "FB",
      descriptors: [{ pack: meta(lin({ packId: "f.a", major: 1 }, { packId: "root", major: 1 }), "3.0.0") }],
    };
    const groups = sortPaletteForkGroupsLike([famA, zebra, famB]);

    expect(forkFamilyKeyFromPaletteGroup(famA)).toBe("root@1");

    const rows = partitionPalettePackGroups(groups);

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

  test("referencedForkParentCoordinates aggregates forkedFrom coords", () => {
    const packs = [
      { lineage: lin({ packId: "parent.a", major: 1 }, { packId: "root", major: 1 }) },
      { lineage: lin({ packId: "parent.b", major: 2 }, { packId: "root", major: 1 }) },
      { dirName: "solo@1" },
    ] as PackPayload[];
    expect([...referencedForkParentCoordinates(packs)].sort()).toEqual(["parent.a@1", "parent.b@2"]);
  });

  test("areForkPaletteParentsRevealedInDock when parent hidden in payload", () => {
    const packs = [
      {
        dirName: "parent@1",
        paletteDock: { hiddenFromForkPaletteDock: true },
      },
      {
        dirName: "fork@1",
        lineage: lin({ packId: "parent", major: 1 }, { packId: "parent", major: 1 }),
      },
    ] as PackPayload[];
    expect(areForkPaletteParentsRevealedInDock(packs)).toBe(false);
    expect(
      areForkPaletteParentsRevealedInDock([
        { dirName: "parent@1" },
        packs[1]!,
      ] as PackPayload[]),
    ).toBe(true);
  });

  test("filterForkParentHiddenPalettePackGroups removes hidden sections", () => {
    const groups = [
      { key: "a@1", label: "A", descriptors: [{ pack: { hiddenFromForkPaletteDock: true } }] },
      { key: "b@1", label: "B", descriptors: [{}] },
    ];
    const kept = filterForkParentHiddenPalettePackGroups(groups as any);
    expect(kept).toHaveLength(1);
    expect(kept[0]!.key).toBe("b@1");
  });

  test("packCoordinateKey", () => {
    expect(packCoordinateKey({ packId: "curio.palette.fork", major: 1 })).toBe("curio.palette.fork@1");
  });

  test("findForkFamilyRootPack matches dirName or packId@major", () => {
    const root = {
      dirName: "root@1",
      packId: "root",
      major: 1,
      lineage: null,
    } as PackPayload;
    const fork = {
      dirName: "fork@1",
      packId: "fork",
      major: 1,
      lineage: lin({ packId: "root", major: 1 }, { packId: "root", major: 1 }),
    } as PackPayload;
    expect(findForkFamilyRootPack("root@1", [root, fork])).toBe(root);
    expect(findForkFamilyRootPack("root@1", [fork])).toBeUndefined();
  });

  test("partitionInstalledPacksForWarehouseList groups forks under root header", () => {
    const root = {
      dirName: "root@1",
      packId: "root",
      major: 1,
      name: "Root pack",
      version: "1.0.0",
      lineage: null,
      kinds: [{ id: "a" }],
    } as PackPayload;
    const forkA = {
      dirName: "fork.a@1",
      packId: "fork.a",
      major: 1,
      name: "Fork A",
      version: "1.0.0",
      lineage: lin({ packId: "root", major: 1 }, { packId: "root", major: 1 }),
      kinds: [{ id: "b" }],
    } as PackPayload;
    const forkB = {
      dirName: "fork.b@1",
      packId: "fork.b",
      major: 1,
      name: "Fork B",
      version: "1.0.0",
      lineage: lin({ packId: "fork.a", major: 1 }, { packId: "root", major: 1 }),
      kinds: [{ id: "c" }],
    } as PackPayload;
    const solo = {
      dirName: "solo@1",
      packId: "solo",
      major: 1,
      name: "Solo",
      version: "1.0.0",
      lineage: null,
      kinds: [{ id: "d" }],
    } as PackPayload;

    const rows = partitionInstalledPacksForWarehouseList([root, forkA, forkB, solo]);

    expect(rows.filter((r) => r.kind === "singleton")).toHaveLength(1);
    expect(rows.find((r) => r.kind === "singleton")?.pack.dirName).toBe("solo@1");

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
