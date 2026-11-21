/**
 * A raster a source after compute makes (a heatmap with `after: 'compute'`) is
 * made in autk-grammar's own run, in autk-db's raster store, which the whole
 * page shares, keyed by workspace and table (`autk.noise`), and read when the
 * run's map draws it. A node whose run makes one holds the page's raster turn
 * (`oneRasterAtATime`) from the run's start to its end (`runInRasterTurn`,
 * `makesRasterAfterCompute`), so another node's run or raster load waits, and
 * the run's own raster loads (`withRasterSources`) are told the turn is held
 * (`{ held: true }`), so nothing waits on itself. A run that makes no raster
 * after compute takes no turn.
 *
 * The runs and loads are stand-ins that a test interleaves: each makes its
 * raster in one page-wide store, then waits where the test says, then reads
 * the store as its map would. The functions this change adds are read off the
 * module as it is, so a build without them fails each case on its own.
 */
const mockFetchRaster = jest.fn();
jest.mock("../../../services/api", () => ({
  fetchRaster: (...args: any[]) => mockFetchRaster(...args),
}));

import * as rasters from "../../../adapters/node/autkRasters";

const { CURIO_RASTER_SOURCE, oneRasterAtATime, withRasterSources } = rasters;
const { makesRasterAfterCompute, runInRasterTurn } = rasters as any;

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const ticks = async (count: number) => {
  for (let i = 0; i < count; i += 1) await tick();
};

/** autk-db's raster store, which every node of the page shares. */
const store = new Map<string, string>();

/** A gate a test opens: `shut` settles once `open` is called. */
function gate(): { shut: Promise<void>; open: () => void } {
  let open: () => void = () => undefined;
  const shut = new Promise<void>((resolve) => {
    open = resolve;
  });
  return { shut, open };
}

/**
 * A grammar whose run makes the raster `autk.noise` after its passes, its
 * cells *cells*, says so (*made*), waits for *drawn*, then draws it: what it
 * drew is what the store held then.
 */
function makingNoise(cells: string, made: () => void, drawn: Promise<void>) {
  const result: { drew?: string } = {};
  const grammar = {
    run: jest.fn(async () => {
      await tick();
      store.set("autk.noise", cells);
      made();
      await drawn;
      await tick();
      result.drew = store.get("autk.noise");
    }),
  };
  return { grammar, result };
}

/** A raster on the input, as a node hands it to its grammar. */
const RASTER_SOURCE = {
  type: CURIO_RASTER_SOURCE,
  outputTableName: "input_0",
  geotiffArrayBuffer: new ArrayBuffer(4),
  load: { coordinateFormat: "EPSG:3395", maxRasterCells: 1, resampleMethod: "nearest" },
  grid: { crs: "EPSG:3395", width: 1, height: 1, originX: 0, originY: 1, resX: 1, resY: -1 },
  cells: 1,
};

/** A node's database, whose loadGeoTiff puts *cells* in the page's store as `autk.input_0`. */
function pageDb(cells: string) {
  return {
    loadGeoTiff: jest.fn(async () => {
      await tick();
      store.set("autk.input_0", cells);
    }),
    getRaster: jest.fn(async () => ({
      type: "FeatureCollection",
      bbox: [0, 0, 1, 1],
      features: [{ type: "Feature", geometry: null, properties: { cells: store.get("autk.input_0"), bands: [] } }],
    })),
    getLayer: jest.fn(),
  };
}

/** autk-grammar's data adapter, as a stand-in that loads nothing of its own. */
const adapterLoadingNothing = (): any => ({ resolveSource: jest.fn(async (db: any) => db) });

beforeEach(() => store.clear());

describe("a run that makes a raster after its passes holds the page's raster turn", () => {
  const HEATMAP_AFTER = [
    { type: "heatmap", outputTableName: "noise", joinDataRef: "copied", near: { distance: 600 }, grid: { rows: 2, columns: 3 }, after: "compute" },
  ];

  test("two nodes' runs that make a raster of one name, interleaved, each draw their own", async () => {
    expect(typeof makesRasterAfterCompute).toBe("function");
    expect(typeof runInRasterTurn).toBe("function");
    const turn = { held: makesRasterAfterCompute(HEATMAP_AFTER) };
    expect(turn.held).toBe(true);

    const drawFirst = gate();
    const firstMade = gate();
    const first = makingNoise("first", firstMade.open, drawFirst.shut);
    const second = makingNoise("second", () => undefined, Promise.resolve());
    const runs = [runInRasterTurn(first.grammar, {}, turn)];
    // The first run made its raster and waits to draw it; the second starts.
    await firstMade.shut;
    runs.push(runInRasterTurn(second.grammar, {}, turn));
    await ticks(5);
    // The second waits for the first's turn, so the store holds the first's raster still.
    expect(store.get("autk.noise")).toBe("first");
    drawFirst.open();
    await Promise.all(runs);

    expect([first.result.drew, second.result.drew]).toEqual(["first", "second"]);
  });

  test("another node's raster load waits for the run's turn, and the run's own raster load does not wait on it", async () => {
    expect(typeof runInRasterTurn).toBe("function");
    const turn = { held: true };
    const own = withRasterSources(adapterLoadingNothing(), undefined, turn);
    const other = withRasterSources(adapterLoadingNothing());
    const ownDb = pageDb("own");
    const otherDb = pageDb("other");
    const seen: { ownLoaded?: boolean; otherBefore?: boolean } = {};
    let otherLoad: Promise<unknown> = Promise.resolve();

    const run = {
      run: async () => {
        // The run's own raster, loaded inside the turn the run holds: at once.
        seen.ownLoaded = await Promise.race([
          own.resolveSource(ownDb, RASTER_SOURCE).then(() => true),
          ticks(20).then(() => false),
        ]);
        // Another node's raster load starts: it waits for the run's turn.
        let otherDone = false;
        otherLoad = other.resolveSource(otherDb, RASTER_SOURCE).then(() => {
          otherDone = true;
        });
        await ticks(5);
        seen.otherBefore = otherDone;
      },
    };
    await runInRasterTurn(run, {}, turn);
    await otherLoad;

    expect(seen).toEqual({ ownLoaded: true, otherBefore: false });
    expect((await ownDb.getLayer("input_0")).features[0].properties.cells).toBe("own");
    expect((await otherDb.getLayer("input_0")).features[0].properties.cells).toBe("other");
  });

  test("guard: a run that makes no raster after its passes takes no turn, and runs while another holds it", async () => {
    expect(typeof makesRasterAfterCompute).toBe("function");
    expect(typeof runInRasterTurn).toBe("function");
    const turn = { held: makesRasterAfterCompute([{ type: "sql", outputTableName: "t", query: "SELECT 1", after: "compute" }]) };
    expect(turn.held).toBe(false);

    const holderDone = gate();
    const holder = oneRasterAtATime(() => holderDone.shut);
    const grammar = { run: jest.fn(async () => undefined) };
    await runInRasterTurn(grammar, {}, turn);
    expect(grammar.run).toHaveBeenCalledTimes(1);
    holderDone.open();
    await holder;
  });
});
