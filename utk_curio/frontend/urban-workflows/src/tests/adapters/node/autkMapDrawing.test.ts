/**
 * An Autark map draws only while its canvas has a layout box, and a map its
 * node drops is destroyed (adapters/node/autkMapDrawing).
 *
 * autk-map renders a started map on every animation frame until the map is
 * destroyed. Curio stops that loop for a map whose canvas has no layout box
 * (`display: none` above it, or out of the page) by cancelling the frame
 * autk-map keeps in `_animationFrameId`, and starts it again with autk-map's
 * own `draw()`; a map nobody will see again goes through its `destroy()`. The
 * first tests pin that on the autk-map Curio installs, so a release that loops
 * or tears down another way fails here instead of letting hidden maps draw
 * again. The others drive Curio's rule through a ResizeObserver whose reports
 * the test makes; jsdom lays nothing out, so each canvas's layout box is set
 * by the test.
 */
import * as path from "path";

// The autk-map build the app bundles, as CommonJS. A map is made without
// WebGPU, which only its `init()` asks for.
const { AutkMap } = require(path.resolve(
    __dirname, "../../../../node_modules/@urban-toolkit/autk-map/dist/autk-map.umd.cjs",
));

type Started = { map: any; canvas: HTMLCanvasElement; renders: jest.SpyInstance; draws: jest.SpyInstance };

/** A map on a canvas in the page, started as autk-grammar starts it. */
function startedMap(canvas: HTMLCanvasElement = document.createElement("canvas")): Started {
    if (!canvas.isConnected) document.body.appendChild(canvas);
    const map = new AutkMap(canvas);
    // jsdom has nothing to draw with: count the frames instead.
    const renders = jest.spyOn(map, "render").mockImplementation(() => undefined);
    map.draw();
    const draws = jest.spyOn(map, "draw");
    return { map, canvas, renders, draws };
}

/** Let the page run its animation frames for *ms* milliseconds. */
const runFrames = (ms: number) => jest.advanceTimersByTime(ms);

beforeEach(() => {
    jest.useFakeTimers();
    document.body.innerHTML = "";
});

afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
});

describe("autk-map's frame loop", () => {
    test("a started map draws on every frame, and stops once the frame it keeps is cancelled", () => {
        const { map, renders } = startedMap();
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(10);
        expect(typeof map._animationFrameId).toBe("number");

        cancelAnimationFrame(map._animationFrameId);
        map._animationFrameId = null;
        const stopped = renders.mock.calls.length;
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(stopped);
    });

    test("draw() starts a stopped map again", () => {
        const { map, renders } = startedMap();
        cancelAnimationFrame(map._animationFrameId);
        map._animationFrameId = null;
        runFrames(1000);
        const stopped = renders.mock.calls.length;

        map.draw();
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(stopped + 10);
        expect(typeof map._animationFrameId).toBe("number");
    });

    test("a destroyed map stays stopped, draw() or not", () => {
        const { map, renders } = startedMap();
        map.destroy();
        const destroyed = renders.mock.calls.length;

        map.draw();
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(destroyed);
        expect(map._animationFrameId).toBeNull();
        expect(map._isDestroyed).toBe(true);
    });

    test("destroy() frees the window resize listener and the controls init() set up", async () => {
        // Without WebGPU, init() says so and sets up the rest as autk-grammar's call does.
        jest.spyOn(console, "error").mockImplementation(() => undefined);
        jest.spyOn(console, "warn").mockImplementation(() => undefined);
        const host = document.createElement("div");
        const canvas = document.createElement("canvas");
        host.appendChild(canvas);
        document.body.appendChild(host);
        const map = new AutkMap(canvas);
        await map.init();
        const resized = jest.spyOn(map.renderer, "resize");
        const controls = () => [...host.children].filter((child) => child !== canvas).length;
        expect(controls()).toBeGreaterThan(0);

        window.dispatchEvent(new Event("resize"));
        expect(resized).toHaveBeenCalledTimes(1);

        map.destroy();
        window.dispatchEvent(new Event("resize"));
        expect(resized).toHaveBeenCalledTimes(1);
        expect(controls()).toBe(0);
    });
});

