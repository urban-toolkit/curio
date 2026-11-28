import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faCheck } from "@fortawesome/free-solid-svg-icons";
import type {
  AgentDatasetCandidateRow,
  AgentDatasetCandidatesPart,
  AgentDatasetPick,
  AgentDatasetSelection,
  AgentDatasetSourceRecord,
  SourceCardStanding,
} from "../../../services/agents";
import { useDatasetDetails } from "../../datasets/catalog/datasetDetailsContext";
import { sanitizeAgentUrl, sourceCardStanding } from "../../../services/agents";
import styles from "./AgentDatasetCandidatesCard.module.css";
import { verificationLabel } from "./verificationChip";
import {
  acquireKey,
  startDiscoveryAcquire,
  useDiscoveryAcquire,
} from "../../../services/discoveryCatalog/discoveryCatalogHooks";
import type { DiscoveryAcquireJob } from "../../../services/discoveryCatalog/discoveryCatalogTypes";
import { isTerminal, jobProgress } from "../../../services/discoveryCatalog/discoveryCatalogTypes";
import { notifyDatasetCatalogRefresh } from "../../../services/datasetCatalog/datasetCatalogApi";
import type { DatasetDiscoverySourceInput } from "../../../services/datasetCatalog/datasetCatalogTypes";

/** Where a file downloaded by hand from this row came from: its Discovery Catalog
 * coordinate when it has one, and its link. Exported for tests. */
export function rowProvenance(row: AgentDatasetCandidateRow): DatasetDiscoverySourceInput | undefined {
  const source: DatasetDiscoverySourceInput = {};
  if (row.sourceId && row.resourceId) {
    source.sourceId = row.sourceId;
    source.resourceId = row.resourceId;
  }
  if (row.url) source.resourceUrl = row.url;
  return Object.keys(source).length ? source : undefined;
}

type Lane = "external" | "catalog";

/** The card's lanes best first: the server's (`laneOrder`, the lane that
 * holds the best row first), then any lane it did not name, in the order a
 * card minted before cards were ranked drew them. */
function laneOrder(part: AgentDatasetCandidatesPart): Lane[] {
  const lanes: Lane[] = ["external", "catalog"];
  const ranked = (part.laneOrder ?? []).filter((lane) => lanes.includes(lane));
  return [...ranked, ...lanes.filter((lane) => !ranked.includes(lane))];
}

/** One row of the card, with the lane and the index a pick addresses it by. */
interface PlacedRow {
  lane: Lane;
  index: number;
  row: AgentDatasetCandidateRow;
}

/** The card's rows as one list, best first: in the server's order
 * (`rowOrder`, by what can be done with each row, then its fit), then any row
 * it does not name, lane by lane in the lanes' order, as a card minted before
 * its rows were one list draws them. An entry that names no row is passed
 * over. Exported for tests. */
export function rowsInOrder(part: AgentDatasetCandidatesPart): PlacedRow[] {
  const placed: PlacedRow[] = [];
  const seen = new Set<string>();
  const place = (lane: unknown, index: unknown) => {
    if ((lane !== "external" && lane !== "catalog") || typeof index !== "number") return;
    const row = (part.lanes[lane] ?? [])[index];
    const key = `${lane}:${index}`;
    if (!row || seen.has(key)) return;
    seen.add(key);
    placed.push({ lane, index, row });
  };
  for (const entry of part.rowOrder ?? []) {
    if (Array.isArray(entry)) place(entry[0], entry[1]);
  }
  for (const lane of laneOrder(part)) {
    (part.lanes[lane] ?? []).forEach((_row, index) => place(lane, index));
  }
  return placed;
}

/** Where a row's data comes from, on one line: its provider (a Data Catalog
 * row with none comes from the Data Catalog), its format and its coverage. */
function originLine(lane: Lane, row: AgentDatasetCandidateRow): string {
  const from = row.provider || (lane === "catalog" ? "Data Catalog" : "");
  return [from, row.format, row.coverage].filter(Boolean).join(" · ");
}

/** The verdicts of a link that gave no data: an error answer, no answer, or
 * a URL the egress policy refused. */
const FAILED_VERDICTS = new Set(["http-error", "unreachable", "refused"]);

