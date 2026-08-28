import { v4 as uuid } from "uuid";
import { NodeType } from "./constants";
import { unversionedNodeType } from "./utils/flowNodeCanonicalType";

// ── Trill types ──────────────────────────────────────────────────────────────

interface TrillNode {
  id: string;
  type: string;
  x: number;
  y: number;
  content?: string;
  in?: unknown;
  out?: unknown;
}

interface TrillEdge {
  id: string;
  source: string;
  target: string;
  type?: string;
}

interface TrillDataflow {
  nodes: TrillNode[];
  edges: TrillEdge[];
  name: string;
  task: string;
  timestamp: number;
  provenance_id: string;
  packages?: string[];
}

export interface TrillSpec {
  dataflow: TrillDataflow;
}

// ── Notebook types ───────────────────────────────────────────────────────────

interface NotebookCell {
  cell_type: "code" | "markdown" | string;
  source: string;
  metadata: Record<string, unknown>;
  outputs: unknown[];
  execution_count: null;
}

export interface Notebook {
  cells: NotebookCell[];
  metadata: Record<string, unknown>;
  nbformat: number;
  nbformat_minor: number;
}

// ── Node type inference ──────────────────────────────────────────────────────

const DATA_LOADING_PATTERN =
  /\bpd\.read_\w+\s*\(|\bgpd\.read_\w+\s*\(|\bgeopandas\.read_\w+\s*\(|\bopen\s*\(|\brequests\.(get|post|put|delete|patch)\s*\(|\bsqlite3\.connect\s*\(|\bpsycopg2\.connect\s*\(|\bcreate_engine\s*\(|\bboto3\b/;

function isVegaLiteJson(text: string): boolean {
  try {
    const parsed = JSON.parse(text.trim()) as Record<string, unknown>;
    if (typeof parsed === "object" && parsed !== null) {
      const schema = parsed["$schema"];
      return typeof schema === "string" && schema.includes("vega-lite");
    }
  } catch {
    // not JSON
  }
  return false;
}

function inferNodeType(code: string): NodeType {
  if (DATA_LOADING_PATTERN.test(code)) return NodeType.DATA_LOADING;
  if (isVegaLiteJson(code)) return NodeType.VIS_VEGA;
  return NodeType.COMPUTATION_ANALYSIS;
}

// ── Import: Notebook → Trill ─────────────────────────────────────────────────

type CellEdge = { source: number; target: number };

function wireCode(
  code: string,
  cellIdx: number,
  lastVars: (string | null)[],
  hasOutgoing: Set<number>,
  incomingSources: Map<number, number[]>,
): string {
  let out = code;
  const sources = incomingSources.get(cellIdx) ?? [];
  if (sources.length === 1) {
    const srcVar = lastVars[sources[0]] ?? "arg";
    out = `${srcVar} = arg\n${out}`;
  } else if (sources.length > 1) {
    out = `# multiple inputs available via arg\n${out}`;
  }
  const lv = lastVars[cellIdx];
  if (hasOutgoing.has(cellIdx) && lv) {
    out = `${out}\nreturn ${lv}`;
  }
  return out;
}

function computeLayout(
  count: number,
  edges: CellEdge[],
): Array<{ x: number; y: number }> {
  const level = new Array<number>(count).fill(0);
  for (const { source, target } of edges) {
    if (level[source] + 1 > level[target]) {
      level[target] = level[source] + 1;
    }
  }
  const countPerLevel = new Map<number, number>();
  return level.map((lv) => {
    const pos = countPerLevel.get(lv) ?? 0;
    countPerLevel.set(lv, pos + 1);
    return { x: lv * 700, y: pos * 450 };
  });
}

export async function notebookToTrill(
  notebook: Record<string, unknown>,
  backendUrl: string
): Promise<TrillSpec> {
  const rawCells = Array.isArray(notebook.cells) ? notebook.cells : [];

  const codeCells = rawCells
    .filter((c) => (c as Record<string, unknown>).cell_type === "code")
    .map((c) => {
      const cell = c as Record<string, unknown>;
      const source = cell.source;
      return Array.isArray(source) ? source.join("") : String(source ?? "");
    });

  // Call backend for AST-based dependency analysis + Altair spec extraction
  type CellAnalysis = {
    defined: string[];
    used: string[];
    last_var: string | null;
    altair_spec: Record<string, unknown> | null;
  };
  let cellEdges: CellEdge[] = [];
  let lastVars: (string | null)[] = [];
  let altairSpecs: (Record<string, unknown> | null)[] = [];
  try {
    const response = await fetch(`${backendUrl}/api/analyzeNotebook`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cells: codeCells }),
    });
    if (response.ok) {
      const data = (await response.json()) as {
        edges: CellEdge[];
        analysis: CellAnalysis[];
      };
      cellEdges = data.edges ?? [];
      lastVars = (data.analysis ?? []).map((a) => a.last_var ?? null);
      altairSpecs = (data.analysis ?? []).map((a) => a.altair_spec ?? null);
    }
  } catch {
    console.warn(
      "NotebookConvertor: backend unreachable, falling back to linear chain."
    );
  }

  // Linear fallback when backend returned no edges
  if (cellEdges.length === 0 && codeCells.length > 1) {
    for (let i = 0; i < codeCells.length - 1; i++) {
      cellEdges.push({ source: i, target: i + 1 });
    }
    // No lastVars available — skip wiring in this path
    lastVars = [];
  }

  // Build wiring sets
  const hasOutgoing = new Set(cellEdges.map((e) => e.source));
  const incomingSources = new Map<number, number[]>();
  for (const { source, target } of cellEdges) {
    if (!incomingSources.has(target)) incomingSources.set(target, []);
    incomingSources.get(target)!.push(source);
  }

  const positions = computeLayout(codeCells.length, cellEdges);

  const nodeIds = codeCells.map(() => uuid());

  const nodes: TrillNode[] = codeCells.map((code, index) => {
    const spec = altairSpecs[index] ?? null;
    const nodeType = spec ? NodeType.VIS_VEGA : inferNodeType(code);
    const content = spec
      ? JSON.stringify(spec, null, 2)
      : lastVars.length > 0
        ? wireCode(code, index, lastVars, hasOutgoing, incomingSources)
        : code;
    return {
      id: nodeIds[index],
      type: nodeType,
      x: positions[index].x,
      y: positions[index].y,
      content,
    };
  });

  const edgeList: TrillEdge[] = cellEdges
    .filter(({ source, target }) => nodes[source] && nodes[target])
    .map(({ source, target }) => ({
      id: uuid(),
      source: nodeIds[source],
      target: nodeIds[target],
    }));

  return {
    dataflow: {
      nodes,
      edges: edgeList,
      name: "Imported Notebook",
      task: "",
      timestamp: Date.now(),
      provenance_id: uuid(),
    },
  };
}

// ── Export: Trill → Notebook ─────────────────────────────────────────────────

function sanitizeId(id: string): string {
  return id.replace(/[^a-zA-Z0-9]/g, "_");
}

function outputVarName(node: TrillNode): string {
  const safe = sanitizeId(node.id);
  // Specs saved since the curio.builtin@1 pack carry versioned ids (dev/64).
  const nodeType = unversionedNodeType(node.type);
  if (nodeType === NodeType.DATA_LOADING) return `data_${safe}`;
  if (nodeType === NodeType.VIS_VEGA) return `vega_${safe}`;
  return `result_${safe}`;
}

function topologicalSort(nodes: TrillNode[], edges: TrillEdge[]): TrillNode[] {
  const inDegree = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  const dependents = new Map<string, string[]>(nodes.map((n) => [n.id, []]));

  for (const edge of edges) {
    if (edge.type === "Interaction") continue;
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    dependents.get(edge.source)?.push(edge.target);
  }

  const queue = nodes.filter((n) => (inDegree.get(n.id) ?? 0) === 0);
  const result: TrillNode[] = [];

  while (queue.length > 0) {
    const node = queue.shift()!;
    result.push(node);
    for (const depId of dependents.get(node.id) ?? []) {
      const newDeg = (inDegree.get(depId) ?? 1) - 1;
      inDegree.set(depId, newDeg);
      if (newDeg === 0) {
        const depNode = nodes.find((n) => n.id === depId);
        if (depNode) queue.push(depNode);
      }
    }
  }

  // Append any remaining nodes (cycles or disconnected)
  const visited = new Set(result.map((n) => n.id));
  for (const node of nodes) {
    if (!visited.has(node.id)) result.push(node);
  }

  return result;
}

/** Templates whose ``content`` is a Python function body, run as ``userCode(arg)``. */
const PYTHON_BODY_TYPES = new Set<string>([
  NodeType.DATA_LOADING,
  NodeType.DATA_TRANSFORMATION,
  NodeType.COMPUTATION_ANALYSIS,
  NodeType.DATA_SUMMARY,
  NodeType.DATA_EXPORT,
]);

/** ``curio.builtin/spatial-join`` has no ``NodeType`` member (the enum predates it). */
const SPATIAL_JOIN_TYPE = "curio.builtin/spatial-join";

function codeCell(source: string): NotebookCell {
  return {
    cell_type: "code",
    source,
    metadata: {},
    outputs: [],
    execution_count: null,
  };
}

function markdownCell(source: string): NotebookCell {
  return {
    cell_type: "markdown",
    source,
    metadata: {},
    outputs: [],
    execution_count: null,
  };
}

/** How a node names the value it received, mirroring the sandbox's ``arg``.
 *
 * ``worker.py`` hands a merge node a *tuple* of its upstream outputs, so several
 * inputs become a tuple here too. No inputs means the body is a source and gets
 * ``None``.
 */
function argExpression(inputNodes: TrillNode[]): string {
  if (inputNodes.length === 0) return "None";
  if (inputNodes.length === 1) return outputVarName(inputNodes[0]);
  return `(${inputNodes.map(outputVarName).join(", ")})`;
}

function indent(text: string): string {
  return text
    .split(/\r?\n/)
    .map((line) => (line.trim() === "" ? "" : `    ${line}`))
    .join("\n");
}

/** A heading a reader can use to line the notebook up against the canvas. */
function nodeHeading(node: TrillNode, inputNodes: TrillNode[]): string {
  const inputs = inputNodes.length
    ? ` &larr; ${inputNodes.map(outputVarName).join(", ")}`
    : "";
  return `### \`${unversionedNodeType(node.type)}\` &mdash; \`${node.id}\`${inputs}`;
}

/** Emit the cells for one node.
 *
 * Returns a list rather than a single cell (or ``null``) so that a node can
 * contribute a heading plus a body, and so that a template a Python kernel
 * cannot run still leaves a record instead of vanishing. The previous version
 * returned ``null`` for every type except three, and ``trillToNotebook`` then
 * dropped those nodes without saying so.
 */
function generateCells(node: TrillNode, inputNodes: TrillNode[]): NotebookCell[] {
  const content = node.content ?? "";
  // Specs saved since the curio.builtin@1 pack carry versioned ids (dev/64),
  // and third-party package ids never match a NodeType at all - so this
  // dispatch always ends in a default branch rather than an enumeration.
  const nodeType = unversionedNodeType(node.type);
  const outVar = outputVarName(node);
  const heading = markdownCell(nodeHeading(node, inputNodes));

  if (PYTHON_BODY_TYPES.has(nodeType)) {
    // A node's content is the body of `def userCode(arg):` - PythonInterpreter
    // indents it by four spaces and the sandbox execs it under exactly that
    // signature. Reproducing the function is the only faithful inversion:
    // emitting the body flat would leave a top-level `return` (a SyntaxError)
    // and an unbound `arg`, which is what shipped.
    const fn = `node_${sanitizeId(node.id)}`;
    const body = content.trim() === "" ? "    pass" : indent(content);
    return [
      heading,
      codeCell(`def ${fn}(arg):\n${body}\n\n\n${outVar} = ${fn}(${argExpression(inputNodes)})`),
    ];
  }

  if (nodeType === NodeType.DATA_POOL) {
    // A pool passes its input through untouched.
    const source = inputNodes.length
      ? `${outVar} = ${outputVarName(inputNodes[0])}`
      : `${outVar} = None`;
    return [heading, codeCell(source)];
  }

  if (nodeType === NodeType.MERGE_FLOW) {
    return [heading, codeCell(`${outVar} = ${argExpression(inputNodes)}`)];
  }

  if (nodeType === NodeType.VIS_VEGA) {
    let spec: unknown = {};
    let parsed = true;
    try {
      spec = JSON.parse(content);
    } catch {
      parsed = false;
    }
    if (!parsed) {
      return [
        heading,
        markdownCell(
          "This Vega-Lite node's specification is not valid JSON, so it is " +
            "recorded here rather than rendered:\n\n```json\n" +
            content +
            "\n```"
        ),
      ];
    }
    // json.loads of a JSON *string* would yield a Python str rather than a
    // dict, which is not a usable mimebundle - so the spec is embedded as a
    // literal object instead.
    const lines = [
      "from IPython.display import display",
      "",
      `_spec = ${JSON.stringify(spec, null, 2)}`,
    ];
    if (inputNodes.length) {
      lines.push(
        "",
        "# Attach the upstream rows the canvas would have supplied.",
        `_spec["data"] = {"values": ${outputVarName(inputNodes[0])}.to_dict(orient="records")}`
      );
    }
    lines.push(
      "",
      'display({"application/vnd.vegalite.v5+json": _spec, "text/plain": "<VegaLite>"}, raw=True)'
    );
    return [heading, codeCell(lines.join("\n"))];
  }

  // Everything a Python kernel cannot run: an Autark grammar document (which
  // goes through the JS interpreter despite its manifest engine), a JavaScript
  // computation, and the presentational templates that carry no content.
  // Recorded, never silently dropped.
  const why =
    nodeType === NodeType.AUTK_GRAMMAR
      ? "An Autark grammar specification. It renders through Curio's WebGPU pipeline, not a Python kernel."
      : nodeType === NodeType.JS_COMPUTATION
        ? "A JavaScript computation. Its source is preserved below; it cannot run in this notebook's Python kernel."
        : nodeType === SPATIAL_JOIN_TYPE
          ? "A spatial join, configured on the canvas rather than in code."
          : nodeType === NodeType.VIS_SIMPLE
            ? "A Simple View node, which displays its input rather than computing anything."
            : "This node is provided by a package and has no Python equivalent here.";
  const fenced = content.trim()
    ? `\n\n\`\`\`\n${content}\n\`\`\``
    : "";
  return [markdownCell(`${nodeHeading(node, inputNodes)}\n\n${why}${fenced}`)];
}

export function trillToNotebook(spec: TrillSpec): Notebook {
  const nodes = spec.dataflow?.nodes ?? [];
  const edges = spec.dataflow?.edges ?? [];

  const inputsOf = new Map<string, string[]>(nodes.map((n) => [n.id, []]));
  for (const edge of edges) {
    if (edge.type !== "Interaction") {
      inputsOf.get(edge.target)?.push(edge.source);
    }
  }

  const nodeById = new Map(nodes.map((n) => [n.id, n]));
  const ordered = topologicalSort(nodes, edges);

  const cells: NotebookCell[] = [];
  for (const node of ordered) {
    const inputNodes = (inputsOf.get(node.id) ?? [])
      .map((id) => nodeById.get(id))
      .filter((n): n is TrillNode => n !== undefined);
    cells.push(...generateCells(node, inputNodes));
  }

  return {
    cells,
    metadata: {
      kernelspec: {
        display_name: "Python 3",
        language: "python",
        name: "python3",
      },
      language_info: { name: "python" },
    },
    nbformat: 4,
    nbformat_minor: 4,
  };
}

export function serializeNotebook(notebook: Notebook): string {
  return JSON.stringify(notebook, null, 2);
}