/** A ResizeObserver whose reports the test makes. */
class Watcher {
    static last: Watcher | null = null;
    readonly watched = new Set<Element>();
    constructor(readonly callback: ResizeObserverCallback) {
        Watcher.last = this;
    }
    observe(target: Element) { this.watched.add(target); }
    unobserve(target: Element) { this.watched.delete(target); }
    disconnect() { this.watched.clear(); }
}

/** One batch of reports, one for each canvas whose size changed. */
function report(...canvases: Element[]) {
    const watcher = Watcher.last;
    if (!watcher) throw new Error("nothing made a ResizeObserver");
    watcher.callback(
        canvases.map((target) => ({ target }) as ResizeObserverEntry),
        watcher as unknown as ResizeObserver,
    );
}

/**
 * Give *canvas* a layout box at *at* (left, top), or take it away, as showing
 * or hiding it with `display: none` does.
 */
function layOut(canvas: Element, laidOut: boolean, at: [number, number] = [0, 0]) {
    const box = { x: at[0], y: at[1], left: at[0], top: at[1], right: at[0] + 300, bottom: at[1] + 200, width: 300, height: 200 };
    Object.defineProperty(canvas, "getClientRects", {
        configurable: true,
        value: () => (laidOut ? [box] : []),
    });
    Object.defineProperty(canvas, "getBoundingClientRect", {
        configurable: true,
        value: () => (laidOut ? box : { ...box, right: 0, bottom: 0, width: 0, height: 0 }),
    });
}

/** A started map whose canvas has a layout box. */
function shownMap(canvas?: HTMLCanvasElement): Started {
    const started = startedMap(canvas);
    layOut(started.canvas, true);
    return started;
}

/** A grammar holding *map* as autk-grammar does: once for each layer it draws. */
const grammarOf = (map: any) => ({ _mapRegistry: new Map([["roads", map], ["buildings", map]]) });

