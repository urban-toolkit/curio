import { getLlmTypes, Cell, CellEdge, wireCode } from "../NotebookConvertor";

describe("getLlmTypes", ()=>{
    beforeEach(() => {
        global.fetch = jest.fn();
    });

    afterEach(() => {
        jest.resetAllMocks();
    });

    test("Empty data", async () => {
        const ambiguous: Cell[] = [];
        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        
        expect(result).toEqual({});
        expect(fetch).not.toHaveBeenCalled();
    })

    test("Authenticated user with an LLM", async () => {
        const ambiguous: Cell[] = [{ index: 1, code: "x = 1" }];

        (fetch as jest.Mock)
        // 1st call: /llm/check
        .mockResolvedValueOnce({
            ok: true,
            json: async () => ({ result: "yes" }),
        })
        // 2nd call: /llm/chat
        .mockResolvedValueOnce({
            ok: true,
            json: async () => ({
                result: JSON.stringify([{ index: 1, codeType: "COMPUTATION_ANALYSIS" }]),
            }),
        });

        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        expect(fetch).toHaveBeenCalledTimes(2);
        expect(result).toEqual({1: "curio.builtin/computation-analysis"});
    })

    test("Empty return for unauthenticated users", async () =>{
        const ambiguous: Cell[] = [
            {index: 1, code: "<This code loads data>"},
            {index: 4, code: "<This code transforms data>"},
            {index: 9, code: "<This code computes data>"}
        ];

        (fetch as jest.Mock)
        // 1st call: /llm/check
        .mockResolvedValueOnce({
            ok: false,
            json: async () => ({"error": "Authorization required."}),
        })

        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        expect(fetch).toHaveBeenCalledTimes(1)
        expect(result).toEqual({})
    })

    test("No LLM configured", async ()=>{
        const ambiguous: Cell[] = [
            {index: 1, code: "<This code loads data>"},
            {index: 4, code: "<This code transforms data>"},
            {index: 9, code: "<This code computes data>"}
        ];

        (fetch as jest.Mock)
        // 1st call: /llm/check
        .mockResolvedValueOnce({
            ok: true,
            json: async () => ({result: "yes"}),
        })
        // 2nd call: /llm/chat
        .mockResolvedValueOnce({
            ok: false,
            status: 400,
            json: async () => { throw new Error("LLM is not available for guest users at this time."); }
        })

        const result = await getLlmTypes(ambiguous, "http://127.0.0.1:5002");
        expect(fetch).toHaveBeenCalledTimes(2)
        expect(result).toEqual({})
    })
})

