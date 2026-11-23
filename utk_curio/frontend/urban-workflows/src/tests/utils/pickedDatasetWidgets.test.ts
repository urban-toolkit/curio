/**
 * A dataset widget an input picks (`options.pickedBy`, `options.choices`) on
 * the canvas: the canvas keeps how it is picked when it reads and saves the
 * widget, reads the value on its circle through the `/get-preview` a chip's
 * hover reads, shows the dataset that value picks, binds every choice, and
 * refuses a drop on its node. What a run writes once it has read that value
 * is in the shared cases (`codeReferences.cases.json`).
 */
const mockFetchPreviewData = jest.fn();
jest.mock("../../services/api", () => ({
  fetchData: jest.fn(),
  fetchPreviewData: (...args: any[]) => mockFetchPreviewData(...args),
}));

import { normalizeWidgets, type WidgetDef } from "../../utils/widgets/widgetModel";
import { datasetWidgetIds, pickedDropRefusal } from "../../utils/widgets/datasetWidgets";
import { waitsForData, resolveReferences, withPickedValues } from "../../utils/references/codeReferences";
import { readInputValue } from "../../utils/references/inputScope";

const CHOICES = {
  W042: "data.sage.idot-w042-records-2025-08",
  W065: "data.sage.idot-w065-records-2025-08",
  W06E: "data.sage.idot-w06e-records-2025-12",
};
const PICKED = {
  name: "data",
  type: "dataset",
  label: "Data",
  default: "",
  options: { pickedBy: "input_0.camera", choices: CHOICES },
};
const STARTER = "data = curio_load_data([!! data !!])\nreturn data\n";

beforeEach(() => mockFetchPreviewData.mockReset());

describe("the canvas keeps how a dataset widget is picked", () => {
  test("normalizeWidgets keeps pickedBy and the map of choices, which a save writes as they were", () => {
    const [widget] = normalizeWidgets([PICKED]);
    expect(widget.options).toEqual({ pickedBy: "input_0.camera", choices: CHOICES });
    expect(JSON.parse(JSON.stringify(normalizeWidgets([PICKED])))).toEqual([PICKED]);
  });

  test("a choice widget's list of choices is kept as before", () => {
    const [widget] = normalizeWidgets([{ name: "w", type: "choice", default: "a", options: { choices: ["a", "b"] } }]);
    expect(widget.options).toEqual({ choices: ["a", "b"] });
  });
});

describe("what the node's Data box shows", () => {
  const widgets = normalizeWidgets([PICKED]) as WidgetDef[];

  test.each(Object.entries(CHOICES))("the camera %s shows its records", (camera, id) => {
    const [shown] = withPickedValues(widgets, [{ slot: 0, dataType: "dict", value: { camera, model: "YOLOv8n" } }]);
    expect(shown.value).toBe(id);
    // The widget itself holds no value: a run picks again from its input.
    expect(widgets[0].value).toBeUndefined();
  });

  test("before its input holds a value, nothing, and a run waits for it", () => {
    const [shown] = withPickedValues(widgets, [{ slot: 0, dataType: "dict" }]);
    expect(shown.value).toBe("");
    const scope = { widgets, inputs: [{ slot: 0, dataType: "dict" }] };
    const { problems } = resolveReferences(STARTER, scope, "python");
    expect(problems).toHaveLength(1);
    expect(waitsForData(problems[0], scope)).toBe(true);
  });

  test("a value no choice names shows nothing, and is no wait: the run is refused", () => {
    const [shown] = withPickedValues(widgets, [{ slot: 0, dataType: "dict", value: { camera: "W999" } }]);
    expect(shown.value).toBe("");
    const scope = { widgets, inputs: [{ slot: 0, dataType: "dict", value: { camera: "W999" } }] };
    const { problems } = resolveReferences(STARTER, scope, "python");
    expect(waitsForData(problems[0], scope)).toBe(false);
  });
});

describe("the value on the circle a widget is picked by", () => {
  test("a dict a Python node returned is read whole through the preview a chip's hover reads", async () => {
    const settings = { camera: "W065", model: "YOLOv8n", classes: ["car", "truck", "bus", "train", "person", "bicycle"] };
    mockFetchPreviewData.mockResolvedValue({ data: settings, dataType: "dict", filename: "art-settings" });
    await expect(readInputValue({ path: "art-settings", dataType: "dict" })).resolves.toEqual(settings);
    expect(mockFetchPreviewData).toHaveBeenCalledWith("art-settings");
  });

  test("a text a Python node returned is read as the text", async () => {
    mockFetchPreviewData.mockResolvedValue({ data: "2050 - 2080", dataType: "str" });
    await expect(readInputValue({ path: "art-period", dataType: "str" })).resolves.toBe("2050 - 2080");
  });

  test("a table or a raster is not read: it holds no text to pick by", async () => {
    await expect(readInputValue({ path: "art-rows", dataType: "dataframe" })).resolves.toBeUndefined();
    await expect(readInputValue({ path: "art-depth", dataType: "raster" })).resolves.toBeUndefined();
    expect(mockFetchPreviewData).not.toHaveBeenCalled();
  });
});

describe("what the node reads and takes", () => {
  test("every choice is a dataset the node is bound to", () => {
    expect(datasetWidgetIds([PICKED])).toEqual(Object.values(CHOICES));
  });

  test("a drop on a node whose Data an input picks is refused, saying why", () => {
    expect(pickedDropRefusal([PICKED], STARTER)).toBe(
      "Data is picked by input_0.camera: change what that input holds to load another dataset.",
    );
  });

  test("a plain Data box takes a drop", () => {
    expect(pickedDropRefusal([{ name: "data", type: "dataset", label: "Data", default: "" }], STARTER)).toBeNull();
  });
});
