/**
 * Fork family grouping keyed by manifest `lineage.root` (palette + Nodes Hub).
 */
import type { PackPayload } from "../api/packsApi";
import type { NodePackMeta } from "../registry/types";

/** sessionStorage prefix for remembering fork branch in the dock palette. */
export const FORK_SELECTION_SESSION_PREFIX = "curio.forkFamilySelection.v1:";

export type LineageCoordLike = Readonly<{ packId: string; major: number }>;

export type LineageLike = Readonly<{ forkedFrom: LineageCoordLike; root: LineageCoordLike }>;

/** Canonical coord string for lineage keys (`packId@major`). */
export function lineageCoordKey(coord: LineageCoordLike): string {
  return `${coord.packId}@${coord.major}`;
}

export function forkFamilyKeyFromLineage(lineage: LineageLike | null | undefined): string | null {
  if (!lineage?.root) return null;
  return lineageCoordKey(lineage.root);
}

export function forkFamilyKeyFromPackPayload(pack: Pick<PackPayload, "lineage">): string | null {
  return forkFamilyKeyFromLineage(pack.lineage ?? null);
}

/**
 * Prefer canvas selection (`activePackKey`), then explicit user/manual pick,
 * then session, then newest member (`members` should be newest-first sorted).
 */
export function resolveForkFamilySelectionKey<G extends { key: string }>(
  rootKey: string,
  members: readonly G[],
  activePackKey: string,
  manualPick: string | undefined,
): string {
  const keysSet = new Set(members.map((m) => m.key));
  if (keysSet.has(activePackKey)) return activePackKey;
  if (manualPick !== undefined && keysSet.has(manualPick)) return manualPick;
  if (typeof sessionStorage !== "undefined") {
    const stored = sessionStorage.getItem(FORK_SELECTION_SESSION_PREFIX + rootKey);
    if (stored !== null && keysSet.has(stored)) return stored;
  }
  return members[0]!.key;
}

export function forkFamilyKeyFromNodePackMeta(meta: Pick<NodePackMeta, "lineage"> | undefined): string | null {
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
      lineage.forkedFrom.packId !== lineage.root.packId || lineage.forkedFrom.major !== lineage.root.major
        ? `${base}; family root ${root}`
        : base,
  };
}

/** Coarse semver sort (numeric parts): higher first. Tie-break lexical. */
export function comparePackVersionDescending(versionA: string, versionB: string): number {
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

/**
 * Partition installed catalog rows / payloads: lineage-free → singletons;
 * same `root` with 2+ packs → families; orphaned lineage (solo fork) → singletons.
 */
export function partitionPacksByForkFamily<T extends Pick<PackPayload, "dirName" | "lineage">>(
  rows: T[],
): { singletons: T[]; families: ForkFamilyGroup<T>[] } {
  const noLineage: T[] = [];
  const withLineage: T[] = [];
  for (const r of rows) {
    if (forkFamilyKeyFromPackPayload(r) == null) noLineage.push(r);
    else withLineage.push(r);
  }
  const byRoot = new Map<string, T[]>();
  for (const r of withLineage) {
    const k = forkFamilyKeyFromPackPayload(r)!;
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
        rootKey: forkFamilyKeyFromPackPayload(members[0]!)!,
        members: sortPackPayloadMembersDescending([...members]),
      });
    }
  }
  families.sort((a, b) => a.rootKey.localeCompare(b.rootKey, undefined, { sensitivity: "base" }));
  return { singletons, families };
}

export function sortPackPayloadMembersDescending<T extends Pick<PackPayload, "lineage" | "version" | "dirName">>(
  members: T[],
): T[] {
  return [...members].sort((a, b) => {
    const c = comparePackVersionDescending(a.version, b.version);
    if (c !== 0) return c;
    return a.dirName.localeCompare(b.dirName, undefined, { sensitivity: "base" });
  });
}

/** One row per standalone pack `<details>`; families share a root fork key. */
export type PalettePackGroupLike = Readonly<{
  key: string;
  label: string;
  descriptors: ReadonlyArray<{ pack?: NodePackMeta | undefined }>;
}>;

export function forkFamilyKeyFromPaletteGroup(group: PalettePackGroupLike): string | null {
  const meta = group.descriptors[0]?.pack;
  return forkFamilyKeyFromNodePackMeta(meta);
}

export type PalettePackRow<G extends PalettePackGroupLike = PalettePackGroupLike> =
  | { kind: "singleton"; group: G }
  | { kind: "family"; rootKey: string; members: G[] };

/**
 * Build dock palette rows. Input `groups` is already sorted (e.g. by label).
 * Fork families appear at the first pack’s position among sorted groups.
 */
export function partitionPalettePackGroups<G extends PalettePackGroupLike>(groups: readonly G[]): PalettePackRow<G>[] {
  const ordered = [...groups];
  const byRoot = new Map<string, G[]>();
  for (const g of ordered) {
    const rk = forkFamilyKeyFromPaletteGroup(g);
    if (rk == null) continue;
    if (!byRoot.has(rk)) byRoot.set(rk, []);
    byRoot.get(rk)!.push(g);
  }

  const rows: PalettePackRow<G>[] = [];
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

export function sortPaletteForkGroupsDescending<G extends PalettePackGroupLike>(
  members: readonly G[],
): G[] {
  return [...members].sort((a, b) => {
    const va = a.descriptors[0]?.pack?.version ?? "";
    const vb = b.descriptors[0]?.pack?.version ?? "";
    const c = comparePackVersionDescending(va, vb);
    if (c !== 0) return c;
    return a.key.localeCompare(b.key, undefined, { sensitivity: "base" });
  });
}

/** `dirName`-style coordinates referenced as `lineage.forkedFrom` by any pack in `packs`. */
export function referencedForkParentCoordinates<T extends Pick<PackPayload, "lineage">>(
  packs: Iterable<T>,
): Set<string> {
  const out = new Set<string>();
  for (const p of packs) {
    const ff = p.lineage?.forkedFrom;
    if (!ff) continue;
    out.add(lineageCoordKey(ff));
  }
  return out;
}

/**
 * Whether every installed pack that acts as someone's fork parent is shown in the
 * Packs dock (not `hiddenFromForkPaletteDock`). True when nothing is fork-installed.
 */
export function areForkPaletteParentsRevealedInDock(packs: PackPayload[]): boolean {
  const parents = referencedForkParentCoordinates(packs);
  if (!parents.size) return true;
  const byDir = new Map(packs.map((p) => [p.dirName, p]));
  for (const dir of parents) {
    const row = byDir.get(dir);
    if (!row) continue;
    if (row.paletteDock?.hiddenFromForkPaletteDock) return false;
  }
  return true;
}

/** Omit groups whose pack metadata says the dock should hide fork-source sections. */
export function filterForkParentHiddenPalettePackGroups<G extends PalettePackGroupLike>(
  groups: readonly G[],
): G[] {
  return groups.filter((g) => !(g.descriptors[0]?.pack?.hiddenFromForkPaletteDock === true));
}
