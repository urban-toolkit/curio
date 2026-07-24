import { v4 as uuid } from "uuid";
import { NodeType } from "./constants";
import { getToken } from "./utils/authApi";

// ── Set up for LLM features ───────────────────────────────────────────

const authHeader = (): Record<string, string> => {
  const token = getToken();
  return token ? { "Authorization": `Bearer ${token}` } : {};
};
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
export interface Cell {
  index: number
  code: string
}

const DATA_LOADING_PATTERN =
  /\bpd\.read_\w+\s*\(|\bgpd\.read_\w+\s*\(|\bgeopandas\.read_\w+\s*\(|\bopen\s*\(|\brequests\.(get|post|put|delete|patch)\s*\(|\bsqlite3\.connect\s*\(|\bpsycopg2\.connect\s*\(|\bcreate_engine\s*\(|\bboto3\b/;

const DATA_EXPORT_PATTERN =
  /\bto_csv\s*\(|\bto_excel\s*\(|\bto_json\s*\(|\bto_parquet\s*\(|\bto_pickle\s*\(|\bto_sql\s*\(|\bto_feather\s*\(|\.to_file\s*\(|\bopen\s*\([^)]*['"]\s*[wa]b?\s*['"]|\bjson\.dump\s*\(|\bpickle\.dump\s*\(|\bnp\.save\w*\s*\(|\bplt\.savefig\s*\(|\bfig\.savefig\s*\(|\bfig\.write_\w+\s*\(|\.upload_file\s*\(|\.upload_fileobj\s*\(|\.put_object\s*\(/;

const MERGE_FLOW_PATTERN = 
  /^gqCoduV9YG0fYdjdPXmWdZAhSKJ5o6uQ$/;

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

// Used to check if the LLM returned valid types
function _validate_node(llm_type: string): NodeType {
  // Change in the future as deemed fit
  const valid_types: Record<string, NodeType> = {
    "DATA_LOADING": NodeType.DATA_LOADING,
    "DATA_EXPORT": NodeType.DATA_EXPORT,
    "DATA_TRANSFORMATION": NodeType.DATA_TRANSFORMATION,
    "COMPUTATION_ANALYSIS": NodeType.COMPUTATION_ANALYSIS,
    "VIS_VEGA": NodeType.VIS_VEGA,
  }

  if(!(llm_type in valid_types)){
    return NodeType.COMPUTATION_ANALYSIS
  }
  return valid_types[llm_type]
}

// Used to identify all cells whose types must be evaluated by the LLM
function _type_is_ambiguous(code: string){
  if (MERGE_FLOW_PATTERN.test(code)) return false;
  if (DATA_LOADING_PATTERN.test(code)) return false;
  if (DATA_EXPORT_PATTERN.test(code)) return false;
  if (isVegaLiteJson(code)) return false;
  return true;
}

// Delete the export once your done
// Confers the cell types with the LLM
export async function getLlmTypes(
  ambiguousCells: Cell[],
  backendUrl: string,
): Promise<Record<number, string>> {
  const llmTypes: Record<number, string> = {};
  type Analysis = {
    index: number,
    codeType: string
  }

  // If there aren't any ambigious cells
  if (ambiguousCells.length < 1){
    return llmTypes
  }

  try{
    // <---------------------------- Backend API calls----------------------------------------------------------------------------------------->
    let message: any = {preamble: "default_preamble", prompt: "jupyter_notebook_prompt", text: JSON.stringify({ cells: ambiguousCells })};
    const response_usage = await fetch(`${backendUrl}/llm/check`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeader(),
      },
      body: JSON.stringify(message),
    });

    if (!response_usage.ok) {
      const body = await response_usage.json().catch(() => ({}));
      throw new Error(body.description || body.error || "LLM request failed.");
    }

    const result_usage = await response_usage.json();

    if(result_usage.result != "yes")
      await new Promise(resolve => setTimeout(resolve, (result_usage.result + 15) * 1000));

    const response = await fetch(`${backendUrl}/llm/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...authHeader(),
        },
        body: JSON.stringify(message),
    });

    if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.description || body.error || "LLM request failed.");
    }
    // <---------------------------- End of API call ------------------------------------------------------------------------------>
    const rawData = await response.json()
    const data: Analysis[]  = JSON.parse(rawData.result);

    data.forEach((cell) => {
      llmTypes[cell.index] = _validate_node(cell.codeType);
    });

    console.log(llmTypes)
  }catch(err){
    console.log(`LLM fetch error: ${err}`)
    // No fallback, return an empty dictionary
  }
  return llmTypes
}

// ── Import: Notebook → Trill ─────────────────────────────────────────────────
// Remove once done
export type CellEdge = { 
  source: number; 
  target: number;
  // We added parentVar
  parent_var?: string
};

// Remove once done
export function wireCode(
  code: string,
  cellIdx: number,
  cellEdges: CellEdge[],
  hasOutgoing: Set<number>,
  incomingSources: Map<number, number[]>,
): string {
  let out = code;
  const sources = incomingSources.get(cellIdx) ?? [];

  if (sources.length === 1) {
    const incomingEdge = cellEdges.find(e => e.source === sources[0] && e.target === cellIdx)
    const parentVar = incomingEdge?.parent_var
    if (!parentVar) {
      // No parent_var means sources[0] is a merge node, not a normal cell.
      // Unpack each of the merge node's own inputs from arg[i].
      const mergeNodeIdx = sources[0];
      const mergeSources = incomingSources.get(mergeNodeIdx) ?? [];
      
      const unpackLines = mergeSources.map((srcIdx, i) => {
        const srcEdge = cellEdges.find(e => e.source === srcIdx && e.target === mergeNodeIdx);
        const srcVar = srcEdge?.parent_var ?? "arg";
        return `${srcVar} = arg[${i}]`;
      });

      out = `${unpackLines.join("\n")}\n${out}`;
    } else {
      out = `${parentVar} = arg\n${out}`;
    }
    // const srcVar = parentVar ?? "arg"
    // out = `${srcVar} = arg\n${out}`
  } 
  // else if (sources.length > 1) {
  //   out = `# multiple inputs available via arg\n${out}`;
  // }

  const outgoingEdge = cellEdges.find(e => e.source === cellIdx)
  const pv = outgoingEdge?.parent_var;

  if (hasOutgoing.has(cellIdx) && pv) {
    out = `${out}\nreturn ${pv}`;
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
  backendUrl: string,
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


  // Call backend for AST-based dependency analysis + Altair spec extraction
  type CellAnalysis = {
    defined: string[];
    used: string[];
    last_var: string | null;
    altair_spec: Record<string, unknown> | null;
  };
  let cellEdges: CellEdge[] = [];
  let parentVars: (string | null)[] = [];
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
      // Adding parentVars
      parentVars = (data.edges ?? []).map((a) => a.parent_var ?? null);
      altairSpecs = (data.analysis ?? []).map((a) => a.altair_spec ?? null);
    }
  } catch {
    console.warn(
      "NotebookConvertor: backend unreachable, falling back to linear chain."
    );
  }

  // ── Step 3: Fallback — naive linear chain ────────────────────────────────
  // Linear fallback was removed

  // ── Step 4: Build quick-lookup structures from the edge list ────────────
  // Build wiring sets

  // const hasOutgoing = new Set(cellEdges.map((e) => e.source));
  // const incomingSources = new Map<number, number[]>();
  // for (const { source, target } of cellEdges) {
  //   if (!incomingSources.has(target)) incomingSources.set(target, []);
  //   incomingSources.get(target)!.push(source);
  // }

  // ── Step 4a: Raw incoming-edge grouping (just for merge detection) ──────
  const rawIncoming = new Map<number, number[]>();
  for (const { source, target } of cellEdges) {
    if (!rawIncoming.has(target)) rawIncoming.set(target, []);
    rawIncoming.get(target)!.push(source);
  }

  rawIncoming.forEach((source, targets)=>{
    console.log(`Raw\n   Source: ${source}\n   Targets: ${targets}`)
  })

  // ── Step 4b: Insert merge-flow cells for nodes with multiple inputs ─────
  for (const [target, sources] of rawIncoming) {
    if (sources.length <= 1) continue;

    const mergeCellIdx = codeCells.length;
    codeCells.push("gqCoduV9YG0fYdjdPXmWdZAhSKJ5o6uQ");

    cellEdges = cellEdges.map((e) =>
      sources.includes(e.source) && e.target === target
        ? { ...e, target: mergeCellIdx }
        : e
    );

    cellEdges.push({ source: mergeCellIdx, target});
  }

  // ── Step 4c: Build final quick-lookup structures (used by wireCode etc.) ─
  const hasOutgoing = new Set(cellEdges.map((e) => e.source));
  const incomingSources = new Map<number, number[]>();
  for (const { source, target } of cellEdges) {
    if (!incomingSources.has(target)) incomingSources.set(target, []);
    incomingSources.get(target)!.push(source);
  }

  console.log(cellEdges)
  console.log(hasOutgoing)
  console.log(incomingSources)

  // ── Step 5: Compute visual layout ────────────────────────────────────────
  const positions = computeLayout(codeCells.length, cellEdges);

  const nodeIds = codeCells.map(() => uuid());

  // ── Step 6: Build the actual TrillNode objects ──────────────────────────
  
  // Cells whose types cannot be determined deterministically 
  const ambiguous: Cell[] = codeCells
  .map((code, i) => ({ index: i, code: code}))
  .filter((cell) => !altairSpecs[cell.index] && _type_is_ambiguous(cell.code))

  // The result of the LLM analysis
  const llm_types = await getLlmTypes(ambiguous, backendUrl)

  cellEdges.forEach((edge, index)=>{
    console.log(`Edge ${index}\n    parent_var: ${edge.parent_var}\n    source: ${edge.source}\n    target: ${edge.target}`)
  })
  const nodes: TrillNode[] = codeCells.map((code, index) => {
    const spec = altairSpecs[index] ?? null;
    let nodeType;
    if (spec) /* - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -  */{ nodeType = NodeType.VIS_VEGA; }
    else if (isVegaLiteJson(code))                                              { nodeType = NodeType.VIS_VEGA; }
    else if (MERGE_FLOW_PATTERN.test(code))/* - - - - - - - - - - - - - - - - */{ nodeType = NodeType.MERGE_FLOW }
    else if (DATA_LOADING_PATTERN.test(code) && !incomingSources.has(index))    { nodeType = NodeType.DATA_LOADING; }
    else if (DATA_EXPORT_PATTERN.test(code) && !hasOutgoing.has(index))/*- - -*/{ nodeType = NodeType.DATA_EXPORT; } 
    else if (llm_types[index])                                                  { nodeType = llm_types[index] } 
    else/*- - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - - */{ nodeType = NodeType.COMPUTATION_ANALYSIS }
    const content = spec
      ? JSON.stringify(spec, null, 2)
      : cellEdges.length > 0  // Changed lastVars.length > 0 to cellEdges.length > 0
        ? wireCode(code, index, cellEdges, hasOutgoing, incomingSources)
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
  const mergeInputCounters: Record<string, number> = {};
  
  const edgeList: TrillEdge[] = cellEdges
    .filter(({ source, target }) => nodes[source] && nodes[target])
    .map(({ source, target }) => {
      const targetNodeId = nodeIds[target];
      const isMergeTarget = nodes[target]?.type === NodeType.MERGE_FLOW;

      let edgeId = uuid();
      if (isMergeTarget) {
        const count = mergeInputCounters[targetNodeId] ?? 0;
        edgeId = `${edgeId}-in_${count}`;
        mergeInputCounters[targetNodeId] = count + 1;
      }

      return {
        id: edgeId,
        source: nodeIds[source],
        target: targetNodeId,
      };
    });
    
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