describe("drawMapsWhileShown", () => {
    let drawMapsWhileShown: (grammar: unknown) => () => void;

    /** The module as the page loads it, with or without a ResizeObserver. */
    const load = (observer: unknown) => {
        (window as any).ResizeObserver = observer;
        Watcher.last = null;
        jest.isolateModules(() => {
            ({ drawMapsWhileShown } = require("../../../adapters/node/autkMapDrawing"));
        });
    };

    beforeEach(() => load(Watcher));

    afterEach(() => {
        delete (window as any).ResizeObserver;
    });

    test("a map draws while its canvas has a layout box, and only then", () => {
        const { map, canvas, renders } = shownMap();
        drawMapsWhileShown(grammarOf(map));
        expect(Watcher.last!.watched.size).toBe(1);
        expect(Watcher.last!.watched.has(canvas)).toBe(true);
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(10);

        layOut(canvas, false);
        report(canvas);
        const hidden = renders.mock.calls.length;
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(hidden);

        layOut(canvas, true);
        report(canvas);
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(hidden + 10);
    });

    test("a canvas with no box when its map is handed over stops the map at once, with no report", () => {
        // A ResizeObserver reports nothing for a canvas that starts with no box:
        // a map run inside a collapsed scenario.
        const { map, canvas, renders } = startedMap();
        layOut(canvas, false);
        drawMapsWhileShown(grammarOf(map));
        const hidden = renders.mock.calls.length;
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(hidden);

        layOut(canvas, true);
        report(canvas);
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(hidden + 10);
    });

    test("a canvas laid out outside the window keeps its map drawing", () => {
        const { map, canvas, renders } = startedMap();
        layOut(canvas, true, [-5000, 4000]);
        drawMapsWhileShown(grammarOf(map));
        report(canvas);
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(10);
    });

    test("a map that draws is not started again, and a stopped one starts once", () => {
        const { map, canvas, draws } = shownMap();
        drawMapsWhileShown(grammarOf(map));

        report(canvas);
        report(canvas);
        expect(draws).not.toHaveBeenCalled();

        layOut(canvas, false);
        report(canvas);
        report(canvas);
        layOut(canvas, true);
        report(canvas);
        report(canvas);
        expect(draws).toHaveBeenCalledTimes(1);
    });

    test("a destroyed map is not started again", () => {
        const { map, canvas, renders, draws } = startedMap();
        layOut(canvas, false);
        drawMapsWhileShown(grammarOf(map));
        map.destroy();

        layOut(canvas, true);
        report(canvas);
        runFrames(1000);
        expect(draws).not.toHaveBeenCalled();
        expect(renders.mock.calls.length).toBe(0);
    });

    test("a canvas that left the page stops its map and is no longer watched", () => {
        const { map, canvas, renders } = shownMap();
        drawMapsWhileShown(grammarOf(map));

        canvas.remove();
        report(canvas);
        expect(Watcher.last!.watched.size).toBe(0);
        const left = renders.mock.calls.length;
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(left);
    });

    test("a node that drops its maps destroys them, wherever their canvases are", () => {
        const { map, canvas, renders } = shownMap();
        const destroyMaps = drawMapsWhileShown(grammarOf(map));

        destroyMaps();
        expect(map._isDestroyed).toBe(true);
        expect(Watcher.last!.watched.size).toBe(0);
        const dropped = renders.mock.calls.length;
        report(canvas);
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(dropped);
    });

    test("a map that cannot be torn down still stops, and the node's other maps are destroyed", () => {
        const warned = jest.spyOn(console, "warn").mockImplementation(() => undefined);
        const broken = shownMap();
        const other = shownMap();
        jest.spyOn(broken.map, "destroy").mockImplementation(() => { throw new Error("no context"); });
        const grammar = { _mapRegistry: new Map([["roads", broken.map], ["buildings", other.map]]) };
        const destroyMaps = drawMapsWhileShown(grammar);

        expect(destroyMaps).not.toThrow();
        expect(warned).toHaveBeenCalled();
        expect(other.map._isDestroyed).toBe(true);
        const dropped = broken.renders.mock.calls.length;
        runFrames(1000);
        expect(broken.renders.mock.calls.length).toBe(dropped);
    });

    test("a canvas given a new map stops the one it had, which keeps the context they share", () => {
        const first = shownMap();
        drawMapsWhileShown(grammarOf(first.map));

        const second = startedMap(first.canvas);
        drawMapsWhileShown(grammarOf(second.map));
        const replaced = first.renders.mock.calls.length;
        runFrames(1000);
        expect(first.renders.mock.calls.length).toBe(replaced);
        expect(second.renders.mock.calls.length).toBeGreaterThan(10);
        expect(Watcher.last!.watched.size).toBe(1);
        expect(Watcher.last!.watched.has(first.canvas)).toBe(true);
        // Destroying it would unconfigure the canvas the new map draws on.
        expect(first.map._isDestroyed).toBe(false);
    });

    test("without a ResizeObserver a map keeps its own loop until its node destroys it", () => {
        load(undefined);
        const { map, canvas, renders } = startedMap();
        layOut(canvas, false);
        const destroyMaps = drawMapsWhileShown(grammarOf(map));
        runFrames(1000);
        expect(renders.mock.calls.length).toBeGreaterThan(10);

        destroyMaps();
        expect(map._isDestroyed).toBe(true);
        const dropped = renders.mock.calls.length;
        runFrames(1000);
        expect(renders.mock.calls.length).toBe(dropped);
    });

    test("a grammar that drew no map is left alone", () => {
        expect(() => drawMapsWhileShown(null)()).not.toThrow();
        expect(() => drawMapsWhileShown({ _mapRegistry: new Map() })()).not.toThrow();
        expect(Watcher.last?.watched.size ?? 0).toBe(0);
    });
});
