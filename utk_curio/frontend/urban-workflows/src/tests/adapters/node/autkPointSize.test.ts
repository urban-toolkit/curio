/**
 * A points layer's `pointSize`, the radius of each point in meters on the
 * ground, reaches its map as autk-map's radius in planar units
 * (urban-toolkit/autk-grammar#22, which Curio installs from vendor/autark/
 * until autk-grammar releases it).
 *
 * autk-map draws each point of a points layer as a disc 64 planar units in
 * radius. The workspace is World Mercator (EPSG:3395), which stretches a meter
 * on the ground by about 1.34 at Chicago, so a point there is a disc about
 * 96 m across. With `"pointSize": 2` the grammar hands autk-map 2 m at the
 * layer's latitude, a disc 4 m across.
 *
 * The grammar is the build the app bundles. Its database and its map are
 * stand-ins, since jsdom has neither DuckDB nor WebGPU: the database holds the
 * tables a document's data section loads, already in the workspace's CRS as
 * Curio hands a node's input to the grammar, and the map keeps what the
 * grammar sets on each of its layers.
 */
import * as path from "path";

/** Autark's packages, as the app installs them. */
const mockAutark = path.resolve(__dirname, "../../../../node_modules/@urban-toolkit");

type StandInMap = {
    /** Each layer's type, by its id. */
    types: Record<string, string>;
    /** What the grammar set on each layer, by its id. */
    renderInfo: Record<string, Record<string, unknown>>;
};

/** Each map a run made, in order. */
const mockMaps: StandInMap[] = [];

// autk-core's package names its ES build before its CommonJS one, so the
// grammar gets the CommonJS build, as the other tests of Autark's builds do.
jest.mock("@urban-toolkit/autk-core", () => jest.requireActual(`${mockAutark}/autk-core/dist/autk-core.umd.cjs`));

jest.mock("@urban-toolkit/autk-db", () => {
    /** Every position of a geometry's *coordinates*, however deep. */
    const positions = (coordinates: any): number[][] =>
        typeof coordinates?.[0] === "number" ? [coordinates] : (coordinates ?? []).flatMap(positions);
    /** The layer type autk-db gives a collection of these geometries. */
    const layerType = (collection: any): string => {
        const geometry = String(collection?.features?.[0]?.geometry?.type ?? "");
        if (geometry.endsWith("Point")) return "points";
        return geometry.endsWith("LineString") ? "polylines" : "polygons";
    };
    class AutkDb {
        private tables = new Map<string, { type: string; collection: any }>();
        async init(): Promise<void> {}
        async loadGeojson({ outputTableName, geojsonObject }: any): Promise<void> {
            this.tables.set(outputTableName, { type: layerType(geojsonObject), collection: geojsonObject });
        }
        async getBoundingBoxFromLayer(name: string) {
            const all = this.tables.get(name)!.collection.features.flatMap((f: any) => positions(f.geometry.coordinates));
            const xs = all.map((p: number[]) => p[0]);
            const ys = all.map((p: number[]) => p[1]);
            return { minLon: Math.min(...xs), minLat: Math.min(...ys), maxLon: Math.max(...xs), maxLat: Math.max(...ys) };
        }
        getTablesMetadata() {
            return [...this.tables].map(([name, { type }]) => ({ name, type, source: "geojson" }));
        }
        getLayersMetadata() {
            return this.getTablesMetadata();
        }
        async getLayer(name: string) {
            return this.tables.get(name)!.collection;
        }
        getWorkspaceConfiguration() {
            return { coordinateFormat: "EPSG:3395" };
        }
    }
    return { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395" };
});

jest.mock("@urban-toolkit/autk-map", () => {
    class AutkMap {
        types: Record<string, string> = {};
        renderInfo: Record<string, Record<string, unknown>> = {};
        events = { on: () => undefined, off: () => undefined };
        style = { setPredefinedStyle: () => undefined };
        layerManager = { searchByLayerId: () => null };
        constructor() {
            mockMaps.push(this);
        }
        async init(): Promise<void> {}
        loadCollection(id: string, { type }: { type: string }) {
            this.types[id] = type;
            this.renderInfo[id] = {};
        }
        updateRenderInfo(id: string, info: Record<string, unknown>) {
            this.renderInfo[id] = { ...this.renderInfo[id], ...info };
        }
        updateColorMap() {}
        updateThematic() {}
        draw() {}
    }
    return { AutkMap, MapEvent: { PICKING: "picking" } };
});

jest.mock("@urban-toolkit/autk-plot", () => ({
    PlotEvent: { CLICK: "click", BRUSH: "brush", BRUSH_X: "brushX", BRUSH_Y: "brushY" },
}));
jest.mock("@urban-toolkit/autk-compute", () => ({}));

// The autk-grammar build the app bundles, as CommonJS.
const { AutkGrammar } = require(`${mockAutark}/autk-grammar/dist/autk-grammar.umd.cjs`);

/** WGS84's semi-major axis, in meters, and its first eccentricity: World Mercator's ellipsoid. */
const WGS84_A = 6378137;
const WGS84_E = 0.0818191908426215;

/** A longitude and a latitude, in degrees, in World Mercator's planar units. */
function worldMercator(lon: number, lat: number): [number, number] {
    const phi = (lat * Math.PI) / 180;
    const s = WGS84_E * Math.sin(phi);
    const y = WGS84_A * Math.log(Math.tan(Math.PI / 4 + phi / 2) * ((1 - s) / (1 + s)) ** (WGS84_E / 2));
    return [(WGS84_A * lon * Math.PI) / 180, y];
}

/** How many of World Mercator's planar units one meter on the ground spans at latitude *lat*. */
function unitsPerMeter(lat: number): number {
    const phi = (lat * Math.PI) / 180;
    return Math.sqrt(1 - (WGS84_E * Math.sin(phi)) ** 2) / Math.cos(phi);
}

/** The latitude of West Madison Street in Chicago's West Loop. */
const MADISON = 41.88183;

/** Three GPS fixes along West Madison Street, a meter and a half apart. */
const FIXES = {
    type: "FeatureCollection",
    features: [-87.648, -87.64798, -87.64796].map((lon, fix) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: worldMercator(lon, MADISON) },
        properties: { fix },
    })),
};

