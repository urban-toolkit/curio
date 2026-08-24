import React, { useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faRobot } from "@fortawesome/free-solid-svg-icons";
import type { AgentProposalPart } from "../../../api/agentsApi";
import { describePackagePermission } from "../../../utils/packagePermissions";
import styles from "./AgentReviewCard.module.css";

/** dev/67-5/67-8/71: the per-node review state (mirror + builderSession). */
export interface PlanNodeReviewState {
  appliedRefs: string[];
  editedGoals: Record<string, string>;
  /** dev/67-8: edge index → planned|applied|refused. */
  edgeStates?: Record<string, string>;
  /** dev/71: ref → planned|created|solving|validated|approved|failed. */
  nodeStates?: Record<string, string>;
  /** dev/72: ref → its content proposal + the attachment it lives on (the
   * node's own agent when homed; legacy string = builder-homed). */
  nodeProposals?: Record<
    string,
    string | { proposalId: string; attachmentId?: string | null }
  >;
}

/** dev/71: what a row's lifecycle state means for its action cluster. */
const ROW_STATE_CHIP: Record<string, string> = {
  solving: "Content review pending",
  validated: "Validated — review below",
  approved: "Solved ✓",
  failed: "Failed — Solve retries",
};

/** One planned node's review row (dev/67-5 + dev/71 progressive lifecycle):
 * editable goal, dependencies by name, Apply → Solve → Run per node. */
const PlanNodeRow: React.FC<{
  node: { ref: string; nodeType: string; title: string; intent: string; expects?: string };
  applied: boolean;
  goal: string;
  /** dev/71: dependency labels + readiness. */
  deps: string[];
  state: string;
  solvable: boolean;
  solveBlocker: string | null;
  onApply: () => Promise<void>;
  onSaveGoal: (goal: string) => Promise<void>;
  onSolve?: () => Promise<void>;
  onRun?: () => Promise<void>;
  /** dev/72: opens the node agent's chat, where the content review lives. */
  onOpenReview?: () => void;
  reviewAgentName?: string;
}> = ({ node, applied, goal, deps, state, solvable, solveBlocker, onApply, onSaveGoal, onSolve, onRun, onOpenReview, reviewAgentName }) => {
  const [draft, setDraft] = useState(goal);
  const [busy, setBusy] = useState(false);
  const [rowBusy, setRowBusy] = useState<"solve" | "run" | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const act = async (kind: "solve" | "run", fn?: () => Promise<void>) => {
    if (!fn || rowBusy) return;
    setRowBusy(kind);
    setRowError(null);
    try {
      await fn();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : `The ${kind} failed`);
    } finally {
      setRowBusy(null);
    }
  };

  const saveGoal = async () => {
    const next = draft.trim();
    if (!next || next === goal.trim()) return;
    setRowError(null);
    try {
      await onSaveGoal(next);
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "The goal edit failed");
    }
  };

  const apply = async () => {
    if (busy || applied) return;
    setBusy(true);
    setRowError(null);
    try {
      await onApply();
    } catch (e) {
      setRowError(e instanceof Error ? e.message : "Creating the node failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className={styles.planNodeRow}>
      <div className={styles.planNodeHead}>
        <span className={styles.planNodeTitle}>{node.title}</span>
        <span className={styles.planNodeType}>{node.nodeType}</span>
        {!applied ? (
          <button
            type="button"
            className={styles.apply}
            disabled={busy}
            onClick={() => void apply()}
            aria-label={`Create node ${node.title}`}
          >
            {busy ? "Creating…" : "Apply"}
          </button>
        ) : (
          <>
            {ROW_STATE_CHIP[state] ? (
              <span
                className={
                  state === "failed" ? styles.planEdgeRefused : styles.planNodeCreated
                }
              >
                {ROW_STATE_CHIP[state]}
                {/* dev/72: the icon-link to the node agent's chat, where the
                    content review (and the Solve trace) lives. */}
                {onOpenReview ? (
                  <button
                    type="button"
                    className={styles.reviewLink}
                    aria-label={`Open ${reviewAgentName ?? "the node agent"}'s chat`}
                    title={`Open ${reviewAgentName ?? "the node agent"}'s chat`}
                    onClick={onOpenReview}
                  >
                    <FontAwesomeIcon icon={faRobot} />
                  </button>
                ) : null}
              </span>
            ) : (
              <span className={styles.planNodeCreated}>Created ✓</span>
            )}
            {onSolve && (state === "created" || state === "failed") ? (
              <button
                type="button"
                className={styles.apply}
                disabled={rowBusy !== null || !solvable}
                title={solveBlocker ?? undefined}
                onClick={() => void act("solve", onSolve)}
                aria-label={`Solve node ${node.title}`}
              >
                {rowBusy === "solve" ? "Solving…" : "Solve"}
              </button>
            ) : null}
            {onRun && state === "approved" ? (
              <button
                type="button"
                className={styles.run}
                disabled={rowBusy !== null}
                onClick={() => void act("run", onRun)}
                aria-label={`Run through node ${node.title}`}
              >
                {rowBusy === "run" ? "Running…" : "Run"}
              </button>
            ) : null}
          </>
        )}
      </div>
      {deps.length ? (
        <div className={styles.planNodeExpects}>needs: {deps.join(", ")}</div>
      ) : null}
      {node.expects ? <div className={styles.planNodeExpects}>{node.expects}</div> : null}
      <textarea
        className={styles.planGoalInput}
        value={draft}
        disabled={applied}
        rows={2}
        aria-label={`Goal for ${node.title}`}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => void saveGoal()}
      />
      {rowError ? <div className={styles.error}>{rowError}</div> : null}
    </li>
  );
};

