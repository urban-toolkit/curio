import React, { useMemo, useState } from "react";

import type { MonitorLlmPayload, MonitorUsagePayload, MonitorUsageView, MonitorWindow } from "../../api/monitorApi";
import { formatCount, formatExactCount, formatMs } from "../../utils/diagnosticsBundle";
import { LinesOverTime, type TimeMark } from "./MonitorCharts";
import { LlmPerformanceSection, exactMs } from "./LlmPerformanceSection";
import { StatTile } from "./StatTile";
import {
  FIRST_WINDOW,
  MARKED_WINDOWS,
  MEASURES,
  SESSION_LINES,
  WINDOWS,
  chartSpan,
  deployMarks,
  hasLonePoint,
  lastDay,
  lineColors,
  measureLines,
  measurePoints,
  pointValue,
  sessionPoints,
  type CombinedStats,
  type UsageField,
  type WindowOption,
} from "./usageSeries";
import styles from "./MonitorPage.module.css";

const NO_MARKS: TimeMark[] = [];
const SESSION_COLORS = lineColors([SESSION_LINES.accounts, SESSION_LINES.guests]);

/** A tile of the last 24 hours' work: its count, its average and its failures. */
const WorkTile: React.FC<{ label: string; stats: CombinedStats | undefined }> = ({ label, stats }) => (
  <StatTile
    label={label}
    value={stats ? formatCount(stats.count) : "n/a"}
    sub={
      stats
        ? `average ${formatMs(stats.averageMs)}${stats.failed > 0 ? ` · ${formatCount(stats.failed)} failed` : ""}`
        : undefined
    }
  />
);

/**
 * One chart of every measure that counted something in the window: each
 * step's average time, 95th percentile time or count (*field*), a line per
 * measure, on a log scale, so a few agent turns and thousands of requests
 * both read, the deploys marked.
 */
const MeasureChart: React.FC<{
  title: string;
  field: UsageField;
  valueTitle: string;
  view: MonitorUsageView | null;
  shown: WindowOption;
  marks: TimeMark[];
}> = ({ title, field, valueTitle, view, shown, marks }) => {
  const lines = useMemo(() => (view ? measureLines(view) : []), [view]);
  const points = useMemo(() => (view ? measurePoints(view, field, lines) : []), [view, field, lines]);
  const colors = useMemo(() => lineColors(lines), [lines]);
  let chart: React.ReactNode;
  if (!view) {
    chart = <p className={styles.empty}>Loading…</p>;
  } else if (lines.length === 0) {
    chart = <p className={styles.empty}>Nothing counted in the {shown.span}.</p>;
  } else {
    chart = (
      <LinesOverTime
        rows={points}
        timeField="t"
        valueField="value"
        seriesField="line"
        valueTitle={valueTitle}
        seriesTitle="measure"
        timeFormat={shown.timeFormat}
        timeDomain={chartSpan(view)}
        colors={colors}
        logY
        durations={field !== "count"}
        points={hasLonePoint(points, pointValue)}
        marks={marks}
        markTitle="version"
        label={`${title} by measure, ${shown.span}`}
      />
    );
  }
  return (
    <div className={styles.card}>
      <h3 className={styles.subHeading}>{title}</h3>
      {chart}
    </div>
  );
};

/** The sessions seen at each step of the window: sign-ins of accounts and of guests. */
const SessionsChart: React.FC<{ view: MonitorUsageView | null; shown: WindowOption; marks: TimeMark[] }> = ({
  view,
  shown,
  marks,
}) => {
  const points = useMemo(() => (view ? sessionPoints(view) : []), [view]);
  let chart: React.ReactNode;
  if (!view) {
    chart = <p className={styles.empty}>Loading…</p>;
  } else if (view.sessions.length === 0) {
    chart = (
      <p className={styles.empty}>
        No sample in the {shown.span}: the backend counts the sessions seen after every 5 minutes.
      </p>
    );
  } else {
    chart = (
      <LinesOverTime
        rows={points}
        timeField="t"
        valueField="value"
        seriesField="line"
        valueTitle="sessions"
        seriesTitle="signed in as"
        timeFormat={shown.timeFormat}
        timeDomain={chartSpan(view)}
        colors={SESSION_COLORS}
        points={hasLonePoint(points, pointValue)}
        marks={marks}
        markTitle="version"
        label={`Sessions seen, accounts and guests, ${shown.span}`}
      />
    );
  }
  return (
    <div className={styles.card}>
      <h3 className={styles.subHeading}>Sessions seen</h3>
      {chart}
    </div>
  );
};

