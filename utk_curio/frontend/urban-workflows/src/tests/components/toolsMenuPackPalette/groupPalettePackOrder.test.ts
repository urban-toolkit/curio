import { groupPalettePacks } from "../../../components/menus/nodes/toolsMenuPackPalette/model";
import type { NodeDescriptor, NodePackMeta } from "../../../registry/types";

function stubPackDesc(meta: NodePackMeta): NodeDescriptor {
  return { source: "pack", pack: meta } as unknown as NodeDescriptor;
}

describe("groupPalettePacks ordering", () => {
  test("orders by manifest createdAtMs descending (ties by coord)", () => {
    const newer: NodePackMeta = {
      packId: "pack.new",
      major: 1,
      version: "1.0.0",
      createdAtMs: 200,
    };
    const older: NodePackMeta = {
      packId: "pack.old",
      major: 1,
      version: "1.0.0",
      createdAtMs: 100,
    };
    const noTs: NodePackMeta = { packId: "pack.nots", major: 1, version: "1.0.0" };

    const groups = groupPalettePacks([
      stubPackDesc(older),
      stubPackDesc(noTs),
      stubPackDesc(newer),
    ]);

    expect(groups.map((g) => g.key)).toEqual(["pack.new@1", "pack.old@1", "pack.nots@1"]);
  });

  test("uses strongest createdAtMs across kinds in one pack coordinate", () => {
    const base: Omit<NodePackMeta, "createdAtMs"> = {
      packId: "pack.multi",
      major: 1,
      version: "1.0.0",
    };
    const other: NodePackMeta = {
      packId: "pack.other",
      major: 1,
      version: "1.0.0",
      createdAtMs: 300,
    };
    const groups = groupPalettePacks([
      stubPackDesc(other),
      stubPackDesc({ ...base, createdAtMs: 50 } as NodePackMeta),
      stubPackDesc({ ...base, createdAtMs: 500 } as NodePackMeta),
    ]);
    expect(groups.map((g) => g.key)).toEqual(["pack.multi@1", "pack.other@1"]);
  });
});