const OUTCOME_LABEL: Record<string, string> = {
  applied: "Applied",
  dismissed: "Dismissed",
  superseded: "Superseded by a newer proposal",
  stale: "The target changed since this was proposed — ask the agent to propose again",
};

/** What one Apply click does, per proposal kind — stated on the card. */
const EFFECT_LINE: Record<string, string> = {
  "node.create": "Applying adds this node to the canvas.",
  "project.install":
    "Applying installs only this project template — nothing is imported, attached, run, or published.",
  "node.template.create":
    "Applying registers the node type in this project and adds its first node.",
  "dataset.install":
    "Applying installs only this dataset into the project's Data Catalog — no agent is installed.",
  "package.install":
    "Applying opens the package install review (permissions, dependencies, conflicts) — nothing installs until you confirm there.",
  "package.draft.apply":
    "Applying installs the exact reviewed artifact and creates its requested nodes — nothing else changes.",
};

/** dev/52 (+dev/59): the plan card's effect line — dynamic and honest about
 * removals. */
function planEffectLine(part: AgentProposalPart): string | null {
  if (part.tool !== "dataflow.plan.write" || !part.plan) return null;
  const n = part.plan.nodes.length;
  const removed = part.plan.removals?.length ?? 0;
  if (removed) {
    return (
      `Applying adds ${n} node${n === 1 ? "" : "s"} and removes ${removed} — ` +
      "removal deletes their content and cannot be undone."
    );
  }
  return `Applying adds these ${n} connected node${n === 1 ? "" : "s"} to the canvas — existing work is untouched.`;
}

/**
 * The review-before-apply card (memo dev/41; the blueprint's planned
 * `AgentReviewCard`). The agent proposes; the USER confirms here — Apply and
 * Dismiss are system review controls (the sanctioned exception family to
 * "no agent action buttons", same as the DEC-035 install dialog). The
 * proposed content is model output: it renders as inert plain text
 * (REQ-SEC-002), never markup. Non-pending proposals render inert with
 * their outcome label.
 */
