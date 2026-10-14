/**
 * The dashboard's own settings (`dataflow.dashboard`): where its Run button
 * stands, read and written the same way by the load and the save.
 */
import {
  normalizeDashboardSettings,
  runButtonPlace,
  serializeDashboardSettings,
} from "../../utils/dashboardSettings";

describe("normalizeDashboardSettings", () => {
  test("keeps a well-formed place, and a size as a positive pair", () => {
    expect(normalizeDashboardSettings({ runButton: { x: 12.5, y: -40 } })).toEqual({ runButton: { x: 12.5, y: -40 } });
    expect(normalizeDashboardSettings({ runButton: { x: 1, y: 2, width: 80, height: 50 } })).toEqual({
      runButton: { x: 1, y: 2, width: 80, height: 50 },
    });
  });

  test.each([
    { x: 1, y: 2, width: 80 },
    { x: 1, y: 2, width: 0, height: 50 },
    { x: 1, y: 2, width: "80", height: 50 },
  ])("drops a size that is not a positive pair: %p", (runButton) => {
    expect(normalizeDashboardSettings({ runButton })).toEqual({ runButton: { x: 1, y: 2 } });
  });

  test.each([
    undefined,
    null,
    [],
    "runButton",
    { runButton: { x: 1 } },
    { runButton: { x: "1", y: 2 } },
    { runButton: { x: Number.NaN, y: 2 } },
    { runButton: [1, 2] },
  ])("reads %p as no settings", (raw) => {
    expect(normalizeDashboardSettings(raw)).toEqual({});
  });

  test("drops what it does not know", () => {
    expect(normalizeDashboardSettings({ runButton: { x: 1, y: 2, z: 3 }, theme: "dark" })).toEqual({
      runButton: { x: 1, y: 2 },
    });
  });
});

describe("serializeDashboardSettings", () => {
  test("writes the settings when there are some, and nothing otherwise", () => {
    expect(serializeDashboardSettings({ runButton: { x: 1, y: 2 } })).toEqual({ runButton: { x: 1, y: 2 } });
    expect(serializeDashboardSettings({})).toBeUndefined();
  });
});

describe("runButtonPlace", () => {
  const tiles = [
    { position: { x: 300, y: 120 } },
    { position: { x: 40, y: 500 } },
  ];

  test("is where, and as big as, the owner left it", () => {
    expect(runButtonPlace({ runButton: { x: 7, y: 9, width: 90, height: 60 } }, tiles)).toEqual({ x: 7, y: 9, width: 90, height: 60 });
    expect(runButtonPlace({ runButton: { x: 7, y: 9 } }, tiles)).toEqual({ x: 7, y: 9, width: 56, height: 44 });
  });

  test("else above the top-left of the tiles, at its own size", () => {
    expect(runButtonPlace({}, tiles)).toEqual({ x: 40, y: 56, width: 56, height: 44 });
  });

  test("at the origin when there are no tiles", () => {
    expect(runButtonPlace({}, [])).toEqual({ x: 0, y: 0, width: 56, height: 44 });
  });
});
