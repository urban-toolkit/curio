/**
 * Autark maps draw on demand, and a map its node drops is destroyed
 * (adapters/node/autkMapDrawing).
 *
 * autk-grammar starts each map drawing on every animation frame. Curio
 * switches each one to autk-map's on-demand rendering, `draw({ onDemand: true
 * })`: one frame, then a frame only when something asks for one. The first
 * tests pin that on the autk-map Curio installs, as Curio relies on it: the
 * switch stops the loop, `requestRender()` draws once per burst, the map asks
 * for a frame itself when its camera moves or the window resizes, and
 * `destroy()` frees what the map holds. The others drive Curio's own part.
 */
import * as path from "path";

// The autk-map build the app bundles, as CommonJS. A map is made without
// WebGPU, which only its `init()` asks for.
const { AutkMap } = require(path.resolve(
    __dirname, "../../../../node_modules/@urban-toolkit/autk-map/dist/autk-map.umd.cjs",
));

type Started = { map: any; canvas: HTMLCanvasElement; renders: jest.SpyInstance; draws: jest.SpyInstance };

/** A map on a canvas in the page, started as autk-grammar starts it: every frame. */
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

/** Frames *started* draws while the page runs for *ms* milliseconds. */
function framesIn(started: Started, ms = 1000): number {
    const before = started.renders.mock.calls.length;
    runFrames(ms);
    return started.renders.mock.calls.length - before;
}

/** Quiet the console: without WebGPU, `init()` says so, then sets up the rest. */
function quietConsole() {
    jest.spyOn(console, "error").mockImplementation(() => undefined);
    jest.spyOn(console, "warn").mockImplementation(() => undefined);
}

beforeEach(() => {
    jest.useFakeTimers();
    document.body.innerHTML = "";
});

afterEach(() => {
    jest.useRealTimers();
    jest.restoreAllMocks();
});

describe("autk-map's on-demand rendering", () => {
    test("draw({ onDemand: true }) stops the loop the grammar started and draws one frame", () => {
        const started = startedMap();
        expect(framesIn(started)).toBeGreaterThan(10);

        started.map.draw({ onDemand: true });
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("requestRender() draws one frame for a burst of requests, and none without one", () => {
        const started = startedMap();
        started.map.draw({ onDemand: true });
        runFrames(1000);

        started.map.requestRender();
        started.map.requestRender();
        started.map.requestRender();
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("a camera change and a window resize ask for a frame themselves", async () => {
        quietConsole();
        const canvas = document.createElement("canvas");
        document.body.appendChild(canvas);
        const map = new AutkMap(canvas);
        await map.init();
        const started = { map, canvas, renders: jest.spyOn(map, "render").mockImplementation(() => undefined) } as Started;
        map.draw({ onDemand: true });
        runFrames(1000);

        map.camera.resize(320, 200);
        expect(framesIn(started)).toBe(1);

        window.dispatchEvent(new Event("resize"));
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("a destroyed map draws nothing, asked or not", () => {
        const started = startedMap();
        started.map.draw({ onDemand: true });
        runFrames(1000);
        started.map.destroy();

        started.map.requestRender();
        started.map.draw({ onDemand: true });
        expect(framesIn(started)).toBe(0);
        expect(started.map._isDestroyed).toBe(true);
    });

    test("destroy() frees the window resize listener and the controls init() set up", async () => {
        quietConsole();
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

/** A grammar holding *map* as autk-grammar does: once for each layer it draws. */
const grammarOf = (map: any) => ({ _mapRegistry: new Map([["roads", map], ["buildings", map]]) });

describe("drawMapsOnDemand", () => {
    // Loaded in each test, so a page that lacks the module fails the test, not the file.
    let drawMapsOnDemand: (grammar: unknown) => () => void;
    beforeEach(() => {
        jest.isolateModules(() => {
            ({ drawMapsOnDemand } = require("../../../adapters/node/autkMapDrawing"));
        });
    });

    test("each map the grammar made draws on demand, switched once however many layers it draws", () => {
        const started = startedMap();
        drawMapsOnDemand(grammarOf(started.map));

        expect(started.draws).toHaveBeenCalledTimes(1);
        expect(started.draws).toHaveBeenCalledWith({ onDemand: true });
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("every map of a grammar is switched", () => {
        const roads = startedMap();
        const buildings = startedMap();
        drawMapsOnDemand({ _mapRegistry: new Map([["roads", roads.map], ["buildings", buildings.map]]) });

        runFrames(1000);
        expect(framesIn(roads)).toBe(0);
        expect(framesIn(buildings)).toBe(0);
    });

    test("a node that drops its maps destroys them", () => {
        const started = startedMap();
        const destroyMaps = drawMapsOnDemand(grammarOf(started.map));
        runFrames(1000);

        destroyMaps();
        expect(started.map._isDestroyed).toBe(true);
        started.map.requestRender();
        expect(framesIn(started)).toBe(0);
    });

    test("a map that cannot be torn down does not keep the node's other maps", () => {
        const warned = jest.spyOn(console, "warn").mockImplementation(() => undefined);
        const broken = startedMap();
        const other = startedMap();
        jest.spyOn(broken.map, "destroy").mockImplementation(() => { throw new Error("no context"); });
        const destroyMaps = drawMapsOnDemand({ _mapRegistry: new Map([["roads", broken.map], ["buildings", other.map]]) });

        expect(destroyMaps).not.toThrow();
        expect(warned).toHaveBeenCalled();
        expect(other.map._isDestroyed).toBe(true);
    });

    test("a grammar that drew no map is left alone", () => {
        expect(() => drawMapsOnDemand(null)()).not.toThrow();
        expect(() => drawMapsOnDemand({ _mapRegistry: new Map() })()).not.toThrow();
    });
});
