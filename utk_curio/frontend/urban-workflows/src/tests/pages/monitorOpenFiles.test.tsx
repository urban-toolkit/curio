/**
 * The monitor's Open files card (pages/monitor/OpenFilesSection.tsx) and its
 * lines (pages/monitor/openFilesSeries.ts): each server's open files at every
 * hourly sample, a line per server in the palette's first two colours, and the
 * limit dashed on a log scale, one line when the servers share it, else one
 * per server. Where no sample counted a server's files, the card says why and
 * draws no chart.
 *
 * Vega does not draw under jsdom (monitorChartRole.test.tsx), so the chart
 * stands in as the Vega-Lite spec `linesOverTimeSpec` makes of what the card
 * hands it.
 */
import React from "react";
import { render, screen, within } from "@testing-library/react";

jest.mock("vega", () => ({}), { virtual: true });
jest.mock("vega-lite", () => ({}), { virtual: true });
jest.mock("../../pages/monitor/MonitorCharts", () => {
  const actual = jest.requireActual("../../pages/monitor/MonitorCharts");
  return {
    ...actual,
    LinesOverTime: (props: any) => (
      <div data-testid="lines-chart" aria-label={props.label} data-spec={JSON.stringify(actual.linesOverTimeSpec(props))} />
    ),
  };
});

import type { MonitorOpenFilesPayload, MonitorOpenFilesSample } from "../../api/monitorApi";
import { CATEGORICAL, LIMIT_INK } from "../../pages/monitor/chartColors";
import { OpenFilesSection } from "../../pages/monitor/OpenFilesSection";
import { limitsDiffer, openFilesLines } from "../../pages/monitor/openFilesSeries";

const LABEL = "Open files of the backend and the sandbox, every hour, against their limits";

function sample(at: string, backend: [number | null, number | null] | null,
                sandbox: [number | null, number | null] | null): MonitorOpenFilesSample {
  const counts = (pair: [number | null, number | null] | null) => (pair ? { open: pair[0], limit: pair[1] } : null);
  return { at, backend: counts(backend), sandbox: counts(sandbox) };
}

function payload(samples: MonitorOpenFilesSample[]): MonitorOpenFilesPayload {
  return {
    computedAt: "2026-11-06T17:02:00Z",
    startedAt: "2026-11-06T15:20:00Z",
    maxDays: 90,
    intervalSeconds: 3600,
    warnAbovePercent: 80,
    clearBelowPercent: 70,
    samples,
  };
}

const SHARED = payload([
  sample("2026-11-06T15:20:07Z", [212, 65536], [96, 65536]),
  sample("2026-11-06T16:20:07Z", [230, 65536], [101, 65536]),
]);

/** The spec of the chart the card drew. */
function drawnSpec(): any {
  const chart = screen.getByTestId("lines-chart");
  expect(chart).toHaveAttribute("aria-label", LABEL);
  return JSON.parse(chart.getAttribute("data-spec") as string);
}

/** Each line's values, in the order the rows hold them. */
function valuesByLine(spec: any): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  for (const row of spec.data.values) (out[row.line] ??= []).push(row.files);
  return out;
}

