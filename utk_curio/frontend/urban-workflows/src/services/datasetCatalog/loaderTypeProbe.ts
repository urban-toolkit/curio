/**
 * The type a loader returns, when its code does not say
 * (plans/data-loading-expressive-preview-memo.md, section 3.7).
 *
 * Two sources, read in this order, and only after the code, the catalog and
 * this tab's last run have said nothing:
 *
 * 1. The run journal (`GET /nodeRuntime`): the node's last run, used only when
 *    it succeeded and its `executedCodeSha256` is the digest of the code in
 *    the node now. A record of other code is stale.
 * 2. A background run of the node's own code, through the request Play sends
 *    (`/processPythonCode`), marked `purpose: "type-probe"` so the backend
 *    saves no dataset and the journal says why it ran. Its answer only fills
 *    the preview: no output is applied to the node, nothing goes downstream.
 *
 * The probe is paced: one at a time, at most `PROBES_PER_DATAFLOW` per
 * dataflow in a session, `PROBE_TIMEOUT_MS` each, never repeated for the same
 * code, and cancelled by the caller's signal (an edit, a Play, an unmount).
 */
import { getToken } from "../../utils/authApi";
import { backendUrl } from "../../utils/backendUrl";
import { findReferences } from "../../utils/references/codeReferences";

/** The journal `kind` a background run is recorded with; NodeOutcomeStrip skips it. */
export const TYPE_PROBE_KIND = "type-probe";
export const PROBES_PER_DATAFLOW = 8;
export const PROBE_TIMEOUT_MS = 60_000;

/**
 * `runtime_journal.normalized_code_sha256` in the browser: Python's
 * `textwrap.dedent` (whitespace-only lines emptied, the common margin of the
 * others removed), then `strip()`, then SHA-256 as hex.
 */
export function normalizeCodeForDigest(code: string): string {
  const lines = String(code ?? "").split("\n").map((line) => (/^[ \t]+$/.test(line) ? "" : line));
  let margin: string | null = null;
  for (const line of lines) {
    if (!line) continue;
    const indent = /^[ \t]*/.exec(line)![0];
    if (margin === null) {
      margin = indent;
      continue;
    }
    let i = 0;
    while (i < margin.length && i < indent.length && margin[i] === indent[i]) i += 1;
    margin = margin.slice(0, i);
  }
  const dedented = margin ? lines.map((line) => (line.startsWith(margin!) ? line.slice(margin!.length) : line)) : lines;
  return dedented.join("\n").replace(/^\s+|\s+$/g, "");
}

export async function normalizedCodeSha256(code: string): Promise<string | null> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) return null;
  const bytes = new TextEncoder().encode(normalizeCodeForDigest(code));
  const digest = await subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
}

