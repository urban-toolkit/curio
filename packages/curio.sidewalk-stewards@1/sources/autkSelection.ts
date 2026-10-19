/** Curio's interaction bus carries selections independently of a node's data output. */
export type AutkSelectionChannel = 'map-pick' | 'plot-brush';

/** The legacy row set remains available, while origin v1 identifies the one
 * map click (if any) independently of a multi-row plot brush. */
export function latestAutkSelection(interactions: unknown): {
    indices: number[];
    kind: 'map-pick' | 'plot-brush' | 'legacy';
    activeIndex: number | null;
    candidateIndices: number[];
    featureId: string | null;
    feature: any | null;
    /** Identity of the delivered event; a remembered map pick must not undo local navigation on rerender. */
    event: unknown;
    layerRef: string | null;
} | null {
    if (!Array.isArray(interactions)) return null;
    const events = interactions.flatMap((interaction: any) => {
        const detail = interaction?.details?.autk_selection;
        if (!detail || !Array.isArray(detail.data)) return [];
        return [{ priority: Number(detail.priority ?? interaction.priority ?? 0), detail }];
    });
    if (!events.length) return null;
    const priority = Math.max(...events.map(event => event.priority));
    const detail = events.filter(event => event.priority === priority).at(-1)!.detail;
    const indices = detail.data.filter((value: unknown) => Number.isInteger(value) && Number(value) >= 0);
    const origin = detail.selectionOrigin;
    const kind = origin?.version === 1 && (origin.kind === 'map-pick' || origin.kind === 'plot-brush')
        ? origin.kind : 'legacy';
    return {
        indices,
        kind,
        activeIndex: kind === 'map-pick' && Number.isInteger(origin.activeIndex) && origin.activeIndex >= 0
            ? origin.activeIndex : null,
        candidateIndices: kind === 'plot-brush' ? indices : [],
        featureId: typeof detail.featureId === 'string' ? detail.featureId : null,
        feature: detail.feature?.type === 'Feature' ? detail.feature : null,
        event: detail,
        layerRef: typeof detail.layerRef === 'string' ? detail.layerRef : null,
    };
}

function stableFeatureId(feature: any): string | null {
    const properties = feature?.properties;
    const value = properties?.tile_id ?? properties?.tileId ?? properties?.id;
    return typeof value === 'string' || typeof value === 'number' ? String(value) : null;
}

/** Stable IDs let linked selections survive different row ordering in map and plot inputs. */
export function featureIdsForSelection(collection: any, indices: number[]): string[] {
    if (!Array.isArray(collection?.features)) return [];
    return [...new Set(indices
        .map(index => collection.features[index])
        .map(stableFeatureId)
        .filter((id): id is string => id !== null))];
}

/** Resolve stable feature IDs to indices for the receiving Autark layer. */
export function featureIndicesForIds(collection: any, ids: string[]): number[] {
    if (!Array.isArray(collection?.features)) return [];
    const wanted = new Set(ids.map(String));
    const features: any[] = collection.features;
    return features.reduce((matches: number[], feature: any, index: number) => {
        const id = stableFeatureId(feature);
        if (id !== null && wanted.has(id)) matches.push(index);
        return matches;
    }, []);
}

/** Latest stable feature IDs for a channel, or null when it has not emitted IDs. */
export function featureIdsForChannel(interactions: unknown, channel: AutkSelectionChannel): string[] | null {
    if (!Array.isArray(interactions)) return null;
    const matches = interactions.flatMap((interaction: any) => {
        const detail = interaction?.details?.autk_selection;
        if (detail?.channel !== channel || !Array.isArray(detail.featureIds)) return [];
        return [{ priority: Number(detail.priority ?? interaction.priority ?? 0), ids: detail.featureIds }];
    });
    if (matches.length === 0) return null;
    const priority = Math.max(...matches.map(item => item.priority));
    return [...new Set(matches.filter(item => item.priority === priority).flatMap(item => item.ids.map(String)))];
}

/** Latest selected row indices for one channel, or null when that channel has no event. */
export function selectionForChannel(interactions: unknown, channel: AutkSelectionChannel): number[] | null {
    if (!Array.isArray(interactions)) return null;
    const matches = interactions.flatMap((interaction: any) => {
        const detail = interaction?.details?.autk_selection;
        if (detail?.channel !== channel) return [];
        const indices = Array.isArray(detail.data)
            ? detail.data.filter((index: unknown) => Number.isInteger(index) && Number(index) >= 0) as number[]
            : [];
        return [{ priority: Number(detail.priority ?? interaction.priority ?? 0), indices }];
    });
    if (matches.length === 0) return null;
    const priority = Math.max(...matches.map(item => item.priority));
    return [...new Set(matches.filter(item => item.priority === priority).flatMap(item => item.indices))];
}

export function featureIdForChannel(interactions: unknown, channel: AutkSelectionChannel): string | null {
    if (!Array.isArray(interactions)) return null;
    const matches = interactions.flatMap((interaction: any) => {
        const detail = interaction?.details?.autk_selection;
        if (detail?.channel !== channel) return [];
        return [{ priority: Number(detail.priority ?? interaction.priority ?? 0), id: detail.featureId }];
    });
    if (matches.length === 0) return null;
    const priority = Math.max(...matches.map(item => item.priority));
    const latest = matches.filter(item => item.priority === priority).at(-1);
    return typeof latest?.id === 'string' && latest.id ? latest.id : null;
}

/** The picked GeoJSON feature, carried with a map-pick so downstream tools do
 * not need to reconstruct a click from a possibly wrapped data artifact. */
export function featureForChannel(interactions: unknown, channel: AutkSelectionChannel): any | null {
    if (!Array.isArray(interactions)) return null;
    const matches = interactions.flatMap((interaction: any) => {
        const detail = interaction?.details?.autk_selection;
        if (detail?.channel !== channel || !detail.feature || typeof detail.feature !== 'object') return [];
        return [{ priority: Number(detail.priority ?? interaction.priority ?? 0), feature: detail.feature }];
    });
    if (matches.length === 0) return null;
    const priority = Math.max(...matches.map(item => item.priority));
    return matches.filter(item => item.priority === priority).at(-1)?.feature ?? null;
}