/** The By measure table: each measure's work over the window. */
const MeasureTable: React.FC<{ payload: MonitorUsagePayload | null; view: MonitorUsageView | null }> = ({
  payload,
  view,
}) => {
  const stats = new Map((view?.measures ?? []).map((each) => [each.key, each]));
  return (
    <div className={`${styles.card} ${styles.spaced}`}>
      <h3 className={styles.subHeading}>By measure</h3>
      <div className={styles.tableScroll}>
        <table className={`${styles.table} ${styles.tokenTable}`} data-testid="monitor-usage-measures">
          <thead>
            <tr>
              <th scope="col">Measure</th>
              <th scope="col" className={styles.num}>Count</th>
              <th scope="col" className={styles.num}>Failed</th>
              <th scope="col" className={styles.num}>Average</th>
              <th scope="col" className={styles.num}>95th percentile</th>
            </tr>
          </thead>
          <tbody>
            {view
              ? MEASURES.map((measure) => {
                  const each = stats.get(measure.key);
                  const count = each?.count ?? 0;
                  const failed = each?.failed ?? 0;
                  return (
                    <tr key={measure.key} data-measure={measure.key}>
                      <td>
                        <span className={styles.swatch} style={{ background: measure.color }} aria-hidden="true" />
                        {measure.label}
                      </td>
                      <td className={styles.num} data-tooltip={`${formatExactCount(count)} ${measure.noun}`}>
                        {formatCount(count)}
                      </td>
                      <td
                        className={styles.num}
                        data-tooltip={`${formatExactCount(failed)} of ${formatExactCount(count)} ${measure.noun} failed`}
                      >
                        {formatCount(failed)}
                      </td>
                      <td className={styles.num} data-tooltip={exactMs(each?.averageMs ?? null)}>
                        {formatMs(each?.averageMs)}
                      </td>
                      <td className={styles.num} data-tooltip={exactMs(each?.p95Ms ?? null)}>
                        {formatMs(each?.p95Ms)}
                      </td>
                    </tr>
                  );
                })
              : (
                <tr>
                  <td colSpan={5} className={styles.empty}>
                    Loading…
                  </td>
                </tr>
              )}
          </tbody>
        </table>
      </div>
      {payload ? (
        <p className={styles.caption} data-testid="monitor-usage-kept">
          The last {payload.maxDays} days are kept across restarts. A node run is a node's code run by Play or by
          a run on the server; a Run All run is a dataflow's run on the server, a dashboard viewer's among them;
          a request is the backend's answer to a page, the monitor's own, streams and files left out.
        </p>
      ) : null}
    </div>
  );
};

/**
 * The monitor's Usage tab: what this Curio did for the people using it, kept
 * across restarts. Its switch shows the last 24 hours in 5-minute steps, 7
 * days in hourly steps (first) or 90 days in daily steps, for every chart and
 * table of the tab, the LLM performance section's included; the tiles always
 * give the last 24 hours. Each chart of 24 hours or 7 days marks the deploys.
 */
export const MonitorUsage: React.FC<{ usage: MonitorUsagePayload | null; llm: MonitorLlmPayload | null }> = ({
  usage,
  llm,
}) => {
  const [shownKey, setShownKey] = useState<MonitorWindow>(FIRST_WINDOW);
  const shown = WINDOWS.find((each) => each.key === shownKey) ?? WINDOWS[0];
  const view = usage?.views[shown.key] ?? null;
  const marks = useMemo(
    () => (view && MARKED_WINDOWS.includes(shown.key) ? deployMarks(view.deploys) : NO_MARKS),
    [view, shown.key]
  );
  const day = usage ? lastDay(usage) : null;
  const sessions = day?.sessions;

  return (
    <>
      <div className={styles.switchRow}>
        <div className={styles.switch} role="group" aria-label="Window of the charts and the tables">
          {WINDOWS.map((each) => (
            <button
              key={each.key}
              type="button"
              className={styles.switchButton}
              aria-pressed={each.key === shown.key}
              onClick={() => setShownKey(each.key)}
            >
              {each.label}
            </button>
          ))}
        </div>
      </div>

      <section className={styles.section} aria-labelledby="mon-activity">
        <h2 id="mon-activity" className={styles.heading}>
          Activity
        </h2>
        <div className={styles.tileGrid} data-testid="monitor-usage">
          <StatTile
            label="Sessions seen, 24 hours"
            value={sessions ? formatCount(sessions.accounts + sessions.guests) : "n/a"}
            sub={
              sessions
                ? `${formatCount(sessions.accounts)} accounts · ${formatCount(sessions.guests)} guests`
                : undefined
            }
          />
          <WorkTile label="Node runs, 24 hours" stats={day?.nodes} />
          <WorkTile label="Agent turns, 24 hours" stats={day?.turns} />
          <WorkTile label="Run All runs, 24 hours" stats={day?.runs} />
          <WorkTile label="Requests, 24 hours" stats={day?.requests} />
        </div>
        <div className={styles.split}>
          <SessionsChart view={view} shown={shown} marks={marks} />
          <MeasureChart title="Count" field="count" valueTitle="count" view={view} shown={shown} marks={marks} />
          <MeasureChart
            title="Average time"
            field="averageMs"
            valueTitle="average time"
            view={view}
            shown={shown}
            marks={marks}
          />
          <MeasureChart
            title="95th percentile time"
            field="p95Ms"
            valueTitle="95th percentile time"
            view={view}
            shown={shown}
            marks={marks}
          />
        </div>
        <MeasureTable payload={usage} view={view} />
      </section>

      <section className={styles.section} aria-labelledby="mon-llm-performance">
        <h2 id="mon-llm-performance" className={styles.heading}>
          LLM performance
        </h2>
        <LlmPerformanceSection payload={llm} shown={shown} marks={marks} />
      </section>
    </>
  );
};

export default MonitorUsage;
