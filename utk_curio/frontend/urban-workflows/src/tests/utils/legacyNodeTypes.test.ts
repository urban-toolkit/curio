/**
 * A dataflow opened from a file with the Scout package's nodes (#1270): its
 * raster nodes are the Rasterization package's, its charts Vega-Lite nodes,
 * and its packages renamed or dropped. The backend's
 * `projects/legacy_node_types.py` holds the same table.
 */
import {
    REPLACED_NODE_TYPES,
    currentNodeType,
    currentPackages,
} from "../../utils/flowNodeCanonicalType";

describe("currentNodeType", () => {
    test("a chart is a Vega-Lite node", () => {
        expect(currentNodeType("curio.scout/bars")).toBe("curio.builtin/vis-vega");
        expect(currentNodeType("curio.scout/donuts@1")).toBe("curio.builtin/vis-vega@1");
    });

    test("a raster node is the Rasterization package's, its major kept", () => {
        expect(currentNodeType("curio.scout/raster-calculator@1")).toBe("curio.rasterization/raster-calculator@1");
        expect(currentNodeType("curio.scout/rasterize-buildings")).toBe("curio.rasterization/rasterize-buildings");
    });

    test("any other type is left as it is", () => {
        expect(currentNodeType("curio.builtin/vis-vega@1")).toBe("curio.builtin/vis-vega@1");
        expect(currentNodeType("model.scout.deep-umbra/accumulated-shadow")).toBe("model.scout.deep-umbra/accumulated-shadow");
    });

    test("every Scout template is mapped", () => {
        expect(Object.keys(REPLACED_NODE_TYPES)).toHaveLength(17);
    });
});

describe("currentPackages", () => {
    test("Scout is renamed while a raster node is left, and dropped otherwise", () => {
        expect(currentPackages(["curio.scout@1", "x@1"], ["curio.rasterization/raster-calculator"])).toEqual([
            "curio.rasterization@1", "x@1",
        ]);
        expect(currentPackages(["curio.scout@1"], ["curio.builtin/vis-vega"])).toEqual([]);
        expect(currentPackages(["curio.scout@1", "curio.rasterization@1"], ["curio.rasterization/rasterize-buildings@1"])).toEqual([
            "curio.rasterization@1",
        ]);
    });
});
