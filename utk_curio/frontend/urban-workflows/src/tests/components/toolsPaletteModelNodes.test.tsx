import React from "react";
import { render } from "@testing-library/react";

/**
 * The tool rail's Node Catalog palette lists no model package's node (PR #819
 * port, step 4.5). A model's node is added by dropping its Model Catalog card
 * on the canvas, as the Model Catalog lists the models; the Node Catalog never
 * does. The registry still holds the node, so a dataflow that has it runs it.
 */

/** What the packages palette was handed, per render. */
const mockPaletteTypes: string[][] = [];

jest.mock("../../components/menus/nodes/datasetPalette", () => ({ DatasetsPaletteDropdown: () => null }));
jest.mock("../../components/menus/nodes/agentsPalette", () => ({ AgentsPaletteDropdown: () => null }));
jest.mock("../../components/menus/nodes/modelsPalette", () => ({ ModelsPaletteDropdown: () => null }));
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
    PackagesPaletteDropdown: () => null,
    groupPalettePackages: (types: { id: string }[]) => {
        mockPaletteTypes.push(types.map((d) => d.id));
        return [];
    },
    paletteDescriptorBootstrapKey: () => "",
    OVERLAY_TRIGGER_DELAY_PROPS: {},
}));

jest.mock("../../registry", () => ({
    getPaletteNodeTypes: () =>
        [
            { id: "curio.builtin/data-loading@1", label: "Data Loading", category: "data",
              package: { packageId: "curio.builtin", major: 1, version: "1.0.0" } },
            { id: "scout.raster-conversion/rasterize-buildings@1", label: "Rasterize Buildings", category: "computation",
              package: { packageId: "scout.raster-conversion", major: 1, version: "1.0.0" } },
            { id: "model.curio.ddrnet23-slim/image-segmentation@1", label: "Image Segmentation", category: "computation",
              package: { packageId: "model.curio.ddrnet23-slim", major: 1, version: "1.0.0",
                         kind: "model", modelType: "semantic-segmentation" } },
        ].map((d) => ({ ...d, icon: require("@fortawesome/free-solid-svg-icons").faUpload })),
    subscribeToRegistry: () => () => {},
}));
jest.mock("../../registry/packagesClient", () => ({ BUILTIN_PACKAGE_ID: "curio.builtin" }));
jest.mock("../../registry/packageRegistryBootstrap", () => ({ refreshPackageRegistry: jest.fn() }));
jest.mock("../../providers/FlowProvider", () => ({
    useFlowContext: () => ({ playAllNodes: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
    useUserContext: () => ({ user: { id: 1 } }),
}));

import ToolsMenu from "../../components/menus/nodes/ToolsMenu";

describe("the tool rail's Node Catalog palette", () => {
    beforeEach(() => {
        mockPaletteTypes.length = 0;
    });

    test("lists a node package's nodes and no model package's", () => {
        render(<ToolsMenu />);
        expect(mockPaletteTypes.length).toBeGreaterThan(0);
        for (const listed of mockPaletteTypes) {
            expect(listed).toEqual(["scout.raster-conversion/rasterize-buildings@1"]);
        }
    });
});