describe("the Open files card", () => {
  test("is headed Open files and draws a line per server and their shared limit, dashed, on a log scale", () => {
    render(<OpenFilesSection payload={SHARED} />);
    expect(screen.getByRole("heading", { name: "Open files" })).toBeInTheDocument();

    const spec = drawnSpec();
    expect(spec.encoding.color.scale).toEqual({
      domain: ["Backend", "Sandbox", "Limit"],
      range: [CATEGORICAL[0], CATEGORICAL[1], LIMIT_INK],
    });
    // Only the limit is dashed.
    expect(spec.encoding.strokeDash.scale).toEqual({
      domain: ["Backend", "Sandbox", "Limit"],
      range: [[1, 0], [1, 0], [6, 4]],
    });
    // Ticked at each power of ten, so a few hundred files and 65,536 both read.
    expect(spec.encoding.y).toMatchObject({
      field: "files", scale: { type: "log" }, axis: { values: [10, 100, 1000, 10000, 100000], tickCount: 5 },
    });
    expect(valuesByLine(spec)).toEqual({ Backend: [212, 230], Sandbox: [96, 101], Limit: [65536, 65536] });
    // From the first sample to now.
    expect(spec.encoding.x.scale).toEqual({
      domain: [Date.parse("2026-11-06T15:20:07Z"), Date.parse("2026-11-06T17:02:00Z")],
    });
    // Two samples draw lines between them, with no dot on each.
    expect(spec.mark.point).toBeUndefined();

    expect(screen.getByTestId("monitor-open-files-last")).toHaveTextContent(
      /backend 230 of 65,536 · sandbox 101 of 65,536\.$/
    );
  });

  test("draws each server's own limit in its colour when the two differ", () => {
    render(
      <OpenFilesSection
        payload={payload([
          sample("2026-11-06T15:20:07Z", [212, 65536], [96, 1024]),
          sample("2026-11-06T16:20:07Z", [230, 65536], null),
        ])}
      />
    );
    const spec = drawnSpec();
    expect(spec.encoding.color.scale).toEqual({
      domain: ["Backend", "Sandbox", "Backend limit", "Sandbox limit"],
      range: [CATEGORICAL[0], CATEGORICAL[1], CATEGORICAL[0], CATEGORICAL[1]],
    });
    expect(spec.encoding.strokeDash.scale.range).toEqual([[1, 0], [1, 0], [6, 4], [6, 4]]);
    expect(valuesByLine(spec)).toEqual({
      Backend: [212, 230],
      Sandbox: [96],
      "Backend limit": [65536, 65536],
      "Sandbox limit": [1024],
    });
    expect(screen.getByTestId("monitor-open-files-last")).toHaveTextContent(
      /backend 230 of 65,536 · sandbox not answering\.$/
    );
  });

  test("where the platform cannot list open files, says so and draws no chart", () => {
    render(<OpenFilesSection payload={payload([sample("2026-11-06T15:20:07Z", [null, null], [null, null])])} />);
    const card = screen.getByTestId("monitor-open-files");
    expect(within(card).getByRole("heading", { name: "Open files" })).toBeInTheDocument();
    expect(within(card).getByText("This platform cannot list a process's open files.")).toBeInTheDocument();
    expect(within(card).queryByTestId("lines-chart")).not.toBeInTheDocument();
    expect(screen.getByTestId("monitor-open-files-last")).toHaveTextContent(
      /backend not counted · sandbox not counted\.$/
    );
  });

  test("before the first sample, says when it comes and draws no chart", () => {
    render(<OpenFilesSection payload={payload([])} />);
    expect(
      screen.getByText("No sample yet: the backend takes one as it starts, then one every hour.")
    ).toBeInTheDocument();
    expect(screen.queryByTestId("lines-chart")).not.toBeInTheDocument();
    expect(screen.queryByTestId("monitor-open-files-last")).not.toBeInTheDocument();
  });

  test("while its first read is on the way, says it is loading", () => {
    render(<OpenFilesSection payload={null} />);
    expect(screen.getByRole("heading", { name: "Open files" })).toBeInTheDocument();
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  test("with one sample, the first hour after a start, draws each line's point as a dot", () => {
    const one = payload([sample("2026-11-06T15:20:07Z", [212, 65536], [96, 65536])]);
    render(<OpenFilesSection payload={{ ...one, computedAt: "2026-11-06T15:25:00Z" }} />);
    const spec = drawnSpec();
    expect(spec.mark.point).toBeTruthy();
    expect(valuesByLine(spec)).toEqual({ Backend: [212], Sandbox: [96], Limit: [65536] });
    // Up to the hour after the sample, when the next one comes.
    expect(spec.encoding.x.scale).toEqual({
      domain: [Date.parse("2026-11-06T15:20:07Z"), Date.parse("2026-11-06T16:20:07Z")],
    });
  });
});

describe("the lines", () => {
  test("a sandbox that did not answer leaves only its point out", () => {
    const lines = openFilesLines(payload([
      sample("2026-11-06T15:20:07Z", [212, 65536], null),
      sample("2026-11-06T16:20:07Z", [230, 65536], [101, 65536]),
    ]));
    expect(lines.counted).toBe(true);
    expect(lines.points).toEqual([
      { t: Date.parse("2026-11-06T15:20:07Z"), line: "Backend", files: 212 },
      { t: Date.parse("2026-11-06T15:20:07Z"), line: "Limit", files: 65536 },
      { t: Date.parse("2026-11-06T16:20:07Z"), line: "Backend", files: 230 },
      { t: Date.parse("2026-11-06T16:20:07Z"), line: "Sandbox", files: 101 },
      { t: Date.parse("2026-11-06T16:20:07Z"), line: "Limit", files: 65536 },
    ]);
    expect(lines.dashed).toEqual(["Limit"]);
  });

  test("the limits differ only where a sample has both and they are not the same", () => {
    expect(limitsDiffer(SHARED.samples)).toBe(false);
    expect(limitsDiffer([sample("2026-11-06T15:20:07Z", [212, 65536], null)])).toBe(false);
    expect(limitsDiffer([sample("2026-11-06T15:20:07Z", [212, 65536], [96, null])])).toBe(false);
    expect(limitsDiffer([sample("2026-11-06T15:20:07Z", [212, 1024], [96, 65536])])).toBe(true);
  });

  test("no count in any sample is nothing to draw", () => {
    const lines = openFilesLines(payload([sample("2026-11-06T15:20:07Z", [null, 1024], null)]));
    expect(lines).toEqual({ points: [], colors: { domain: [], range: [] }, dashed: [], counted: false });
  });
});
