/**
 * #448: a node's Provenance tab looks its runs up by node id
 * (`provenanceGraphNodes[data.nodeId]`, NodeProvenance.tsx). The runs have to
 * be filed under that id.
 *
 * The callers used to pass `nodeType + "-" + nodeId` and the provider cut at
 * the first dash. Every built-in type has a dash in it
 * (`curio.builtin/data-loading`), so a run of node `<uuid>` was filed under
 * `loading@1-<uuid>` and the tab never showed one. This runs a node through
 * the real interpreter into the real provider.
 */
import React from "react";
import { renderHook, act } from "@testing-library/react";
import ProvenanceProvider, { useProvenanceContext } from "../../providers/ProvenanceProvider";
import { PythonInterpreter } from "../../PythonInterpreter";

jest.mock("../../utils/authApi", () => ({
    getToken: () => "test-token",
}));

jest.mock("../../utils/formatters", () => ({
    formatDate: () => "2024-01-01T00:00:00",
    mapTypes: (t: any) => t,
}));

const flushPromises = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(ProvenanceProvider, null, children);

const NODE_ID = "3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57";

beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
            stdout: [],
            stderr: "",
            input: { dataType: "" },
            output: { path: "abc123", dataType: "dataframe" },
        }),
    }) as any;
});

test("a run of a data-loading node is filed under the node's own id", async () => {
    const { result } = renderHook(() => useProvenanceContext(), { wrapper });

    await act(async () => {
        new PythonInterpreter().interpretCode(
            "return 1",
            "return 1",
            "",
            [],
            jest.fn(),
            "curio.builtin/data-loading@1",
            NODE_ID,
            "workflow-1",
            result.current.nodeExecProv,
        );
        await flushPromises();
    });

    expect(Object.keys(result.current.provenanceGraphNodes)).toEqual([NODE_ID]);
    expect(result.current.provenanceGraphNodes[NODE_ID]).toHaveLength(1);
    expect(result.current.provenanceGraphNodes[NODE_ID][0].code).toBe("return 1");
});
