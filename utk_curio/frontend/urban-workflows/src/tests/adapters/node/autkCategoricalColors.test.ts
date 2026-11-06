/**
 * autk-map colors numbers under a categorical color map by their category
 * (urban-toolkit/autark#122, which Curio installs from vendor/autark/ until
 * Autark releases it).
 *
 * The shader reads a categorical thematic value as the index of its category
 * among the legend's labels. autk-map 4.1.1 gave a number its own value
 * instead, so example 30's clusters, numbered 1 to 8, were drawn in the colors
 * the legend showed for other clusters, 7 and 8 alike, and the scheme's first
 * color never. The map is made as Autark's own tests make it, without its
 * constructor, so it needs neither a canvas nor WebGPU; the layer is a real
 * polygon layer of the build the app bundles, one triangle per feature.
 */
import * as path from "path";

const AUTARK = path.resolve(__dirname, "../../../../node_modules/@urban-toolkit");
// The autk-map build the app bundles, as CommonJS.
const { AutkMap, LayerManager } = require(path.join(AUTARK, "autk-map/dist/autk-map.umd.cjs"));
const { ColorMapDomainStrategy, ColorMapInterpolator } = require(
    path.join(AUTARK, "autk-core/dist/autk-core.umd.cjs"),
);

/** Vertices of each feature's triangle. */
const POINTS = 3;

/** Clusters numbered 1 to 8, in the order a layer meets them. */
const ORDERS: [string, number[]][] = [
    ["in order, as example 30 lists them", [1, 2, 3, 4, 5, 6, 7, 8]],
    ["in the order its squares came before", [4, 8, 7, 3, 1, 6, 2, 5]],
];

/**
 * Colors a polygon layer whose features hold *clusters* under *interpolator*:
 * the thematic value each feature is drawn with, and the legend's labels.
 */
function colorByCluster(clusters: (number | string)[], interpolator: string) {
    const layers = new LayerManager();
    const layer = layers.addLayer(
        { id: "clusters", zIndex: 0, typeLayer: "polygons" },
        {
            opacity: 1,
            isColorMap: true,
            colormap: {
                config: { interpolator, domainSpec: { type: ColorMapDomainStrategy.MIN_MAX } },
                computedDomain: [],
            },
        },
        {
            geometry: clusters.map((_, i) => ({
                position: new Float32Array([i, 0, i + 1, 0, i, 1]),
                indices: new Uint32Array([0, 1, 2]),
            })),
            components: clusters.map((_, featureIndex) => ({ nPoints: POINTS, nTriangles: 1, featureIndex })),
        },
    );
    const map = Object.create(AutkMap.prototype);
    map._layerManager = layers;
    map._ui = { refreshLegend: () => undefined };
    map.updateThematic("clusters", {
        collection: {
            type: "FeatureCollection",
            features: clusters.map((cluster) => ({ type: "Feature", geometry: null, properties: { cluster } })),
        },
        property: "properties.cluster",
    });
    return {
        drawnWith: clusters.map((_, i) => layer.thematic[i * POINTS]),
        labels: layer.layerRenderInfo.colormap.computedLabels as string[],
    };
}

describe("autk-map's categorical colors", () => {
    test.each(ORDERS)("clusters numbered 1 to 8, met %s, are each drawn in their legend label's color", (_, clusters) => {
        const { drawnWith, labels } = colorByCluster(clusters, ColorMapInterpolator.CAT_TABLEAU10);
        expect(labels).toEqual(clusters.map(String));
        expect(drawnWith).toEqual(clusters.map((cluster) => labels.indexOf(String(cluster))));
    });

    test("numbers are drawn as the same categories written as text", () => {
        expect(colorByCluster([8, 1, 7, 2], ColorMapInterpolator.CAT_TABLEAU10).drawnWith)
            .toEqual(colorByCluster(["h", "a", "g", "b"], ColorMapInterpolator.CAT_TABLEAU10).drawnWith);
    });

    test("numbers under a sequential color map keep their values", () => {
        expect(colorByCluster([3, 1, 2, 1], ColorMapInterpolator.SEQ_VIRIDIS).drawnWith).toEqual([3, 1, 2, 1]);
    });
});
