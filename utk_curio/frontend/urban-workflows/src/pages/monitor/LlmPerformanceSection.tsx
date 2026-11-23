import React, { useMemo } from "react";

import type { MonitorLlmModel, MonitorLlmPayload } from "../../api/monitorApi";
import { formatCount, formatExactCount, formatMs, formatRate } from "../../utils/diagnosticsBundle";
import { LinesOverTime, type TimeMark } from "./MonitorCharts";
import {
  hasLonePoint,
  lineColors,
  modelLines,
  responseTimes,
  type ModelLine,
  type ResponsePoint,
} from "./llmPerformanceSeries";
import { chartSpan, type WindowOption } from "./usageSeries";
import { StatTile } from "./StatTile";
import styles from "./MonitorPage.module.css";

const NO_LINES = new Map<string, ModelLine>();
const NO_POINTS: ResponsePoint[] = [];

/** A time cell's exact milliseconds, its Curio tooltip; none without a time. */
export function exactMs(ms: number | null): string | undefined {
  return ms == null ? undefined : `${formatExactCount(ms)} ms`;
}

/**
 * The performance of this Curio's own LLM models, kept across restarts: the
 * last 24 hours as tiles, then each model's average response time as a chart
 * and its numbers in a table, both over the window the Usage tab's switch
 * shows (*shown*): 24 hours in 5-minute steps, 7 days in hourly steps or 90
 * days in daily steps, with the deploys marked (*marks*). The table also
 * names the chart's lines.
 */
export const LlmPerformanceSection: React.FC<{
  payload: MonitorLlmPayload | null;
  shown: WindowOption;
  marks?: TimeMark[];
}> = ({ payload, shown, marks }) => {
  const view = payload?.views[shown.key] ?? null;
  const lines = useMemo(() => (view ? modelLines(view) : NO_LINES), [view]);
  const colors = useMemo(() => lineColors(lines), [lines]);
  const points = useMemo(() => (view ? responseTimes(view, lines) : NO_POINTS), [view, lines]);
  const day = payload?.views["24h"].all;
  const week = payload?.views["7d"].all;
  const models: MonitorLlmModel[] = view?.models ?? [];
  const none = `No LLM requests in the ${shown.span}.`;

  let chart: React.ReactNode;
  if (!view) {
    chart = <p className={styles.empty}>Loading…</p>;
  } else if (view.rows.length === 0) {
    chart = <p className={styles.empty}>{none}</p>;
  } else {
    chart = (
      <LinesOverTime
        rows={points}
        timeField="t"
        valueField="averageMs"
        seriesField="line"
        valueTitle="average response time"
        seriesTitle="model"
        timeFormat={shown.timeFormat}
        timeDomain={chartSpan(view)}
        colors={colors}
        durations
        points={hasLonePoint(points)}
        marks={marks}
        markTitle="version"
        label={`Average response time by model, ${shown.span}`}
      />
    );
  }

  return (
    <div data-testid="monitor-llm-performance">
      <div className={styles.tileGrid}>
        <StatTile
          label="Requests, 24 hours"
          value={day ? formatCount(day.requests) : "n/a"}
          sub={day && week ? `${formatCount(day.failed)} failed · ${formatCount(week.requests)} in 7 days` : undefined}
        />
        <StatTile
          label="Average response time, 24 hours"
          value={formatMs(day?.averageMs)}
          sub={day?.p95Ms != null ? `95th percentile ${formatMs(day.p95Ms)}` : undefined}
        />
        <StatTile
          label="Output tokens per second, 24 hours"
          value={formatRate(day?.tokensPerSecond)}
          sub={day?.firstTokenMs != null ? `first token in ${formatMs(day.firstTokenMs)}` : undefined}
        />
      </div>

      <div className={`${styles.card} ${styles.spaced}`}>
        <h3 className={styles.subHeading}>Average response time</h3>
        {chart}
      </div>

      <div className={`${styles.card} ${styles.spaced}`}>
        <h3 className={styles.subHeading}>By model</h3>
        <div className={styles.tableScroll}>
          <table className={`${styles.table} ${styles.tokenTable}`} data-testid="monitor-llm-models">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col" className={styles.num}>Requests</th>
                <th scope="col" className={styles.num}>Failed</th>
                <th scope="col" className={styles.num}>Average</th>
                <th scope="col" className={styles.num}>95th percentile</th>
                <th scope="col" className={styles.num}>First token</th>
                <th scope="col" className={styles.num}>Tokens per second</th>
              </tr>
            </thead>
            <tbody>
              {models.map((entry) => {
                const line = lines.get(entry.model);
                return (
                  <tr key={entry.model} data-model={entry.model}>
                    <td>
                      <span
                        className={styles.swatch}
                        style={line ? { background: line.color } : undefined}
                        aria-hidden="true"
                      />
                      {entry.model}
                    </td>
                    <td className={styles.num} data-tooltip={`${formatExactCount(entry.requests)} requests`}>
                      {formatCount(entry.requests)}
                    </td>
                    <td
                      className={styles.num}
                      data-tooltip={`${formatExactCount(entry.failed)} of ${formatExactCount(entry.requests)} requests failed`}
                    >
                      {formatCount(entry.failed)}
                    </td>
                    <td className={styles.num} data-tooltip={exactMs(entry.averageMs)}>
                      {formatMs(entry.averageMs)}
                    </td>
                    <td className={styles.num} data-tooltip={exactMs(entry.p95Ms)}>
                      {formatMs(entry.p95Ms)}
                    </td>
                    <td className={styles.num} data-tooltip={exactMs(entry.firstTokenMs)}>
                      {formatMs(entry.firstTokenMs)}
                    </td>
                    <td className={styles.num}>{formatRate(entry.tokensPerSecond)}</td>
                  </tr>
                );
              })}
              {models.length === 0 ? (
                <tr>
                  <td colSpan={7} className={styles.empty}>
                    {payload ? none : "Loading…"}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {payload ? (
          <p className={styles.caption} data-testid="monitor-llm-kept">
            This Curio's own models, the last {payload.maxDays} days, kept across restarts. A request on a key a
            user set for their own is not counted.
          </p>
        ) : null}
      </div>
    </div>
  );
};

export default LlmPerformanceSection;
