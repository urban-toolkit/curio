/**
 * #448: dataflows saved before the fix carry each node's runs under the key
 * the provider used to cut out of `nodeType + "-" + nodeId`, everything after
 * the type's first dash: `loading@1-<uuid>` for a data-loading node. Opening
 * one moves those runs under the node id the Provenance tab reads.
 */
import * as fs from "fs";
import * as path from "path";
import { rekeyNodeProvenance } from "../../utils/nodeProvenanceKeys";
import type { NodeExecRecord } from "../../providers/ProvenanceProvider";

const run = (id: number): NodeExecRecord => ({
    id,
    parentId: null,
    code: `run ${id}`,
    inputs: [],
    outputs: [],
    startTime: "",
    endTime: "",
});

const UUID = "3f2a9c1e-7b4d-4e8a-9c1f-2d6b8e0a4c57";

describe("rekeyNodeProvenance", () => {
    test("moves an old key under the node id it ends with", () => {
        expect(rekeyNodeProvenance({ [`loading@1-${UUID}`]: [run(1), run(2)] }, [UUID])).toEqual({
            [UUID]: [run(1), run(2)],
        });
    });

    test("merges old and new runs of one node, in run order", () => {
        const out = rekeyNodeProvenance(
            { [UUID]: [run(3)], [`vega@1-${UUID}`]: [run(1), run(2)] },
            [UUID],
        );
        expect(out[UUID].map((r) => r.id)).toEqual([1, 2, 3]);
        expect(Object.keys(out)).toEqual([UUID]);
    });

    test("keeps keys that already are node ids, and keys of nodes no longer in the dataflow", () => {
        const saved = { "node-1": [run(1)], "loading-gone": [run(2)] };
        expect(rekeyNodeProvenance(saved, ["node-1"])).toEqual(saved);
    });

    test("picks the longest node id an old key ends with", () => {
        // Node ids "b" and "a-b": the key of node "a-b" also ends with "-b".
        expect(rekeyNodeProvenance({ "loading-a-b": [run(1)] }, ["b", "a-b"])).toEqual({
            "a-b": [run(1)],
        });
    });

    test("opening a dataflow passes its saved runs through it", () => {
        // Read as source, as useCodeRestoresNodeSettings.test.ts reads this
        // hook: useCode cannot be mounted without the whole provider stack.
        const useCode = fs.readFileSync(path.join(__dirname, "..", "..", "hook", "useCode.ts"), "utf-8");
        expect(useCode).toContain(
            "loadNodeProvenance(rekeyNodeProvenance(trill.nodeProvenance, nodes.map((n) => n.id)))",
        );
        expect(useCode).not.toMatch(/loadNodeProvenance\(trill\.nodeProvenance\)/);
    });
});
