/**
 * A building's height, the way autk-map extrudes it.
 *
 * autk-map (autk-core's `TriangulatorBuildings.computeBuildingHeights`) takes a
 * part's top from the first of `height`, `levels` and `building:levels` the
 * part HAS, whatever its value, and its base from the first of `min_height`,
 * `min_level` and `building:min_level`. A part whose top is not above its base
 * is culled. A table gives every row every column, and autk-db's `loadGeojson`
 * gives every feature every key it found, so a building tagged only with
 * `building:levels` arrives with `height: null` and is culled.
 *
 * No autk import here: this stays testable under jest.
 */

/** Metres per level, as autk-map's building renderer counts them. */
export const METRES_PER_LEVEL = 3.4;

const num = (v: any) => { const n = parseFloat(String(v)); return Number.isFinite(n) && n > 0 ? n : 0; };

/** Base and top from the first key that holds a number. */
function valueHeights(props: any): { base: number; top: number } {
    const LEVEL = METRES_PER_LEVEL;
    const base = num(props?.min_height) || LEVEL * num(props?.min_level) || LEVEL * num(props?.['building:min_level']);
    let top = num(props?.height) || LEVEL * num(props?.levels) || LEVEL * num(props?.['building:levels']);
    if (top === 0 && Array.isArray(props?.parts)) {
        for (const p of props.parts) { const h = num(p?.height) || LEVEL * num(p?.levels); if (h > top) top = h; }
    }
    return { base, top };
}

// Guarantee a footprint extrudes instead of being culled as "no valid height
// metadata". autk-map culls a building part when its top height <= its base
// (`min_height`), which also covers the no-height case (0 <= 0). Mirror that
// computation and, only when the part would be culled, return a height that clears
// the base by a visible amount; otherwise return null to leave the real tags
// untouched. `parts` lifting covers a feature whose height lived only per-part.
export function deriveBuildingHeight(props: any): number | null {
    const { base, top } = valueHeights(props);
    return top > base ? null : base + 6;
}

// autk-core's own reading: the first key present wins, and a value that is not
// a number reads as 0.
const autkNum = (v: any) => parseFloat(String(v)) || 0;

function autkTop(p: Record<string, any>): number {
    if ("height" in p) return autkNum(p.height);
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
 * autk-map would read them wrong: a `height` (or `levels`) key with no number
 * in it hides `building:levels`, and a building with no height at all gets the
 * one {@link deriveBuildingHeight} gives it. The same object when autk-map
 * already reads it right.
 */
export function readableBuildingProperties<T extends Record<string, any> | null | undefined>(props: T): T {
    const p: Record<string, any> = props ?? {};
    const { base } = valueHeights(p);
    const top = deriveBuildingHeight(p) ?? valueHeights(p).top;
    const out: Record<string, any> = { ...p };
    let changed = false;
    if (autkBase(p) !== base) { out.min_height = base; changed = true; }
    if (autkTop(p) !== top) { out.height = top; changed = true; }
    return (changed ? out : props) as T;
}
