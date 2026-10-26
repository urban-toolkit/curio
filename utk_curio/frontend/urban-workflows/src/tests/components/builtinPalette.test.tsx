import React from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";

import {
    TOOLS_PALETTE_DROPDOWN_ATTR,
    TOOLS_PALETTE_PANEL_ATTR,
} from "../../components/menus/nodes/toolsPaletteDismiss";

/**
 * The built-in nodes sit behind a "Built-in" button in the tool rail, the way
 * the catalogs do (owner, 2026-10-20). The rail starts with every palette
 * closed; a click on the button opens the built-in tiles into the strip beside
 * the rail, grouped as before; and the Built-in palette takes ToolsMenu's one
 * `activePalette` slot, so opening it closes a catalog palette and the reverse.
 *
 * The four catalog dropdowns are stubbed down to a trigger and an open marker,
 * as in toolsPalette.test.tsx, so these tests drive ToolsMenu and the real
 * Built-in palette.
 */

const paletteStub = (name: string) =>
    function Stub({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
        return (
            <div>
                <button onClick={() => setOpen(!open)}>{`toggle ${name}`}</button>
                {open && <div data-testid={`${name}-panel`} />}
            </div>
        );
    };

jest.mock("../../components/menus/nodes/datasetPalette", () => ({
    DatasetsPaletteDropdown: paletteStub("datasets"),
}));
jest.mock("../../components/menus/nodes/agentsPalette", () => ({
    AgentsPaletteDropdown: paletteStub("agents"),
}));
jest.mock("../../components/menus/nodes/modelsPalette", () => ({
    ModelsPaletteDropdown: paletteStub("models"),
}));
jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
    PackagesPaletteDropdown: paletteStub("packages"),
    groupPalettePackages: () => [],
    paletteDescriptorBootstrapKey: () => "",
}));

/** Built-in templates as packages/curio.builtin@1/manifest.json has them, in
 *  palette order. Prefixed `mock` so jest's hoisted mock factory may read it. */
const mockBuiltin = [
    { id: "curio.builtin/data-loading@1", label: "Data Loading", category: "data" },
    { id: "curio.builtin/data-export@1", label: "Data Export", category: "data" },
    { id: "curio.builtin/computation-analysis@1", label: "Python Computation", category: "computation" },
    { id: "curio.builtin/data-transformation@1", label: "Data Transformation", category: "data" },
    { id: "curio.builtin/spatial-join@1", label: "Spatial Join", category: "data" },
    { id: "curio.builtin/autk-grammar@1", label: "Autark", category: "vis_grammar", badge: "AUTK" },
    { id: "curio.builtin/vis-vega@1", label: "Vega-Lite", category: "vis_grammar", badge: "VEGA" },
    { id: "curio.builtin/vis-simple@1", label: "Simple View", category: "vis_simple" },
    { id: "curio.builtin/data-summary@1", label: "Data Summary", category: "computation" },
    { id: "curio.builtin/js-computation@1", label: "JS Computation", category: "computation" },
    { id: "curio.builtin/data-pool@1", label: "Data Pool", category: "data" },
    { id: "curio.builtin/edit-features@1", label: "Map Editor", category: "data" },
    { id: "curio.builtin/note@1", label: "Note", category: "flow" },
];
/** What the registry holds; a test empties it to stand for one not loaded yet. */
let mockPaletteTypes = mockBuiltin;

