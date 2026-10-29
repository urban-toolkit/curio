/**
 * A dataflow's Trill and its Yjs doc, each made from the other, on the canvas
 * (`providers/collab/docMapping.ts`), as the server's mapping makes them
 * (`collaboration/doc_mapping.py`, whose tests these follow case by case).
 *
 * Every dataflow Curio ships goes to a doc and comes back as itself, directly
 * and through a sync to another tab. Every field `TrillGenerator.generateTrill`
 * writes, for a node with every setting set, has its row in the layout the
 * server shares (`src/contracts/dataflowDoc.json`), and each row is a field it
 * writes: a field added to `generateTrill` later fails here until the layout
 * has its place.
 */
import fs from "fs";
import path from "path";
import * as Y from "yjs";

import {
    applyDataflow,
    dataflowToDoc,
    DocMappingError,
    docId,
    docToDataflow,
    LAYOUT,
    nodeIds,
    owned,
    replaceText,
} from "../../../providers/collab/docMapping";
import { TrillGenerator } from "../../../TrillGenerator";
import { EdgeType } from "../../../constants";

const REPO = path.join(__dirname, "..", "..", "..", "..", "..", "..", "..");
const EXAMPLES = path.join(REPO, "docs", "examples");
/** Fewer would mean the shipped dataflows were read wrong. */
const AT_LEAST_SHIPPED = 50;

function shipped(): Array<[string, any]> {
    const files: string[] = [];
    for (const name of fs.readdirSync(EXAMPLES).sort()) {
        if (name.endsWith(".json") && name !== "use-cases.json") files.push(path.join(EXAMPLES, name));
    }
    const tests = path.join(EXAMPLES, "dataflows");
    for (const name of fs.readdirSync(tests).sort()) {
        if (name.endsWith(".json")) files.push(path.join(tests, name));
    }
    return files.map((file) => [path.relative(EXAMPLES, file), JSON.parse(fs.readFileSync(file, "utf-8")).dataflow]);
}

/** *value* as text that tells key orders apart only where order matters. */
function sorted(value: unknown): string {
    const canon = (v: any): any => {
        if (Array.isArray(v)) return v.map(canon);
        if (v && typeof v === "object") {
            return Object.fromEntries(Object.keys(v).sort().map((k) => [k, canon(v[k])]));
        }
        return v;
    };
    return JSON.stringify(canon(value));
}

function roundTrip(dataflow: any): [Y.Doc, any] {
    const doc = new Y.Doc();
    dataflowToDoc(dataflow, doc, "test");
    return [doc, docToDataflow(doc)];
}

const SHIPPED = shipped();

describe("every shipped dataflow round-trips", () => {
    test("Curio ships the dataflows this reads", () => {
        expect(SHIPPED.length).toBeGreaterThanOrEqual(AT_LEAST_SHIPPED);
    });

    test.each(SHIPPED)("%s", (_name, dataflow) => {
        const [doc, back] = roundTrip(dataflow);
        expect(sorted(back)).toBe(sorted(owned(dataflow)));
        expect((back.nodes ?? []).map((n: any) => n.id)).toEqual((dataflow.nodes ?? []).map((n: any) => n.id));
        expect((back.edges ?? []).map((e: any) => e.id)).toEqual((dataflow.edges ?? []).map((e: any) => e.id));

        // A tab that syncs gets the same Trill, to the text.
        const tab = new Y.Doc();
        Y.applyUpdate(tab, Y.encodeStateAsUpdate(doc, Y.encodeStateVector(tab)));
        expect(JSON.stringify(docToDataflow(tab))).toBe(JSON.stringify(back));
        expect(docId(tab)).toBe("test");
    });
});