export const AgentReviewCard: React.FC<{
  part: AgentProposalPart;
  /** Tint class carrying the agent's category color for the accent dot. */
  tintClassName?: string;
  onApply?: (proposalId: string) => Promise<void>;
  onDismiss?: (proposalId: string) => Promise<void>;
  /** dev/67-5 (plan proposals): the per-node review state from the
   * activeProposal mirror; enables the per-node rows when present. */
  planNodeState?: PlanNodeReviewState;
  onApplyPlanNode?: (proposalId: string, ref: string) => Promise<void>;
  onSavePlanGoal?: (proposalId: string, ref: string, goal: string) => Promise<void>;
  /** dev/67-8: apply plan edges (a subset by index, or all pending). */
  onApplyPlanEdges?: (proposalId: string, indices?: number[]) => Promise<void>;
  /** dev/71: per-row Solve (the 67-7 validate loop) and Run (through node). */
  onSolvePlanNode?: (ref: string) => Promise<void>;
  onRunPlanNode?: (ref: string) => Promise<void>;
  /** dev/72: the icon-link route to a homed content review's chat. */
  onOpenAgentChat?: (attachmentId: string) => void;
  delegateExists?: (attachmentId: string) => boolean;
}> = ({ part, tintClassName, onApply, onDismiss, planNodeState, onApplyPlanNode, onSavePlanGoal, onApplyPlanEdges, onSolvePlanNode, onRunPlanNode, onOpenAgentChat, delegateExists }) => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [edgeBusy, setEdgeBusy] = useState<string | null>(null);

  const applyEdges = async (indices?: number[]) => {
    if (!onApplyPlanEdges || edgeBusy) return;
    setEdgeBusy(indices ? String(indices[0]) : "all");
    setError(null);
    try {
      await onApplyPlanEdges(part.proposalId, indices);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Connecting failed");
    } finally {
      setEdgeBusy(null);
    }
  };

  const act = async (fn?: (proposalId: string) => Promise<void>) => {
    if (!fn || busy) return;
    setBusy(true);
    setError(null);
    try {
      await fn(part.proposalId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The review action failed");
    } finally {
      setBusy(false);
    }
  };

  const pending = part.status === "pending";
  return (
    <div className={styles.card} role="group" aria-label={`Review proposal: ${part.summary}`}>
      <div className={`${styles.header} ${tintClassName ?? ""}`}>
        <span className={styles.accentDot} aria-hidden="true" />
        <span>{part.summary}</span>
        <span className={styles.kind}>review</span>
      </div>
      {part.tool === "node.template.create" && part.justification ? (
        // The adequacy gate (dev/48 §3.2b): the model's reasoning is what the
        // user judges — rendered verbatim FIRST, above the definition.
        <div className={styles.justification} aria-label="Why a new node type is needed">
          {part.justification}
        </div>
      ) : null}
      {part.tool === "node.template.create" && part.template ? (
        <div className={styles.meta}>
          {part.template.label} · {part.template.engine}
          {part.template.description ? ` — ${part.template.description}` : ""}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan ? (
        // Summary first (dev/52): counts + goal at a glance; the node list
        // scrolls in the preview region below — plans can be large.
        <div className={styles.meta}>
          {part.plan.nodes.length} nodes · {part.plan.edgeCount} connections — {part.plan.goal}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan?.removals?.length ? (
        // DEC-049.2: removals reviewed by NAME — every victim, with a
        // content flag; impossible to miss.
        <div className={styles.removals} role="group" aria-label="Nodes this plan removes">
          <div className={styles.removalsTitle}>
            Removes {part.plan.removals.length} node
            {part.plan.removals.length === 1 ? "" : "s"}
            {part.plan.cascadeCount
              ? ` (and ${part.plan.cascadeCount} connected edge${part.plan.cascadeCount === 1 ? "" : "s"})`
              : ""}
          </div>
          <ul className={styles.removalsList}>
            {part.plan.removals.map((victim) => (
              <li key={victim.id}>
                {victim.label}
                {victim.nodeType ? ` · ${victim.nodeType}` : ""}
                {victim.contentChars > 0
                  ? ` — contains ${victim.contentChars} chars of content`
                  : " — empty"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {part.tool === "package.draft.apply" && part.draft ? (
        // dev/96: the diff, dependencies, and preview the Apply text claims
        // the user reviewed — collapsed to counts by default; blocking
        // findings and failed previews render OPEN (impossible to miss).
        // Every capped list states its overflow; all text renders inert.
        <>
          <details className={styles.draftSection}>
            <summary>
              Files — {part.draft.files.addedTotal} added ·{" "}
              {part.draft.files.modifiedTotal} modified ·{" "}
              {part.draft.files.preservedTotal} preserved
            </summary>
            <ul className={styles.draftList}>
              {part.draft.files.added.map((name) => (
                <li key={`a:${name}`}>added {name}</li>
              ))}
              {part.draft.files.addedTotal > part.draft.files.added.length ? (
                <li className={styles.draftOverflow}>
                  …and {part.draft.files.addedTotal - part.draft.files.added.length} more added
                </li>
              ) : null}
              {part.draft.files.modified.map((name) => (
                <li key={`m:${name}`}>modified {name}</li>
              ))}
              {part.draft.files.modifiedTotal > part.draft.files.modified.length ? (
                <li className={styles.draftOverflow}>
                  …and {part.draft.files.modifiedTotal - part.draft.files.modified.length} more modified
                </li>
              ) : null}
              <li>
                templates: {part.draft.templates.addedTotal} added ·{" "}
                {part.draft.templates.modifiedTotal} modified ·{" "}
                {part.draft.templates.preservedTotal} preserved
                {part.draft.templates.added.length
                  ? ` (${part.draft.templates.added.join(", ")}${
                      part.draft.templates.addedTotal > part.draft.templates.added.length
                        ? ", …" : ""})`
                  : ""}
              </li>
            </ul>
          </details>
          {part.draft.dependencies ? (
            <details className={styles.draftSection} open={part.draft.dependencies.blocked}>
              <summary>
                Dependencies — {part.draft.dependencies.pythonTotal} python ·{" "}
                {part.draft.dependencies.jsTotal} js ·{" "}
                {part.draft.dependencies.findingsTotal} finding
                {part.draft.dependencies.findingsTotal === 1 ? "" : "s"}
              </summary>
              <ul className={styles.draftList}>
                {part.draft.dependencies.python.map((row) => (
                  <li key={`py:${row.name}`}>python · {row.name} {row.constraint}</li>
                ))}
                {part.draft.dependencies.js.map((row) => (
                  <li key={`js:${row.name}`}>js · {row.name} {row.version}</li>
                ))}
                {part.draft.dependencies.pythonTotal + part.draft.dependencies.jsTotal >
                 part.draft.dependencies.python.length + part.draft.dependencies.js.length ? (
                  <li className={styles.draftOverflow}>
                    …and {part.draft.dependencies.pythonTotal
                      + part.draft.dependencies.jsTotal
                      - part.draft.dependencies.python.length
                      - part.draft.dependencies.js.length} more dependencies
                  </li>
                ) : null}
                {part.draft.dependencies.findings.map((finding, index) => (
                  <li
                    key={`f:${finding.code}:${index}`}
                    className={
                      finding.severity === "block"
                        ? styles.findingBlock
                        : finding.severity === "warn"
                          ? styles.findingWarn
                          : undefined
                    }
                  >
                    {finding.severity}: {finding.message}
                  </li>
                ))}
                {part.draft.dependencies.findingsTotal >
                 part.draft.dependencies.findings.length ? (
                  <li className={styles.draftOverflow}>
                    …and {part.draft.dependencies.findingsTotal
                      - part.draft.dependencies.findings.length} more findings
                  </li>
                ) : null}
              </ul>
            </details>
          ) : null}
          {part.draft.preview ? (
            <details
              className={styles.draftSection}
              open={part.draft.preview.status === "failed"}
            >
              <summary>Preview — {part.draft.preview.status}</summary>
              <ul className={styles.draftList}>
                {part.draft.preview.reasons.map((reason, index) => (
                  <li
                    key={`r:${index}`}
                    className={part.draft!.preview!.status === "ok"
                      ? undefined : styles.findingWarn}
                  >
                    {reason}
                  </li>
                ))}
                {part.draft.preview.templates.map((row) => (
                  <li key={`t:${row.templateId}`}>
                    {row.templateId}:{" "}
                    {row.ok ? "all states rendered" :
                      `failed states — ${row.failedStates.join(", ")}`}
                  </li>
                ))}
                {part.draft.preview.runnerVersion ? (
                  <li>runner {part.draft.preview.runnerVersion}</li>
                ) : null}
              </ul>
            </details>
          ) : null}
          {part.draft.requestedNodes ? (
            <div className={styles.draftNodesRow}>
              Creates {part.draft.requestedNodes.total} node
              {part.draft.requestedNodes.total === 1 ? "" : "s"} after install:{" "}
              {part.draft.requestedNodes.rows
                .map((row) => `${row.title}${row.color ? ` (${row.color})` : ""}`)
                .join(", ")}
              {part.draft.requestedNodes.total > part.draft.requestedNodes.rows.length
                ? `, …and ${part.draft.requestedNodes.total
                    - part.draft.requestedNodes.rows.length} more`
                : ""}
            </div>
          ) : null}
        </>
      ) : null}
      {part.tool === "package.draft.apply" && part.backend ? (
        // dev/91 §5: the trust edge is stated ON the card, before Apply —
        // server-side handlers + declared permissions, impossible to miss.
        <div
          className={styles.removals}
          role="group"
          aria-label="Server-side code this package runs"
        >
          <div className={styles.removalsTitle}>
            Runs server-side code in the package sandbox
            {part.backend.network
              ? " — may reach the network (server-network declared)"
              : " — no network access"}
          </div>
          <ul className={styles.removalsList}>
            {part.backend.handlers.map((h) => (
              <li key={`handler:${h.name}`}>
                handler {h.name}
                {h.timeoutClass ? ` · ${h.timeoutClass} limits` : ""}
              </li>
            ))}
            {part.backend.permissions.map((perm) => {
              const meaning = describePackagePermission(perm);
              return (
                <li key={`perm:${perm}`}>
                  permission {perm}
                  {meaning ? ` — ${meaning}` : ""}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {part.validation ? (
        // dev/67-7: the validation verdict — real runtime evidence, rendered
        // inert. PASS or FAIL, Apply stays available (labeled honestly).
        <div
          className={`${styles.validation} ${
            part.validation.verdict === "pass" ? styles.validationPass : styles.validationFail
          }`}
          role="status"
          aria-label={`Validation ${part.validation.verdict}`}
        >
          <span className={styles.validationBadge}>
            {part.validation.verdict === "pass" ? "PASS" : "FAIL"}
          </span>
          <span>
            {part.validation.verdict === "pass"
              ? `Executed through the dataflow${
                  part.validation.evidence?.outputDataType
                    ? ` — output: ${part.validation.evidence.outputDataType}`
                    : ""
                }`
              : part.validation.evidence?.kind === "upstream-blocker"
                ? `Upstream node ${part.validation.evidence?.blockerLabel ?? "?"} failed before this node ran`
                : (part.validation.evidence?.detail ??
                   `Validation failed after ${part.validation.rounds} round${part.validation.rounds === 1 ? "" : "s"}`)}
            {part.validation.rounds > 1
              ? ` (${part.validation.rounds} generation rounds)`
              : ""}
          </span>
          {part.validation.evidence?.stderrTail ? (
            <details className={styles.validationDetails}>
              <summary>error output</summary>
              <pre>{part.validation.evidence.stderrTail}</pre>
            </details>
          ) : null}
        </div>
      ) : null}
      {part.tool === "dataflow.plan.write" && part.plan && pending && onApplyPlanNode ? (
        // dev/67-5 (Simulation Mode: create): every planned node individually
        // inspectable — editable goal, expects, per-node Apply. Replaces the
        // text preview for pending plans; no generated code ever renders here
        // (plans are content-free by contract).
        <ul className={styles.planNodes} aria-label="Planned nodes">
          {part.plan.nodes.map((node) => {
            // dev/71: readiness from the ledgers the mirror already carries.
            const planEdges = part.plan!.edges ?? [];
            const nodeStates = planNodeState?.nodeStates ?? {};
            const edgeStates = planNodeState?.edgeStates ?? {};
            const planRefSet = new Set(part.plan!.nodes.map((n) => n.ref));
            const incoming = planEdges
              .map((edge, index) => ({ ...edge, index }))
              .filter((edge) => edge.to === node.ref);
            const deps = incoming.map((edge) => edge.fromLabel);
            const applied = (planNodeState?.appliedRefs ?? []).includes(node.ref);
            const state = nodeStates[node.ref] ?? (applied ? "created" : "planned");
            const disconnected = incoming.filter(
              (edge) => edgeStates[String(edge.index)] !== "applied",
            );
            const unsolvedUpstream = incoming.filter(
              (edge) => planRefSet.has(edge.from) && nodeStates[edge.from] !== "approved",
            );
            const solvable =
              applied && disconnected.length === 0 && unsolvedUpstream.length === 0;
            const solveBlocker = !applied
              ? null
              : disconnected.length
                ? `needs '${disconnected[0].fromLabel}' connected first`
                : unsolvedUpstream.length
                  ? `needs '${unsolvedUpstream[0].fromLabel}' solved first`
                  : null;
            // dev/72: the ref's content review lives on the node's own agent
            // when homed — the chip links there (stale/absent → no link).
            const proposalEntry = planNodeState?.nodeProposals?.[node.ref];
            const reviewHomeId =
              proposalEntry && typeof proposalEntry === "object"
                ? (proposalEntry.attachmentId ?? null)
                : null;
            const reviewLinkable = Boolean(
              reviewHomeId &&
                onOpenAgentChat &&
                (delegateExists ? delegateExists(reviewHomeId) : true),
            );
            return (
              <PlanNodeRow
                key={node.ref}
                node={node}
                applied={applied}
                goal={planNodeState?.editedGoals?.[node.ref] ?? node.intent}
                deps={deps}
                state={state}
                solvable={solvable}
                solveBlocker={solveBlocker}
                onApply={() => onApplyPlanNode(part.proposalId, node.ref)}
                onSaveGoal={(goal) =>
                  onSavePlanGoal
                    ? onSavePlanGoal(part.proposalId, node.ref, goal)
                    : Promise.resolve()
                }
                onSolve={onSolvePlanNode ? () => onSolvePlanNode(node.ref) : undefined}
                onRun={onRunPlanNode ? () => onRunPlanNode(node.ref) : undefined}
                onOpenReview={
                  reviewLinkable ? () => onOpenAgentChat!(reviewHomeId!) : undefined
                }
              />
            );
          })}
        </ul>
      ) : (
        <div className={styles.preview}>{part.preview}</div>
      )}
      {part.tool === "dataflow.plan.write" && part.plan?.edges?.length && pending && onApplyPlanEdges ? (
        // dev/67-8 (Simulation Mode: connect): edges reviewed BY NAME in a
        // vertical list — you always know which two nodes a click connects.
        <div className={styles.planEdges} role="group" aria-label="Planned connections">
          <div className={styles.planEdgesHead}>
            <span>Connections</span>
            <button
              type="button"
              className={styles.apply}
              disabled={edgeBusy !== null}
              onClick={() => void applyEdges()}
            >
              {edgeBusy === "all" ? "Connecting…" : "Connect all"}
            </button>
          </div>
          <ul className={styles.planEdgesList}>
            {part.plan.edges.map((edge, index) => {
              const state = planNodeState?.edgeStates?.[String(index)];
              const applied = planNodeState?.appliedRefs ?? [];
              const fromReady =
                !part.plan!.nodes.some((n) => n.ref === edge.from) || applied.includes(edge.from);
              const toReady =
                !part.plan!.nodes.some((n) => n.ref === edge.to) || applied.includes(edge.to);
              const blockedBy = !fromReady ? edge.fromLabel : !toReady ? edge.toLabel : null;
              return (
                <li key={index} className={styles.planEdgeRow}>
                  <span className={styles.planEdgeNames}>
                    {edge.fromLabel} → {edge.toLabel}
                    {edge.toHandle ? ` [${edge.toHandle}]` : ""}
                  </span>
                  {state === "applied" ? (
                    <span className={styles.planNodeCreated}>Connected ✓</span>
                  ) : state === "refused" ? (
                    <span className={styles.planEdgeRefused}>Refused ✗</span>
                  ) : (
                    <button
                      type="button"
                      className={styles.apply}
                      disabled={edgeBusy !== null || blockedBy !== null}
                      title={blockedBy ? `create '${blockedBy}' first` : undefined}
                      aria-label={`Connect ${edge.fromLabel} to ${edge.toLabel}`}
                      onClick={() => void applyEdges([index])}
                    >
                      {edgeBusy === String(index) ? "Connecting…" : "Connect"}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
      {planEffectLine(part) ? (
        <div className={styles.meta}>{planEffectLine(part)}</div>
      ) : EFFECT_LINE[part.tool] ? (
        <div className={styles.meta}>{EFFECT_LINE[part.tool]}</div>
      ) : null}
      {pending && (onApply || onDismiss) ? (
        <div className={styles.actions}>
          {onApply ? (
            <button
              type="button"
              className={styles.apply}
              disabled={busy}
              onClick={() => void act(onApply)}
            >
              {busy
                ? "Applying…"
                : part.validation?.verdict === "fail"
                  ? "Apply anyway"
                  : "Apply"}
            </button>
          ) : null}
          {onDismiss ? (
            <button
              type="button"
              className={styles.dismiss}
              disabled={busy}
              onClick={() => void act(onDismiss)}
            >
              Dismiss
            </button>
          ) : null}
        </div>
      ) : !pending ? (
        <div
          className={`${styles.outcome} ${
            styles[`outcome_${part.status}` as keyof typeof styles] ?? ""
          }`}
        >
          {OUTCOME_LABEL[part.status] ?? part.status}
        </div>
      ) : null}
      {error ? <div className={styles.error}>{error}</div> : null}
    </div>
  );
};