/** Whether a person downloads *row* from its portal: the probe said so, or
 * the link answered a web page, which is no data. Never a row Curio
 * downloads itself. */
function manualDownload(row: AgentDatasetCandidateRow): boolean {
  if (row.acquirable) return false;
  return row.access === "manual-download" || (row.verification?.status === "verified" && Boolean(row.verification.webPage));
}

/** *text* without the full stop it ends with. */
function unstopped(text: string | undefined): string {
  return (text ?? "").trim().replace(/\.$/, "");
}

/** The one warning a row carries, or null: what keeps it from being used as
 * it is. A row Curio downloads, and a link that answered data, carry none
 * but their requirement. A portal download says why, and that its dataset id
 * is not confirmed when its portal did not confirm its coordinate; a link
 * that gave no data says what it answered, in the words of the one label
 * table (`verificationLabel`); a link never checked says so. Exported for
 * tests. */
export function rowWarning(lane: Lane, row: AgentDatasetCandidateRow): string | null {
  const requirement = unstopped(row.requirement) ? `${unstopped(row.requirement)}.` : null;
  if (lane === "catalog" || row.acquirable) return requirement;
  if (manualDownload(row)) {
    const why = unstopped(row.accessWhy) || (row.verification?.webPage ? "the data URL answered with a web page" : "");
    const unconfirmed = row.sourceId && row.resourceId ? "its dataset id is not confirmed" : "";
    const reasons = [why, unconfirmed].filter(Boolean).join(", and ");
    return reasons ? `Manual download: ${reasons}.` : "Manual download.";
  }
  const verification = row.verification;
  if (verification && FAILED_VERDICTS.has(verification.status)) {
    return `${verificationLabel(verification.status, verification).replace(/ ✗$/, "")}: not usable as offered.`;
  }
  if (verification && verification.status !== "verified") {
    return `${verificationLabel(verification.status, verification)}.`;
  }
  return requirement;
}

/** dev/114: whose chat the card lives in — the Dataset Finder's (the DEC-047
 * install / hand-off prompt) or the Node Builder's (the runtime minted the
 * candidates from a dataset.discover delegation; the confirmation asks the
 * builder to build from the selection). */
export type CandidatesVariant = "finder" | "builder";

/** Compose the docs/06 confirmation prompt from the current selection —
 * catalog picks route to the reviewed install, external picks to the
 * DEC-047 Node Builder handoff. In a Node Builder chat (dev/114) the same
 * selection reads as the build request instead. Exported for tests. */
export function composeConfirmationPrompt(
  catalogRows: AgentDatasetCandidateRow[],
  externalRows: AgentDatasetCandidateRow[],
  variant: CandidatesVariant = "finder",
  /** The agent the rest go to, by its manifest's name: the one the host
   * agent hands nodes to build to. */
  handoffName?: string | null,
): string {
  const bits: string[] = [];
  if (variant === "builder") {
    if (catalogRows.length) {
      bits.push(
        `load from the Data Catalog: ${catalogRows
          .map((r) => `${r.name} (${r.datasetId ?? "?"})`)
          .join(", ")}`,
      );
    }
    const fetched = externalRows.filter((r) => !r.acquirable);
    if (fetched.length) {
      bits.push(
        `fetch from: ${fetched
          .map((r) => (r.url ? `${r.name} (${r.url})` : r.name))
          .join(", ")}`,
      );
    }
    return bits.length ? `Build the data-loading node. ${sentence(bits)}` : "";
  }
  if (catalogRows.length) {
    bits.push(
      `install from the Data Catalog: ${catalogRows
        .map((r) => `${r.name} (${r.datasetId ?? "?"})`)
        .join(", ")}`,
    );
  }
  // A row Curio can download is downloaded by its own button on the card, not
  // asked for in the chat. The rest go to the agent that builds nodes, which
  // is the right answer for a source no provider covers.
  const handoff = externalRows.filter((r) => !r.acquirable);
  if (handoff.length) {
    bits.push(
      `hand off to ${(handoffName ?? "").trim() || "an agent that builds nodes"}: ${handoff.map((r) => r.name).join(", ")}`,
    );
  }
  return bits.length ? `Confirm my selection. ${sentence(bits)}` : "";
}

