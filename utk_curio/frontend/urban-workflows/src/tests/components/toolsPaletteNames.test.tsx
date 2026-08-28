import React from "react";
import { render, screen } from "@testing-library/react";

/**
 * Every built-in palette tile must have an accessible name.
 *
 * A user test found ten of the twelve tiles unnamed: `DraggableTool` rendered an
 * icon inside a bare `<div id={tutorialID}>`, so there was no `aria-label`, no
 * `title` and no text content — the hover tooltip was the only label, and four
 * tiles had no `id` either because the builtin manifest gave them no
 * `tutorialId`. The node rail is the primary way to author anything, so it being
 * invisible to assistive technology is the whole feature being unreachable.
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
    { id: "curio.builtin/data-loading", label: "Data Loading", category: "data", tutorialId: "step-loading" },
    { id: "curio.builtin/data-export", label: "Data Export", category: "data", tutorialId: "step-export" },
    { id: "curio.builtin/data-transformation", label: "Data Transformation", category: "data", tutorialId: "step-transformation" },
    { id: "curio.builtin/spatial-join", label: "Spatial Join", category: "data", tutorialId: "step-spatial-join" },
    { id: "curio.builtin/merge-flow", label: "Merge Flow", category: "flow", tutorialId: "step-merge" },
    { id: "curio.builtin/data-pool", label: "Data Pool", category: "data", tutorialId: "step-pool" },
    { id: "curio.builtin/computation-analysis", label: "Python Computation", category: "computation", tutorialId: "step-analysis" },
    { id: "curio.builtin/data-summary", label: "Data Summary", category: "computation", tutorialId: "step-summary" },
    { id: "curio.builtin/js-computation", label: "JS Computation", category: "computation", tutorialId: "step-js" },
    { id: "curio.builtin/autk-grammar", label: "Autark", category: "vis_grammar", tutorialId: "step-utk", badge: "AUTK" },
    { id: "curio.builtin/vis-vega", label: "Vega-Lite", category: "vis_grammar", tutorialId: "step-vega", badge: "VEGA" },
    { id: "curio.builtin/vis-simple", label: "Simple View", category: "vis_simple", tutorialId: "step-image" },
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
jest.mock("../../api/packagesApi", () => ({ refreshPackageRegistry: jest.fn() }));
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

    test("every tile carries the manifest's tutorial anchor id", () => {
        // Four templates had no tutorialId, so those tiles rendered with no id
        // at all. The in-app tutorial only queries the eight anchors it names,
        // so adding the rest is additive.
        const { container } = render(<ToolsMenu />);
        for (const template of mockBuiltin) {
            expect(container.querySelector(`#${template.tutorialId}`)).not.toBeNull();
        }
    });
});
