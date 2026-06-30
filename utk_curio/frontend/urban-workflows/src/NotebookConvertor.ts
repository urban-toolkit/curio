import { v4 as uuid } from "uuid";
import { NodeType } from "./constants";

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

type CellEdge = { 
  source: number; 
  target: number 
  // We might need to add more here
};

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
  // ── Step 1: Extract code cells ──────────────────────────────────────────
  const rawCells = Array.isArray(notebook.cells) ? notebook.cells : [];

  const codeCells = rawCells
    .filter((c) => (c as Record<string, unknown>).cell_type === "code")
    .map((c) => {
      const cell = c as Record<string, unknown>;
      const source = cell.source;
      return Array.isArray(source) ? source.join("") : String(source ?? "");
    });

  // Needed for debbuging
  console.log(codeCells)

  // Call backend for AST-based dependency analysis + Altair spec extraction
  type CellAnalysis = {
    defined: string[];
    used: string[];
    last_var: string | null;
    altair_spec: Record<string, unknown> | null;
    //We might need to add more here
  };
  let cellEdges: CellEdge[] = [];
  let lastVars: (string | null)[] = [];
  let altairSpecs: (Record<string, unknown> | null)[] = [];

  // ── Step 2: Ask the backend for real dependency analysis ────────────────
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

  // ── Step 3: Fallback — naive linear chain ────────────────────────────────
  // Linear fallback when backend returned no edges
  if (cellEdges.length === 0 && codeCells.length > 1) {
    for (let i = 0; i < codeCells.length - 1; i++) {
      cellEdges.push({ source: i, target: i + 1 });
    }
    // No lastVars available — skip wiring in this path
    lastVars = [];
  }

  // ── Step 4: Build quick-lookup structures from the edge list ────────────
  // Build wiring sets
  const hasOutgoing = new Set(cellEdges.map((e) => e.source));
  const incomingSources = new Map<number, number[]>();
  for (const { source, target } of cellEdges) {
    if (!incomingSources.has(target)) incomingSources.set(target, []);
    incomingSources.get(target)!.push(source);
  }

  // ── Step 5: Compute visual layout ────────────────────────────────────────
  const positions = computeLayout(codeCells.length, cellEdges);

  const nodeIds = codeCells.map(() => uuid());

  // ── Step 6: Build the actual TrillNode objects ──────────────────────────
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

  // ── Step 7: Build the edge list ──────────────────────────────────────────
  const edgeList: TrillEdge[] = cellEdges
    .filter(({ source, target }) => nodes[source] && nodes[target])
    .map(({ source, target }) => ({
      id: uuid(),
      source: nodeIds[source],
      target: nodeIds[target],
    }));
    
    // ── Step 8: Assemble and return the final spec ──────────────────────────
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
  if (node.type === NodeType.DATA_LOADING) return `data_${safe}`;
  if (node.type === NodeType.VIS_VEGA) return `vega_${safe}`;
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

function generateCell(
  node: TrillNode,
  inputNodes: TrillNode[]
): NotebookCell | null {
  const content = node.content ?? "";

  const inputComments = inputNodes
    .map((n) => `# input: ${outputVarName(n)}`)
    .join("\n");

  if (node.type === NodeType.DATA_LOADING) {
    return {
      cell_type: "code",
      source: content,
      metadata: {},
      outputs: [],
      execution_count: null,
    };
  }

  if (node.type === NodeType.COMPUTATION_ANALYSIS) {
    const source = inputComments ? `${inputComments}\n${content}` : content;
    return {
      cell_type: "code",
      source,
      metadata: {},
      outputs: [],
      execution_count: null,
    };
  }

  if (node.type === NodeType.VIS_VEGA) {
    let specJson = "{}";
    try {
      specJson = JSON.stringify(JSON.parse(content));
    } catch {
      specJson = JSON.stringify(content);
    }
    const displayCode = [
      "import json",
      "from IPython.display import display",
      `_spec = json.loads(${JSON.stringify(specJson)})`,
      `display({"application/vnd.vegalite.v5+json": _spec, "text/plain": "<VegaLite>"}, raw=True)`,
    ].join("\n");
    const source = inputComments ? `${inputComments}\n${displayCode}` : displayCode;
    return {
      cell_type: "code",
      source,
      metadata: {},
      outputs: [],
      execution_count: null,
    };
  }

  return null;
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
    const cell = generateCell(node, inputNodes);
    if (cell) cells.push(cell);
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
