/**
 * Export half of NotebookConvertor.
 *
 * Written after a user test exported a three-node dataflow as a one-cell
 * notebook whose only cell did not compile. Nothing here existed before, which
 * is why both defects shipped: `generateCell` returned `null` for every node
 * type except three, and the cells it did emit carried the node body verbatim -
 * a body that ends in `return`, which is a SyntaxError at a notebook's top
 * level, and that reads an input nothing ever bound.
 */
import { trillToNotebook, serializeNotebook, type TrillSpec } from "../NotebookConvertor";
import { NodeType } from "../constants";

type NodeSpec = { id: string; type: string; content?: string };

/** An edge is [source, target], or [source, target, targetHandle] for a circle. */
function spec(nodes: NodeSpec[], edges: Array<[string, string, string?]> = []): TrillSpec {
  return {
    dataflow: {
      nodes: nodes.map((n, i) => ({ ...n, x: i * 700, y: 0 })),
      edges: edges.map(([source, target, targetHandle], i) => ({
        id: `e${i}`,
        source,
        target,
        ...(targetHandle ? { targetHandle } : {}),
      })),
      name: "Test",
      task: "",
      timestamp: 0,
      provenance_id: "p",
    },
  };
}

const codeCells = (nb: ReturnType<typeof trillToNotebook>) =>
  nb.cells.filter((c) => c.cell_type === "code");

/** Every top-level `return` is a SyntaxError in a notebook. */
function topLevelReturns(source: string): string[] {
  return source.split(/\r?\n/).filter((line) => /^return\b/.test(line));
}

