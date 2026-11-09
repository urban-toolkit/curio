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
 * naming only models; the error log deliberately does. See
 * `utk_curio/backend/app/monitor/errors.py` and `llm_tokens.py`.
 */
import { apiFetch } from "../utils/authApi";
import { backendUrl } from "../utils/backendUrl";

export interface MonitorDeployment {
  version: string;
  isolation: string;
  isolationActive: string;
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

export interface MonitorPayload {
  generatedAt: string;
  uptimeSeconds: number;
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

/** Tokens and requests in one window, or in one hour. */
export interface MonitorLlmCounts {
  inputTokens: number;
  outputTokens: number;
  requests: number;
}

/** One model's tokens in one UTC hour (`hour`, `YYYY-MM-DDTHH:00:00Z`). */
export interface MonitorLlmHour extends MonitorLlmCounts {
  hour: string;
  model: string;
  /** On this Curio's own endpoint, rather than on a key a user set for their own. */
  curio: boolean;
}

/** One model's totals: the last 24 hours, the last 7 days, every hour kept. */
export interface MonitorLlmModel {
  model: string;
  curio: boolean;
  last24h: MonitorLlmCounts;
  last7d: MonitorLlmCounts;
  kept: MonitorLlmCounts;
}

/**
 * `GET /api/monitor/llm`: each model's tokens since the backend started
 * (`startedAt`), at most `maxDays` days, as hourly rows from `hourlyFrom` to
 * `hourlyTo` (the last 7 days, hours with no request left out) and totals.
 */
export interface MonitorLlmPayload {
  computedAt: string;
  startedAt: string;
  maxDays: number;
  ageSeconds: number;
  ttlSeconds: number;
  hourlyFrom: string;
  hourlyTo: string;
  hourly: MonitorLlmHour[];
  models: MonitorLlmModel[];
}

/** One server's open files and its soft limit on them; null where unknown. */
export interface MonitorOpenFilesCounts {
  open: number | null;
  limit: number | null;
}

/**
 * One hourly sample (`at`, `YYYY-MM-DDTHH:MM:SSZ`) of both servers. The
 * sandbox's part is null when it did not answer.
 */
export interface MonitorOpenFilesSample {
  at: string;
  backend: MonitorOpenFilesCounts | null;
  sandbox: MonitorOpenFilesCounts | null;
}

/**
 * `GET /api/monitor/open-files`: every sample since the backend started
 * (`startedAt`), at most `maxDays` days, one each `intervalSeconds`. A sample
 * above `warnAbovePercent` of a server's limit records an error, and another
 * only once its count fell below `clearBelowPercent`.
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
}

export interface MonitorErrorsPayload {
  generatedAt: string;
  serverWindow: number;
  clientWindow: number;
  sandboxWindow: number | null;
  droppedClient: number;
  errors: MonitorError[];
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
