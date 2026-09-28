import React, { useCallback, useEffect, useState } from "react";
import modal from "../modal-content.module.css";
import styles from "./ModelTrainingSection.module.css";
import {
  trainingApi,
  type TrainingCapability,
  type TrainingJob,
  type TrainingPreview,
} from "../../api/trainingApi";

/**
 * dev/122 (DEC-078): Settings → Model training.
 *
 * Three states and no fourth:
 *
 * - **Unavailable** — one sentence naming the endpoint's own reason, and no
 *   controls. No disabled buttons pretending a feature exists.
 * - **Ready** — what would be sent (fixtures, rows, bytes, destination host,
 *   licences, and the ones excluded with their reasons), a consent control
 *   that must be ticked, and Start. When no fixture is approved yet the copy
 *   says that instead and offers nothing, because the corpus ships awaiting
 *   review.
 * - **A job exists** — its status with the time it was read, Cancel while
 *   cancellable, the trained model when there is one, the gate's verdict or
 *   the reason it is not satisfied, then Activate and, after activation,
 *   Rollback.
 *
 * The body mounts only while the disclosure is open (the dev/116 deviation,
 * reused deliberately): a closed section adds no fields, buttons or comboboxes
 * to the modal's accessibility tree. Nothing here polls on a timer — a
 * fine-tune runs for minutes to hours, so a status carries the time it was
 * read and Refresh is a button.
 */
