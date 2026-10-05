/**
 * Grounding and validation evidence: dataset candidate rows, source refs, remedies, the user's dataset selection, and one validation attempt.
 *
 * Split out of `api/agentsApi.ts` (memo dev/142, F1); every shape keeps its name.
 */

/** One dev/50 candidate row (docs/06 row contract) — informational metadata,
 * bounded and scheme-allowlisted server-side, sanitized again at render. */
export interface AgentDatasetCandidateRow {
  name: string;
  sourceType: "api" | "endpoint" | "portal" | "catalog" | "document" | "database" | "discovery";
  url?: string;
  provider?: string;
  format?: string;
  coverage?: string;
  requirement?: string;
  fit?: { score: number; rationale: string };
  /** Catalog lane only: the id dataset.install proposals reference. */
  datasetId?: string;
  installed?: boolean;
  /** dev/132: what can be DONE with this row, read from the probe's own
   * observation (never the model's prose) — code can fetch it, a person must
   * download it from the portal, or the runtime could not tell. */
  access?: "fetchable" | "manual-download" | "unknown" | string;
  /** The one-line reason for `access` — the content type, status or page title
   * the probe actually saw. */
  accessWhy?: string;
  /** Manual rows only: the portal's own download steps, as observed. */
  downloadSteps?: string[];
  /** dev/132: a catalog row the user imported themselves after the card was
   * minted — its file is here, so nothing needs installing first. */
  imported?: boolean;
  /** External lane only: the portal coordinate a discovery.acquire proposal
   *  references. Both or neither - half a coordinate is dropped server-side. */
  sourceId?: string;
  resourceId?: string;
  /** Whether Curio can actually download this row. **Set by the runtime**
   *  against the real source roster and the probe, never by the model: it may
   *  name a source, it may not claim the run can act on one. A row Curio
   *  downloads offers only that, never the portal steps. */
  acquirable?: boolean;
  /** A confirmed pick Curio downloaded, or is downloading: where it came from. */
  discoverySource?: { sourceId?: string; resourceId?: string };
  /** A confirmed pick whose download is still running. */
  acquiring?: { jobId: string };
  /** Why a confirmed row's download failed. */
  acquireError?: string;
  /** dev/67-4 (DEC-053): the deterministic verification verdict — external
   * rows only; runtime-probed through the egress policy, never model-claimed. */
  verification?: {
    status: "verified" | "unreachable" | "refused" | "unverified" | string;
    detail?: string;
    httpStatus?: number;
    provider?: string;
    datasetId?: string;
    datasetName?: string;
    columns?: string[];
    checkedAt?: string;
  };
}

/** dev/114: one grounded source reference on a proposal. */
export interface AgentSourceRef {
  kind: "catalog" | "external" | "user-path" | "synthetic" | "secret" | string;
  /** The literal the code uses: a path, a curio_data_path("<id>") call, or a URL. */
  value?: string;
  datasetId?: string;
  title?: string;
  format?: string;
  /** external only: the DEC-053 probe verdict the runtime recorded. */
  verification?: AgentDatasetCandidateRow["verification"];
  /** external only: "credential-gated" when the endpoint answered 401/403. */
  requirement?: string;
  /** external only (dev/116): a saved connection key is bound to this host. */
  hint?: string;
  /** secret only (dev/116): the connection key the code reaches by name. */
  name?: string;
  host?: string;
  delivery?: string;
}

/** dev/116: what a `source-missing` failure asks the user for.
 *  dev/126 adds `dataset-selection`: the node's source is with the user —
 *  its Dataset Finder holds candidates awaiting a selection. */
export interface AgentRemedy {
  kind: "connection-key" | "use-connection-key" | "dataset-selection" | "llm-config" | string;
  /** llm-config: the agent no LLM configuration answers. */
  agentId?: string | null;
  host?: string;
  /** connection-key: a name the settings form can suggest. */
  suggestedName?: string;
  /** use-connection-key: the saved key the builder did not use. */
  name?: string;
  /** dataset-selection (dev/126): the chat to open, and the node it resolves. */
  attachmentId?: string;
  nodeId?: string;
}

/** dev/126: one confirmed candidate — identifiers ONLY. The server resolves
 *  the key against the rows it proposed itself, so a client can never
 *  introduce a source the runtime did not verify. */
export interface AgentDatasetPick {
  lane: "catalog" | "external";
  key: string;
}

/** dev/126: the recorded selection for a node. */
export interface AgentDatasetSelection {
  attachmentId: string;
  nodeId?: string;
  status: "resolved" | "awaiting-install" | "candidates-pending" | string;
  picks: AgentDatasetCandidateRow[];
  /** dev/132: what the runtime did with the confirmation — a fetchable source
   * is handed to the node's own builder automatically (no prompt to compose);
   * a portal row waits for the download and the Import button. */
  delegated?: {
    status:
      | "delegating"
      | "session-running"
      | "manual-download"
      | "no-builder"
      | "skipped"
      | "acquiring"
      | "acquire-failed"
      | string;
    reason?: string;
    attachmentId?: string;
    nodeId?: string;
    executionId?: string;
    sources?: string[];
    jobIds?: string[];
  };
  /** The Discovery Catalog downloads the confirmation started, one per acquirable row. */
  acquisitions?: {
    name?: string;
    sourceId: string;
    resourceId: string;
    status: "acquired" | "acquiring" | "failed" | string;
    datasetId?: string;
    jobId?: string;
    error?: string;
    alreadyPresent?: boolean;
  }[];
}

/** dev/115: one round of the verified-content loop, as the cards render it. */
export interface AgentValidationAttempt {
  round: number;
  verdict: "pass" | "fail" | "infrastructure" | string;
  kind?: string;
  detail?: string;
  stderrTail?: string;
  outputDataType?: string;
  durationMs?: number;
  contentSha256?: string;
  /** "current content" (round 0 ran the node as it was) or "generated". */
  source?: string;
  /** dev/115 field fix: what the fetched endpoint actually answered when the round failed. */
  endpointEvidence?: string;
  /** dev/116: a credential decline's concrete remedy. */
  remedy?: AgentRemedy;
  /** dev/127: the candidate this round ran (failed rounds only). */
  code?: string;
  codeTruncated?: boolean;
  codeIsProse?: boolean;
  /** dev/118: ancestors whose earlier output stood in for a re-run. */
  reusedNodes?: string[];
  /** dev/118: a vanished reused artifact made the slice run whole once (not a round). */
  reuseRetried?: boolean;
}
