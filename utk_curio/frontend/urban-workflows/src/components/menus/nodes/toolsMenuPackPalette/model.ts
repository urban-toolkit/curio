import { PACK_STAGING_MIME } from "../../../../constants/packPaletteStaging";
import { draftPackSectionKey, type PackStagedRow } from "../../../../providers/PackPaletteContext";
import { NodeDescriptor, NodePackMeta } from "../../../../registry/types";
import {
    paletteGroupCreatedAtMs,
    resolveForkFamilySelectionKey,
    type PalettePackRow,
} from "../../../../utils/forkPackLineage";

export interface PackPaletteGroup {
    key: string;
    label: string;
    descriptors: NodeDescriptor[];
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

export function formatPackSectionLabel(meta: NodePackMeta): string {
    const coord = `${meta.packId}@${meta.major}`;
    if (meta.publisher?.trim()) {
        return `${meta.publisher} · ${coord}`;
    }
    return coord;
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
            const label = formatPackSectionLabel(sorted[0].pack!);
            return { key, label, descriptors: sorted };
        })
        .sort((a, b) => {
            const c = paletteGroupCreatedAtMs(b) - paletteGroupCreatedAtMs(a);
            if (c !== 0) return c;
            return a.key.localeCompare(b.key, undefined, { sensitivity: "base" });
        });
}

/**
 * Mirrors what the PACKS dropdown lists: filtered groups only; fork-family rows count the
 * **selected** fork's kinds (+ staged canvas rows when edit mode is on).
 */
export function visiblePaletteTriggerKindsCount(opts: {
    paletteRows: PalettePackRow<PackPaletteGroup>[];
    packsPaletteEditMode: boolean;
    stagedRowsByPackKey: Readonly<Record<string, readonly PackStagedRow[]>>;
    draftPackSectionIds: readonly string[];
    activePackKey: string | null;
    forkManualPickByRoot: Record<string, string>;
}): number {
    const {
        paletteRows,
        packsPaletteEditMode,
        stagedRowsByPackKey,
        draftPackSectionIds,
        activePackKey,
        forkManualPickByRoot,
    } = opts;

    let n = 0;
    if (packsPaletteEditMode) {
        for (const draftId of draftPackSectionIds) {
            const sectionKey = draftPackSectionKey(draftId);
            n += (stagedRowsByPackKey[sectionKey] ?? []).length;
        }
    }
    const activeKey = activePackKey ?? "";
    for (const row of paletteRows) {
        if (row.kind === "singleton") {
            const staged = stagedRowsByPackKey[row.group.key] ?? [];
            n += row.group.descriptors.length + (packsPaletteEditMode ? staged.length : 0);
            continue;
        }
        const resolverMembers = row.members.map((m) => ({ key: m.key }));
        const resolvedDir = resolveForkFamilySelectionKey(
            row.rootKey,
            resolverMembers,
            activeKey,
            forkManualPickByRoot[row.rootKey],
        );
        const g = row.members.find((m) => m.key === resolvedDir) ?? row.members[0]!;
        const staged = stagedRowsByPackKey[g.key] ?? [];
        n += g.descriptors.length + (packsPaletteEditMode ? staged.length : 0);
    }
    return n;
}