export interface JournalRun {
  status: string;
  dataType: string;
  executedCodeSha256: string;
  kind: string;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** The node's last run in the journal, or null when there is none or it cannot be read. */
export async function fetchJournalRun(
  dataflowId: string,
  nodeId: string,
  signal?: AbortSignal,
): Promise<JournalRun | null> {
  if (!dataflowId || !nodeId) return null;
  try {
    const response = await fetch(
      `${backendUrl()}/nodeRuntime?dataflowId=${encodeURIComponent(dataflowId)}&nodeId=${encodeURIComponent(nodeId)}`,
      { headers: authHeaders(), signal },
    );
    if (!response.ok) return null;
    const run = (await response.json())?.run;
    if (!run || typeof run !== "object") return null;
    return {
      status: String(run.status ?? ""),
      dataType: String(run.output?.dataType ?? ""),
      executedCodeSha256: String(run.executedCodeSha256 ?? ""),
      kind: String(run.kind ?? ""),
    };
  } catch {
    return null;
  }
}

/** The journal's type for *code*: a successful run of exactly this code, or null. */
export async function journalDataTypeFor(
  dataflowId: string,
  nodeId: string,
  code: string,
  signal?: AbortSignal,
): Promise<string | null> {
  const [run, digest] = await Promise.all([
    fetchJournalRun(dataflowId, nodeId, signal),
    normalizedCodeSha256(code),
  ]);
  if (!run || !digest) return null;
  if (run.status !== "ok" || run.executedCodeSha256 !== digest) return null;
  return run.dataType || null;
}

export interface TypeProbeRequest {
  dataflowId: string | null | undefined;
  nodeId: string;
  nodeType: string;
  code: string;
}

/** Whether *code* can run as it stands: references need the node's widgets resolved first. */
export function probeableCode(code: string): boolean {
  return !!code.trim() && findReferences(code).length === 0;
}

// ── The queue ────────────────────────────────────────────────────────────────

interface Job {
  request: TypeProbeRequest;
  signal?: AbortSignal;
  resolve: (dataType: string | null) => void;
}

const queue: Job[] = [];
let running = false;
/** Per dataflow: how many probes this session has started. */
const started = new Map<string, number>();
/** `${dataflow}::${node}::${digest-free code}` already tried: never twice. */
const tried = new Map<string, Promise<string | null>>();

function keyOf(request: TypeProbeRequest): string {
  return `${request.dataflowId ?? ""}::${request.nodeId}::${normalizeCodeForDigest(request.code)}`;
}

async function runProbe(request: TypeProbeRequest, signal?: AbortSignal): Promise<string | null> {
  const timeout = new AbortController();
  const timer = setTimeout(() => timeout.abort(), PROBE_TIMEOUT_MS);
  const onAbort = () => timeout.abort();
  signal?.addEventListener("abort", onAbort);
  try {
    // Indented as Play indents it: the sandbox wraps the code in a function.
    const body = {
      code: request.code.split("\n").map((line) => `    ${line}\n`).join(""),
      input: "",
      inputTypes: [],
      nodeType: request.nodeType,
      nodeId: request.nodeId,
      ...(request.dataflowId ? { dataflowId: request.dataflowId } : {}),
      saveOutputDataset: false,
      purpose: TYPE_PROBE_KIND,
    };
    const response = await fetch(`${backendUrl()}/processPythonCode`, {
      method: "POST",
      body: JSON.stringify(body),
      headers: { "Content-type": "application/json; charset=UTF-8", ...authHeaders() },
      signal: timeout.signal,
    });
    if (!response.ok) return null;
    const json = await response.json();
    const path = json?.output?.path;
    const dataType = json?.output?.dataType;
    return typeof path === "string" && path && typeof dataType === "string" ? dataType : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", onAbort);
  }
}

function pump(): void {
  if (running) return;
  const job = queue.shift();
  if (!job) return;
  if (job.signal?.aborted) {
    job.resolve(null);
    pump();
    return;
  }
  running = true;
  const dataflow = job.request.dataflowId ?? "";
  started.set(dataflow, (started.get(dataflow) ?? 0) + 1);
  void runProbe(job.request, job.signal).then((dataType) => {
    running = false;
    job.resolve(job.signal?.aborted ? null : dataType);
    pump();
  });
}

/**
 * Queue one background run of a loader. Resolves to the returned `dataType`,
 * or null when the run failed, timed out, was cancelled, or is not allowed
 * (the per-dataflow budget is spent, the code cannot run as it stands, or this
 * code was already tried this session).
 */
export function requestTypeProbe(request: TypeProbeRequest, signal?: AbortSignal): Promise<string | null> {
  if (!probeableCode(request.code)) return Promise.resolve(null);
  const key = keyOf(request);
  const previous = tried.get(key);
  if (previous) return previous;
  const dataflow = request.dataflowId ?? "";
  const queuedForDataflow = queue.filter((j) => (j.request.dataflowId ?? "") === dataflow).length;
  if ((started.get(dataflow) ?? 0) + queuedForDataflow >= PROBES_PER_DATAFLOW) return Promise.resolve(null);
  const promise = new Promise<string | null>((resolve) => {
    queue.push({ request, signal, resolve });
    pump();
  });
  tried.set(key, promise);
  // A cancelled probe may be asked again later (the user undid the edit).
  void promise.then((dataType) => {
    if (dataType === null && signal?.aborted) tried.delete(key);
  });
  return promise;
}

/** Forget the session's probes (tests, or a new session). */
export function resetTypeProbes(): void {
  queue.splice(0, queue.length);
  running = false;
  started.clear();
  tried.clear();
}
