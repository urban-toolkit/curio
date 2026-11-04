/**
 * A node's run asks for the save that installs the dataset it made, but a Data
 * Pool's does not: it passes its input on, and every brush on it emits it
 * again. A node is a Data Pool by the behavior its template declares, as the
 * rules in registry/declaredNodes read it: a package template that declares
 * `data-pool` is one, and a template only named like it is not. A type no
 * template is registered for is the built-in Data Pool by its id.
 */
import { renderHook } from "@testing-library/react";

jest.mock("../../utils/palettePackageFactoryDraft", () => ({
    resolveNodeDisplayLabel: () => "Node",
}));

import { CURIO_UNIVERSAL_NODE_TYPE } from "../../constants";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor } from "../../registry/types";
import { useInstallSave } from "../../providers/flow/useInstallSave";

/** Registers the template *id* (`<packageId>/<templateId>@<major>`), declaring *behavior*. */
function registerTemplate(id: string, behavior: string): void {
    const [unversioned, major] = id.split("@");
    const packageId = unversioned.split("/")[0];
    registerNode({
        id,
        source: "package",
        package: { packageId, major: Number(major), version: "1.0.0", name: packageId, publisher: "Test" },
        behavior,
        category: "computation",
        label: id,
        icon: {},
        inputPorts: [],
        outputPorts: [],
        editor: "code",
        inPalette: true,
        description: "",
        hasCode: true,
        hasWidgets: false,
        hasGrammar: false,
        adapter: { handles: [], editor: null, container: {}, useNodeBehavior: () => ({}) },
    } as unknown as NodeDescriptor);
}

/** Whether a run of a node of *nodeType* asks for the install save. */
function asksForTheSave(nodeType: string): boolean {
    const node = { id: "n1", type: CURIO_UNIVERSAL_NODE_TYPE, position: { x: 0, y: 0 }, data: { nodeType } };
    const beginPendingInstall = jest.fn();
    const scheduleInstallSyncRef = { current: (_nodeId: string) => {} };
    const flushInstallSyncRef = { current: () => {} };
    const { unmount } = renderHook(() =>
        useInstallSave({
            scheduleInstallSyncRef,
            dashboardOn: false,
            reactFlow: { getNode: () => node } as any,
            defaultSaveOutputDataset: true,
            isDashboardSource: () => false,
            workflowOps: {
                beginPendingInstall,
                endPendingInstall: jest.fn(),
                failPendingInstall: jest.fn(),
                recordOutputs: jest.fn(() => Promise.resolve({ failedNodeIds: [] })),
            } as any,
            flushInstallSyncRef,
        }),
    );
    scheduleInstallSyncRef.current("n1");
    const asked = beginPendingInstall.mock.calls.length > 0;
    unmount();
    return asked;
}

afterEach(() => {
    clearPackageNodes();
});

test("a package template that declares the Data Pool's behavior asks for no save", () => {
    registerTemplate("me.pools/pool@1", "data-pool");
    expect(asksForTheSave("me.pools/pool@1")).toBe(false);
});

test("a template named like the Data Pool that declares code asks for the save", () => {
    registerTemplate("me.pools/data-pool@1", "code");
    expect(asksForTheSave("me.pools/data-pool@1")).toBe(true);
});

test("a code node asks for the save", () => {
    registerTemplate("me.tools/clean@1", "code");
    expect(asksForTheSave("me.tools/clean@1")).toBe(true);
});

test("the built-in Data Pool asks for no save, before and after its template registers", () => {
    // clearPackageNodes keeps curio.builtin's templates, so this one runs last.
    expect(asksForTheSave("curio.builtin/data-pool@1")).toBe(false);
    registerTemplate("curio.builtin/data-pool@1", "data-pool");
    expect(asksForTheSave("curio.builtin/data-pool@1")).toBe(false);
});