export const ModelTrainingSection: React.FC<{ sharedGuest?: boolean }> = ({
  sharedGuest = false,
}) => {
  const [open, setOpen] = useState(false);
  const [capability, setCapability] = useState<TrainingCapability | null>(null);
  const [capabilityError, setCapabilityError] = useState<string | null>(null);
  const [preview, setPreview] = useState<TrainingPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [baseModel, setBaseModel] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCapability = useCallback(async (refresh: boolean) => {
    setCapabilityError(null);
    try {
      setCapability(await trainingApi.capability(refresh));
    } catch (e) {
      setCapabilityError(e instanceof Error ? e.message : "Could not ask this endpoint.");
    }
  }, []);

  const loadPreview = useCallback(async () => {
    setPreviewError(null);
    try {
      const next = await trainingApi.preview();
      setPreview(next);
      // Any change to what would be sent invalidates a tick: consent is for
      // one exact set (the digest is echoed on start).
      setConfirmed(false);
    } catch (e) {
      setPreview(null);
      setPreviewError(e instanceof Error ? e.message : "Could not build the training set.");
    }
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const listing = await trainingApi.list();
      setJob(listing.jobs[0] ?? null);
    } catch {
      // A listing that cannot be read is not an error worth a banner here; the
      // capability and preview states carry the information that matters.
      setJob(null);
    }
  }, []);

  useEffect(() => {
    if (!open || sharedGuest) return;
    void loadCapability(true);
    void loadJobs();
  }, [open, sharedGuest, loadCapability, loadJobs]);

  useEffect(() => {
    if (!open || sharedGuest) return;
    if (capability?.supported) void loadPreview();
  }, [open, sharedGuest, capability?.supported, loadPreview]);

  useEffect(() => {
    if (capability?.baseModels?.length && !baseModel) {
      setBaseModel(capability.baseModels[0]);
    }
  }, [capability?.baseModels, baseModel]);

  const run = useCallback(
    async (what: string, action: () => Promise<TrainingJob>) => {
      setBusy(what);
      setError(null);
      try {
        setJob(await action());
      } catch (e) {
        setError(e instanceof Error ? e.message : `Could not ${what}.`);
      } finally {
        setBusy(null);
      }
    },
    [],
  );

  const cancellable =
    job?.submitted && (job.status === "queued" || job.status === "running");
  const activatable = job?.status === "succeeded" && !job.activation.activatedAt;
  const rollbackable = Boolean(job?.activation.activatedAt && !job.activation.rolledBackAt);

  const body = (
    <div>
      <p className={styles.intro}>
        Fine-tunes the model this account uses on Curio's own approved example
        dataflows, so it plans in the shape the canvas accepts. The examples are
        sent as prompts and expected graph shapes; your data is not.
      </p>

      {sharedGuest ? (
        <p className={styles.warning}>
          Training is not available on the shared guest account.
        </p>
      ) : null}

      {capabilityError ? <p className={modal.error}>{capabilityError}</p> : null}

      {capability && !capability.supported ? (
        <>
          {/* The Unavailable state: the endpoint's own reason, and nothing
              else. There is no Start button to disable. */}
          <p className={styles.unavailable}>{capability.reason}</p>
          {capability.source === "remembered" && capability.seenAt ? (
            <p className={styles.seen}>
              Last asked {capability.seenAt}.{" "}
              <button
                type="button"
                className={modal.ghostBtn}
                onClick={() => void loadCapability(true)}
              >
                Ask again
              </button>
            </p>
          ) : null}
        </>
      ) : null}

      {capability?.supported ? (
        <>
          {previewError ? <p className={modal.error}>{previewError}</p> : null}

          {preview ? (
            <>
              <div className={modal.field}>
                <label className={modal.label} htmlFor="training-base-model">
                  Base model to train
                </label>
                <input
                  id="training-base-model"
                  className={modal.input}
                  type="text"
                  value={baseModel}
                  onChange={(e) => setBaseModel(e.target.value)}
                  placeholder={
                    capability.baseModels.length
                      ? capability.baseModels[0]
                      : "the base model to tune"
                  }
                  list={capability.baseModels.length ? "training-base-models" : undefined}
                />
                {capability.baseModels.length ? (
                  <datalist id="training-base-models">
                    {capability.baseModels.map((model) => (
                      <option key={model} value={model} />
                    ))}
                  </datalist>
                ) : (
                  <p className={styles.note}>
                    This endpoint did not say which models it can tune, so type
                    one.
                  </p>
                )}
              </div>

              <p className={styles.status}>
                {preview.consent.sentence} Examples:{" "}
                {preview.consent.fixtureIds.join(", ")}.
              </p>
              <p className={styles.note}>{preview.consent.note}</p>
              {preview.dataset.excluded.length ? (
                <ul className={styles.excluded}>
                  {preview.dataset.excluded.map((entry) => (
                    <li key={entry.fixtureId}>
                      {entry.fixtureId} — not included: {entry.reason}
                    </li>
                  ))}
                </ul>
              ) : null}

              <label className={styles.consent}>
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(e) => setConfirmed(e.target.checked)}
                  aria-describedby="training-consent-note"
                />
                <span id="training-consent-note">
                  Send these {preview.consent.rows} examples to{" "}
                  {preview.consent.destinationHost} to train {baseModel || "a model"}.
                  Your provider bills this run; Curio does not know its price.
                </span>
              </label>

              <div className={modal.buttonRow}>
                <button
                  type="button"
                  className={modal.primaryBtn}
                  disabled={!confirmed || !baseModel || busy !== null}
                  onClick={() =>
                    void run("start training", () =>
                      trainingApi.start({
                        baseModel,
                        rowsDigest: preview.consent.rowsDigest,
                        confirmed: true,
                      }),
                    )
                  }
                >
                  {busy === "start training" ? "Starting…" : "Start training"}
                </button>
                <button
                  type="button"
                  className={modal.ghostBtn}
                  onClick={() => void loadPreview()}
                >
                  Refresh the set
                </button>
              </div>
            </>
          ) : null}
        </>
      ) : null}

      {error ? <p className={modal.error}>{error}</p> : null}

      {job ? (
        <div className={styles.gate} role="status" aria-label="Training job">
          <p className={styles.status}>
            {job.status}
            {job.rawStatus && job.rawStatus !== job.status
              ? ` (${job.rawStatus})`
              : ""}
            {job.statusReadAt ? ` — read ${job.statusReadAt}` : ""}
            {job.consentedOnly ? " — consented, nothing was sent" : ""}
          </p>
          {job.error ? <p className={modal.error}>{job.error}</p> : null}
          {job.trainedModel ? (
            <p className={styles.status}>Trained model: {job.trainedModel}</p>
          ) : null}
          {job.usage.trainedTokens != null ? (
            <p className={styles.note}>
              {job.usage.trainedTokens} trained tokens, as the provider reported
              them.{" "}
              {job.cost
                ? `About $${job.cost.estimatedUsd} at the rate you supplied.`
                : "Curio has no price table, so no cost is shown."}
            </p>
          ) : null}
          {job.gate ? (
            <p className={styles.note}>
              {job.gate.satisfied
                ? `Evaluated on the held-out examples${
                    job.gate.meanScore != null
                      ? ` — mean score ${job.gate.meanScore}`
                      : ""
                  }. ${job.gate.note ?? ""}`
                : `Not evaluated yet: ${job.gate.reason ?? ""}`}
            </p>
          ) : null}
          {job.rollbackNote ? <p className={styles.note}>{job.rollbackNote}</p> : null}

          <div className={modal.buttonRow}>
            <button
              type="button"
              className={modal.ghostBtn}
              disabled={busy !== null}
              onClick={() => void run("refresh", () => trainingApi.status(job.jobId))}
            >
              Refresh
            </button>
            {cancellable ? (
              <button
                type="button"
                className={modal.ghostBtn}
                disabled={busy !== null}
                onClick={() => void run("cancel", () => trainingApi.cancel(job.jobId))}
                aria-describedby="training-cancel-note"
              >
                {busy === "cancel" ? "Cancelling…" : "Cancel"}
              </button>
            ) : null}
            {activatable ? (
              <button
                type="button"
                className={modal.primaryBtn}
                disabled={busy !== null || !job.gate?.satisfied}
                onClick={() => void run("activate", () => trainingApi.activate(job.jobId))}
                aria-describedby="training-activate-note"
              >
                {busy === "activate" ? "Activating…" : "Use this model"}
              </button>
            ) : null}
            {rollbackable ? (
              <button
                type="button"
                className={modal.ghostBtn}
                disabled={busy !== null}
                onClick={() => void run("roll back", () => trainingApi.rollback(job.jobId))}
                aria-describedby="training-rollback-note"
              >
                {busy === "roll back" ? "Rolling back…" : "Go back to the previous model"}
              </button>
            ) : null}
          </div>
          {cancellable ? (
            <p className={styles.note} id="training-cancel-note">
              Asks the provider to stop the job. Work already billed stays
              billed.
            </p>
          ) : null}
          {activatable ? (
            <p className={styles.note} id="training-activate-note">
              {job.gate?.satisfied
                ? "Points this account's agents at the trained model. The previous model is recorded so you can go back."
                : "Available once this model has been evaluated on the held-out examples."}
            </p>
          ) : null}
          {rollbackable ? (
            <p className={styles.note} id="training-rollback-note">
              Restores {job.activation.previousModel || "the deployment default"}.
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
      data-testid="model-training-section"
    >
      <summary className={styles.summary}>Model training</summary>
      {/* The body mounts only while open: a closed section adds no fields or
          buttons to the modal's accessibility tree (the dev/116 pattern). */}
      {open ? body : null}
    </details>
  );
};
