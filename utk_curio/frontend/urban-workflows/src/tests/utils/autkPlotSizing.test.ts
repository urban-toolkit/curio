/**
 * An Autark plot fills its pane where its document did not size it
 * (`utils/autkPlotSizing.ts`), the Vega-Lite node's rule. Before, autk-plot's
 * fixed 800 x 500 overflowed every node smaller than that.
 */
import { MIN_FITTED_PLOT_PX, fitPlotToPane } from "../../utils/autkPlotSizing";

const PANE = { width: 735.6, height: 480.2 };

describe("fitPlotToPane", () => {
  test("fills the pane where the document set no size", () => {
    const plot = { dataRef: "roads", mark: "bar", axis: ["sunlight"] };

    expect(fitPlotToPane(plot, PANE)).toEqual({ ...plot, width: 735, height: 480 });
  });

  test("keeps each size the document set", () => {
    expect(fitPlotToPane({ mark: "bar", width: 1200 }, PANE)).toEqual({
      mark: "bar",
      width: 1200,
      height: 480,
    });
    expect(fitPlotToPane({ mark: "bar", height: 300 }, PANE)).toEqual({
      mark: "bar",
      width: 735,
      height: 300,
    });
  });

  test("gives a pane smaller than the plot's margins the smallest plot, which scrolls", () => {
    expect(fitPlotToPane({ mark: "bar" }, { width: 180, height: 90 })).toEqual({
      mark: "bar",
      width: MIN_FITTED_PLOT_PX,
      height: MIN_FITTED_PLOT_PX,
    });
  });

  test("leaves a dimension the pane has not laid out yet to autk-plot", () => {
    expect(fitPlotToPane({ mark: "bar" }, { width: 0, height: 480 })).toEqual({
      mark: "bar",
      height: 480,
    });
  });

  test("leaves several plots alone, like a multi-view Vega-Lite spec", () => {
    const plots = [{ mark: "bar" }, { mark: "scatter" }];

    expect(fitPlotToPane(plots, PANE)).toBe(plots);
  });

  test("does not change the document's own plot", () => {
    const plot = { mark: "bar" };

    fitPlotToPane(plot, PANE);

    expect(plot).toEqual({ mark: "bar" });
  });
});
