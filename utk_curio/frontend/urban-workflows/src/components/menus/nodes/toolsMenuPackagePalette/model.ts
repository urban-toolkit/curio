import { Node as RFNode } from "reactflow";
import { PACKAGE_STAGING_MIME } from "../../../../constants/packagePaletteStaging";
import { draftPackageSectionKey, type PackageStagedRow } from "../../../../providers/PackagePaletteContext";
import { tryGetNodeDescriptor } from "../../../../registry/nodeRegistry";
import { NodeDescriptor, NodeKindId, NodePackageMeta } from "../../../../registry/types";
import { canvasKindLabelFromNode, normalizeKindLabel } from "../../../../utils/palettePackageFactoryDraft";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
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

export function parseStagingPayload(dataTransfer: DataTransfer): string | null {
    const raw = dataTransfer.getData(PACKAGE_STAGING_MIME).trim();
    if (!raw) return null;
    try {
        const parsed = JSON.parse(raw) as { nodeId?: string };
        return typeof parsed.nodeId === "string" ? parsed.nodeId : null;
    } catch {
        return null;
    }
}

export function canvasKindLabelForNodeId(
    nodeId: string,
    rfNodes: readonly RFNode[],
): string | undefined {
    const n = rfNodes.find((x) => x.id === nodeId);
    if (!n) return undefined;
    const nt = getFlowNodeCanonicalType(n);
    if (!nt) return undefined;
    const desc = tryGetNodeDescriptor(nt as NodeKindId);
    if (!desc) return undefined;
    return canvasKindLabelFromNode(n, desc);
}

export function normalizedStagedReplacementLabels(
    stagedRows: readonly PackageStagedRow[],
    labelForNodeId: (id: string) => string | undefined,
): Set<string> {
    const out = new Set<string>();
    for (const row of stagedRows) {
        const label = labelForNodeId(row.canvasNodeId);
        if (label?.trim()) out.add(normalizeKindLabel(label));
    }
    return out;
}

export function packageDescriptorsAfterStagedReplacements(
    descriptors: readonly NodeDescriptor[],
    replacementLabelNorms: ReadonlySet<string>,
): NodeDescriptor[] {
    if (!replacementLabelNorms.size) return [...descriptors];
    return descriptors.filter((d) => !replacementLabelNorms.has(normalizeKindLabel(d.label)));
}

export function packageDescriptorsAfterPaletteEdits(
    descriptors: readonly NodeDescriptor[],
    removedKindIds: readonly string[],
    replacementLabelNorms: ReadonlySet<string>,
): NodeDescriptor[] {
    const removed = new Set(removedKindIds);
    const withoutRemoved = descriptors.filter((d) => !removed.has(d.id));
    return packageDescriptorsAfterStagedReplacements(withoutRemoved, replacementLabelNorms);
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

/**
 * Package count for the PACKAGES palette trigger badge: one per dock row (singleton or
 * fork family), plus draft sections while edit mode is on.
 */
export function visiblePaletteTriggerPackagesCount(opts: {
    paletteRows: PalettePackageRow<PackagePaletteGroup>[];
    packagesPaletteEditMode: boolean;
    draftPackageSectionIds: readonly string[];
}): number {
    let n = opts.paletteRows.length;
    if (opts.packagesPaletteEditMode) {
        n += opts.draftPackageSectionIds.length;
    }
    return n;
}