describe("a change between two Trills, made on a doc", () => {
    test.each(SHIPPED.map(([name], i) => [name, i]))("%s changes into the next", (_name, index) => {
        const before = SHIPPED[index as number][1];
        const after = SHIPPED[((index as number) + 1) % SHIPPED.length][1];
        const [doc] = roundTrip(before);
        const written: Uint8Array[] = [];
        doc.on("update", (update: Uint8Array) => written.push(update));

        expect(applyDataflow(doc, before, after)).toEqual([]);
        const got = docToDataflow(doc);
        expect(sorted(got)).toBe(sorted(roundTrip(owned(after))[1]));
        expect(nodeIds(doc)).toEqual((after.nodes ?? []).map((n: any) => n.id));
        const count = written.length;
        applyDataflow(doc, after, after);
        expect(written.length).toBe(count);
    });

    test("what the doc changed meanwhile stays, and code both changed keeps the doc's", () => {
        const base = {
            nodes: [
                { id: "a", type: "t", x: 0, y: 0, content: "a = 1\n",
                  metadata: { widgets: [{ name: "w", type: "number", default: 1, value: 1 }] } },
                { id: "b", type: "t", x: 9, y: 9, content: "b = 1\n" },
            ],
            edges: [], name: "base", task: "base task",
        };
        const [doc] = roundTrip(base);
        doc.transact(() => {
            const nodes = doc.getMap("nodes");
            const a = nodes.get("a") as Y.Map<any>;
            (a.get("content") as Y.Text).insert(0, "# doc\n");
            ((a.get("widgets") as Y.Map<any>).get("w") as Y.Map<any>).set("value", JSON.stringify(2));
            doc.getMap("dataflow").set("task", JSON.stringify("the doc's task"));
        });
        const target = JSON.parse(JSON.stringify(base));
        target.name = "theirs";
        target.nodes[0].x = 5;
        target.nodes[0].content = "a = 2\n";
        target.nodes[0].metadata.widgets[0].default = 3;
        target.nodes[1].content = "b = 2\n";

        expect(applyDataflow(doc, base, target)).toEqual(["a"]);
        const got = docToDataflow(doc);
        expect(got.name).toBe("theirs");
        expect(got.task).toBe("the doc's task");
        const [first, second] = got.nodes;
        expect(first.content).toBe("# doc\na = 1\n");
        expect(first.x).toBe(5);
        expect(second.content).toBe("b = 2\n");
        expect(first.metadata.widgets).toEqual([{ name: "w", type: "number", default: 3, value: 2 }]);
    });

    test("a code change rewrites only what differs, so typing elsewhere meanwhile stays", () => {
        const base = { nodes: [{ id: "n", type: "t", content: "héllo wörld 😀\n" }], edges: [] };
        const [server] = roundTrip(base);
        const tab = new Y.Doc();
        Y.applyUpdate(tab, Y.encodeStateAsUpdate(server));
        const content = (tab.getMap("nodes").get("n") as Y.Map<any>).get("content") as Y.Text;
        content.insert(content.length, "# tab\n");
        const typed = Y.encodeStateAsUpdate(tab, Y.encodeStateVector(server));

        applyDataflow(server, base, { nodes: [{ id: "n", type: "t", content: "HÉLLO wörld 😀\n" }], edges: [] });
        Y.applyUpdate(server, typed);
        expect(docToDataflow(server).nodes[0].content).toBe("HÉLLO wörld 😀\n# tab\n");
    });

    test("a change inside a surrogate pair takes the pair whole", () => {
        const doc = new Y.Doc();
        const text = doc.getText("t");
        text.insert(0, "a😀b");
        replaceText(text, "a😃b");
        expect(text.toString()).toBe("a😃b");
        replaceText(text, "😃b");
        expect(text.toString()).toBe("😃b");
    });
});

/** A canvas node with every setting `generateTrill` writes set. */
function everyFieldNode(): any {
    return {
        id: "full",
        type: "universal",
        position: { x: 10, y: 20 },
        data: {
            nodeId: "full",
            nodeType: "curio.builtin/python-computation@1",
            nodeWidth: 640, nodeHeight: 480, minimized: true,
            dashboardPinned: true, dashboardX: 1, dashboardY: 2, dashboardWidth: 300, dashboardHeight: 200,
            saveOutputDataset: true,
            code: "x = 1\n",
            out: "DATAFRAME", in: "GEODATAFRAME", goal: "Compute it",
            keywords: [3, 4],
            datasetRefs: ["data.utk.parks@1"],
            datasetSource: { datasetId: "data.utk.parks@1", title: "Parks" },
            datasetWidgets: { data: { id: "data.utk.parks@1", title: "Parks", format: "csv", refs: ["data.utk.parks@1"] } },
            modelRefs: [{ id: "model.utk.trees@1", name: "Trees" }],
            appearance: { backgroundColor: "#ffefb0" },
            spatialJoin: { predicate: "within", output: "counts" },
            simpleVis: { imageColumn: "image" },
            packageTemplateLabel: "Renamed kind",
            packageTemplateConfig: { description: "configured" },
            dataPool: { insideChart: "MERGE_AND", betweenCharts: "MERGE_OR" },
            widgets: [{ name: "rows", type: "number", default: 5, value: 9, label: "Rows", options: { min: 1, step: 1 } }],
            copiedFrom: ["origin"],
            selections: [{ name: "picked", node: "chart", column: "id", ids: [1, 2] }],
            title: "Full node",
            appliedDatasets: { a: { datasetId: "data.utk.parks@1", title: "Parks" } },
        },
    };
}

function everyFieldTrill(): any {
    const edges = [
        { id: "e1", source: "full", target: "other", sourceHandle: "out", targetHandle: "in", data: { keywords: [1] } },
        { id: "e2", source: "full", target: "other", sourceHandle: "in/out", targetHandle: "in/out", type: EdgeType.BIDIRECTIONAL_EDGE },
    ];
    const other = { ...everyFieldNode(), id: "other", data: { ...everyFieldNode().data, nodeId: "other" } };
    return TrillGenerator.generateTrill(
        [everyFieldNode(), other], edges, "Every field", "a task", ["curio.builtin@1"], "a description",
        [{ datasetId: "data.utk.parks@1", title: "Parks" }], { city: ["Chicago"] },
        [{ id: "s1", name: "Base", color: "#4477aa", nodes: ["full"], description: "d", collapsed: true,
           box: { x: 1, y: 2 }, source: { project: "p", scenario: "s" } } as any],
        true,
    );
}

