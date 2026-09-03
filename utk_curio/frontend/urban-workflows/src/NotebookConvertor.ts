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
  /** Display header. Absent here until #235 - which is why every imported
   *  cell rendered as an identical "Python Computation". */
  title?: string;
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

const COLUMN_STRIDE = 700;
const ROW_STRIDE = 450;

/**
 * How many nodes a level may stack before it starts a new column.
 *
 * Every node with no incoming edge lands on level 0, so a notebook full of
 * independent cells used to produce one unbounded vertical column - twenty
 * cells meant a 9000px drop nobody scrolls through (#235). Wrapping keeps a
 * level roughly screen-shaped. The cap applies to every level uniformly and
 * only engages past it, so an ordinary pipeline lays out exactly as before.
 */
const MAX_ROWS_PER_LEVEL = 6;

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
    // Overflow spills into sub-columns to the right of the level. The stride
    // is half a column so a wrapped level stays visually part of its own
    // stage rather than reading as the next one.
    const wrap = Math.floor(pos / MAX_ROWS_PER_LEVEL);
    return {
      x: lv * COLUMN_STRIDE + wrap * (COLUMN_STRIDE / 2),
      y: (pos % MAX_ROWS_PER_LEVEL) * ROW_STRIDE,
    };
  });
}

export const SETUP_NODE_TITLE = "Setup / Imports";

/**
 * Fold several import-only cells into one block of source.
 *
 * Lines are deduplicated on their trimmed text and kept in first-seen order,
 * because notebooks routinely repeat `import pandas as pd` in three separate
 * setup cells and the merged node should read like something a person wrote.
 * Blank lines are dropped: the cell boundaries they used to separate no
 * longer exist.
 */
export function mergeImportCells(sources: string[]): string {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const source of sources) {
    for (const raw of source.split("\n")) {
      const line = raw.trimEnd();
      const key = line.trim();
      if (key === "") continue;
      if (seen.has(key)) continue;
      seen.add(key);
      lines.push(line);
    }
  }
  return lines.join("\n");
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
    is_import_only?: boolean;
  };
  let cellEdges: CellEdge[] = [];
  let lastVars: (string | null)[] = [];
  let altairSpecs: (Record<string, unknown> | null)[] = [];
  let importOnly: boolean[] = [];
  // Whether the analyzer actually answered. Distinct from "returned no edges":
  // a notebook of genuinely independent cells has none, and fabricating a
  // chain for it would wire `arg` between cells the AST proved unrelated - and
  // stretch the layout 700px per cell for dependencies that do not exist.
  let analyzed = false;
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
      importOnly = (data.analysis ?? []).map((a) => a.is_import_only === true);
      analyzed = Array.isArray(data.analysis);
    }
  } catch {
    console.warn(
      "NotebookConvertor: backend unreachable, falling back to linear chain."
    );
  }

  // Linear fallback, for when the analyzer could not be reached at all. A
  // chain is a guess, but a defensible one with no information; it used to
  // fire whenever the response merely carried no edges, which meant a notebook
  // the analyzer had correctly found to be independent got the guess anyway.
  if (!analyzed && codeCells.length > 1) {
    for (let i = 0; i < codeCells.length - 1; i++) {
      cellEdges.push({ source: i, target: i + 1 });
    }
    // No lastVars available — skip wiring in this path
    lastVars = [];
    // …and no analysis, so nothing can be classified. Merging on a guess would
    // silently move code the user wrote into a node they did not: without the
    // backend, every cell keeps its own node exactly as before.
    importOnly = [];
  }

  // Build wiring sets
  const hasOutgoing = new Set(cellEdges.map((e) => e.source));
  const incomingSources = new Map<number, number[]>();
  for (const { source, target } of cellEdges) {
    if (!incomingSources.has(target)) incomingSources.set(target, []);
    incomingSources.get(target)!.push(source);
  }

  // Import-only cells collapse into a single Setup node. They can have no
  // edges by construction (see analyzer._is_import_only), so removing them
  // cannot disconnect anything - which is what makes the remap below safe.
  const mergedCells = codeCells.filter((_, i) => importOnly[i]);
  const keptIndices = codeCells
    .map((_, i) => i)
    .filter((i) => !importOnly[i]);

  // Original cell index -> index among the kept cells. Edges, positions and
  // ids are all in kept-space; wiring stays in original-space, because
  // `lastVars`/`hasOutgoing`/`incomingSources` are indexed by cell.
  const keptSlot = new Map<number, number>();
  keptIndices.forEach((original, slot) => keptSlot.set(original, slot));

  const keptEdges: CellEdge[] = cellEdges
    .filter(({ source, target }) => keptSlot.has(source) && keptSlot.has(target))
    .map(({ source, target }) => ({
      source: keptSlot.get(source)!,
      target: keptSlot.get(target)!,
    }));

  const positions = computeLayout(keptIndices.length, keptEdges);
  const nodeIds = keptIndices.map(() => uuid());

  const nodes: TrillNode[] = keptIndices.map((original, slot) => {
    const code = codeCells[original];
    const spec = altairSpecs[original] ?? null;
    const nodeType = spec ? NodeType.VIS_VEGA : inferNodeType(code);
    const content = spec
      ? JSON.stringify(spec, null, 2)
      : lastVars.length > 0
        ? wireCode(code, original, lastVars, hasOutgoing, incomingSources)
        : code;
    const node: TrillNode = {
      id: nodeIds[slot],
      type: nodeType,
      x: positions[slot].x,
      y: positions[slot].y,
      content,
    };
    // Name the node after what it produces. Without this every node renders
    // as its template label, so a twenty-cell notebook imported as twenty
    // boxes all reading "Python Computation" (#235).
    const producedName = lastVars[original];
    if (producedName) node.title = producedName;
    return node;
  });

  if (mergedCells.length > 0) {
    // Placed up and to the left of the pipeline rather than in column 0, where
    // it would sit on top of the first real stage. Curio hoists a node's
    // imports into a session-scoped namespace, so one Setup node run first
    // genuinely serves the rest of the dataflow - this is not just grouping.
    nodes.unshift({
      id: uuid(),
      type: NodeType.COMPUTATION_ANALYSIS,
      x: -COLUMN_STRIDE / 2,
      y: -ROW_STRIDE / 2,
      title: SETUP_NODE_TITLE,
      content: mergeImportCells(mergedCells),
    });
  }

  const edgeList: TrillEdge[] = keptEdges.map(({ source, target }) => ({
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