describe("Testing the addition of Merge Flow", ()=>{
    test("Does not wire a non-existant connection", ()=>{
        const cellEdges: CellEdge[] = [
            { source: 0, target: 2, parent_var: "x" },
        ];
        
        const hasOutgoing = new Set<number>([0]);
        const incomingSources = new Map<number, number[]>([
            [2, [0]],
        ]);

        const code = wireCode(
            "y = compute_something()",
            1,
            cellEdges,
            hasOutgoing,
            incomingSources,
        );
        expect(code).toBe("y = compute_something()")
    })

    test("Wires a single incoming source to its parent variable, and adds a return for the outgoing node", () => {
        const cellEdges: CellEdge[] = [
            { source: 0, target: 1, parent_var: "x" },
        ];

        const hasOutgoing = new Set<number>([0]);
        const incomingSources = new Map<number, number[]>([
            [1, [0]],
        ]);

        // Source cell (0): has outgoing edge, should get `return x` appended
        const sourceCode = wireCode(
            "x = compute_something()",
            0,
            cellEdges,
            hasOutgoing,
            incomingSources,
        );
        expect(sourceCode).toBe("x = compute_something()\nreturn x");

        // Target cell (1): has single incoming source, should get `x = arg` prepended
        const targetCode = wireCode(
            "y = x + 1",
            1,
            cellEdges,
            hasOutgoing,
            incomingSources,
        );
        expect(targetCode).toBe("x = arg\ny = x + 1");
    });

    test("Merge-Flow", ()=>{
        // Source 3 is assumed to be the newly added MergeFlow node
        const cellEdges: CellEdge[] = [
            { source: 1, target: 4, parent_var: "y" },
            { source: 0, target: 4, parent_var: "x" },
            { source: 2, target: 4, parent_var: "z" },
            { source: 4, target: 3 } // Allegedly 4 is the Merge Flow node
        ];

        const hasOutgoing = new Set<number>([0, 1, 2, 3]);
        const incomingSources = new Map<number, number[]>([
            [4, [1, 0, 2]],
            [3, [4]],
        ]);

        // Make sure the output are all good
        const source1 = wireCode("x = compute_something()", 0, cellEdges, hasOutgoing, incomingSources);
        const source2 = wireCode("y = compute_something()", 1, cellEdges, hasOutgoing, incomingSources);
        const source3 = wireCode("z = compute_something()", 2, cellEdges, hasOutgoing, incomingSources);

        expect(source1).toBe("x = compute_something()\nreturn x");
        expect(source2).toBe("y = compute_something()\nreturn y");
        expect(source3).toBe("z = compute_something()\nreturn z");

        const merge_flow_out = wireCode("", 4, cellEdges, hasOutgoing, incomingSources)
        expect(merge_flow_out).toBe("")

        const merge_output = wireCode("product = x * y * z", 3, cellEdges, hasOutgoing, incomingSources);
        expect(merge_output).toBe("y = arg[0]\nx = arg[1]\nz = arg[2]\nproduct = x * y * z")
    })

    test("3 dependancies for 1 Merge-Flow, and 3 for another", ()=>{
        const cellEdges: CellEdge[] = [
            { source: 0, target: 3, parent_var: "a" },
            { source: 1, target: 3, parent_var: "b" },
            { source: 2, target: 3, parent_var: "c" },
            { source: 3, target: 4 },
            { source: 4, target: 8, parent_var: "x" },
            { source: 5, target: 8, parent_var: "p" },
            { source: 6, target: 8, parent_var: "q" },
            { source: 8, target: 9 },
        ];
        const hasOutgoing = new Set<number>([0, 1, 2, 3, 4, 5, 6, 8]);
        const incomingSources = new Map<number, number[]>([
            [3, [0, 1, 2]],
            [4, [3]],
            [8, [4, 5, 6]],
            [9, [8]],
        ]);

        const node4 = wireCode("x = a + b + c", 4, cellEdges, hasOutgoing, incomingSources);
        expect(node4).toBe("a = arg[0]\nb = arg[1]\nc = arg[2]\nx = a + b + c\nreturn x");
        
        const node8 = wireCode("", 8, cellEdges, hasOutgoing, incomingSources);
        expect(node8).toBe("");
    })


    test("5 dependancies Merge-Flow", ()=>{
        // A single Merge-Flow Node can have a maximum of 5 connections
        const cellEdges: CellEdge[] = [
            { source: 0, target: 6, parent_var: "a" },
            { source: 1, target: 6, parent_var: "b" },
            { source: 2, target: 6, parent_var: "c" },
            { source: 3, target: 6, parent_var: "d" },
            { source: 4, target: 6, parent_var: "e" },
            { source: 6, target: 5 } // 5 is the Merge Flow node
        ];

        const hasOutgoing = new Set<number>([0, 1, 2, 3, 5]);
        const incomingSources = new Map<number, number[]>([
            [6, [0, 1, 2, 3, 4]],
            [5, [6]],
        ]);

        const merge_node_out = wireCode("gqCoduV9YG0fYdjdPXmWdZAhSKJ5o6uQ", 6, cellEdges, hasOutgoing, incomingSources)
        expect(merge_node_out).toBe("gqCoduV9YG0fYdjdPXmWdZAhSKJ5o6uQ")

        const out = wireCode("print(a+b+c+d+e)", 5, cellEdges, hasOutgoing, incomingSources)
        expect(out).toBe("a = arg[0]\nb = arg[1]\nc = arg[2]\nd = arg[3]\ne = arg[4]\nprint(a+b+c+d+e)")
    })

    test("9 dependancies Merge-Flow", ()=>{
        // At 9 dependencies, 2 nested Merge-FLow nodes are needed
        const cellEdges: CellEdge[] = [
            { source: 0, target: 10, parent_var: "a" },
            { source: 1, target: 10, parent_var: "b" },
            { source: 2, target: 10, parent_var: "c" },
            { source: 3, target: 10, parent_var: "d" },
            { source: 4, target: 11, parent_var: "e" },
            { source: 5, target: 11, parent_var: "f" },
            { source: 6, target: 11, parent_var: "g" },
            { source: 7, target: 11, parent_var: "h" },
            { source: 8, target: 11, parent_var: "i" },
            { source: 11, target: 10 }, // inner Merge-Flow node feeds outer merge
            { source: 10, target: 9 }   // 9 is the final Merge Flow node
        ];

        const hasOutgoing = new Set<number>([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]);
        const incomingSources = new Map<number, number[]>([
            [11, [4, 5, 6, 7, 8]],    // inner merge's own sources: e,f,g,h,i
            [10, [0, 1, 2, 3, 11]],   // outer merge: a,b,c,d + inner merge (node 11)
            [9, [10]],                // final consumer takes outer merge's single output
        ]);
        const out = wireCode("print(a+b+c+d+e+f+g+h+i)", 9, cellEdges, hasOutgoing, incomingSources)
        expect(out).toBe("a = arg[0]\nb = arg[1]\nc = arg[2]\nd = arg[3]\ne = arg[4][0]\nf = arg[4][1]\ng = arg[4][2]\nh = arg[4][3]\ni = arg[4][4]\nprint(a+b+c+d+e+f+g+h+i)")
    })

    test("10 dependancies Merge-Flow", ()=>{
        //At 10 dependencies, 3 nested merge flows are needed
        const cellEdges: CellEdge[] = [
            { source: 0, target: 11, parent_var: "a" },
            { source: 1, target: 11, parent_var: "b" },
            { source: 2, target: 11, parent_var: "c" },
            { source: 3, target: 11, parent_var: "d" },
            { source: 4, target: 12, parent_var: "e" },
            { source: 5, target: 12, parent_var: "f" },
            { source: 6, target: 12, parent_var: "g" },
            { source: 7, target: 12, parent_var: "h" },
            { source: 8, target: 13, parent_var: "i" },
            { source: 9, target: 13, parent_var: "j" },
            { source: 13, target: 12 }, // innermost merge feeds middle merge
            { source: 12, target: 11 }, // middle merge feeds outer merge
            { source: 11, target: 10 }  // outer merge feeds final consumer, 10
        ];

        const hasOutgoing = new Set<number>([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13]);
        const incomingSources = new Map<number, number[]>([
            [13, [8, 9]],             // innermost merge: i, j
            [12, [4, 5, 6, 7, 13]],   // middle merge: e,f,g,h + innermost merge (13)
            [11, [0, 1, 2, 3, 12]],   // outer merge: a,b,c,d + middle merge (12)
            [10, [11]],               // final consumer takes outer merge's output
        ]);

        const out = wireCode("print(a+b+c+d+e+f+g+h+i+j)", 10, cellEdges, hasOutgoing, incomingSources)
        expect(out).toBe("a = arg[0]\nb = arg[1]\nc = arg[2]\nd = arg[3]\ne = arg[4][0]\nf = arg[4][1]\ng = arg[4][2]\nh = arg[4][3]\ni = arg[4][4][0]\nj = arg[4][4][1]\nprint(a+b+c+d+e+f+g+h+i+j)")
    })
})

// cd utk_curio/frontend/urban-workflows
// npm test -- NotebookConverter