describe("every field generateTrill writes has its place in the doc", () => {
    const trill = everyFieldTrill();
    const node = trill.dataflow.nodes[0];
    const levels: Array<[string, string[], Record<string, string>]> = [
        ["dataflow", Object.keys(trill.dataflow), LAYOUT.dataflow],
        ["node", Object.keys(node), LAYOUT.node],
        ["metadata", Object.keys(node.metadata), LAYOUT.metadata],
        ["edge", Array.from(new Set(trill.dataflow.edges.flatMap((e: any) => Object.keys(e)))), LAYOUT.edge],
        ["scenario", Object.keys(trill.dataflow.scenarios[0]), LAYOUT.scenario],
        ["widget", Object.keys(node.metadata.widgets[0]), LAYOUT.widget],
    ];

    test.each(levels)("%s", (_level, written, table) => {
        const layout = Object.keys(table);
        expect(written.filter((field) => !layout.includes(field))).toEqual([]);
        expect(layout.filter((field) => !written.includes(field))).toEqual([]);
    });

    test("the full dataflow comes back from its doc as written", () => {
        const [, back] = roundTrip(trill.dataflow);
        expect(sorted(back)).toBe(sorted(owned(trill.dataflow)));
    });
});

describe("the rules the shipped dataflows do not all exercise", () => {
    test("absent and empty stay apart", () => {
        const cases = [
            { nodes: [], edges: [], name: "listed", scenarios: [] },
            { nodes: [], edges: [], name: "unlisted" },
            { nodes: [], edges: [], name: "no packages yet", packages: [] },
            { nodes: [
                { id: "empty", type: "t", content: "" },
                { id: "none", type: "t" },
                { id: "wide", type: "t", width: 400 },
                { id: "placed", type: "t", dashboardX: 1, dashboardY: 2 },
                { id: "pinned", type: "t", dashboardPinned: false },
                { id: "w", type: "t", metadata: { widgets: [
                    { name: "unset", type: "number", default: 1 },
                    { name: "cleared", type: "number", default: 1, value: null },
                ] } },
            ], edges: [], name: "fields" },
        ];
        for (const dataflow of cases) expect(sorted(roundTrip(dataflow)[1])).toBe(sorted(dataflow));
        const [, back] = roundTrip({ nodes: [
            { id: "a", type: "t", metadata: {} },
            { id: "b", type: "t", metadata: { widgets: [] } },
        ], edges: [] });
        expect(back.nodes).toEqual([{ id: "a", type: "t" }, { id: "b", type: "t" }]);
    });

    test("an object keeps the order of its keys", () => {
        const dataflow = {
            nodes: [{ id: "n", type: "t", x: 1.5, y: 2, metadata: {
                spatialJoin: { predicate: "within", output: "counts" },
                widgets: [{ name: "w", type: "slider", default: 5, options: { step: 0.5, min: 0 }, value: 5 }],
            } }],
            edges: [],
            name: "forms",
            categories: { Topic: "Heat", City: "Chicago", Complexity: "Basic" },
            datasets: [{ title: "z first", datasetId: "a" }],
        };
        expect(JSON.stringify(roundTrip(dataflow)[1])).toBe(JSON.stringify(dataflow));
    });

    test("a list that cannot be keyed is kept whole", () => {
        const dataflow = {
            nodes: [{ id: "n", type: "t", metadata: { widgets: [
                { name: "twice", type: "number", default: 1 },
                { name: "twice", type: "number", default: 2 },
            ] } }],
            edges: [{ id: "e", source: "a", target: "b" }, { id: "e", source: "b", target: "c" }],
            name: "unkeyed",
            scenarios: [{ name: "no id", color: "#000", nodes: [] }],
        };
        const [doc, back] = roundTrip(dataflow);
        expect(sorted(back)).toBe(sorted(dataflow));
        expect(typeof doc.getMap("dataflow").get("edges")).toBe("string");
        expect(typeof doc.getMap("dataflow").get("scenarios")).toBe("string");
    });

    test("the agents' sections stay outside the doc", () => {
        const [doc, back] = roundTrip({
            nodes: [], edges: [], name: "with agents",
            agents: [{ agentId: "a" }], agentAttachments: [{ attachmentId: "x" }], agentDefaults: { model: "m" },
        });
        expect(back).toEqual({ nodes: [], edges: [], name: "with agents" });
        expect(Array.from(doc.getMap("dataflow").keys()).filter((k) => LAYOUT.outsideTheDoc.includes(k))).toEqual([]);
    });

    test("a node field named like a doc key is refused", () => {
        expect(() => roundTrip({ nodes: [{ id: "n", type: "t", place: "here" }], edges: [] })).toThrow(DocMappingError);
    });
});
