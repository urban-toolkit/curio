/**
 * The Run All button shows a run in flight and offers to cancel it (#271).
 *
 * The guard that refused a second run lived in a ref, so the button looked
 * identical whether a run was in progress, wedged, or idle, and a click during
 * one did nothing at all. It now reads `isRunActive` and flips to Cancel.
 */
import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";

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
jest.mock("../../registry/packagesClient", () => ({ BUILTIN_PACKAGE_ID: "curio.builtin" }));
jest.mock("../../api/packagesApi", () => ({ refreshPackageRegistry: jest.fn() }));

const mockFlow = {
    playAllNodes: jest.fn(),
    cancelRun: jest.fn(),
    isRunActive: false,
};
jest.mock("../../providers/FlowProvider", () => ({
    useFlowContext: () => mockFlow,
}));
jest.mock("../../providers/UserProvider", () => ({
    useUserContext: () => ({ user: { id: 1 } }),
}));

import ToolsMenu from "../../components/menus/nodes/ToolsMenu";

beforeEach(() => {
    jest.clearAllMocks();
    mockFlow.isRunActive = false;
});

describe("ToolsMenu Run All button (#271)", () => {
    test("idle: the button runs all nodes", () => {
        render(<ToolsMenu />);
        const button = screen.getByRole("button", { name: /run all nodes/i });
        expect(button).not.toHaveAttribute("data-run-active");

        fireEvent.click(button);

        expect(mockFlow.playAllNodes).toHaveBeenCalledTimes(1);
        expect(mockFlow.cancelRun).not.toHaveBeenCalled();
    });

    test("running: the same button cancels the run, and says so", () => {
        mockFlow.isRunActive = true;
        render(<ToolsMenu />);

        expect(screen.queryByRole("button", { name: /run all nodes/i })).toBeNull();
        const button = screen.getByRole("button", { name: /cancel run/i });
        expect(button).toHaveAttribute("data-run-active", "true");
        expect(button).toHaveAttribute("title", expect.stringMatching(/cancel/i));

        fireEvent.click(button);

        expect(mockFlow.cancelRun).toHaveBeenCalledTimes(1);
        expect(mockFlow.playAllNodes).not.toHaveBeenCalled();
    });
});
