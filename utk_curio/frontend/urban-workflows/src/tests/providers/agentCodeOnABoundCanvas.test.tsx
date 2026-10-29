/**
 * An agent's applied code on a canvas bound to the dataflow's doc
 * (`useGraphEdits.applyNodeContent`). The server wrote the code into the doc,
 * which brings it to the canvas: the canvas writes nothing of it, since two
 * writes of one text merge into two copies, and files the change's entry,
 * named after the agent, with the code it replaced. The doc can bring the
 * code before the apply answers; the entry then holds what the doc's change
 * replaced (`dataflowDoc.codeBefore`).
 */
import { renderHook } from "@testing-library/react";

jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { addNewVersionProvenance: jest.fn() } }));

import { useGraphEdits, type AppliedCodeDoc } from "../../providers/flow/useGraphEdits";

const BEFORE = "x = 1\n";
const AFTER = "x = 2\n";

function edits(shown: string, doc: AppliedCodeDoc | null) {
    const setNodes = jest.fn();
    const nodeEditProv = jest.fn();
    const markDirty = jest.fn();
    const node = { id: "n", position: { x: 0, y: 0 }, data: { nodeId: "n", code: shown, defaultCode: shown } };
    const { result } = renderHook(() => useGraphEdits({
        setNodes,
        setEdges: jest.fn(),
        reactFlow: { getNodes: () => [node], getEdges: () => [] } as any,
        workflowNameRef: { current: "Bound" },
        outputsRef: { current: [] },
        markNodeStaleRef: { current: jest.fn() },
        setOutputs: jest.fn(),
        nodeEditProv,
        markDirtyRef: { current: markDirty },
        codeDocRef: { current: doc },
    }));
    return { apply: result.current.applyNodeContent, setNodes, nodeEditProv, markDirty };
}

const boundDoc = (brought?: { before: string; after: string }): AppliedCodeDoc => ({
    bound: () => true,
    codeBefore: (_nodeId, code) => (brought && brought.after === code ? brought.before : undefined),
});

test("on a bound canvas the agent's code is not written here, and its entry holds the code it replaced", () => {
    const { apply, setNodes, nodeEditProv, markDirty } = edits(BEFORE, boundDoc());
    apply("n", AFTER, "Node Builder");
    expect(setNodes).not.toHaveBeenCalled();
    expect(nodeEditProv).toHaveBeenCalledWith("n", AFTER, "Node Builder", BEFORE);
    expect(markDirty).toHaveBeenCalled();
});

test("when the doc brought the code first, the entry holds what the doc's change replaced", () => {
    const { apply, setNodes, nodeEditProv } = edits(AFTER, boundDoc({ before: BEFORE, after: AFTER }));
    apply("n", AFTER, "Node Builder");
    expect(setNodes).not.toHaveBeenCalled();
    expect(nodeEditProv).toHaveBeenCalledWith("n", AFTER, "Node Builder", BEFORE);
});

