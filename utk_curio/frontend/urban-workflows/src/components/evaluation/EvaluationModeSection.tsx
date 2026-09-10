import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "./EvaluationModeSection.module.css";
import {
  PHASE_LABEL,
  evaluationApi,
  type EvaluationFixture,
  type EvaluationReadiness,
  type EvaluationRun,
} from "../../api/evaluationApi";

/**
 * dev/123 (DEC-079): Settings → Evaluation mode.
 *
 * Asks the question the fixtures exist to answer, where the model is chosen:
 * *can the model I configured rebuild one of Curio's own examples?* A run
 * happens in the product — its own project, the normal install and attach, the
 * normal plan → review/apply → Solve lifecycle — so what it measures is what a
 * person would get.
 *
 * Five states, and the blocked one carries the requirement the owner named: a
 * model configured by `curio.py start --llm-model` is as real as one typed
 * into AI Settings, so the panel reports WHICH of the two supplied it and
 * never tells an operator who passed the flag that they configured nothing.
 *
 * The body mounts only while the disclosure is open (the dev/116 pattern), and
 * nothing polls on a timer: a run takes minutes, so the phase line says what
 * it is doing and for how long.
 */
export const EvaluationModeSection: React.FC<{ sharedGuest?: boolean }> = ({
  sharedGuest = false,
}) => {
  const [open, setOpen] = useState(false);
  const [readiness, setReadiness] = useState<EvaluationReadiness | null>(null);
  const [fixtures, setFixtures] = useState<EvaluationFixture[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [run, setRun] = useState<EvaluationRun | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reviewNote, setReviewNote] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [ready, listing, runs] = await Promise.all([
        evaluationApi.readiness(),
        evaluationApi.fixtures(),
        evaluationApi.list(),
      ]);
      setReadiness(ready);
      setFixtures(listing.fixtures);
      setRun(runs.runs[0] ?? null);
      setSelected((current) => current || listing.fixtures[0]?.fixtureId || "");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not read the evaluation state.");
    }
  }, []);

  useEffect(() => {
    if (!open || sharedGuest) return;
    void load();
  }, [open, sharedGuest, load]);

  // A running evaluation is followed by asking, not by a spinner: the phases
  // are minutes apart, so a slow poll is honest and cheap. It stops the moment
  // the run is terminal.
  useEffect(() => {
    if (!open || !run || run.terminal) {
      if (timer.current) {
        clearInterval(timer.current);
        timer.current = null;
      }
      return;
    }
    const runId = run.runId;
    timer.current = setInterval(() => {
      evaluationApi
        .status(runId)
        .then(setRun)
        .catch(() => undefined);
    }, 3000);
    return () => {
      if (timer.current) clearInterval(timer.current);
      timer.current = null;
    };
  }, [open, run?.runId, run?.terminal]);

  const fixture = useMemo(
    () => fixtures.find((f) => f.fixtureId === selected) ?? null,
    [fixtures, selected],
  );

  const act = useCallback(
    async (what: string, action: () => Promise<EvaluationRun>) => {
      setBusy(what);
      setError(null);
      try {
        setRun(await action());
      } catch (e) {
        setError(e instanceof Error ? e.message : `Could not ${what}.`);
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const review = useCallback(
    async (status: "approved" | "pending-owner-review") => {
      if (!fixture) return;
      setBusy("review");
      setError(null);
      try {
        const result = await evaluationApi.review(fixture.fixtureId, status);
        setReviewNote(
          result.status === "approved"
            ? `Approved by ${result.reviewedBy}.`
            : "Back to awaiting review.",
        );
        const listing = await evaluationApi.fixtures();
        setFixtures(listing.fixtures);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Could not record the review.");
      } finally {
        setBusy(null);
      }
    },
    [fixture],
  );

  const elapsed = run
    ? Math.max(0, Math.round((run.latencyMs || 0) / 1000))
    : 0;

  const body = (
    <div>
      <p className={styles.intro}>
        Runs one of Curio's own example prompts through the real agent
        lifecycle with the model this account uses, in a project of its own,
        then scores the dataflow it built against the saved example. Your
        current dataflow is not touched.
      </p>

      {sharedGuest ? (
        <p className={styles.blocked}>
          Evaluation mode is not available on the shared guest account.
        </p>
      ) : null}

      {error ? <p className={modal.error}>{error}</p> : null}

      {readiness && !readiness.configured ? (
        <p className={styles.blocked}>
          No model is configured, so there is nothing to evaluate.{" "}
          {readiness.reason} Set a provider and model in the fields above, or
          start Curio with <code>--llm-provider</code>,{" "}
          <code>--llm-base-url</code> and <code>--llm-model</code>.
        </p>
      ) : null}

      {readiness?.configured ? (
        <>
          <p className={styles.who}>
            <strong>{readiness.provider.model}</strong>
            {readiness.provider.baseUrlHost
              ? ` at ${readiness.provider.baseUrlHost}`
              : ""}{" "}
            will answer.{" "}
            <span className={styles.source}>
              {readiness.source === "deployment"
                ? "Configured by this deployment's start command."
                : "From your AI Settings above."}
            </span>
          </p>

          <div className={modal.field}>
            <label className={modal.label} htmlFor="evaluation-fixture">
              Example to rebuild
            </label>
            <select
              id="evaluation-fixture"
              className={modal.input}
              value={selected}
              onChange={(e) => {
                setSelected(e.target.value);
                setReviewNote(null);
              }}
            >
              {fixtures.map((f) => (
                <option key={f.fixtureId} value={f.fixtureId}>
                  {f.fixtureId} · {f.tier}
                  {f.reviewStatus === "approved" ? " · approved" : ""}
                </option>
              ))}
            </select>
          </div>

          {fixture ? (
            <>
              <p className={styles.meta}>
                {fixture.expectedNodes} nodes, {fixture.expectedEdges} edges in the
                reference · split {fixture.split}
                {fixture.needs.length ? ` · needs ${fixture.needs.join(", ")}` : ""}
              </p>
              <div
                className={styles.prompt}
                role="region"
                aria-label="The prompt that will be sent"
              >
                {fixture.prompt}
              </div>
              {fixture.skip.length ? (
                <ul className={styles.categories}>
                  {fixture.skip.map((entry) => (
                    <li key={entry.when}>Not measured: {entry.reason}</li>
                  ))}
                </ul>
              ) : null}

              <div className={styles.review}>
                {fixture.reviewStatus === "approved" ? (
                  <>
                    <span>
                      Prompt approved
                      {fixture.reviewedBy ? ` by ${fixture.reviewedBy}` : ""}.
                    </span>
                    <button
                      type="button"
                      className={modal.ghostBtn}
                      disabled={busy !== null}
                      onClick={() => void review("pending-owner-review")}
                    >
                      Withdraw approval
                    </button>
                  </>
                ) : (
                  <>
                    <span>
                      This prompt was drafted by a model and is awaiting review.
                    </span>
                    <button
                      type="button"
                      className={modal.ghostBtn}
                      disabled={busy !== null}
                      onClick={() => void review("approved")}
                      aria-describedby="evaluation-approve-note"
                    >
                      {busy === "review" ? "Recording…" : "Approve this prompt"}
                    </button>
                  </>
                )}
              </div>
              <p className={styles.meta} id="evaluation-approve-note">
                Approving records your name against the prompt and lets it be
                exported later. An evaluation runs either way.
              </p>
              {reviewNote ? <p className={modal.success}>{reviewNote}</p> : null}
            </>
          ) : null}

          <div className={modal.buttonRow}>
            <button
              type="button"
              className={modal.primaryBtn}
              disabled={!selected || busy !== null || Boolean(run && !run.terminal)}
              onClick={() =>
                void act("start the evaluation", () => evaluationApi.start(selected))
              }
            >
              {busy === "start the evaluation" ? "Starting…" : "Run evaluation"}
            </button>
          </div>
        </>
      ) : null}

      {run ? (
        <div className={styles.report} role="status" aria-label="Evaluation run">
          <p className={styles.phase}>
            {run.fixtureId}: {PHASE_LABEL[run.phase] ?? run.phase}
            {run.terminal ? "" : ` · ${elapsed}s`}
          </p>
          {run.error ? <p className={modal.error}>{run.error}</p> : null}
          {run.failures.map((failure) => (
            <p key={failure.phase + failure.detail} className={modal.error}>
              Stopped in {failure.phase}: {failure.detail}
            </p>
          ))}

          {run.score ? (
            <>
              <p className={styles.total}>
                Overall accuracy {(run.score.total * 100).toFixed(0)}%
              </p>
              <table className={styles.table}>
                <caption>Per category</caption>
                <tbody>
                  {Object.entries(run.score.dimensions).map(([name, value]) => (
                    <tr key={name}>
                      <th scope="row">{name}</th>
                      <td>
                        {value === null
                          ? "not measured"
                          : `${(value * 100).toFixed(0)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {run.score.categories.length ? (
                <ul className={styles.categories}>
                  {run.score.categories.map((category) => (
                    <li key={category}>{category}</li>
                  ))}
                </ul>
              ) : null}
              {run.score.notes.map((note) => (
                <p key={note} className={styles.meta}>
                  {note}
                </p>
              ))}
            </>
          ) : null}

          {run.pending.length ? (
            <ul className={styles.categories}>
              {run.pending.map((entry) => (
                <li key={entry.tool + entry.target}>
                  Left pending: {entry.tool} — {entry.reason}
                </li>
              ))}
            </ul>
          ) : null}

          <p className={styles.meta}>
            {run.usage.inputTokens + run.usage.outputTokens > 0
              ? `${run.usage.inputTokens} in / ${run.usage.outputTokens} out tokens · `
              : ""}
            {run.provider.model}
          </p>

          <div className={modal.buttonRow}>
            {run.projectId ? (
              <a
                className={modal.ghostBtn}
                href={`/dataflow/${run.projectId}`}
                target="_blank"
                rel="noreferrer"
                aria-describedby="evaluation-project-note"
              >
                Open the generated dataflow
              </a>
            ) : null}
            {!run.terminal ? (
              <button
                type="button"
                className={modal.ghostBtn}
                disabled={busy !== null || run.cancelRequested}
                onClick={() =>
                  void act("cancel", () => evaluationApi.cancel(run.runId))
                }
                aria-describedby="evaluation-cancel-note"
              >
                {run.cancelRequested ? "Stopping…" : "Cancel"}
              </button>
            ) : null}
            <button
              type="button"
              className={modal.ghostBtn}
              disabled={busy !== null}
              onClick={() => void act("refresh", () => evaluationApi.status(run.runId))}
            >
              Refresh
            </button>
          </div>
          {run.projectId ? (
            <p className={styles.meta} id="evaluation-project-note">
              Opens the project this run built, so you can see the graph behind
              the score. It is yours to keep or delete.
            </p>
          ) : null}
          {!run.terminal ? (
            <p className={styles.meta} id="evaluation-cancel-note">
              Stops at the next step; a request already sent to the model cannot
              be recalled.
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );

  return (
    <details
      className={styles.section}
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
      data-testid="evaluation-mode-section"
    >
      <summary className={styles.summary}>Evaluation mode</summary>
      {/* The body mounts only while open: a closed section adds no fields,
          buttons or selects to the modal's accessibility tree (dev/116). */}
      {open ? body : null}
    </details>
  );
};
