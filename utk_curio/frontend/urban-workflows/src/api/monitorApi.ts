/**
 * The monitor page's backend calls.
 *
 * Five read routes plus one write. All are public and unauthenticated, but
 * they go through `apiFetch` anyway: it resolves the backend origin through
 * `backendUrl()` (which the e2e harness injects per browser context) and
 * throws an Error carrying `.status`, which is the convention every other
 * `src/api/*Api.ts` module follows. The Bearer token it attaches when a
 * session cookie happens to exist is harmless on a public route.
 *
 * The four aggregate payloads carry no identifiers by design, the LLM one
 * naming only this Curio's own models; the error log deliberately does. See
 * `utk_curio/backend/app/monitor/errors.py` and `llm_performance.py`.
 */
import { apiFetch } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";

export interface MonitorDeployment {
  version: string;
  isolation: string;
  isolationActive: string;
  /**
   * The memory limit isolated nodes run under: a cgroup at each node's
   * budget, the address-space cap where the container's cgroups cannot hold
   * them, or none where nodes run in the sandbox's process.
   */
  memoryLimit: "cgroup" | "address space" | "none" | "unknown";
  /** Why not a cgroup, in words from a closed list; null otherwise. */
  memoryLimitReason: string | null;
  execUserConfigured: boolean;
  authEnabled: boolean;
  projectsEnabled: boolean;
  guestLoginAllowed: boolean;
  factoryPublishAllowed: boolean;
  saveNodeOutputDefault: boolean;
  llmProviderConfigured: boolean;
  searchToolConfigured: boolean;
  /**
   * The bucket mount service's self-test (docker-compose.bucket-mounts.yml):
   * `none` when this deployment names no service.
   */
  bucketMounts: "none" | "pending" | "passed" | "unavailable";
  /** Why the service is unavailable, in words from a closed list; null otherwise. */
  bucketMountsProblem: string | null;
  env: string;
  platform: string;
  pythonVersion: string;
}

export interface DurationBucket {
  leMs: number | null;
  count: number;
}

export interface MonitorBackendExecution {
  total: number;
  ok: number;
  error: number;
  python: number;
  javascript: number;
  inFlight: number;
  distinctNodeTypes: number;
  lastExecutionAt: string | null;
  durations: {
    windowSize: number;
    count: number;
    p50Ms: number | null;
    p90Ms: number | null;
    p99Ms: number | null;
    maxMs: number | null;
    buckets: DurationBucket[];
  };
}

export interface MonitorSandboxExecution {
  reachable: boolean;
  isolation: string | null;
  isolationActive: string | null;
  zygoteRunning: boolean | null;
  parallelism: number | null;
  slotsInUse: number | null;
  memoryLimitMb: number | null;
  cpuSecondsLimit: number | null;
  wallTimeoutSeconds: number | null;
  total: number | null;
  isolated: number | null;
  inProcess: number | null;
  childDeaths: Record<string, number> | null;
}

export interface MonitorHardware {
  cpu: {
    model: string;
    arch: string;
    logicalCores: number | null;
    physicalCores: number | null;
    maxFrequencyMhz: number | null;
    usagePercent: number | null;
  };
  memory: {
    totalBytes: number | null;
    availableBytes: number | null;
    usedPercent: number | null;
    swapTotalBytes: number | null;
    swapUsedBytes: number | null;
  };
  load: {
    avg1m: number | null;
    avg5m: number | null;
    avg15m: number | null;
    perCore: number | null;
  };
  processes: {
    backendRssBytes: number | null;
    sandboxRssBytes: number | null;
  };
}

/**
 * Which backend processes a payload holds the part of, in a start of several
 * (`curio.py start --backend-processes N`): the home process asks every other
 * one for its part and merges them. Those that did not answer are left out.
 * Absent with one process, and from the payloads of the histories (LLM
 * performance, open files), which every process writes into one file.
 */
export interface MonitorBackendProcesses {
  count: number;
  answered: number[];
  missing: number[];
}

export interface MonitorPayload {
  generatedAt: string;
  uptimeSeconds: number;
  backendProcesses?: MonitorBackendProcesses;
  deployment: MonitorDeployment;
  hardware: MonitorHardware;
  execution: {
    backend: MonitorBackendExecution;
    sandbox: MonitorSandboxExecution;
  };
  accounts: {
    total: number;
    registered: number;
    guest: number;
    createdLast24h: number;
    sessions: { active: number; seenLast5m: number; seenLast1h: number };
    signIn: {
      windowMinutes: number;
      success: number;
      failure: number;
      distinctSources: number;
    };
  };
  content: {
    projects: {
      total: number;
      createdLast24h: number;
      openedLast24h: number;
      storesWithProjects: number;
    };
    datasets: {
      total: number;
      imported: number;
      computed: number;
      stores: number;
      totalBytes: number;
      largestBytes: number;
      medianBytes: number;
    };
    execCacheEntries: number;
  };
}

export interface SizeBucket {
  leBytes: number | null;
  count: number;
}

export interface MonitorStoragePayload {
  computedAt: string;
  ageSeconds: number;
  ttlSeconds: number;
  walkMs: number;
  truncated: boolean;
  userStores: {
    count: number;
    totalBytes: number;
    largestBytes: number;
    medianBytes: number;
    buckets: SizeBucket[];
  };
  breakdown: { area: string; bytes: number; files: number }[];
  disk: { totalBytes: number | null; freeBytes: number | null };
}

