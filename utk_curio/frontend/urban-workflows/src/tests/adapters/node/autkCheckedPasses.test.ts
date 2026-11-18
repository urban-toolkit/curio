/**
 * A map node checks every pass its grammar's run computes by wrapping the
 * compute adapter the grammar keeps (`withCheckedPasses`,
 * adapters/node/autkComputeScopes), as `withRasterSources` wraps its data
 * adapter. These tests pin that autk-grammar's build keeps it there and hands
 * it each pass of a run: the run's passes go through the check, in error
 * scopes on autk-compute's device, and one the GPU refuses fails the run,
 * named by the table it writes.
 *
 * The grammar is the build the app bundles, as CommonJS. jsdom has neither
 * DuckDB nor WebGPU: the database is a stand-in that holds the tables a data
 * section loads, and autk-compute the stand-in of _support/autkComputeStandIns.
 */
jest.mock("@urban-toolkit/autk-core", () => require("../../_support/autkComputeStandIns").autkCoreBuild());
jest.mock("@urban-toolkit/autk-map", () => require("../../_support/autkComputeStandIns").autkMapModule);
jest.mock("@urban-toolkit/autk-plot", () => require("../../_support/autkComputeStandIns").autkPlotModule);
jest.mock("@urban-toolkit/autk-compute", () => require("../../_support/autkComputeStandIns").autkComputeModule);
jest.mock("@urban-toolkit/autk-db", () => {
    class AutkDb {
        private tables = new Map<string, { type: string; collection: any }>();
        private workspace = "autk";
        async init(): Promise<void> {}
        getCurrentWorkspace(): string {
            return this.workspace;
        }
        async setWorkspace(name: string): Promise<void> {
            this.workspace = name;
        }
        async loadGeojson({ outputTableName, geojsonObject, layerType }: any): Promise<void> {
            this.tables.set(outputTableName, { type: layerType ?? "polygons", collection: geojsonObject });
        }
        async getBoundingBoxFromLayer(): Promise<never> {
            throw new Error("this stand-in keeps no bounding boxes");
        }
        getTablesMetadata() {
            return [...this.tables].map(([name, { type }]) => ({ name, type, source: "geojson" }));
        }
        getLayersMetadata() {
            return this.getTablesMetadata();
        }
        async getLayer(name: string) {
            const table = this.tables.get(name);
            if (!table) throw new Error(`Table ${name} not found.`);
            return table.collection;
        }
        getWorkspaceConfiguration() {
            return { coordinateFormat: "EPSG:3395" };
        }
    }
    return { AutkDb, DEFAULT_WORKSPACE_COORDINATE_FORMAT: "EPSG:3395", DEFAULT_WORKSPACE_NAME: "autk" };
});

import { grammarBuild, computeDevice, computeRuns, gpuErrors, resetComputeStandIns } from "../../_support/autkComputeStandIns";
import { withCheckedPasses } from "../../../adapters/node/autkComputeScopes";

const { AutkGrammar } = grammarBuild();

/** A square of side 40 at *x*, in the workspace's planar units, *height* tall. */
function building(x: number, height: number) {
    const ring = [[x, 0], [x + 40, 0], [x + 40, 40], [x, 40], [x, 0]];
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [ring] }, properties: { height } };
}

/** A data section of two buildings and two spots between them, already in the workspace's CRS. */
const DATA = [
    {
        type: "geojson", outputTableName: "towers", coordinateFormat: "EPSG:3395",
        geojsonObject: { type: "FeatureCollection", features: [building(0, 150), building(60, 150)] },
    },
    {
        type: "geojson", outputTableName: "spots", coordinateFormat: "EPSG:3395",
        geojsonObject: {
            type: "FeatureCollection",
            features: [[50, 20], [500, 20]].map((coordinates, spot) => ({
                type: "Feature", geometry: { type: "Point", coordinates }, properties: { spot },
            })),
        },
    },
];

const RENDER = {
    type: "render", outputTableName: "sky",
    layers: [{ id: "towers", dataRef: "towers", type: "buildings" }],
    viewpoints: { dataRef: "spots" },
    aggregation: { type: "classes", includeBackground: true, backgroundLayerType: "sky" },
};

const GPGPU = {
    dataRef: "towers", attributes: { h: "height" }, wgslFunction: "return h * 2.0;",
    outputColumnName: "twice", outputTableName: "doubled",
};

beforeEach(() => {
    resetComputeStandIns();
});

describe("autk-grammar's run hands each pass to the compute adapter a map node checks", () => {
    test("a render pass runs through the check, in the device's three error scopes", async () => {
        const grammar = new AutkGrammar({});
        withCheckedPasses(grammar);

        await grammar.run({ data: DATA, compute: [RENDER] });

        expect(computeRuns.render).toHaveBeenCalledTimes(1);
        expect(computeDevice.pushErrorScope.mock.calls.map((call) => call[0]).sort())
            .toEqual(["internal", "out-of-memory", "validation"]);
        expect(computeDevice.popErrorScope).toHaveBeenCalledTimes(3);
        // The run keeps the table the pass wrote, as the grammar's own run does.
        const sky = await grammar.data.sky;
        expect(sky.features.map((f: any) => f.properties.spot)).toEqual([0, 1]);
    });

    test("a render pass the GPU refuses fails the run, named by the table it writes", async () => {
        gpuErrors.next = { validation: "Binding size is smaller than the minimum binding size" };
        const grammar = new AutkGrammar({});
        withCheckedPasses(grammar);

        await expect(grammar.run({ data: DATA, compute: [RENDER] })).rejects.toThrow(
            "sky: the GPU could not run this compute pass: Binding size is smaller than the minimum binding size",
        );
    });

    test("a GPGPU pass the GPU refuses fails the run the same way", async () => {
        gpuErrors.next = { internal: "CreateComputePipelines failed with VK_ERROR_UNKNOWN" };
        const grammar = new AutkGrammar({});
        withCheckedPasses(grammar);

        await expect(grammar.run({ data: DATA, compute: [GPGPU] })).rejects.toThrow(
            "doubled: the GPU could not run this compute pass: CreateComputePipelines failed with VK_ERROR_UNKNOWN",
        );
        expect(computeRuns.gpgpu).toHaveBeenCalledTimes(1);
    });
});
