/**
 * Fork family grouping keyed by manifest `lineage.root` (palette + Nodes Hub).
 */
import type { PackagePayload } from "../api/packagesApi";
import type { NodePackageMeta } from "../registry/types";

/** Epoch ms derived from canonical ``manifest.createdAt`` (`createdAtMs` from API). */
export function packageCreatedAtMs(
  meta: Partial<Pick<NodePackageMeta, "createdAtMs">> | null | undefined,
): number {
  const n = meta?.createdAtMs;
  if (typeof n === "number" && Number.isFinite(n)) return n;
  if (typeof n === "string") {
    const parsed = Number(n);
    if (Number.isFinite(parsed)) return parsed;
  }
  return 0;
}

/** Strongest ``createdAtMs`` signal among palette templates sharing a package coordinate. */
export function paletteGroupCreatedAtMs(group: {
  descriptors: ReadonlyArray<{
    package?: Partial<Pick<NodePackageMeta, "createdAtMs">> | null | undefined;
  }>;
}): number {
  let m = 0;
  for (const d of group.descriptors) {
    m = Math.max(m, packageCreatedAtMs(d.package));
  }
  return m;
}



export const FORK_SELECTION_SESSION_PREFIX = "curio.forkFamilySelection.v1:";

export type LineageCoordLike = Readonly<{ packageId: string; major: number }>;

export type LineageLike = Readonly<{ forkedFrom: LineageCoordLike; root: LineageCoordLike }>;

/** Canonical coord string for lineage keys (`packageId@major`). */
export function lineageCoordKey(coord: LineageCoordLike): string {
  return `${coord.packageId}@${coord.major}`;
}

export function forkFamilyKeyFromLineage(lineage: LineageLike | null | undefined): string | null {
  if (!lineage?.root) return null;
  return lineageCoordKey(lineage.root);
}

export function forkFamilyKeyFromPackagePayload(pkg: Pick<PackagePayload, "lineage">): string | null {
  return forkFamilyKeyFromLineage(pkg.lineage ?? null);
}

/**
 * Prefer canvas selection (`activePackageKey`), then explicit user/manual pick,
 * then session, then newest member (`members` should be newest-first sorted).
 */
export function resolveForkFamilySelectionKey<G extends { key: string }>(
  rootKey: string,
  members: readonly G[],
  activePackageKey: string,
  manualPick: string | undefined,
): string {
  const keysSet = new Set(members.map((m) => m.key));
  if (keysSet.has(activePackageKey)) return activePackageKey;
  if (manualPick !== undefined && keysSet.has(manualPick)) return manualPick;
  if (typeof sessionStorage !== "undefined") {
    const stored = sessionStorage.getItem(FORK_SELECTION_SESSION_PREFIX + rootKey);
    if (stored !== null && keysSet.has(stored)) return stored;
  }
  return members[0]!.key;
}

export function forkFamilyKeyFromNodePackageMeta(meta: Pick<NodePackageMeta, "lineage"> | undefined): string | null {
  return forkFamilyKeyFromLineage(meta?.lineage ?? null);
}

/** Human line + tooltip for cards / captions. */
export function formatForkOfSubtitle(lineage: LineageLike): { text: string; title: string } {
  const forked = lineageCoordKey(lineage.forkedFrom);
  const root = lineageCoordKey(lineage.root);
  const base = `Fork of ${forked}`;
  return {
    text: base,
    title:
      lineage.forkedFrom.packageId !== lineage.root.packageId || lineage.forkedFrom.major !== lineage.root.major
        ? `${base}; family root ${root}`
        : base,
  };
}

/** Coarse semver sort (numeric parts): higher first. Tie-break lexical. */
export function comparePackageVersionDescending(versionA: string, versionB: string): number {
  const pa = parseSemverLoose(versionA);
  const pb = parseSemverLoose(versionB);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const da = pa[i] ?? 0;
    const db = pb[i] ?? 0;
    if (da !== db) return db - da;
  }
  return versionB.localeCompare(versionA, undefined, { sensitivity: "base" });
}

function parseSemverLoose(v: string): number[] {
  const core = v.trim().split(/[-+]/, 1)[0] ?? "";
  const parts = core.split(".").map((s) => {
    const n = parseInt(/^(\d+)/.exec(s)?.[1] ?? "NaN", 10);
    return Number.isFinite(n) ? n : 0;
  });
  return parts.length ? parts : [0];
}