/** The block south of them, as a polygon. */
const BLOCK = {
    type: "FeatureCollection",
    features: [{
        type: "Feature",
        geometry: {
            type: "Polygon",
            coordinates: [[[-87.6481, 41.8817], [-87.6478, 41.8817], [-87.6478, 41.8814], [-87.6481, 41.8814], [-87.6481, 41.8817]]
                .map(([lon, lat]) => worldMercator(lon, lat))],
        },
        properties: { block: 1 },
    }],
};

/**
 * A map of the block and the fixes, the fixes' layer with *fixes* added to it,
 * as a node hands its document to the grammar: its inputs as `input_0` and
 * `input_1`, in the workspace's CRS.
 */
function walkMap(fixes: Record<string, unknown>, block: Record<string, unknown> = {}) {
    return {
        data: [
            { type: "geojson", geojsonObject: FIXES, outputTableName: "input_0", coordinateFormat: "EPSG:3395" },
            { type: "geojson", geojsonObject: BLOCK, outputTableName: "input_1", coordinateFormat: "EPSG:3395" },
        ],
        map: {
            layerRefs: [
                { dataRef: "input_1", title: "Block", color: "#cccccc", ...block },
                { dataRef: "input_0", title: "GPS fixes", color: "#f28e2b", ...fixes },
            ],
        },
    };
}

/** Run *spec* with the vendored grammar on a map canvas; the map it made. */
async function draw(spec: object): Promise<StandInMap> {
    document.body.innerHTML = '<canvas id="walk-map"></canvas>';
    const made = mockMaps.length;
    await new AutkGrammar({ map: "walk-map" }).run(spec);
    expect(mockMaps).toHaveLength(made + 1);
    return mockMaps[made];
}

describe("a points layer's pointSize, with the vendored autk-grammar", () => {
    test("reaches the map as the radius of 2 m on the ground, in planar units at the layer's latitude", async () => {
        const map = await draw(walkMap({ pointSize: 2 }));
        expect(map.types["GPS fixes"]).toBe("points");
        const radius = map.renderInfo["GPS fixes"].pointSize as number;
        expect(radius).toBeCloseTo(2 * unitsPerMeter(MADISON), 6);
        // World Mercator stretches a meter by 1.3411 here.
        expect(radius).toBeCloseTo(2.682, 3);
    });

    test("leaves autk-map's own radius on a points layer that sets none", async () => {
        const map = await draw(walkMap({}));
        expect(map.types["GPS fixes"]).toBe("points");
        expect(map.renderInfo["GPS fixes"]).not.toHaveProperty("pointSize");
    });

    test("is ignored on a layer that is not of points", async () => {
        const map = await draw(walkMap({ pointSize: 2 }, { pointSize: 2 }));
        expect(map.types.Block).toBe("polygons");
        expect(map.renderInfo.Block).not.toHaveProperty("pointSize");
        expect(map.renderInfo["GPS fixes"].pointSize).toBeCloseTo(2 * unitsPerMeter(MADISON), 6);
    });

    test.each([
        [0, "0"],
        ["2", '"2"'],
    ])("refuses %p, naming the layer", async (pointSize, shown) => {
        const made = mockMaps.length;
        await expect(new AutkGrammar({ map: "walk-map" }).run(walkMap({ pointSize }))).rejects.toThrow(
            `Layer "GPS fixes": pointSize must be a number of meters greater than 0, not ${shown}.`,
        );
        expect(mockMaps).toHaveLength(made);
    });
});
