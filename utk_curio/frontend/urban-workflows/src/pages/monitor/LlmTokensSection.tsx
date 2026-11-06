import React, { useMemo } from "react";

import type { MonitorLlmCounts, MonitorLlmPayload } from "../../api/monitorApi";
import { formatCount, formatExactCount } from "../../utils/diagnosticsBundle";
import { LinesOverTime } from "./MonitorCharts";
import {
  endpointLabel,
  lineColors,
  modelKey,
  sumOf,
  tokenLines,
  tokensPerHour,
  type TokenLine,
  type TokenPoint,
} from "./llmSeries";
import { StatTile } from "./StatTile";
import styles from "./MonitorPage.module.css";

const NO_LINES = new Map<string, TokenLine>();
const NO_POINTS: TokenPoint[] = [];

function inAndOut(counts: MonitorLlmCounts): string {
  return `${formatCount(counts.inputTokens)} in · ${formatCount(counts.outputTokens)} out`;
}

function exactly(counts: MonitorLlmCounts): string {
  return `${formatExactCount(counts.inputTokens)} input tokens, ${formatExactCount(
    counts.outputTokens
  )} output tokens, ${formatExactCount(counts.requests)} requests`;
}

/**
 * The monitor's LLM tokens, since the backend started: the last 24 hours as
 * tiles, each model's input and output tokens per hour over the last 7 days
 * as two charts, and each model's totals in a table, which also names the
 * lines' models and their numbers.
 */
export const LlmTokensSection: React.FC<{ payload: MonitorLlmPayload | null }> = ({ payload }) => {
  const lines = useMemo(() => (payload ? tokenLines(payload) : NO_LINES), [payload]);
  const colors = useMemo(() => lineColors(lines), [lines]);
  const input = useMemo(
    () => (payload ? tokensPerHour(payload, "inputTokens", lines) : NO_POINTS),
    [payload, lines]
  );
  const output = useMemo(
    () => (payload ? tokensPerHour(payload, "outputTokens", lines) : NO_POINTS),
    [payload, lines]
  );
  const models = payload?.models ?? [];
  const day = sumOf(models, "last24h");
  const dayOnCurio = sumOf(models.filter((entry) => entry.curio), "last24h");
  const week = sumOf(models, "last7d");
  const hours: [number, number] | undefined = payload
    ? [Date.parse(payload.hourlyFrom), Date.parse(payload.hourlyTo)]
    : undefined;

  const chart = (points: TokenPoint[], valueTitle: string, label: string) => {
    if (!payload) return <p className={styles.empty}>Loading…</p>;
    if (payload.hourly.length === 0) {
      return <p className={styles.empty}>No LLM requests in the last 7 days.</p>;
    }
    return (
      <LinesOverTime
        rows={points}
        timeField="t"
        valueField="tokens"
        seriesField="line"
        valueTitle={valueTitle}
        seriesTitle="model"
        timeFormat="%b %-d, %H:00"
        timeDomain={hours}
        colors={colors}
        label={label}
      />
    );
  };

  return (
    <div data-testid="monitor-llm-tokens">
      <div className={styles.tileGrid}>
        <StatTile
          label="Input tokens, 24 hours"
          value={payload ? formatCount(day.inputTokens) : "n/a"}
          sub={payload ? `${formatCount(dayOnCurio.inputTokens)} on Curio's endpoint` : undefined}
        />
        <StatTile
          label="Output tokens, 24 hours"
          value={payload ? formatCount(day.outputTokens) : "n/a"}
          sub={payload ? `${formatCount(dayOnCurio.outputTokens)} on Curio's endpoint` : undefined}
        />
        <StatTile
          label="Requests, 24 hours"
          value={payload ? formatCount(day.requests) : "n/a"}
          sub={payload ? `${formatCount(week.requests)} in 7 days` : undefined}
        />
      </div>

      <div className={styles.split}>
        <div className={styles.card}>
          <h3 className={styles.subHeading}>Input tokens per hour</h3>
          {chart(input, "input tokens", "Input tokens per hour by model, last 7 days")}
        </div>
        <div className={styles.card}>
          <h3 className={styles.subHeading}>Output tokens per hour</h3>
          {chart(output, "output tokens", "Output tokens per hour by model, last 7 days")}
        </div>
      </div>

      <div className={`${styles.card} ${styles.spaced}`}>
        <h3 className={styles.subHeading}>By model</h3>
        <div className={styles.tableScroll}>
          <table className={`${styles.table} ${styles.tokenTable}`} data-testid="monitor-llm-models">
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Endpoint</th>
                <th scope="col" className={styles.num}>24 hours</th>
                <th scope="col" className={styles.num}>7 days</th>
                <th scope="col" className={styles.num}>All kept</th>
                <th scope="col" className={styles.num}>Requests</th>
              </tr>
            </thead>
            <tbody>
              {models.map((entry) => {
                const key = modelKey(entry.model, entry.curio);
                const line = lines.get(key);
                return (
                  <tr key={key} data-model={entry.model} data-endpoint={entry.curio ? "curio" : "own"}>
                    <td>
                      <span
                        className={styles.swatch}
                        style={line ? { background: line.color } : undefined}
                        aria-hidden="true"
                      />
                      {entry.model}
                    </td>
                    <td>{endpointLabel(entry.curio)}</td>
                    <td className={styles.num} data-tooltip={exactly(entry.last24h)}>
                      {inAndOut(entry.last24h)}
                    </td>
                    <td className={styles.num} data-tooltip={exactly(entry.last7d)}>
                      {inAndOut(entry.last7d)}
                    </td>
                    <td className={styles.num} data-tooltip={exactly(entry.kept)}>
                      {inAndOut(entry.kept)}
                    </td>
                    <td className={styles.num}>{formatCount(entry.kept.requests)}</td>
                  </tr>
                );
              })}
              {models.length === 0 ? (
                <tr>
                  <td colSpan={6} className={styles.empty}>
                    {payload ? "No LLM requests since the backend started." : "Loading…"}
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        {payload ? (
          <p className={styles.caption}>
            Since the backend started, {new Date(payload.startedAt).toLocaleString()}, and at most
            the last {payload.maxDays} days.
          </p>
        ) : null}
      </div>
    </div>
  );
};

export default LlmTokensSection;
