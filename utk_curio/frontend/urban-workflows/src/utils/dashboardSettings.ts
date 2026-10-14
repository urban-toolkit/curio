/**
 * The dashboard's own settings, saved with the dataflow as `dataflow.dashboard`:
 * where its Run button stands and how big it is. A tile's place is its node's
 * (`dashboardX`, `dashboardY`, `dashboardWidth`, `dashboardHeight`); the Run
 * button is no node, so it is kept here.
 *
 * Pure, so the load and the save share one reading of it.
 */

/** A point on the dashboard page, in its flow coordinates. */
export interface DashboardPoint {
    x: number;
    y: number;
}

/** Where the Run button stands, and its size once it was resized. */
export interface RunButtonPlace extends DashboardPoint {
    width?: number;
    height?: number;
}

export interface DashboardSettings {
    /** The Run button's place; absent until the owner moves or resizes it. */
    runButton?: RunButtonPlace;
}

/** The Run button's size until it is resized, in the page's coordinates. */
export const RUN_BUTTON_SIZE = { width: 56, height: 44 } as const;

/** The smallest the Run button can be made. */
export const RUN_BUTTON_MIN_SIZE = { width: 36, height: 32 } as const;

/** How far above the tiles the Run button stands when nobody placed it. */
const DEFAULT_GAP = 64;

const isFiniteNumber = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value);

const isObject = (value: unknown): value is Record<string, unknown> =>
    value != null && typeof value === "object" && !Array.isArray(value);

/** *raw* as settings: what it holds that is well formed, nothing else. */
export function normalizeDashboardSettings(raw: unknown): DashboardSettings {
    if (!isObject(raw)) return {};
    const place = raw.runButton;
    if (!isObject(place) || !isFiniteNumber(place.x) || !isFiniteNumber(place.y)) return {};
    const runButton: RunButtonPlace = { x: place.x, y: place.y };
    // A size is kept as a pair, and only one that is positive.
    if (isFiniteNumber(place.width) && isFiniteNumber(place.height) && place.width > 0 && place.height > 0) {
        runButton.width = place.width;
        runButton.height = place.height;
    }
    return { runButton };
}

/** The settings as the spec stores them, or undefined when there are none. */
export function serializeDashboardSettings(settings: DashboardSettings): DashboardSettings | undefined {
    const normalized = normalizeDashboardSettings(settings);
    return Object.keys(normalized).length > 0 ? normalized : undefined;
}

/**
 * Where the Run button stands and how big it is: as the owner left it, else
 * above the top-left tile, so it shows without covering one, at its own size.
 */
export function runButtonPlace(
    settings: DashboardSettings,
    tiles: readonly { position: { x: number; y: number } }[],
): Required<RunButtonPlace> {
    const saved = settings.runButton;
    const width = saved?.width ?? RUN_BUTTON_SIZE.width;
    const height = saved?.height ?? RUN_BUTTON_SIZE.height;
    if (saved) return { x: saved.x, y: saved.y, width, height };
    if (tiles.length === 0) return { x: 0, y: 0, width, height };
    const x = Math.min(...tiles.map((tile) => tile.position.x));
    const y = Math.min(...tiles.map((tile) => tile.position.y));
    return { x, y: y - DEFAULT_GAP, width, height };
}
