/**
 * A node folded to its chip stays folded across a save and a load.
 *
 * The header's Minimize folds a node to its chip, and the fold is saved state:
 * `TrillGenerator` writes `minimized: true` on the spec node, beside `width`
 * and `height`, and `loadTrill` puts it back on the node's data, where
 * `NodeContainer` reads it. An open node writes nothing. komar41 found the fold
 * lost on every reload (his #914).
 *
 * `loadTrill` runs for real here, with the flow context it reads mocked, as
 * the provider would hand it over.
 */
import { act, renderHook } from "@testing-library/react";

const mockLoadParsedTrill = jest.fn();

jest.mock("../../providers/FlowProvider", () => ({
    useFlowContext: () => ({
        nodes: [],
        addNode: () => {},
        setOutputs: () => {},
        interactionsCallback: () => {},
        applyNewPropagation: () => {},
        applyNewOutput: () => {},
        loadParsedTrill: (...args: unknown[]) => mockLoadParsedTrill(...args),
        markDirty: () => {},
        defaultSaveOutputDataset: false,
    }),
}));
jest.mock("../../providers/ProvenanceProvider", () => ({
    useProvenanceContext: () => ({ loadNodeProvenance: () => {} }),
}));

import { useCode } from "../../hook/useCode";
import { TrillGenerator } from "../../TrillGenerator";

const NODE_TYPE = "curio.builtin/computation-analysis";

function spec() {
    const node = (id: string, x: number, extra: Record<string, unknown> = {}) => ({
        id, type: NODE_TYPE, x, y: 0, content: "return 1\n", in: "DEFAULT", out: "DEFAULT", goal: "", ...extra,
    });
    return {
        dataflow: {
            name: "Minimized",
            task: "",
            timestamp: 1789193389280,
            provenance_id: "Minimized",
            nodes: [
                node("folded", 0, { minimized: true, width: 640, height: 400 }),
                node("open", 1000),
                // Never written, but a hand-edited spec may say it.
                node("unfolded", 2000, { minimized: false }),
            ],
            edges: [],
        },
    };
}

beforeEach(() => {
    TrillGenerator.reset();
    mockLoadParsedTrill.mockReset();
});

describe("a minimized node across a save and a load", () => {
    test("loads minimized with the size it opens back to, and saves minimized again", () => {
        const { result } = renderHook(() => useCode());
        let loaded: { nodes: any[]; edges: any[] } = { nodes: [], edges: [] };
        act(() => {
            loaded = result.current.loadTrill(spec());
        });

        // On the node's data, where NodeContainer reads it.
        const data = Object.fromEntries(loaded.nodes.map((node) => [node.id, node.data]));
        expect({
            folded: [data.folded.minimized, data.folded.nodeWidth, data.folded.nodeHeight],
            open: data.open.minimized,
            unfolded: data.unfolded.minimized,
        }).toEqual({ folded: [true, 640, 400], open: undefined, unfolded: undefined });

        // A save writes it on the folded node alone.
        const saved = TrillGenerator.generateTrill(loaded.nodes, loaded.edges, "Minimized");
        const written = saved.dataflow.nodes.map((node: any) => [node.id, "minimized" in node ? node.minimized : "absent"]);
        expect(written).toEqual([["folded", true], ["open", "absent"], ["unfolded", "absent"]]);
        expect(saved.dataflow.nodes[0]).toMatchObject({ width: 640, height: 400 });
    });
});