describe("trillToNotebook", () => {
  it("emits a cell for every node type, not just the three the importer makes", () => {
    const everyType = [
      NodeType.DATA_LOADING,
      NodeType.DATA_TRANSFORMATION,
      NodeType.COMPUTATION_ANALYSIS,
      NodeType.DATA_SUMMARY,
      NodeType.DATA_EXPORT,
      NodeType.DATA_POOL,
      NodeType.VIS_VEGA,
      NodeType.VIS_SIMPLE,
      NodeType.AUTK_GRAMMAR,
      NodeType.JS_COMPUTATION,
      "curio.builtin/spatial-join",
      "acme.geo/buffer@2", // a third-party package node
    ];
    const nb = trillToNotebook(
      spec(
        everyType.map((type, i) => ({
          id: `n${i}`,
          type,
          content: type === NodeType.VIS_VEGA ? '{"mark":"bar"}' : "return input_0\n",
        }))
      )
    );

    for (const type of everyType) {
      expect(serializeNotebook(nb)).toContain(type.split("@")[0]);
    }
    // Each node contributes at least one cell.
    expect(nb.cells.length).toBeGreaterThanOrEqual(everyType.length);
  });

  it("emits Python cells with no top-level return", () => {
    const nb = trillToNotebook(
      spec([
        {
          id: "loader",
          type: NodeType.DATA_LOADING,
          content: "import pandas as pd\n\nreturn pd.DataFrame({'a': [1, 2]})\n",
        },
        {
          id: "xform",
          type: NodeType.DATA_TRANSFORMATION,
          content: "df = input_0.copy()\ndf['b'] = df['a'] * 2\nreturn df\n",
        },
      ])
    );

    for (const cell of codeCells(nb)) {
      expect(topLevelReturns(cell.source)).toEqual([]);
    }
  });

  it("keeps a multi-line return intact by preserving the function", () => {
    // A textual `return X` -> `var = X` rewrite mangles this; wrapping the body
    // back into its function does not. simple-view.json contains exactly this.
    const content = "import pandas as pd\n\nreturn pd.DataFrame({\n    'city': ['Chicago'],\n})\n";
    const nb = trillToNotebook(spec([{ id: "n", type: NodeType.DATA_LOADING, content }]));
    const source = codeCells(nb)[0].source;

    expect(source).toContain("def node_n():");
    expect(source).toContain("    return pd.DataFrame({");
    expect(source).toContain("        'city': ['Chicago'],");
    expect(source).toContain("data_n = node_n()");
  });

  it("binds input_0 to the upstream value", () => {
    const nb = trillToNotebook(
      spec(
        [
          { id: "src", type: NodeType.DATA_LOADING, content: "return 1\n" },
          { id: "dst", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0 + 1\n" },
        ],
        [["src", "dst"]]
      )
    );
    const downstream = codeCells(nb).find((c) => c.source.includes("node_dst"))!;

    // The upstream variable is passed in, not merely mentioned in a comment.
    expect(downstream.source).toContain("result_dst = node_dst(input_0=data_src)");
  });

  it("passes a node's several inputs each as its circle's input_k, as the sandbox does", () => {
    // The edges are listed against circle order on purpose: `a` feeds circle 1
    // and `b` circle 0, so each must go to its circle, not follow the edge list.
    const nb = trillToNotebook(
      spec(
        [
          { id: "a", type: NodeType.DATA_LOADING, content: "return 1\n" },
          { id: "b", type: NodeType.DATA_LOADING, content: "return 2\n" },
          { id: "m", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0, input_1\n" },
        ],
        [
          ["a", "m", "in_1"],
          ["b", "m", "in"],
        ]
      )
    );
    const cell = codeCells(nb).find((c) => c.source.includes("def node_m(input_0=None, input_1=None):"))!;
    expect(cell.source.split("\n").pop()).toBe("result_m = node_m(input_0=data_b, input_1=data_a)");
  });

  it("records a node a Python kernel cannot run instead of dropping it", () => {
    const nb = trillToNotebook(
      spec([{ id: "js", type: NodeType.JS_COMPUTATION, content: "return input_0 * 2;" }])
    );
    const markdown = nb.cells.filter((c) => c.cell_type === "markdown");

    expect(markdown.some((c) => c.source.includes("JavaScript"))).toBe(true);
    expect(serializeNotebook(nb)).toContain("return input_0 * 2;");
    // And it did not pretend to be runnable Python.
    expect(codeCells(nb)).toHaveLength(0);
  });

  it("embeds a Vega-Lite spec as an object, not a JSON string", () => {
    const nb = trillToNotebook(
      spec([{ id: "v", type: NodeType.VIS_VEGA, content: '{"mark": "bar"}' }])
    );
    const source = codeCells(nb)[0].source;

    expect(source).toContain('_spec = {');
    expect(source).toContain('"mark": "bar"');
    // The old form round-tripped the spec through a string literal, so
    // json.loads produced a str and the mimebundle was unusable.
    expect(source).not.toContain("json.loads");
  });

  it("embeds a package chart that draws with Vega-Lite as the Vega-Lite node's spec is, its widgets read", () => {
    // A SCOUT Comparison chart draws with the Vega-Lite node's behavior; its
    // spec reads the columns its widgets name.
    const { VEGA_LITE_TEMPLATE, registerVegaLiteTemplate, clearVegaLiteTemplate } = require("./_support/vegaLiteTemplate");
    registerVegaLiteTemplate();
    try {
      const chart = {
        id: "v",
        type: VEGA_LITE_TEMPLATE,
        content: '{"mark": "bar", "encoding": {"y": {"field": "[!! y !!]"}}}',
        metadata: { widgets: [{ name: "y", type: "text", label: "Y column", default: "y", value: "pedestrians" }] },
      };
      const source = codeCells(trillToNotebook(spec([chart as NodeSpec])))[0].source;

      expect(source).toContain('_spec = {');
      expect(source).toContain('"field": "pedestrians"');
      expect(source).not.toContain("[!!");
    } finally {
      clearVegaLiteTemplate();
    }
  });

  it("does not lose a node that sits in a cycle", () => {
    const nb = trillToNotebook(
      spec(
        [
          { id: "a", type: NodeType.DATA_TRANSFORMATION, content: "return input_0\n" },
          { id: "b", type: NodeType.DATA_TRANSFORMATION, content: "return input_0\n" },
        ],
        [
          ["a", "b"],
          ["b", "a"],
        ]
      )
    );
    expect(serializeNotebook(nb)).toContain("node_a");
    expect(serializeNotebook(nb)).toContain("node_b");
  });
});

describe("trillToNotebook with inputs named input_k", () => {
  it("a source takes no inputs", () => {
    const nb = trillToNotebook(spec([{ id: "n", type: NodeType.DATA_LOADING, content: "return 1\n" }]));
    const source = codeCells(nb)[0].source;
    expect(source).toContain("def node_n():");
    expect(source).toContain("data_n = node_n()");
  });

  it("passes the upstream value as input_0", () => {
    const nb = trillToNotebook(
      spec(
        [
          { id: "src", type: NodeType.DATA_LOADING, content: "return 1\n" },
          { id: "dst", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0 + 1\n" },
        ],
        [["src", "dst"]]
      )
    );
    const downstream = codeCells(nb).find((c) => c.source.includes("node_dst"))!;
    expect(downstream.source).toContain("def node_dst(input_0=None):");
    expect(downstream.source).toContain("result_dst = node_dst(input_0=data_src)");
  });

  it("passes each input as its circle's input_k, and an input_k with no edge is None", () => {
    // `a` feeds circle 2 and `b` circle 0, against the edge list's order.
    const nb = trillToNotebook(
      spec(
        [
          { id: "a", type: NodeType.DATA_LOADING, content: "return 1\n" },
          { id: "b", type: NodeType.DATA_LOADING, content: "return 2\n" },
          { id: "m", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0, input_1, [!! input_2 !!]\n" },
        ],
        [
          ["a", "m", "in_2"],
          ["b", "m", "in"],
        ]
      )
    );
    const cell = codeCells(nb).find((c) => c.source.includes("node_m"))!;
    expect(cell.source).toContain("def node_m(input_0=None, input_1=None, input_2=None):");
    expect(cell.source).toContain("    return input_0, input_1, input_2");
    expect(cell.source.split("\n").pop()).toBe("result_m = node_m(input_0=data_b, input_2=data_a)");
  });

  it("an input_k read only inside an f-string's braces is a parameter too, as the sandbox makes it", () => {
    const nb = trillToNotebook(
      spec(
        [
          { id: "a", type: NodeType.DATA_LOADING, content: "return 1\n" },
          { id: "m", type: NodeType.COMPUTATION_ANALYSIS, content: 'return f"{input_0} and {input_1}, not input_2"\n' },
        ],
        [["a", "m"]]
      )
    );
    const cell = codeCells(nb).find((c) => c.source.includes("node_m"))!;
    expect(cell.source).toContain("def node_m(input_0=None, input_1=None):");
  });
});