/** The windows the LLM route views its requests in. */
export type MonitorLlmWindow = "24h" | "7d" | "90d";

/**
 * What a window's requests read, one model's or every model's together:
 * times in milliseconds, each null when no request gave it.
 */
export interface MonitorLlmStats {
  requests: number;
  failed: number;
  averageMs: number | null;
  p95Ms: number | null;
  /** The average time to the first word or call of the streamed requests. */
  firstTokenMs: number | null;
  /** The output tokens over the time of the requests whose provider reported them. */
  tokensPerSecond: number | null;
}

/** One model's stats over a window. */
export interface MonitorLlmModel extends MonitorLlmStats {
  model: string;
}

/**
 * One model's requests in one 5-minute slot, hour or UTC day (`at`, its
 * start, `YYYY-MM-DDTHH:MM:00Z`): how many, how many failed, and their
 * total milliseconds.
 */
export interface MonitorLlmRow {
  at: string;
  model: string;
  requests: number;
  failed: number;
  ms: number;
}

/**
 * One window of the requests: its rows, one every `stepSeconds` from the
 * start of the first (`from`) to the start of the current one (`to`), steps
 * with no request left out, and each model's stats over the window, most
 * requests first, with every model's together (`all`).
 */
export interface MonitorLlmView {
  from: string;
  to: string;
  stepSeconds: number;
  rows: MonitorLlmRow[];
  models: MonitorLlmModel[];
  all: MonitorLlmStats;
}

/**
 * `GET /api/monitor/llm`: the requests of this Curio's own LLM models, kept
 * across restarts for the last `maxDays` days, in three views: the last 24
 * hours in 5-minute rows, the last 7 days in hourly rows and the last 90
 * days in daily rows. A request on a key a user set for their own is not
 * counted.
 */
export interface MonitorLlmPayload {
  computedAt: string;
  maxDays: number;
  ageSeconds: number;
  ttlSeconds: number;
  views: Record<MonitorLlmWindow, MonitorLlmView>;
}

/** One server's open files and its soft limit on them; null where unknown. */
export interface MonitorOpenFilesCounts {
  open: number | null;
  limit: number | null;
}

/**
 * One hour's sample (`at`, `YYYY-MM-DDTHH:MM:SSZ`) of both servers: the
 * busiest of the hour. The sandbox's part is null when it did not answer.
 */
export interface MonitorOpenFilesSample {
  at: string;
  backend: MonitorOpenFilesCounts | null;
  sandbox: MonitorOpenFilesCounts | null;
  /** With several backend processes, the busiest one in this hour, whose counts `backend` is. */
  backendProcess?: number;
}

/**
 * `GET /api/monitor/open-files`: a sample an hour over the last `maxDays`
 * days, kept across restarts, from `startedAt` (when the oldest was taken),
 * one each `intervalSeconds`. A sample above `warnAbovePercent` of a server's
 * limit records an error, and another only once its count fell below
 * `clearBelowPercent`.
 */
export interface MonitorOpenFilesPayload {
  computedAt: string;
  startedAt: string;
  maxDays: number;
  intervalSeconds: number;
  warnAbovePercent: number;
  clearBelowPercent: number;
  samples: MonitorOpenFilesSample[];
}

export type MonitorErrorSource = "node" | "sandbox" | "backend" | "client";

export interface MonitorError {
  at: string;
  source: MonitorErrorSource;
  summary: string;
  detail: string;
  context: Record<string, unknown>;
  count: number;
  /** With several backend processes, the process that holds the entry; none on the sandbox's. */
  process?: number;
}

export interface MonitorErrorsPayload {
  generatedAt: string;
  serverWindow: number;
  clientWindow: number;
  sandboxWindow: number | null;
  droppedClient: number;
  errors: MonitorError[];
  backendProcesses?: MonitorBackendProcesses;
}

export function fetchMonitor(signal?: AbortSignal): Promise<MonitorPayload> {
  return apiFetch<MonitorPayload>("/api/monitor", { signal });
}

export function fetchMonitorStorage(
  signal?: AbortSignal
): Promise<MonitorStoragePayload> {
  return apiFetch<MonitorStoragePayload>("/api/monitor/storage", { signal });
}

export function fetchMonitorErrors(
  signal?: AbortSignal
): Promise<MonitorErrorsPayload> {
  return apiFetch<MonitorErrorsPayload>("/api/monitor/errors", { signal });
}

export function fetchMonitorLlm(signal?: AbortSignal): Promise<MonitorLlmPayload> {
  return apiFetch<MonitorLlmPayload>("/api/monitor/llm", { signal });
}

export function fetchMonitorOpenFiles(signal?: AbortSignal): Promise<MonitorOpenFilesPayload> {
  return apiFetch<MonitorOpenFilesPayload>("/api/monitor/open-files", { signal });
}

/**
 * Post one browser error. Deliberately NOT built on `apiFetch`.
 *
 * This is called from a window error handler, so it must not throw, must not
 * retry, and must not care what comes back. `apiFetch` throws on a non-OK
 * response, which is exactly the behaviour a crash reporter cannot have: an
 * error raised while reporting an error is how a render loop becomes a request
 * loop.
 */
export function postClientError(report: {
  message: string;
  stack: string;
  url: string;
  userAgent: string;
}): void {
  try {
    void fetch(`${backendUrl()}/api/monitor/errors/client`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* never let the reporter become the failure */
  }
}
