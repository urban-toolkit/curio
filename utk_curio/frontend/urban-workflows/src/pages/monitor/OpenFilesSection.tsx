import React, { useMemo } from "react";

import type { MonitorOpenFilesPayload } from "../../api/monitorApi";
import { formatOpenFiles } from "../../utils/diagnosticsBundle";
import { LinesOverTime } from "./MonitorCharts";
import { openFilesLines, SERVERS } from "./openFilesSeries";
import { deployMarks } from "./usageSeries";
import styles from "./MonitorPage.module.css";

/**
 * The chart's span: from the first sample to now, and at least to the hour
 * after the first sample, when the next one comes.
 */
function timeSpan(payload: MonitorOpenFilesPayload): [number, number] | undefined {
  const first = Date.parse(payload.samples[0]?.at ?? "");
  const end = Math.max(Date.parse(payload.computedAt), first + payload.intervalSeconds * 1000);
  return Number.isNaN(first) || Number.isNaN(end) ? undefined : [first, end];
}

/**
 * Each server's open files, sampled every hour over the last 90 days, kept
 * across restarts, against its limit: a line per server and the limit dashed,
 * on a log scale, so a count of a few hundred and a limit of tens of thousands
 * both read, and each deploy marked with its version. The last sample's
 * counts are written under it.
 */
export const OpenFilesSection: React.FC<{ payload: MonitorOpenFilesPayload | null }> = ({ payload }) => {
  const lines = useMemo(() => (payload ? openFilesLines(payload) : null), [payload]);
  const marks = useMemo(() => deployMarks(payload?.deploys), [payload]);
  const samples = payload?.samples ?? [];
  const last = samples[samples.length - 1];
  // A sample of a start of several backend processes names the busiest one.
  const ofSeveral = samples.some((sample) => sample.backendProcess !== undefined);

  let body: React.ReactNode;
  if (!payload) {
    body = <p className={styles.empty}>Loading…</p>;
  } else if (samples.length === 0) {
    body = <p className={styles.empty}>No sample yet: the backend takes one as it starts, then one every hour.</p>;
  } else if (!lines?.counted) {
    body = <p className={styles.empty}>This platform cannot list a process's open files.</p>;
  } else {
    // The first hour after a start holds one sample, and a line of one point
    // draws nothing but its dot.
    body = (
      <LinesOverTime
        rows={lines.points}
        timeField="t"
        valueField="files"
        seriesField="line"
        valueTitle="files"
        seriesTitle="line"
        timeDomain={timeSpan(payload)}
        colors={lines.colors}
        logY
        dashed={lines.dashed}
        points={samples.length === 1}
        marks={marks}
        markTitle="version"
        label="Open files of the backend and the sandbox, every hour, against their limits"
      />
    );
  }

  return (
    <div className={`${styles.card} ${styles.spaced}`} data-testid="monitor-open-files">
      <h3 className={styles.subHeading}>Open files</h3>
      {body}
      {last ? (
        <p className={styles.caption} data-testid="monitor-open-files-last">
          Last sample, {new Date(last.at).toLocaleString()}:{" "}
          {SERVERS.map((server) => formatOpenFiles(server, last[server])).join(" · ")}.
        </p>
      ) : null}
      {payload ? (
        <p className={styles.caption} data-testid="monitor-open-files-kept">
          A sample every hour, the last {payload.maxDays} days, kept across restarts. A server above{" "}
          {payload.warnAbovePercent}% of its limit adds an entry to Recent errors.
        </p>
      ) : null}
      {ofSeveral ? (
        <p className={styles.caption} data-testid="monitor-open-files-processes">
          With several backend processes, the backend line is the busiest one in each hour, against that
          process's own limit.
        </p>
      ) : null}
    </div>
  );
};

export default OpenFilesSection;
