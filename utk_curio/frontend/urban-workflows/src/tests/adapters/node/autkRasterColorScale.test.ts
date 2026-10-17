/**
 * autk-map colors a raster with one color scale, built once for the whole
 * raster (urban-toolkit/autark#118, which Curio installs from vendor/autark/
 * until Autark releases it).
 *
 * autk-map 4.1.1 built a d3 scale for every cell, through autk-core's
 * `ColorMap.getColor`, which kept the page busy for seconds while a map drew a
 * raster as large as SCOUT's flood grid. autk-map's build carries autk-core
 * and d3 inside it and exports no `ColorMap`, so the builder cannot be spied
 * on. Each scale is built from the layer's colormap interpolator, which
 * `loadRaster` reads once per scale it builds: once per cell through
 * `getColor` in 4.1.1, once per raster through `getColorFunction` in
 * autark#118. The first tests count those reads on the build the app bundles;
 * the others check that every cell keeps the color `getColor` gives it.
 */
import * as path from "path";

const AUTARK = path.resolve(__dirname, "../../../../node_modules/@urban-toolkit");
// The autk-map build the app bundles, as CommonJS. A raster layer is colored
// without WebGPU, which only drawing it asks for.
const { LayerManager } = require(path.join(AUTARK, "autk-map/dist/autk-map.umd.cjs"));
// autk-core from npm, whose getColor gives the color of one cell.
const { ColorMap, ColorMapDomainStrategy, ColorMapInterpolator } = require(
    path.join(AUTARK, "autk-core/dist/autk-core.umd.cjs"),
);

/** The colormap's domain; every value of the rasters below falls inside it. */
const DOMAIN: [number, number] = [-40, 40];

/** Raster sizes, width by height. */
const SIZES: [number, number][] = [[4, 3], [64, 48]];

/** A width by height ramp, row by row, whose first cell is nodata. */
function ramp(width: number, height: number): Float32Array {
    const values = new Float32Array(width * height);
    for (let i = 0; i < values.length; i++) {
        values[i] = ((i % width) - width / 2) * 0.5 + Math.floor(i / width) * 0.25;
    }
    values[0] = NaN;
    return values;
}

/**
 * A raster layer of *values* in Reds over DOMAIN, made as autk-map makes one,
 * and how many times its colormap's interpolator has been read.
 */
function rasterLayer(width: number, height: number, values: Float32Array) {
    const reads = { count: 0 };
    const config = {
        domainSpec: { type: ColorMapDomainStrategy.USER, params: DOMAIN },
        get interpolator() {
            reads.count += 1;
            return ColorMapInterpolator.SEQ_REDS;
        },
    };
    const layer = new LayerManager().addLayer(
        { id: "raster", zIndex: 0, typeLayer: "raster" },
        { opacity: 1, colormap: { config, computedDomain: DOMAIN } },
        {
            geometry: [{
                position: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]),
                indices: new Uint32Array([0, 1, 2, 0, 2, 3]),
                texCoord: new Float32Array([0, 0, 1, 0, 1, 1, 0, 1]),
            }],
            components: [{ nPoints: 4, nTriangles: 2, featureIndex: 0, featureId: 0 }],
            rasterResX: width,
            rasterResY: height,
            raster: values,
        },
    );
    return { layer, reads };
}

describe("autk-map's raster colors", () => {
    test.each(SIZES)("a %i by %i raster is colored with one color scale, built once for the raster", (width, height) => {
        const values = ramp(width, height);
        const { layer, reads } = rasterLayer(width, height, values);
        reads.count = 0;
        layer.loadRaster(values);
        expect({ cells: values.length, colorScalesBuilt: reads.count })
            .toEqual({ cells: width * height, colorScalesBuilt: 1 });
    });

    test.each(SIZES)("each cell of a %i by %i raster keeps the color getColor gives it", (width, height) => {
        const values = ramp(width, height);
        const { layer } = rasterLayer(width, height, values);
        const drawn: number[] = [];
        const expected: number[] = [];
        values.forEach((value, i) => {
            drawn.push(...Array.from(layer.rasterData.subarray(i * 4, i * 4 + 3) as Float32Array));
            if (Number.isNaN(value)) {
                expected.push(0, 0, 0);
                return;
            }
            const { r, g, b } = ColorMap.getColor(value, ColorMapInterpolator.SEQ_REDS, DOMAIN);
            expected.push(r, g, b);
        });
        expect(drawn).toEqual(expected);
    });
});
