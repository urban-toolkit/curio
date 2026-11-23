/**
 * A building's height, the way autk-map extrudes it.
 *
 * autk-map (autk-core's `TriangulatorBuildings.computeBuildingHeights`) takes a
 * part's top from the first of `height`, `building:height`, `levels` and
 * `building:levels` the part HAS, whatever its value, and its base from the
 * first of `min_height`, `min_level` and `building:min_level`. A part whose top
 * is not above its base is culled, unless its layer sets `buildingsZeroHeight`
 * and it holds none of those four keys: then autk-map raises it at a random 3
 * to 7 floors. A table gives every row every column, and autk-db's
 * `loadGeojson` gives every feature every key it found, so a building tagged
 * only with `building:levels` arrives with `height: null` and is culled.
 *
 * A part with no height keeps none in the data Curio loads and hands on. Where
 * a number is used, Curio takes it to be {@link DEFAULT_BUILDING_HEIGHT} m tall
 * above its base: a map draws it so, and a compute pass reads it so
 * ({@link withDefaultHeight}).
 *
 * No autk import here: this stays testable under jest.
 */

/** Metres per level, as autk-map's building renderer counts them. */
export const METRES_PER_LEVEL = 3.4;

/**
 * How tall, in metres above its base, Curio takes a building part with no
 * height to be where a number is used: as a map draws it and as a compute pass
 * reads it.
 */
export const DEFAULT_BUILDING_HEIGHT = 6;

/** The keys autk-map reads a building part's top from, the first it holds winning. */
export const TOP_KEYS = ['height', 'building:height', 'levels', 'building:levels'] as const;

const num = (v: any) => { const n = parseFloat(String(v)); return Number.isFinite(n) && n > 0 ? n : 0; };

/** Base and top from the first key that holds a number. */
function valueHeights(props: any): { base: number; top: number } {
    const LEVEL = METRES_PER_LEVEL;
    const base = num(props?.min_height) || LEVEL * num(props?.min_level) || LEVEL * num(props?.['building:min_level']);
    let top = num(props?.height) || num(props?.['building:height'])
        || LEVEL * num(props?.levels) || LEVEL * num(props?.['building:levels']);
    if (top === 0 && Array.isArray(props?.parts)) {
        for (const p of props.parts) { const h = num(p?.height) || LEVEL * num(p?.levels); if (h > top) top = h; }
    }
    return { base, top };
}

/**
 * The height Curio takes a building part with no height above its base to
 * have where a number is used, {@link DEFAULT_BUILDING_HEIGHT} m above that
 * base; null for a part with a height, whose own tags stay. autk-map culls a
 * part when its top height <= its base (`min_height`), which also covers the
 * no-height case (0 <= 0). `parts` lifting covers a feature whose height lived
 * only per part.
 */
export function deriveBuildingHeight(props: any): number | null {
    const { base, top } = valueHeights(props);
    return top > base ? null : base + DEFAULT_BUILDING_HEIGHT;
}

// autk-core's own reading: the first key present wins, and a value that is not
// a number reads as 0.
const autkNum = (v: any) => parseFloat(String(v)) || 0;

function autkTop(p: Record<string, any>): number {
    if ("height" in p) return autkNum(p.height);
    if ("building:height" in p) return autkNum(p["building:height"]);
    if ("levels" in p) return METRES_PER_LEVEL * autkNum(p.levels);
    if ("building:levels" in p) return METRES_PER_LEVEL * autkNum(p["building:levels"]);
    return 0;
}

function autkBase(p: Record<string, any>): number {
    if ("min_height" in p) return autkNum(p.min_height);
    if ("min_level" in p && autkNum(p.min_level) >= 0) return METRES_PER_LEVEL * autkNum(p.min_level);
    if ("building:min_level" in p) return METRES_PER_LEVEL * autkNum(p["building:min_level"]);
    return 0;
}

/**
 * A building's properties with `height` and `min_height` written where
 * autk-map would read the height the building holds wrong: a `height` (or
 * `levels`) key with no number in it hides `building:levels`. A building with
 * a height and no `height` key gets the height autk-map draws, so a compute
 * that reads `properties.height` reads it too, whether or not a table handed
 * the building on. A building with no height keeps none. The same object when
 * nothing changes.
 */
export function readableBuildingProperties<T extends Record<string, any> | null | undefined>(props: T): T {
    const p: Record<string, any> = props ?? {};
    const { base, top } = valueHeights(p);
    const out: Record<string, any> = { ...p };
    let changed = false;
    if (autkBase(p) !== base) { out.min_height = base; changed = true; }
    if (top > base && (autkTop(p) !== top || !("height" in p))) { out.height = top; changed = true; }
    return (changed ? out : props) as T;
}

/**
 * *fc*, a buildings table, with each feature's properties as a map reads them
 * ({@link readableBuildingProperties}): the same object when no feature
 * changes, and each feature that does not change the same object.
 */
export function readableBuildingFeatures<C extends { features?: readonly any[] }>(fc: C): C {
    const features: readonly any[] = Array.isArray(fc?.features) ? fc.features : [];
    let changed = false;
    const next = features.map((feature) => {
        const properties = feature?.properties;
        const readable = readableBuildingProperties(properties);
        if (readable === properties) return feature;
        changed = true;
        return { ...feature, properties: readable };
    });
    return (changed ? { ...fc, features: next } : fc) as C;
}

/**
 * A building's properties as a map draws it and a compute pass reads it: its
 * readable ones ({@link readableBuildingProperties}), and, for a building with
 * no height above its base, a `height` {@link DEFAULT_BUILDING_HEIGHT} m above
 * that base ({@link deriveBuildingHeight}). The same object when nothing
 * changes.
 */
export function withDefaultHeight<T extends Record<string, any> | null | undefined>(props: T): T {
    const readable: Record<string, any> | null | undefined = readableBuildingProperties(props);
    const height = deriveBuildingHeight(readable ?? {});
    return (height === null ? readable : { ...(readable ?? {}), height }) as T;
}

/** Whether *value* holds a number autk-map reads: a number, or text that starts with one. */
const holdsNumber = (value: unknown): boolean => Number.isFinite(parseFloat(String(value)));

/** *part* without the keys of TOP_KEYS that hold no number; the same object when it has none. */
function partWithoutEmptyHeights(part: Record<string, any>): Record<string, any> {
    const empty = TOP_KEYS.filter((key) => key in part && !holdsNumber(part[key]));
    if (empty.length === 0) return part;
    const out: Record<string, any> = { ...part };
    for (const key of empty) delete out[key];
    return out;
}

/**
 * A building's properties without the keys autk-map reads its top from that
 * hold no number (a `height` of null, an empty `levels`), on the building and
 * on each of its `parts`: autk-map's `buildingsZeroHeight` draws a part at a
 * random height of 3 to 7 floors only when it holds none of those keys, and
 * reads the first of them a part holds, so such a key would leave the part
 * out, or hide the levels after it. The same object when no key holds no number.
 */
export function withoutEmptyHeights<T extends Record<string, any> | null | undefined>(props: T): T {
    if (props === null || props === undefined || typeof props !== 'object') return props;
    const out = partWithoutEmptyHeights(props as Record<string, any>);
    const parts = (props as Record<string, any>).parts;
    if (!Array.isArray(parts)) return out as T;
    const cleaned = parts.map((part) => (part && typeof part === 'object' ? partWithoutEmptyHeights(part) : part));
    if (cleaned.every((part, at) => part === parts[at])) return out as T;
    return { ...out, parts: cleaned } as unknown as T;
}