/** *bits*, the parts of a selection's message, as one sentence: joined with
 * semicolons, its first letter a capital, ending with a full stop. */
function sentence(bits: string[]): string {
  const text = bits.join("; ");
  return `${text.charAt(0).toUpperCase()}${text.slice(1)}.`;
}

/** How a pick addresses a row, matching the server's `row_key`. Exported for tests. */
export function pickKey(
  lane: "external" | "catalog",
  row: AgentDatasetCandidateRow,
): string | undefined {
  if (lane === "catalog") return row.datasetId;
  if (row.url) return row.url;
  if (row.sourceId && row.resourceId) return `${row.sourceId}/${row.resourceId}`;
  return undefined;
}

/** Where a recorded pick comes from, as its row says: its provider, else the
 * Data Catalog for a row of the catalog. */
function pickOrigin(pick: AgentDatasetCandidateRow): string | null {
  if (pick.provider) return pick.provider;
  return pick.sourceType === "catalog" ? "Data Catalog" : null;
}

/** What the card says once its node's Dataset Finder recorded the pick: what
 * was picked and where it comes from, then what comes of the pick, as the
 * server said it (the record's `next`), the same in every chat and tab
 * ("Recorded: Chicago Neighborhoods (Data Catalog). The Dataflow Builder
 * builds CPL branches from it."). The Source recorded turns the server
 * writes are the agents' alone, so the chat says it once, here. Exported for
 * tests. */
export function recordedLine(record: AgentDatasetSourceRecord): string {
  const names = (record.picks ?? [])
    .map((pick) => {
      const name = pick.name || pick.datasetId || pick.url || "";
      const origin = pickOrigin(pick);
      return origin ? `${name} (${origin})` : name;
    })
    .join(", ");
  const next = (record.next ?? "").trim();
  return next ? `Recorded: ${names}. ${next}` : `Recorded: ${names}.`;
}

/** What a closed card says: why nothing is to pick on it any more. *node* is
 * the node's name, *record* its Finder's record. Exported for tests. */
export function closedLine(
  standing: Exclude<SourceCardStanding, { kind: "live" } | { kind: "recorded" }>,
  node: string,
  record: AgentDatasetSourceRecord | null,
): string {
  if (standing.kind === "superseded") return "Closed: newer candidates replaced these.";
  switch (standing.why) {
    case "finder-gone":
      return `Closed: its Dataset Finder was taken off ${node}.`;
    case "node-gone":
      return `Closed: ${node} is no longer on the canvas.`;
    case "skipped":
      return record?.skippedBecause
        ? `Closed: the source of ${node} is grounded already (${record.skippedBecause}), so no pick is needed.`
        : `Closed: the source of ${node} is grounded already, so no pick is needed.`;
    default:
      return "Closed: its Dataset Finder no longer holds these candidates.";
  }
}

/** The portal page an external row may link to: only a URL the runtime
 *  vouched for (a source it can download from, or one its probe verified),
 *  and only over http(s). Anything else stays plain text (REQ-SEC-002). */
export function verifiedPortalUrl(row: AgentDatasetCandidateRow): string | null {
  if (!row.url) return null;
  if (!row.acquirable && row.verification?.status !== "verified") return null;
  const safe = sanitizeAgentUrl(row.url);
  return safe && /^https?:\/\//i.test(safe) ? safe : null;
}

/**
 * The Sources card (board S04): a node's candidates as one list, best first,
 * of keyboard-operable multi-select rows carrying safe metadata only. Each
 * row says what it is, where it comes from, why it fits the node (with no
 * score) and, at most, one warning: what keeps it from being used as it is.
 * Toggling a selection composes the editable confirmation prompt into the
 * chat input (the suggested-prompt vehicle); Apply/Dismiss stay exclusively
 * on review cards. The one row action is Download, on a row Curio can
 * download: the same download the Discovery Catalog page runs. A row may also
 * open what it names, read-only, with one link: a catalog row's View details,
 * or the portal page of an external row whose link the runtime vouched for.
 * A portal download's How to get it opens the portal's own steps and Import
 * dataset. Every text field arrives bounded + scheme-allowlisted from the
 * server and renders as plain text here (REQ-SEC-002).
 *
 * The card of a node's candidates, in its Dataset Finder's chat and in the
 * chat that asked for them, is named for the node, and its Use this source
 * records the pick on the Finder, naming the card it was made on; in the
 * chat that asked, None fits? goes to the Finder's chat. It follows the
 * Finder's record (`sourceCardStanding`): its rows show only while the
 * record asks for its pick; the card the pick was made on says Recorded, with
 * the pick, where it comes from and what comes of it; a card a newer search
 * replaced, or one whose Finder, node or record is gone, or whose node needs
 * no pick, is closed and says why.
 */
