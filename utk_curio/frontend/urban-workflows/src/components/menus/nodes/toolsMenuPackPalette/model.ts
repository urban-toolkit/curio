import { Node as RFNode } from "reactflow";
import { PACK_STAGING_MIME } from "../../../../constants/packPaletteStaging";
import { draftPackSectionKey, type PackStagedRow } from "../../../../providers/PackPaletteContext";
import { tryGetNodeDescriptor } from "../../../../registry/nodeRegistry";
import { NodeDescriptor, NodeKindId, NodePackMeta } from "../../../../registry/types";
import { canvasKindLabelFromNode, normalizeKindLabel } from "../../../../utils/palettePackFactoryDraft";
import { getFlowNodeCanonicalType } from "../../../../utils/flowNodeCanonicalType";
import {
    findForkFamilyRootPaletteGroup,
    paletteGroupCreatedAtMs,
    type PalettePackRow,
} from "../../../../utils/forkPackLineage";

export interface PackPaletteGroup {
    key: string;
    /** Human-readable pack name (manifest `name`). */
    name: string;
    /** Secondary line: publisher · packId@major (tooltips / fork chrome). */
    label: string;
    descriptors: NodeDescriptor[];
}

export function packDisplayName(meta: NodePackMeta): string {
    if (meta.name?.trim()) return meta.name.trim();
    if (meta.publisher?.trim()) return meta.publisher.trim();
    return `${meta.packId}@${meta.major}`;
}

export function formatPackSectionLabel(meta: NodePackMeta): string {
    const coord = `${meta.packId}@${meta.major}`;
    if (meta.publisher?.trim()) {
        return `${meta.publisher} · ${coord}`;
    }
    return coord;
}

export function parseStagingPayload(dataTransfer: DataTransfer): string | null {
    const raw = dataTransfer.getData(PACK_STAGING_MIME).trim();
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
    stagedRows: readonly PackStagedRow[],
    labelForNodeId: (id: string) => string | undefined,
): Set<string> {
    const out = new Set<string>();
    for (const row of stagedRows) {
        const label = labelForNodeId(row.canvasNodeId);
        if (label?.trim()) out.add(normalizeKindLabel(label));
    }
    return out;
}

export function packDescriptorsAfterStagedReplacements(
    descriptors: readonly NodeDescriptor[],
    replacementLabelNorms: ReadonlySet<string>,
): NodeDescriptor[] {
    if (!replacementLabelNorms.size) return [...descriptors];
    return descriptors.filter((d) => !replacementLabelNorms.has(normalizeKindLabel(d.label)));
}

export function packDescriptorsAfterPaletteEdits(
    descriptors: readonly NodeDescriptor[],
    removedKindIds: readonly string[],
    replacementLabelNorms: ReadonlySet<string>,
): NodeDescriptor[] {
    const removed = new Set(removedKindIds);
    const withoutRemoved = descriptors.filter((d) => !removed.has(d.id));
    return packDescriptorsAfterStagedReplacements(withoutRemoved, replacementLabelNorms);
}

/**
 * One group per installed pack coordinate (`packId@major`).
 * Rows are **newest-first** by canonical `createdAtMs` from `manifest.createdAt`.
 */
export function groupPalettePacks(packTypes: NodeDescriptor[]): PackPaletteGroup[] {
    const byKey = new Map<string, NodeDescriptor[]>();
    for (const d of packTypes) {
        if (d.source !== "pack" || !d.pack) continue;
        const key = `${d.pack.packId}@${d.pack.major}`;
        if (!byKey.has(key)) byKey.set(key, []);
        byKey.get(key)!.push(d);
    }
    return Array.from(byKey.entries())
        .map(([key, descriptors]) => {
            const sorted = [...descriptors].sort(
                (a, b) => (a.paletteOrder ?? 999) - (b.paletteOrder ?? 999),
            );
            const packMeta = sorted[0].pack!;
            const name = packDisplayName(packMeta);
            const label = formatPackSectionLabel(packMeta);
            return { key, name, label, descriptors: sorted };
        })
        .sort((a, b) => {
            const c = paletteGroupCreatedAtMs(b) - paletteGroupCreatedAtMs(a);
            if (c !== 0) return c;
            return a.key.localeCompare(b.key, undefined, { sensitivity: "base" });
        });
}

/** Display name for a fork-family toolbar row — always the root pack's title. */
export function forkFamilyRootDisplayName(
    rootKey: string,
    members: readonly PackPaletteGroup[],
): string {
    const root = findForkFamilyRootPaletteGroup(rootKey, members);
    if (root) return root.name;
    return members[0]?.name ?? rootKey;
}

/**
 * Pack count for the PACKS palette trigger badge: one per dock row (singleton or
 * fork family), plus draft sections while edit mode is on.
 */
export function visiblePaletteTriggerPacksCount(opts: {
    paletteRows: PalettePackRow<PackPaletteGroup>[];
    packsPaletteEditMode: boolean;
    draftPackSectionIds: readonly string[];
}): number {
    let n = opts.paletteRows.length;
    if (opts.packsPaletteEditMode) {
        n += opts.draftPackSectionIds.length;
    }
    return n;
}
