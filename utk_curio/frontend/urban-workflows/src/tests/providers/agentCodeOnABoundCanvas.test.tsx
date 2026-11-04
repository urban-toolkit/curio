/**
 * An agent's applied code (`useGraphEdits.applyNodeContent`). On a canvas
 * bound to the dataflow's doc, the server wrote the code into the doc, which
 * brings it to the canvas, and recorded the change in the dataflow's history:
 * the canvas writes nothing of it, since two writes of one text merge into
 * two copies, files no entry and leaves the dataflow as it was saved. On a
 * canvas bound to no doc, the canvas writes the code and files the change's
 * entry, named after the agent, with the code it replaced.
 */
import { renderHook } from "@testing-library/react";

jest.mock("../../TrillGenerator", () => ({ TrillGenerator: { addNewVersionProvenance: jest.fn() } }));

import { useGraphEdits, type AppliedCodeDoc } from "../../providers/flow/useGraphEdits";

const BEFORE = "x = 1\n";
const AFTER = "x = 2\n";

function edits(doc: AppliedCodeDoc | null) {
    const setNodes = jest.fn();
    const agentEditProv = jest.fn();
    const markDirty = jest.fn();
    const node = { id: "n", position: { x: 0, y: 0 }, data: { nodeId: "n", code: BEFORE, defaultCode: BEFORE } };
    const { result } = renderHook(() => useGraphEdits({
        setNodes,
        setEdges: jest.fn(),
        reactFlow: { getNodes: () => [node], getEdges: () => [] } as any,
        workflowNameRef: { current: "Bound" },
        outputsRef: { current: [] },
        markNodeStaleRef: { current: jest.fn() },
        setOutputs: jest.fn(),
        agentEditProv,
        markDirtyRef: { current: markDirty },
        codeDocRef: { current: doc },
    }));
    return { apply: result.current.applyNodeContent, setNodes, agentEditProv, markDirty };
}

test("on a bound canvas the agent's code is not written here, and nothing is filed or left unsaved", () => {
    const { apply, setNodes, agentEditProv, markDirty } = edits({ bound: () => true });
    apply("n", AFTER, "Node Builder");
    expect(setNodes).not.toHaveBeenCalled();
    expect(agentEditProv).not.toHaveBeenCalled();
    expect(markDirty).not.toHaveBeenCalled();
});

test("on a canvas bound to no doc the code is written here, and its entry holds the code it replaced", () => {
    const { apply, setNodes, agentEditProv, markDirty } = edits({ bound: () => false });
    apply("n", AFTER, "Node Builder");
    expect(setNodes).toHaveBeenCalledTimes(1);
    expect(agentEditProv).toHaveBeenCalledWith("n", AFTER, "Node Builder", BEFORE);
    expect(markDirty).toHaveBeenCalled();
});