export interface ForkFamilyGroup<T> {
  rootKey: string;
  members: T[];
}

export function forkFamilyLatestCreatedAtMs<T extends Partial<Pick<PackagePayload, "createdAtMs">>>(
  family: ForkFamilyGroup<T>,
): number {
  let m = 0;
  for (const p of family.members) m = Math.max(m, packageCreatedAtMs(p));
  return m;
}
/**
 * Partition installed catalog rows / payloads: lineage-free → singletons;
 * same `root` with 2+ packages → families; orphaned lineage (solo fork) → singletons.
 */
export function partitionPackagesByForkFamily<
  T extends Pick<PackagePayload, "dirName" | "lineage" | "version" | "createdAtMs">,
>(
  rows: T[],
): { singletons: T[]; families: ForkFamilyGroup<T>[] } {
  const noLineage: T[] = [];
  const withLineage: T[] = [];
  for (const r of rows) {
    if (forkFamilyKeyFromPackagePayload(r) == null) noLineage.push(r);
    else withLineage.push(r);
  }
  const byRoot = new Map<string, T[]>();
  for (const r of withLineage) {
    const k = forkFamilyKeyFromPackagePayload(r)!;
    if (!byRoot.has(k)) byRoot.set(k, []);
    byRoot.get(k)!.push(r);
  }
  const singletons = [...noLineage];
  const families: ForkFamilyGroup<T>[] = [];
  for (const [, members] of byRoot) {
    if (members.length < 2) {
      singletons.push(...members);
    } else {
      families.push({
        rootKey: forkFamilyKeyFromPackagePayload(members[0]!)!,
        members: sortPackagePayloadMembersDescending([...members]),
      });
    }
  }
  families.sort((a, b) => {
    const c = forkFamilyLatestCreatedAtMs(b) - forkFamilyLatestCreatedAtMs(a);
    if (c !== 0) return c;
    return a.rootKey.localeCompare(b.rootKey, undefined, { sensitivity: "base" });
  });
  return { singletons, families };
}

export function sortPackagePayloadMembersDescending<
  T extends Pick<PackagePayload, "lineage" | "version" | "dirName" | "createdAtMs">,
>(members: T[]): T[] {
  return [...members].sort((a, b) => {
    const c = packageCreatedAtMs(b) - packageCreatedAtMs(a);
    if (c !== 0) return c;
    const vc = comparePackageVersionDescending(a.version, b.version);
    if (vc !== 0) return vc;
    return a.dirName.localeCompare(b.dirName, undefined, { sensitivity: "base" });
  });
}

/** One row per standalone package `<details>`; families share a root fork key. */
export type PalettePackageGroupLike = Readonly<{
  key: string;
  label: string;
  descriptors: ReadonlyArray<{ pkg?: NodePackageMeta | undefined }>;
}>;

export function forkFamilyKeyFromPaletteGroup(group: PalettePackageGroupLike): string | null {
  const meta = group.descriptors[0]?.package;
  return forkFamilyKeyFromNodePackageMeta(meta);
}

export type PalettePackageRow<G extends PalettePackageGroupLike = PalettePackageGroupLike> =
  | { kind: "singleton"; group: G }
  | { kind: "family"; rootKey: string; members: G[] };

/**
 * Build dock palette rows. Input `groups` is sorted (typically newest `createdAtMs` first).
 * Fork families appear at the first package’s position among sorted groups.
 */
export function partitionPalettePackageGroups<G extends PalettePackageGroupLike>(groups: readonly G[]): PalettePackageRow<G>[] {
  const ordered = [...groups];
  const byRoot = new Map<string, G[]>();
  for (const g of ordered) {
    const rk = forkFamilyKeyFromPaletteGroup(g);
    if (rk == null) continue;
    if (!byRoot.has(rk)) byRoot.set(rk, []);
    byRoot.get(rk)!.push(g);
  }

  const rows: PalettePackageRow<G>[] = [];
  const emittedRoot = new Set<string>();

  for (const g of ordered) {
    const rk = forkFamilyKeyFromPaletteGroup(g);
    if (rk == null) {
      rows.push({ kind: "singleton", group: g });
      continue;
    }
    if (emittedRoot.has(rk)) continue;
    emittedRoot.add(rk);
    const members = byRoot.get(rk)!;
    if (members.length < 2) {
      rows.push({ kind: "singleton", group: members[0]! });
    } else {
      rows.push({
        kind: "family",
        rootKey: rk,
        members: sortPaletteForkGroupsDescending(members),
      });
    }
  }

  return rows;
}

