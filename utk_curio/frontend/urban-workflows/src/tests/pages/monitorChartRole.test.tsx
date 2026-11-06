/**
 * A monitor chart keeps its role and its name once Vega has drawn it
 * (pages/monitor/MonitorCharts.tsx). Vega makes the element it draws into a
 * "graphics-document" named "Vega visualization" (vega-view's
 * initializeAria). A chart whose role="img" and aria-label sat on that element
 * lost both at its first draw: every chart on the monitor was a "Vega
 * visualization" to a screen reader, and the e2e test's `[role="img"] svg`
 * found no chart.
 *
 * Vega is the build the app bundles, drawing SVG into jsdom. Vega-Lite's build
 * reads `structuredClone`, which jsdom's window does not have, so its compile
 * hands Vega a spec of one bar and no text: what Vega does to its element does
 * not depend on the spec. The monitor's own specs are drawn by the e2e test
 * (test_monitor_page_e2e.py).
 */
import React from "react";
import { render, screen, waitFor } from "@testing-library/react";

jest.mock("vega", () => require(require("path").resolve(__dirname, "../../../node_modules/vega/build/vega.js")), {
  virtual: true,
});
jest.mock(
  "vega-lite",
  () => ({
    compile: () => ({
      spec: {
        width: 120,
        height: 40,
        padding: 0,
        autosize: "none",
        marks: [
          {
            type: "rect",
            encode: {
              enter: {
                x: { value: 0 },
                y: { value: 0 },
                width: { value: 60 },
                height: { value: 20 },
                fill: { value: "#2a78d6" },
              },
            },
          },
        ],
      },
    }),
  }),
  { virtual: true },
);

import { DurationHistogram, LinesOverTime } from "../../pages/monitor/MonitorCharts";

/** The image named *label*, once it holds the SVG Vega drew in an element of its own. */
async function drawnChart(label: string): Promise<HTMLElement> {
  const image = await screen.findByRole("img", { name: label });
  await waitFor(() => expect(image.querySelector("svg.marks")).not.toBeNull());
  // Vega's own element, inside the image: the one it renamed.
  expect(image.querySelector("svg.marks")?.parentElement?.getAttribute("role")).toBe("graphics-document");
  return image;
}

test("the lines over time keep their role and their name once Vega has drawn them", async () => {
  const label = "Input tokens per hour by model, last 7 days";
  render(
    <LinesOverTime
      rows={[
        { t: 0, line: "gemma4 (Curio)", tokens: 120 },
        { t: 3600000, line: "gemma4 (Curio)", tokens: 0 },
      ]}
      timeField="t"
      valueField="tokens"
      seriesField="line"
      valueTitle="input tokens"
      label={label}
    />,
  );
  await drawnChart(label);
});

test("a histogram keeps its role and its name once Vega has drawn it", async () => {
  render(
    <DurationHistogram
      buckets={[
        { leMs: 100, count: 2 },
        { leMs: null, count: 1 },
      ]}
    />,
  );
  await drawnChart("Distribution of node execution times");
});
