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
import scenarioChips from "../utils/scenarios/scenarioChips.cases.json";

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

/** The words a Python literal holds outside its strings, and what JSON writes for each. */
const PYTHON_WORDS = new Map([["True", "true"], ["False", "false"], ["None", "null"]]);

/**
 * *text*, a Python literal of dicts, lists, double-quoted strings, numbers,
 * True, False and None, read back as the value it holds. JSON's own true,
 * false and null are no Python (a kernel raises a NameError on each), so any
 * word but Python's three is refused.
 */
function pythonLiteral(text: string): unknown {
  let json = "";
  let at = 0;
  while (at < text.length) {
    const rest = text.slice(at);
    if (rest[0] === '"') {
      let end = 1;
      while (end < rest.length && rest[end] !== '"') end += rest[end] === "\\" ? 2 : 1;
      json += rest.slice(0, end + 1);
      at += end + 1;
      continue;
    }
    const number = /^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/.exec(rest);
    if (number) {
      json += number[0];
      at += number[0].length;
      continue;
    }
    const word = /^[A-Za-z_]\w*/.exec(rest);
    if (word) {
      const literal = PYTHON_WORDS.get(word[0]);
      if (literal === undefined) throw new Error(`not a Python literal: ${word[0]}`);
      json += literal;
      at += word[0].length;
      continue;
    }
    json += rest[0];
    at += 1;
  }
  return JSON.parse(json);
}

/** The spec a chart cell assigns to `_spec`, read back from its Python literal. */
const embeddedSpec = (source: string): unknown => pythonLiteral(source.split("_spec = ")[1].split("\n\n")[0]);

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

  it("writes the spec as Python writes it: true, false and null as True, False and None, which a kernel runs", () => {
    const chart = {
      mark: { type: "point", tooltip: true, filled: false },
      encoding: { x: { field: "true", type: "nominal", title: null }, y: { field: "a \"null\" here", type: "quantitative" } },
      config: { view: { stroke: null }, padding: [5, -1.5, 1e21, 0] },
      usermeta: { note: "None of False is True" },
    };
    const source = codeCells(trillToNotebook(spec([{ id: "v", type: NodeType.VIS_VEGA, content: JSON.stringify(chart) }])))[0].source;

    expect(embeddedSpec(source)).toEqual(chart);
    expect(source).toContain('"tooltip": True');
    expect(source).toContain('"filled": False');
    expect(source).toContain('"title": None');
  });

  it("embeds a package chart that draws with Vega-Lite as the Vega-Lite node's spec is, its widgets read", () => {
    // A Scout chart draws with the Vega-Lite node's behavior; its
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

describe("trillToNotebook with a chart that reads its inputs stacked", () => {
  /** load feeds base, in the Baseline box, and free, in no box; both feed the chart. */
  function stackedChart(chartSpec: string): TrillSpec {
    const flow = spec(
      [
        { id: "load", type: NodeType.DATA_LOADING, content: "return 1\n" },
        { id: "base", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0\n" },
        { id: "free", type: NodeType.COMPUTATION_ANALYSIS, content: "return input_0\n", title: "Free node" } as NodeSpec,
        { id: "v", type: NodeType.VIS_VEGA, content: chartSpec },
      ],
      [
        ["load", "base"],
        ["load", "free"],
        ["base", "v", "in"],
        ["free", "v", "in_1"],
      ],
    );
    flow.dataflow.scenarios = [{ id: "s-base", name: "Baseline", color: "#2a9d8f", nodes: ["base"] }];
    return flow;
  }
  const chartCell = (nb: ReturnType<typeof trillToNotebook>) =>
    codeCells(nb).find((c) => c.source.includes("_spec = {"))!.source;

  it("draws scenario_name in the boxes' colors and order, then an input from no box, as the canvas does", () => {
    const chart = '{"data": {"name": "inputs"}, "mark": "bar", "encoding": {"color": {"field": "scenario_name", "type": "nominal"}}}';
    const source = chartCell(trillToNotebook(stackedChart(chart)));
    const embedded = embeddedSpec(source) as any;
    expect(embedded.encoding.color.scale).toEqual({ domain: ["Baseline", "Free node"], range: ["#2a9d8f", "#8a8f98"] });
  });

  it("with no input from a box, keeps the spec's own colors, as the canvas does", () => {
    const chart = {
      data: { name: "inputs" },
      mark: "bar",
      encoding: { color: { field: "scenario_name", type: "nominal", scale: { range: ["#000000", "#999999"] } } },
    };
    const flow = stackedChart(JSON.stringify(chart));
    flow.dataflow.scenarios = [];
    expect(embeddedSpec(chartCell(trillToNotebook(flow)))).toEqual(chart);
  });

  it("stacks its inputs with utk_curio's stack_inputs, each under its box, as the canvas does", () => {
    const source = chartCell(trillToNotebook(stackedChart('{"data": {"name": "inputs"}, "mark": "bar"}')));
    expect(source).toContain("from utk_curio.sandbox.util.scenario_stack import input_rows, stack_inputs");
    expect(source).toContain(
      [
        '_spec["datasets"]["inputs"] = stack_inputs([',
        '    ("s-base", "Baseline", result_base),',
        '    (None, "Free node", result_free),',
        "])",
      ].join("\n"),
    );
    // Each input is its own dataset too, a value as rows as the stacking reads
    // it, and the spec keeps reading inputs.
    expect(source).toContain('_spec["datasets"]["input_0"] = input_rows(result_base)');
    expect(source).toContain('_spec["datasets"]["input_1"] = input_rows(result_free)');
    expect(source).not.toContain("to_dict(");
    expect(source).not.toContain('_spec["data"] =');
  });

  it("a chart that does not read inputs stacks nothing and imports nothing of Curio's", () => {
    const source = chartCell(trillToNotebook(stackedChart('{"mark": "bar"}')));
    expect(source).not.toContain("utk_curio");
    expect(source).not.toContain("stack_inputs");
    expect(source).toContain('_spec["datasets"]["input_1"] = result_free.to_dict(orient="records")');
    expect(source).toContain('_spec["data"] = {"name": "input_0"}');
    // The same dataflow's chart that reads inputs does.
    expect(chartCell(trillToNotebook(stackedChart('{"data": {"name": "inputs"}, "mark": "bar"}')))).toContain("stack_inputs(");
  });
});

describe("trillToNotebook writes each spec with its scenario chips resolved, as the server does", () => {
  // scenarioChips.cases.json: test_scenario_chips.py resolves the same nodes
  // through WorkflowSpec.node_code, which a server run and the agents' check use.
  type ChipCase = { name: string; node: string; grammar?: string; dataflow: TrillSpec["dataflow"]; expected: string };
  const chipCases = (scenarioChips.cases as unknown as ChipCase[]).map((c) => [c.name, c] as const);

  it.each(chipCases)("%s", (_name, c) => {
    const nb = trillToNotebook({ dataflow: { ...c.dataflow, name: "Chips", task: "", timestamp: 0, provenance_id: "p" } });
    // The node's heading names it; a chart's cell follows it, an Autark map's is it.
    const at = nb.cells.findIndex((cell) => cell.cell_type === "markdown" && cell.source.includes(`\`${c.node}\``));
    expect(at).toBeGreaterThanOrEqual(0);
    if (c.grammar === "vega-lite") {
      const cell = nb.cells[at + 1];
      expect(cell.cell_type).toBe("code");
      expect(embeddedSpec(cell.source)).toEqual(JSON.parse(c.expected));
    } else {
      expect(nb.cells[at].source).toContain("```\n" + c.expected + "\n```");
    }
  });
});
