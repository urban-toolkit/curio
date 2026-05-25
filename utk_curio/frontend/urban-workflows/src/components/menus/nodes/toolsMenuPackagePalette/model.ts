import { NodeDescriptor, NodePackageMeta } from "../../../../registry/types";
import {
    findForkFamilyRootPaletteGroup,
    paletteGroupCreatedAtMs,
    type PalettePackageRow,
} from "../../../../utils/forkPackageLineage";

export interface PackagePaletteGroup {
    key: string;
    /** Human-readable package name (manifest `name`). */
    name: string;
    /** Secondary line: publisher · packageId@major (tooltips / fork chrome). */
    label: string;
    descriptors: NodeDescriptor[];
}

export function packageDisplayName(meta: NodePackageMeta): string {
    if (meta.name?.trim()) return meta.name.trim();
    if (meta.publisher?.trim()) return meta.publisher.trim();
    return `${meta.packageId}@${meta.major}`;
}

export function formatPackageSectionLabel(meta: NodePackageMeta): string {
    const coord = `${meta.packageId}@${meta.major}`;
    if (meta.publisher?.trim()) {
        return `${meta.publisher} · ${coord}`;
    }
    return coord;
}

/**
 * One group per installed package coordinate (`packageId@major`).
 * Rows are **newest-first** by canonical `createdAtMs` from `manifest.createdAt`.
 */
export function groupPalettePackages(packageTypes: NodeDescriptor[]): PackagePaletteGroup[] {
    const byKey = new Map<string, NodeDescriptor[]>();
    for (const d of packageTypes) {
        if (d.source !== "package" || !d.package) continue;
        const key = `${d.package.packageId}@${d.package.major}`;
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key)!.push(d);
    }
    return Array.from(byKey.entries())
        .map(([key, descriptors]) => {
            const sorted = [...descriptors].sort(
                (a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999),
            );
            const packageMeta = sorted[0].package!;
            const name = packageDisplayName(packageMeta);
            const label = formatPackageSectionLabel(packageMeta);
            return { key, name, label, descriptors: sorted };
        })
        .sort((a, b) => {
            const c = paletteGroupCreatedAtMs(b) - paletteGroupCreatedAtMs(a);
            if (c !== 0) return c;
            return a.key.localeCompare(b.key, undefined, { sensitivity: "base" });
        });
}

/** Display name for a fork-family toolbar row — always the root package's title. */
export function forkFamilyRootDisplayName(
    rootKey: string,
    members: readonly PackagePaletteGroup[],
): string {
    const root = findForkFamilyRootPaletteGroup(rootKey, members);
    if (root) return root.name;
    return members[0]?.name ?? rootKey;
}

/** Package count for the PACKAGES palette trigger badge: one per dock row (singleton or fork family). */
export function visiblePaletteTriggerPackagesCount(opts: {
    paletteRows: PalettePackageRow<PackagePaletteGroup>[];
}): number {
    return opts.paletteRows.length;
}
