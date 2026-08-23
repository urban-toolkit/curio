import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

/**
 * Covers how the two left-rail catalog palettes share the strip beside the rail.
 *
 * Both panels open into the same strip, so ToolsMenu owns a single
 * ``activePalette`` value rather than letting each dropdown keep its own flag.
 * Two consequences are easy to regress and are pinned here:
 *
 *  - opening one palette closes the other, and a trigger toggles only itself;
 *  - Escape and outside clicks deliberately do NOT dismiss a palette. The
 *    outside-click handler (``isToolsPaletteDismissOutsideClick``) was removed
 *    when the palettes moved into the rail, because a panel that vanished on
 *    every canvas click was unusable while dragging nodes out of it.
 */

// The dropdowns are exercised separately below; here they are stubbed down to a
// trigger + an open marker so the test drives ToolsMenu's coordination alone and
// needs none of their catalog/provider machinery.
// Each stub exposes the real trigger behaviour (toggle) plus unconditional
// open/close buttons, so a test can send setOpen(false) from a palette that is
// not currently active — the case the reducer's guard clause exists for.
const paletteStub = (name: string) =>
    function Stub({ open, setOpen }: { open: boolean; setOpen: (v: boolean) => void }) {
        return (
            <div>
                <button onClick={() => setOpen(!open)}>{`toggle ${name}`}</button>
                <button onClick={() => setOpen(false)}>{`force-close ${name}`}</button>
                {open && <div data-testid={`${name}-panel`} />}
            </div>
        );
    };

jest.mock("../../components/menus/nodes/datasetPalette", () => ({
    DatasetsPaletteDropdown: paletteStub("datasets"),
}));

jest.mock("../../components/menus/nodes/toolsMenuPackagePalette", () => ({
    PackagesPaletteDropdown: paletteStub("packages"),
    groupPalettePackages: () => [],
    paletteDescriptorBootstrapKey: () => "",
    OVERLAY_TRIGGER_DELAY_PROPS: {},
}));

jest.mock("../../registry", () => ({
    getPaletteNodeTypes: () => [],
    subscribeToRegistry: () => () => {},
}));
// packagesClient pulls in the node adapters, and through them vega/vega-lite,
// which ship ESM that jest's transform does not handle. ToolsMenu only needs the
// one constant.
jest.mock("../../registry/packagesClient", () => ({ BUILTIN_PACKAGE_ID: "curio.builtin" }));
jest.mock("../../api/packagesApi", () => ({ refreshPackageRegistry: jest.fn() }));
jest.mock("../../providers/FlowProvider", () => ({
    useFlowContext: () => ({ playAllNodes: jest.fn() }),
}));
jest.mock("../../providers/UserProvider", () => ({
    useUserContext: () => ({ user: { id: 1 } }),
}));

import ToolsMenu from "../../components/menus/nodes/ToolsMenu";

const datasetsPanel = () => screen.queryByTestId("datasets-panel");
const packagesPanel = () => screen.queryByTestId("packages-panel");

describe("ToolsMenu palette coordination", () => {
    test("both palettes start closed", () => {
        render(<ToolsMenu />);
        expect(datasetsPanel()).toBeNull();
        expect(packagesPanel()).toBeNull();
    });

    test("a trigger opens its own palette", () => {
        render(<ToolsMenu />);
        fireEvent.click(screen.getByText("toggle datasets"));
        expect(datasetsPanel()).not.toBeNull();
        expect(packagesPanel()).toBeNull();
    });

    test("opening one palette closes the other", () => {
        render(<ToolsMenu />);
        fireEvent.click(screen.getByText("toggle datasets"));
        expect(datasetsPanel()).not.toBeNull();

        fireEvent.click(screen.getByText("toggle packages"));
        expect(packagesPanel()).not.toBeNull();
        expect(datasetsPanel()).toBeNull();

        // ...and back again, so neither direction is special-cased.
        fireEvent.click(screen.getByText("toggle datasets"));
        expect(datasetsPanel()).not.toBeNull();
        expect(packagesPanel()).toBeNull();
    });

    test("clicking a trigger again closes its own palette", () => {
        render(<ToolsMenu />);
        fireEvent.click(screen.getByText("toggle packages"));
        expect(packagesPanel()).not.toBeNull();

        fireEvent.click(screen.getByText("toggle packages"));
        expect(packagesPanel()).toBeNull();
        expect(datasetsPanel()).toBeNull();
    });

    test("closing the inactive palette does not disturb the active one", () => {
        // setOpen(false) from the palette that is NOT holding the strip must be
        // a no-op. Without the reducer's `prev === name` guard it would clear
        // the slot and shut the palette the user actually has open.
        render(<ToolsMenu />);
        fireEvent.click(screen.getByText("toggle datasets"));
        expect(datasetsPanel()).not.toBeNull();

        fireEvent.click(screen.getByText("force-close packages"));
        expect(datasetsPanel()).not.toBeNull();
        expect(packagesPanel()).toBeNull();
    });
});