export const AgentDatasetCandidatesCard: React.FC<{
  part: AgentDatasetCandidatesPart;
  tintClassName?: string;
  /** Prefill the chat input (a prefill never overwrites a user-typed draft). */
  onComposePrompt?: (prompt: string) => void;
  /** dev/114: the host agent's chat — decides the confirmation prompt's shape. */
  variant?: CandidatesVariant;
  /** The agent the host hands a source to, by its manifest's name: the
   * finder variant's hand-off names it. */
  handoffName?: string | null;
  /** dev/126: record the confirmed selection for the node this Dataset Finder
   * is attached to. Present only there; without it the card keeps its
   * dev/114 behavior exactly (select → prompt). */
  onRecordSelection?: (picks: AgentDatasetPick[]) => Promise<AgentDatasetSelection>;
  /** dev/132: the ONE catalog import (`useDatasetImport`), so a row that must
   * be downloaded from a portal can be brought in from the card that taught
   * the download. Resolves to the imported dataset's id, or null when the
   * import failed (the hook has already shown its own toast). */
  onImportDataset?: (file: File, discoverySource?: DatasetDiscoverySourceInput) => Promise<string | null>;
  /** The node these are candidates for, by the name its header shows: the
   * card is named for it. */
  nodeLabel?: string | null;
  /** The node's id, which whatever points at the card finds it by. */
  nodeId?: string | null;
  /** The node's source as its Dataset Finder records it (the listing's
   * `sourceRecord`), which the card follows. */
  record?: AgentDatasetSourceRecord | null;
  /** Whether the node still waits for the user's pick: its Finder's
   * `waitsForYou` names it. */
  waitsForPick?: boolean;
  /** The id of the search that minted these candidates (`discoveryId`). */
  discoveryId?: string | null;
  /** Whether the node's Dataset Finder is still on the dataflow, and the node
   * on the canvas. */
  finderPresent?: boolean;
  nodePresent?: boolean;
  /** Brings the card the record offers now into view, for a card a newer
   * search replaced. */
  onShowNewest?: (() => void) | null;
  /** The chat of the node's Dataset Finder, for a card in another chat: its
   * None fits? goes there. */
  finderChat?: { name: string; onOpen: () => void } | null;
}> = ({
  part,
  tintClassName,
  onComposePrompt,
  variant = "finder",
  handoffName,
  onRecordSelection,
  onImportDataset,
  nodeLabel = null,
  nodeId = null,
  record = null,
  waitsForPick = false,
  discoveryId = null,
  finderPresent = true,
  nodePresent = true,
  onShowNewest = null,
  finderChat = null,
}) => {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  // The rows whose How to get it is open.
  const [howToOpen, setHowToOpen] = useState<Set<string>>(new Set());
  const { openDatasetDetails } = useDatasetDetails();
  const [recording, setRecording] = useState(false);
  const [recorded, setRecorded] = useState<AgentDatasetSelection | null>(null);
  const [recordError, setRecordError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);
  const [downloaded, setDownloaded] = useState<string | null>(null);
  const { jobs } = useDiscoveryAcquire();

  const rowKey = (lane: string, index: number) => `${lane}:${index}`;

  /** The server addresses rows by identifier: a catalog row's datasetId, an
   * external row's url, or its Discovery Catalog coordinate when it has no url. A row
   * with none of these cannot be confirmed. */
  const picksFor = (keys: Set<string>): AgentDatasetPick[] => {
    const out: AgentDatasetPick[] = [];
    (["catalog", "external"] as const).forEach((lane) => {
      (part.lanes[lane] ?? []).forEach((row, i) => {
        if (!keys.has(rowKey(lane, i))) return;
        const key = pickKey(lane, row);
        if (key) out.push({ lane, key });
      });
    });
    return out;
  };

  const confirm = async () => {
    if (!onRecordSelection || recording) return;
    const picks = picksFor(selected);
    if (!picks.length) return;
    setRecording(true);
    setRecordError(null);
    try {
      setRecorded(await onRecordSelection(picks));
    } catch (e) {
      setRecordError(e instanceof Error ? e.message : "the selection could not be recorded");
    } finally {
      setRecording(false);
    }
  };

  /** dev/132: the download's other half — the file the user just fetched from
   * the portal is imported through the SAME catalog pathway as everywhere
   * else, and its id is then confirmed as this node's source, so solving
   * continues from it without the user explaining anything further. */
  const importAndConfirm = async (file: File, row: AgentDatasetCandidateRow) => {
    if (!onImportDataset || importing) return;
    setImporting(true);
    setRecordError(null);
    try {
      const datasetId = await onImportDataset(file, rowProvenance(row));
      if (!datasetId) return; // the import hook reported its own failure
      if (onRecordSelection) {
        setRecorded(await onRecordSelection([{ lane: "catalog", key: datasetId }]));
      }
    } catch (e) {
      setRecordError(
        e instanceof Error ? e.message : "the imported dataset could not be recorded",
      );
    } finally {
      setImporting(false);
    }
  };

  /** The Discovery Catalog page's own download: the same endpoint and the same job,
   * followed after this card unmounts. The dataset it lands is this node's
   * source, confirmed by id like an import. */
  const download = async (row: AgentDatasetCandidateRow) => {
    if (!row.sourceId || !row.resourceId) return;
    setRecordError(null);
    try {
      await startDiscoveryAcquire(row.sourceId, row.resourceId, {}, (job) => {
        void landed(row, job);
      });
    } catch (e) {
      setRecordError(e instanceof Error ? e.message : "the download could not start");
    }
  };

  const landed = async (row: AgentDatasetCandidateRow, job: DiscoveryAcquireJob) => {
    if (job.status !== "completed" || !job.datasetId) {
      setRecordError(job.error || `The download of ${row.name} was ${job.status}.`);
      return;
    }
    notifyDatasetCatalogRefresh();
    if (!onRecordSelection) {
      setDownloaded(`${row.name} is in your Data Catalog.`);
      return;
    }
    try {
      setRecorded(await onRecordSelection([{ lane: "catalog", key: job.datasetId }]));
    } catch (e) {
      setRecordError(
        e instanceof Error ? e.message : "the downloaded dataset could not be recorded",
      );
    }
  };

  const downloadControl = (row: AgentDatasetCandidateRow) => {
    const job = row.sourceId && row.resourceId
      ? jobs[acquireKey(row.sourceId, row.resourceId)]
      : undefined;
    const running = !!job && !isTerminal(job.status);
    const progress = job && running ? jobProgress(job) : null;
    const label = running
      ? `Downloading…${progress !== null ? ` ${Math.round(progress * 100)}%` : ""}`
      : job?.status === "completed"
        ? "Downloaded"
        : job
          ? "Retry download"
          : "Download";
    return (
      <button
        type="button"
        className={styles.importButton}
        disabled={running || job?.status === "completed"}
        onClick={(e) => {
          e.preventDefault();
          void download(row);
        }}
      >
        {label}
      </button>
    );
  };

  const recordedNote = (selection: AgentDatasetSelection): string => {
    // The node the pick is for, named as the Source recorded turns name it.
    const recordedFor = nodeLabel ? `Source recorded for ${nodeLabel}` : "Source recorded";
    // dev/132: when the runtime handed the fetch to the node's own builder,
    // say THAT: the user has nothing left to compose or press.
    const delegated = selection.delegated;
    if (delegated?.status === "delegating") {
      return `${recordedFor}: its ${delegated.name || "builder"} is writing the loader from it now.`;
    }
    if (delegated?.status === "session-running") {
      return `${recordedFor}: the running Solve session builds its loader on its next pass.`;
    }
    if (delegated?.reason) {
      const reason = delegated.reason.trim().replace(/\.$/, "");
      return `${recordedFor}. ${reason.charAt(0).toUpperCase()}${reason.slice(1)}.`;
    }
    if (selection.status === "resolved") {
      return `${recordedFor}: Solve it to build its loader from this source.`;
    }
    if (selection.status === "awaiting-install") {
      return `${recordedFor}: install the dataset from the Data Catalog, then Solve it.`;
    }
    return "Nothing selectable was confirmed: its link answered with an error, or not at all. Pick another row.";
  };

  const toggle = (lane: "external" | "catalog", index: number) => {
    const key = rowKey(lane, index);
    const next = new Set(selected);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSelected(next);
    const pick = (l: "external" | "catalog") =>
      (part.lanes[l] ?? []).filter((_, i) => next.has(rowKey(l, i)));
    onComposePrompt?.(composeConfirmationPrompt(pick("catalog"), pick("external"), variant, handoffName));
  };

  const toggleHowTo = (key: string) => {
    const next = new Set(howToOpen);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setHowToOpen(next);
  };

  const renderRow = ({ lane, row, index }: PlacedRow) => {
    const key = rowKey(lane, index);
    const origin = originLine(lane, row);
    const why = (row.fit?.rationale ?? "").trim();
    const warning = rowWarning(lane, row);
    // What the warning leaves out, on its tooltip: what the probe saw of a
    // link that gave no data, or the row's requirement.
    const failed = row.verification && FAILED_VERDICTS.has(row.verification.status);
    const requirement = row.requirement?.trim() || undefined;
    const warningDetail =
      (failed ? row.verification?.detail : undefined) ?? (requirement && !warning?.startsWith(unstopped(requirement)) ? requirement : undefined);
    const portalUrl = lane === "external" ? verifiedPortalUrl(row) : null;
    const datasetId = lane === "catalog" ? row.datasetId : undefined;
    const downloadable = lane === "external" && Boolean(row.acquirable);
    // dev/132: a portal download's own steps (or what the probe observed,
    // never invented here), and the import of the file they fetch; else a
    // link the runtime did not vouch for, as plain text, unless it gave no
    // data.
    const manual = lane === "external" && manualDownload(row);
    const steps = manual ? row.downloadSteps ?? [] : [];
    const plainUrl = lane === "external" && row.url && !portalUrl && !failed && steps.length === 0 ? row.url : null;
    const imports = manual && Boolean(onImportDataset);
    const howTo = steps.length > 0 || Boolean(plainUrl) || imports;
    const open = howTo && howToOpen.has(key);
    return (
      <li key={key} className={styles.row}>
        <label className={styles.rowLabel}>
          <input
            type="checkbox"
            checked={selected.has(key)}
            onChange={() => toggle(lane, index)}
            aria-label={`Select ${row.name}`}
          />
          <span className={styles.rowBody}>
            <span className={styles.name}>{row.name}</span>
            {origin ? <span className={styles.origin}>{origin}</span> : null}
            {why ? <span className={styles.why}>{why}</span> : null}
            {warning ? (
              <span className={styles.warning} data-tooltip={warningDetail}>
                {warning}
              </span>
            ) : null}
          </span>
        </label>
        {downloadable || howTo || portalUrl || datasetId ? (
          // Outside the label, so nothing here toggles the selection.
          <div className={styles.rowActions}>
            {downloadable ? downloadControl(row) : null}
            {howTo ? (
              <button
                type="button"
                className={styles.rowLink}
                aria-expanded={open}
                onClick={() => toggleHowTo(key)}
              >
                How to get it
              </button>
            ) : null}
            {portalUrl ? (
              <a className={styles.rowLink} href={portalUrl} target="_blank" rel="noopener noreferrer">
                Portal ↗
              </a>
            ) : null}
            {datasetId ? (
              <button type="button" className={styles.rowLink} onClick={() => openDatasetDetails(datasetId)}>
                View details
              </button>
            ) : null}
          </div>
        ) : null}
        {open ? (
          <div className={styles.download} role="region" aria-label={`How to get ${row.name}`}>
            {plainUrl ? <span className={styles.url}>{plainUrl}</span> : null}
            {steps.length ? (
              <ol className={styles.steps}>
                {steps.map((step, si) => (
                  <li key={si}>{step}</li>
                ))}
              </ol>
            ) : null}
            {imports ? (
              <label className={styles.importControl}>
                <input
                  type="file"
                  className={styles.importInput}
                  disabled={importing}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (file) void importAndConfirm(file, row);
                  }}
                />
                <span className={styles.importButton} aria-disabled={importing || undefined}>
                  {importing ? "Importing…" : "Import dataset"}
                </span>
              </label>
            ) : null}
          </div>
        ) : null}
      </li>
    );
  };

  // The rows as one list, best first, as the server ranked them.
  const rows = rowsInOrder(part);
  // The card's own name: the node its candidates are for, when it knows it.
  const title = nodeLabel ? `Sources for ${nodeLabel}` : "Dataset candidates";
  // Where the card stands by its node's Finder's record: a card with no pick
  // of its own (a selection composes a message) is always open.
  const standing: SourceCardStanding = onRecordSelection
    ? sourceCardStanding({ discoveryId, record, waitsForPick, finderPresent, nodePresent })
    : { kind: "live" };
  const live = standing.kind === "live";
  // What the server said comes next of a pick made on this card that still
  // asks something of the user (a portal file to import, another row to
  // pick), in every tab, when this tab has no answer of its own to show.
  const serverNote =
    live && record?.next && (record.picks ?? []).length > 0 && (!discoveryId || record.pickedFrom === discoveryId)
      ? record.next
      : null;

  return (
    <div
      className={styles.card}
      role="group"
      aria-label={title}
      data-curio-source-pick={nodeId ?? undefined}
      data-curio-discovery={discoveryId ?? undefined}
    >
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{title}</span>
      </div>
      {standing.kind === "recorded" && record ? (
        <div className={styles.done} role="status">
          <span className={styles.doneIcon} aria-hidden="true">
            <FontAwesomeIcon icon={faCheck} />
          </span>
          <span>{recordedLine(record)}</span>
        </div>
      ) : null}
      {standing.kind === "superseded" || standing.kind === "closed" ? (
        <div className={styles.closed}>
          <span role="status">{closedLine(standing, nodeLabel ?? "this node", record)}</span>
          {standing.kind === "superseded" && onShowNewest ? (
            <button type="button" className={styles.rowLink} onClick={onShowNewest}>
              Show the newest
            </button>
          ) : null}
        </div>
      ) : null}
      {live && rows.length > 0 ? <ul className={styles.rows}>{rows.map(renderRow)}</ul> : null}
      {onRecordSelection && live ? (
        <div className={styles.confirmRow}>
          <button
            type="button"
            className={styles.confirm}
            disabled={recording || picksFor(selected).length === 0}
            data-tooltip="Records this source for the node: its loader is built from exactly this source, and from nothing else."
            onClick={() => void confirm()}
          >
            {recording ? "Recording…" : "Use this source"}
          </button>
          {finderChat ? (
            // In the chat that asked: the Finder's chat, to ask it for more.
            <button type="button" className={`${styles.rowLink} ${styles.finderLink}`} onClick={finderChat.onOpen}>
              None fits? Ask its {finderChat.name}
            </button>
          ) : null}
          {recorded || serverNote ? (
            <span className={styles.recorded} role="status">
              {recorded ? recordedNote(recorded) : serverNote}
            </span>
          ) : null}
          {recordError ? (
            <span className={styles.recordError} role="alert">{recordError}</span>
          ) : null}
        </div>
      ) : null}
      {!onRecordSelection && (downloaded || recordError) ? (
        // A chat with no node to confirm for: the download still lands in the
        // Data Catalog, and the card says so, or says why it did not.
        <div className={styles.confirmRow}>
          {downloaded ? (
            <span className={styles.recorded} role="status">{downloaded}</span>
          ) : null}
          {recordError ? (
            <span className={styles.recordError} role="alert">{recordError}</span>
          ) : null}
        </div>
      ) : null}
    </div>
  );
};