export function sortPaletteForkGroupsDescending<G extends PalettePackageGroupLike>(
  members: readonly G[],
): G[] {
  return [...members].sort((a, b) => {
    const ta = paletteGroupCreatedAtMs(a);
    const tb = paletteGroupCreatedAtMs(b);
    if (tb !== ta) return tb - ta;
    const va = a.descriptors[0]?.package?.version ?? "";
    const vb = b.descriptors[0]?.package?.version ?? "";
    const c = comparePackageVersionDescending(va, vb);
    if (c !== 0) return c;
    return a.key.localeCompare(b.key, undefined, { sensitivity: "base" });
  });
}

export function packageCoordinateKey(pkg: Pick<PackagePayload, "packageId" | "major">): string {
  return `${pkg.packageId}@${pkg.major}`;
}

/** Installed package with `lineage == null` that anchors a fork family (`rootKey`). */
export function findForkFamilyRootPackage<
  T extends Pick<PackagePayload, "dirName" | "packageId" | "major" | "lineage">,
>(rootKey: string, packages: readonly T[]): T | undefined {
  return packages.find(
    (p) =>
      p.lineage == null &&
      (p.dirName === rootKey || packageCoordinateKey(p) === rootKey),
  );
}

/** Palette dock group for the lineage-free root package in a fork family. */
export function findForkFamilyRootPaletteGroup<G extends PalettePackageGroupLike>(
  rootKey: string,
  members: readonly G[],
): G | undefined {
  return (
    members.find((m) => {
      const meta = m.descriptors[0]?.package;
      if (!meta || meta.lineage != null) return false;
      return m.key === rootKey || packageCoordinateKey(meta) === rootKey;
    }) ??
    members.find((m) => m.key === rootKey)
  );
}

export type InstalledPackageWarehouseRow<T extends PackagePayload = PackagePayload> =
  | { kind: "singleton"; package: T }
  | { kind: "family"; rootKey: string; rootPack: T | null; members: T[] };

/** Singleton rows + fork-family accordions (root package omitted from singleton list). */
export function partitionInstalledPackagesForWarehouseList<T extends PackagePayload>(
  packages: readonly T[],
): InstalledPackageWarehouseRow<T>[] {
  const list = [...packages];
  const { singletons, families } = partitionPackagesByForkFamily(list);
  const rootPackageDirsUsed = new Set<string>();
  const rows: InstalledPackageWarehouseRow<T>[] = [];

  for (const family of families) {
    const rootPack = findForkFamilyRootPackage(family.rootKey, list) ?? null;
    if (rootPack) rootPackageDirsUsed.add(rootPack.dirName);
    rows.push({
      kind: "family",
      rootKey: family.rootKey,
      rootPack,
      members: family.members,
    });
  }

  for (const pkg of singletons) {
    if (!rootPackageDirsUsed.has(pkg.dirName)) {
      rows.push({ kind: "singleton", package: pkg });
    }
  }

  rows.sort((a, b) => {
    const ta =
      a.kind === "singleton"
        ? packageCreatedAtMs(a.package)
        : Math.max(
            packageCreatedAtMs(a.rootPack),
            forkFamilyLatestCreatedAtMs({ rootKey: a.rootKey, members: a.members }),
          );
    const tb =
      b.kind === "singleton"
        ? packageCreatedAtMs(b.package)
        : Math.max(
            packageCreatedAtMs(b.rootPack),
            forkFamilyLatestCreatedAtMs({ rootKey: b.rootKey, members: b.members }),
          );
    const c = tb - ta;
    if (c !== 0) return c;
    const keyA = a.kind === "singleton" ? a.package.dirName : a.rootKey;
    const keyB = b.kind === "singleton" ? b.package.dirName : b.rootKey;
    return keyA.localeCompare(keyB, undefined, { sensitivity: "base" });
  });

  return rows;
}

/** `dirName`-style coordinates referenced as `lineage.forkedFrom` by any package in `packages`. */
export function referencedForkParentCoordinates<T extends Pick<PackagePayload, "lineage">>(
  packages: Iterable<T>,
): Set<string> {
  const out = new Set<string>();
  for (const p of packages) {
    const ff = p.lineage?.forkedFrom;
    if (!ff) continue;
    out.add(lineageCoordKey(ff));
  }
  return out;
}