jest.mock("../../registry", () => ({
    getPaletteNodeTypes: () =>
        mockPaletteTypes.map((t) => ({
            ...t,
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

/** The groups the tiles came in before, top to bottom: data and flow, then
 *  computation, then the views. */
const GROUPS = [
    ["data-loading", "data-export", "data-transformation", "spatial-join", "data-pool", "edit-features", "note"],
    ["computation-analysis", "data-summary", "js-computation"],
    ["autk-grammar", "vis-vega", "vis-simple"],
];

const OTHER_PALETTES = ["packages", "datasets", "agents", "models"];

const builtinTrigger = () => screen.getByRole("button", { name: /built-in/i });
const builtinPanel = () => screen.queryByRole("region", { name: "Built-in palette" });
const tiles = () => document.querySelectorAll<HTMLElement>('[id^="tile-"]');

/** The tiles' ids without `tile-`, one list per block that holds them. */
function tileGroups(panel: HTMLElement): string[][] {
    const blocks = new Map<Element, string[]>();
    panel.querySelectorAll<HTMLElement>('[id^="tile-"]').forEach((tile) => {
        const block = tile.parentElement as Element;
        if (!blocks.has(block)) blocks.set(block, []);
        blocks.get(block)!.push(tile.id.replace(/^tile-/, ""));
    });
    return Array.from(blocks.values());
}

afterEach(() => {
    mockPaletteTypes = mockBuiltin;
});

describe("the Built-in palette in the tool rail", () => {
    test("the rail starts with it closed: a trigger, and no tile drawn", () => {
        render(<ToolsMenu />);
        const trigger = builtinTrigger();
        expect(trigger).toHaveAttribute("aria-expanded", "false");
        expect(trigger).toHaveAttribute("data-tooltip", "Open built-in palette");
        // It counts its nodes, as the catalog triggers count theirs.
        expect(trigger).toHaveTextContent(String(mockBuiltin.length));
        expect(builtinPanel()).toBeNull();
        expect(tiles()).toHaveLength(0);
    });

    test("a click opens the tiles into the strip, grouped as before", () => {
        render(<ToolsMenu />);
        fireEvent.click(builtinTrigger());

        expect(builtinTrigger()).toHaveAttribute("aria-expanded", "true");
        expect(builtinTrigger()).toHaveAttribute("data-tooltip", "Close built-in palette");
        const panel = builtinPanel();
        expect(panel).not.toBeNull();
        // Every tile is in the panel, under its own id and its manifest label.
        expect(tiles()).toHaveLength(mockBuiltin.length);
        for (const template of mockBuiltin) {
            const tile = within(panel!).getByLabelText(template.label);
            expect(tile.id).toBe(`tile-${template.id.replace("curio.builtin/", "").replace("@1", "")}`);
        }
        expect(tileGroups(panel!)).toEqual(GROUPS);
    });

    test("opening a catalog palette closes it, and opening it closes the catalog palette", () => {
        render(<ToolsMenu />);
        for (const other of OTHER_PALETTES) {
            fireEvent.click(builtinTrigger());
            expect(builtinPanel()).not.toBeNull();

            fireEvent.click(screen.getByText(`toggle ${other}`));
            expect(screen.queryByTestId(`${other}-panel`)).not.toBeNull();
            expect(builtinPanel()).toBeNull();
            expect(builtinTrigger()).toHaveAttribute("aria-expanded", "false");

            fireEvent.click(builtinTrigger());
            expect(builtinPanel()).not.toBeNull();
            expect(screen.queryByTestId(`${other}-panel`)).toBeNull();

            // Its own trigger closes it, leaving the strip empty.
            fireEvent.click(builtinTrigger());
            expect(builtinPanel()).toBeNull();
            for (const name of OTHER_PALETTES) {
                expect(screen.queryByTestId(`${name}-panel`)).toBeNull();
            }
        }
    });

    test("Escape and a click on the canvas leave it open, as they leave its peers", () => {
        render(
            <>
                <ToolsMenu />
                <div data-testid="canvas">canvas</div>
            </>,
        );
        fireEvent.click(builtinTrigger());
        expect(builtinPanel()).not.toBeNull();

        fireEvent.keyDown(document, { key: "Escape" });
        fireEvent.keyDown(document.body, { key: "Escape" });
        const canvas = screen.getByTestId("canvas");
        fireEvent.pointerDown(canvas);
        fireEvent.mouseDown(canvas);
        fireEvent.click(canvas);
        expect(builtinPanel()).not.toBeNull();

        fireEvent.click(builtinTrigger());
        expect(builtinPanel()).toBeNull();
    });

    test("its root and its panel carry the palette markers, the panel beside the trigger", () => {
        render(<ToolsMenu />);
        const trigger = builtinTrigger();
        const root = trigger.closest("#builtin-palette") as HTMLElement;
        expect(root).not.toBeNull();
        expect(root).toHaveAttribute(TOOLS_PALETTE_DROPDOWN_ATTR, "true");
        // The dock is pointer-events: none and each palette root re-enables its
        // direct children, so the trigger's column and the panel stay children
        // of the root, as in the catalog palettes.
        expect(trigger.parentElement?.parentElement).toBe(root);

        fireEvent.click(trigger);
        const panel = builtinPanel()!;
        expect(panel).toHaveAttribute(TOOLS_PALETTE_PANEL_ATTR, "true");
        expect(panel.parentElement).toBe(root);
    });

    test("a tile is a drag source for its node type", () => {
        render(<ToolsMenu />);
        fireEvent.click(builtinTrigger());
        const setData = jest.fn();
        fireEvent.dragStart(document.getElementById("tile-data-loading") as HTMLElement, {
            dataTransfer: { setData, effectAllowed: "" },
        });
        expect(setData).toHaveBeenCalledWith("application/reactflow", "curio.builtin/data-loading@1");
    });

    test("before the registry has answered, it says its nodes are loading", () => {
        mockPaletteTypes = [];
        render(<ToolsMenu />);
        expect(builtinTrigger()).toHaveTextContent("0");
        fireEvent.click(builtinTrigger());
        expect(within(builtinPanel()!).getByText("Loading built-in nodes…")).toBeTruthy();
        expect(tiles()).toHaveLength(0);
    });
});
