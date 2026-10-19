import type { FeatureCollection } from './geojson';

/** Resolve a prepared resource path from one selected upstream feature. */
export function resolveSelectedResourceTemplate(
    template: string,
    selection: FeatureCollection,
): string {
    if (!template.trim()) throw new Error('An explicit image or network resource path is required. Connect Sidewalk Prepare or configure the resource template.');
    const properties = selection.features[0]?.properties;
    if (!properties) throw new Error('A selected spatial feature is required to load this resource.');
    return template.replace(/\{([a-zA-Z][a-zA-Z0-9_]*)\}/g, (_token, key: string) => {
        const value = properties[key];
        if ((typeof value !== 'string' && typeof value !== 'number')
            || !/^[a-zA-Z0-9_-]+$/.test(String(value))) {
            throw new Error(`Selected feature has no safe ${key} value for the resource path.`);
        }
        return encodeURIComponent(String(value));
    });
}

/** Curio extension: load a prepared GeoJSON file for the selected region/tile. */
export function resolveSelectedGeojsonSources(
    sources: any[],
    selection?: FeatureCollection,
): any[] {
    return sources.map(source => {
        if (typeof source.geojsonFileUrlTemplate !== 'string') return source;
        if (!selection) throw new Error('Select a region or tile before loading its spatial layers.');
        const { geojsonFileUrlTemplate, ...rest } = source;
        return {
            ...rest,
            geojsonFileUrl: resolveSelectedResourceTemplate(geojsonFileUrlTemplate, selection),
        };
    });
}
