import React from "react";
import { render, screen } from "@testing-library/react";

/**
 * Every built-in palette tile must have an accessible name.
 *
 * A user test found ten of the twelve tiles unnamed: `DraggableTool` rendered an
 * icon inside a bare `<div>`, so there was no `aria-label`, no `title` and no
 * text content — the hover tooltip was the only label. The node rail is the
 * primary way to author anything, so it being invisible to assistive technology
 * is the whole feature being unreachable.
 *
 * The sibling test file (toolsPalette.test.tsx) stubs the descriptor registry to
 * an empty list to test palette coordination, which is why it never rendered a
 * tile and could not catch this.
 */

const paletteStub = (name: string) =>
    function Stub() {
        return <div data-testid={`${name}-stub`} />;
    };

jest.mock("../../components/menus/nodes/datasetPalette", () => ({
    DatasetsPaletteDropdown: paletteStub("datasets"),
}));
jest.mock("../../components/menus/nodes/agentsPalette", () => ({
    AgentsPaletteDropdown: paletteStub("agents"),
}));
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
    PackagesPaletteDropdown: paletteStub("packages"),
    groupPalettePackages: () => [],
    paletteDescriptorBootstrapKey: () => "",
    OVERLAY_TRIGGER_DELAY_PROPS: {},
}));

/** The twelve built-in templates, as packages/curio.builtin@1/manifest.json has them.
 *  Prefixed `mock` so jest's hoisted mock factory may reference it. */
const mockBuiltin = [
    { id: "curio.builtin/data-loading@1", label: "Data Loading", category: "data" },
    { id: "curio.builtin/data-export@1", label: "Data Export", category: "data" },
    { id: "curio.builtin/data-transformation@1", label: "Data Transformation", category: "data" },
    { id: "curio.builtin/spatial-join@1", label: "Spatial Join", category: "data" },
    { id: "curio.builtin/merge-flow@1", label: "Merge Flow", category: "flow" },
    { id: "curio.builtin/data-pool@1", label: "Data Pool", category: "data" },
    { id: "curio.builtin/computation-analysis@1", label: "Python Computation", category: "computation" },
    { id: "curio.builtin/data-summary@1", label: "Data Summary", category: "computation" },
    { id: "curio.builtin/js-computation@1", label: "JS Computation", category: "computation" },
    { id: "curio.builtin/autk-grammar@1", label: "Autark", category: "vis_grammar", badge: "AUTK" },
    { id: "curio.builtin/vis-vega@1", label: "Vega-Lite", category: "vis_grammar", badge: "VEGA" },
    { id: "curio.builtin/vis-simple@1", label: "Simple View", category: "vis_simple" },
];

jest.mock("../../registry", () => ({
    getPaletteNodeTypes: () =>
        mockBuiltin.map((t) => ({
            ...t,
            // Required inside the factory: jest hoists mock factories above the
            // imports, so an out-of-scope binding is a ReferenceError.
            icon: require("@fortawesome/free-solid-svg-icons").faUpload,
            package: { packageId: "curio.builtin" },
        })),
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

describe("built-in palette tiles are named", () => {
    test("every tile is findable by its manifest label", () => {
        render(<ToolsMenu />);
        for (const template of mockBuiltin) {
            expect(
                screen.getByLabelText(template.label),
                // jest prints the label on failure, which is the useful part.
            ).toBeTruthy();
        }
    });

    test("no tile is left with an empty accessible name", () => {
        const { container } = render(<ToolsMenu />);
        const tiles = Array.from(
            container.querySelectorAll<HTMLElement>("div[draggable='true']"),
        );
        expect(tiles).toHaveLength(mockBuiltin.length);
        for (const tile of tiles) {
            const name =
                tile.getAttribute("aria-label") ||
                tile.getAttribute("title") ||
                (tile.textContent ?? "").trim();
            expect(name).not.toBe("");
        }
    });

    test("every tile carries the id named after its template", () => {
        // The e2e suites find tiles by these ids: curio.builtin/data-loading@1
        // is #tile-data-loading.
        const { container } = render(<ToolsMenu />);
        for (const template of mockBuiltin) {
            const name = template.id.replace("curio.builtin/", "").replace("@1", "");
            const tile = container.querySelector(`#tile-${name}`);
            expect(tile).not.toBeNull();
            expect(tile!.getAttribute("aria-label")).toBe(template.label);
        }
    });
});
