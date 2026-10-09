/**
 * Autark maps draw on demand, and a map its node drops is destroyed
 * (adapters/node/autkMapDrawing).
 *
 * autk-grammar starts each map with autk-map's `draw()`, which draws on
 * demand: one frame, then a frame only when something asks for one. The first
 * tests pin that on the autk-map Curio installs, as Curio relies on it:
 * `draw()` draws once and then rests, `requestRender()` draws once per burst,
 * the map asks for a frame itself when its camera moves or the window resizes,
 * and `destroy()` frees what the map holds. The others drive Curio's own part:
 * the maps a node keeps draw nothing while nothing changes them and are
 * destroyed when it drops them, and `renderMapsForReading`, through which a
 * reader of map pixels reads each map in the frame that renders it.
 */
import * as path from "path";

// The autk-map build the app bundles, as CommonJS. A map is made without
// WebGPU, which only its `init()` asks for.
const { AutkMap } = require(path.resolve(
    __dirname, "../../../../node_modules/@urban-toolkit/autk-map/dist/autk-map.umd.cjs",
));

type Started = { map: any; canvas: HTMLCanvasElement; renders: jest.SpyInstance };

/** A map on a canvas in the page, started as autk-grammar starts it: `draw()`. */
function startedMap(canvas: HTMLCanvasElement = document.createElement("canvas")): Started {
    if (!canvas.isConnected) document.body.appendChild(canvas);
    const map = new AutkMap(canvas);
    // jsdom has nothing to draw with: count the frames instead.
    const renders = jest.spyOn(map, "render").mockImplementation(() => undefined);
    map.draw();
    return { map, canvas, renders };
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
    test("draw(), as autk-grammar starts a map, draws one frame, then none until something asks for one", () => {
        const started = startedMap();
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("requestRender() draws one frame for a burst of requests, and none without one", () => {
        const started = startedMap();
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
        map.draw();
        runFrames(1000);

        map.camera.resize(320, 200);
        expect(framesIn(started)).toBe(1);

        window.dispatchEvent(new Event("resize"));
        expect(framesIn(started)).toBe(1);
        expect(framesIn(started)).toBe(0);
    });

    test("a destroyed map draws nothing, asked or not", () => {
        const started = startedMap();
        runFrames(1000);
        started.map.destroy();

        started.map.requestRender();
        started.map.draw();
        started.map.draw(60);
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

describe("trackMaps", () => {
    // Loaded in each test, so a page that lacks the module fails the test, not the file.
    let trackMaps: (grammar: unknown) => () => void;
    beforeEach(() => {
        jest.isolateModules(() => {
            ({ trackMaps } = require("../../../adapters/node/autkMapDrawing"));
        });
    });

    test("each map the grammar made draws its frame, then nothing while nothing changes it", () => {
        const roads = startedMap();
        const buildings = startedMap();
        trackMaps({ _mapRegistry: new Map([["roads", roads.map], ["buildings", buildings.map], ["water", roads.map]]) });

        runFrames(1000);
        expect(roads.renders).toHaveBeenCalledTimes(1);
        expect(buildings.renders).toHaveBeenCalledTimes(1);
        expect(framesIn(roads)).toBe(0);
        expect(framesIn(buildings)).toBe(0);
    });

    test("a node that drops its maps destroys them", () => {
        const started = startedMap();
        const destroyMaps = trackMaps(grammarOf(started.map));
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
        const destroyMaps = trackMaps({ _mapRegistry: new Map([["roads", broken.map], ["buildings", other.map]]) });

        expect(destroyMaps).not.toThrow();
        expect(warned).toHaveBeenCalled();
        expect(other.map._isDestroyed).toBe(true);
    });

    test("a grammar that drew no map is left alone", () => {
        expect(() => trackMaps(null)()).not.toThrow();
        expect(() => trackMaps({ _mapRegistry: new Map() })()).not.toThrow();
    });
});

/**
 * The page's animation frames, run by hand the way a browser runs them: each
 * callback, then the microtasks it queued, then the next callback; a callback
 * asked for during a frame waits for the next one. A frame ends ("frame end")
 * after its last callback: the browser then presents what the frame rendered,
 * and a canvas read later reads that presented picture, not the frame's.
 */
function framesByHand() {
    const asked = new Map<number, FrameRequestCallback>();
    let next = 1;
    const real = { request: window.requestAnimationFrame, cancel: window.cancelAnimationFrame };
    window.requestAnimationFrame = (callback: FrameRequestCallback) => {
        asked.set(next, callback);
        return next++;
    };
    window.cancelAnimationFrame = (id: number) => {
        asked.delete(id);
    };
    const microtasks = async () => {
        for (let turn = 0; turn < 20; turn++) await Promise.resolve();
    };
    return {
        async run(log: string[] = []) {
            for (const id of [...asked.keys()]) {
                const callback = asked.get(id);
                if (!callback) continue;
                asked.delete(id);
                callback(0);
                await microtasks();
            }
            log.push("frame end");
        },
        restore() {
            window.requestAnimationFrame = real.request;
            window.cancelAnimationFrame = real.cancel;
        },
    };
}

describe("renderMapsForReading", () => {
    // Loaded in each test, so a page that lacks the module fails the test, not the file.
    let trackMaps: (grammar: unknown) => () => void;
    let renderMapsForReading: () => Promise<void>;
    let frames: ReturnType<typeof framesByHand>;
    beforeEach(() => {
        jest.isolateModules(() => {
            ({ trackMaps, renderMapsForReading } = require("../../../adapters/node/autkMapDrawing"));
        });
        frames = framesByHand();
    });
    afterEach(() => frames.restore());

    /** *started*'s map, kept by its node, its first frame drawn; *log* gets its renders from now on. */
    async function kept(started: Started, name: string, log: string[]) {
        const destroyMaps = trackMaps(grammarOf(started.map));
        await frames.run();
        started.renders.mockImplementation(() => {
            log.push(`${name} rendered`);
        });
        return destroyMaps;
    }

    test("every map a node keeps renders once, and the reader goes on in that frame, before it ends", async () => {
        const log: string[] = [];
        await kept(startedMap(), "roads", log);
        await kept(startedMap(), "buildings", log);

        const read = renderMapsForReading().then(() => {
            log.push("read");
        });
        await frames.run(log);
        await frames.run(log);
        await read;
        expect(log).toEqual(["roads rendered", "buildings rendered", "read", "frame end", "frame end"]);
    });

    test("a map already waiting for its frame renders once, before the reader", async () => {
        const log: string[] = [];
        const started = startedMap();
        await kept(started, "map", log);
        started.map.requestRender();

        const read = renderMapsForReading().then(() => {
            log.push("read");
        });
        await frames.run(log);
        await frames.run(log);
        await read;
        expect(log).toEqual(["map rendered", "read", "frame end", "frame end"]);
    });

    test("a map its node dropped is not asked, and the others still are", async () => {
        const log: string[] = [];
        const dropped = startedMap();
        const destroyDropped = await kept(dropped, "dropped", log);
        await kept(startedMap(), "kept", log);
        destroyDropped();
        const askedDropped = jest.spyOn(dropped.map, "requestRender");

        const read = renderMapsForReading().then(() => {
            log.push("read");
        });
        await frames.run(log);
        await read;
        expect(askedDropped).not.toHaveBeenCalled();
        expect(log).toEqual(["kept rendered", "read", "frame end"]);
    });

    test("with no map on the page, the reader goes on in the next frame", async () => {
        const log: string[] = [];
        const read = renderMapsForReading().then(() => {
            log.push("read");
        });
        await frames.run(log);
        await read;
        expect(log).toEqual(["read", "frame end"]);
    });

    test("in a hidden page, which runs no frames, the reader goes on at once and no map is asked", async () => {
        const started = startedMap();
        await kept(started, "map", []);
        const asked = jest.spyOn(started.map, "requestRender");
        jest.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");

        await expect(renderMapsForReading()).resolves.toBeUndefined();
        expect(asked).not.toHaveBeenCalled();
    });

    test("the page holds it for the e2e captures, which read maps the same way", () => {
        expect(typeof renderMapsForReading).toBe("function");
        expect((window as any).__curio_renderMapsForReading).toBe(renderMapsForReading);
    });
});
