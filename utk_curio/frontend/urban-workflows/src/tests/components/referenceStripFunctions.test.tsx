/**
 * Functions in the header above a node's code: what its code can call, beside
 * Inputs, with its count, closed until clicked. Open, a line per module that
 * offers a function, the node's own package's first, then Curio's own, which
 * need no import; each function a tag whose hover, in the one Curio tooltip,
 * shows its call and the first paragraph of its docstring, and whose click
 * hands it and its module to the editor (`functionCalls.insertFunctionCall`).
 * A spec lists none.
 *
 * The list is Accumulated Shadow's, as `GET /api/packages/node-functions`
 * gives it: Deep Umbra's `deep_umbra`, then Rasterization's modules, then Curio's.
 */
import React from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import { ReferenceStrip } from "../../components/editing/widgets/WidgetTag";
import { closeEveryCategory } from "../../components/editing/widgets/stripCategories";
import { FUNCTION_HOW, FUNCTION_HOW_IMPORT, functionGroups } from "../../components/editing/widgets/functionCalls";
import { TooltipLayer } from "../../components/tooltip/TooltipLayer";
import { resetTooltipStore } from "../../components/tooltip/tooltipStore";
import type { NodeFunctionsPayload } from "../../services/packages/types";
import { categoryButton, chipsOf, headerRow, openCategory } from "../_support/stripCategories";
import { getByTooltip } from "../_support/tooltips";

const SEASON_DOC =
  "Minutes of shadow a pixel at 1 stands for, in *season* (SCOUT's ``run_shadow_model``). SCOUT gives fall 720, " +
  "though its date input reads fall as it reads spring.";

const SHADOW_LIST: NodeFunctionsPayload = {
  engine: "python",
  modules: [
    {
      package: "model.scout.deep-umbra@1",
      module: "deep_umbra",
      problem: null,
      functions: [
        {
          name: "accumulated_shadow",
          call: "accumulated_shadow(value, season, model, output_file)",
          doc: "The accumulated shadow of the heights in *value*, in *season*, from the Deep Umbra session *model*.",
          insert: "accumulated_shadow(value, season, model, output_file)",
        },
        { name: "season_factor", call: "season_factor(season)", doc: SEASON_DOC, insert: "season_factor(season)" },
      ],
    },
    {
      package: "curio.rasterization@1",
      module: "scout_rasters.raster_algebra",
      problem: null,
      functions: [
        {
          name: "raster_calculate",
          call: "raster_calculate(operation, rasters, codes=None, *, absolute=False, output_file=None)",
          doc: "*operation* over *rasters* cell by cell: a rasterio dataset.",
          insert: "raster_calculate(operation, rasters)",
        },
      ],
    },
    // A module that offers nothing has no line.
    { package: "curio.rasterization@1", module: "scout_rasters.convert_to_raster", problem: null, functions: [] },
  ],
  curio: [
    {
      name: "curio_load_model",
      call: "curio_load_model(model_id)",
      doc: "Loads a Model Catalog model.",
      insert: "curio_load_model(model_id)",
    },
  ],
};

// Each test its own node, so no category it opens is open in another.
let made = 0;
const newNode = () => `functions-node-${(made += 1)}`;

function shadowHeader(more: Record<string, unknown> = {}) {
  return (
    <ReferenceStrip
      nodeId={newNode()}
      widgets={[{ name: "season", type: "choice", default: "summer", options: { choices: ["spring", "summer"] } }]}
      inputs={[{ slot: 0, label: "Rasterize Buildings" }]}
      functions={functionGroups(SHADOW_LIST)}
      language="python"
      onInsert={jest.fn()}
      {...more}
    />
  );
}

describe("Functions in the header", () => {
  afterEach(cleanup);

  test("sits beside Inputs with its count, closed, and only when the code can call something", () => {
    const view = render(shadowHeader());
    expect(headerRow(view.container)).toEqual([
      { category: "inputs", label: "Inputs 1", open: false },
      { category: "functions", label: "Functions 4", open: false },
      { category: "widgets", label: "Widgets 1", open: false },
    ]);
    expect(chipsOf(view.container, "functions")).toBeNull();
    expect(view.container.querySelector("[data-function-tag]")).toBeNull();
    view.unmount();

    const none = render(shadowHeader({ functions: [] }));
    expect(categoryButton(none.container, "functions")).toBeNull();
    none.unmount();

    // A spec calls nothing: no Functions, whatever it is given.
    const spec = render(shadowHeader({ language: "json" }));
    expect(categoryButton(spec.container, "functions")).toBeNull();
  });

  test("opens to a line per module, its own package's first, then Curio's, each with its functions in order", () => {
    const view = render(shadowHeader());
    const chips = openCategory(view.container, "functions");
    const lines = Array.from(chips.querySelectorAll<HTMLElement>("[data-function-group]")).map((line) => ({
      group: line.getAttribute("data-function-group"),
      title: line.firstElementChild?.textContent,
      tags: Array.from(line.querySelectorAll("[data-function-tag]")).map((tag) => tag.textContent),
    }));
    expect(lines).toEqual([
      { group: "deep_umbra", title: "deep_umbra", tags: ["accumulated_shadow", "season_factor"] },
      { group: "scout_rasters.raster_algebra", title: "scout_rasters.raster_algebra", tags: ["raster_calculate"] },
      { group: "curio", title: "Curio", tags: ["curio_load_model"] },
    ]);
    // One category open at a time, as the others.
    openCategory(view.container, "inputs");
    expect(chipsOf(view.container, "functions")).toBeNull();
  });

  test("each tag tells its call through the one Curio tooltip, a package's with its import", () => {
    const view = render(shadowHeader());
    openCategory(view.container, "functions");
    const season = getByTooltip(view.container, `season_factor(season). ${FUNCTION_HOW_IMPORT}`);
    expect(season.getAttribute("data-function-tag")).toBe("season_factor");
    expect(season.getAttribute("data-function-module")).toBe("deep_umbra");
    const load = getByTooltip(view.container, `curio_load_model(model_id). ${FUNCTION_HOW}`);
    expect(load.getAttribute("data-function-module")).toBe("");
    // Never a native title.
    expect(view.container.querySelector("[title]")).toBeNull();
  });

  test("a click hands the function and its module to the editor; a read-only node's does nothing", () => {
    const onInsertFunction = jest.fn();
    const view = render(shadowHeader({ onInsertFunction }));
    const chips = openCategory(view.container, "functions");
    fireEvent.click(chips.querySelector('[data-function-tag="season_factor"]')!);
    fireEvent.keyDown(chips.querySelector('[data-function-tag="curio_load_model"]')!, { key: "Enter" });
    expect(onInsertFunction.mock.calls).toEqual([
      [SHADOW_LIST.modules[0].functions[1], "deep_umbra"],
      [SHADOW_LIST.curio[0], null],
    ]);
    // Clicked, never dragged: a call is not a chip.
    expect(chips.querySelector('[data-function-tag="season_factor"]')!.getAttribute("draggable")).toBeNull();
    view.unmount();

    const readOnly = jest.fn();
    const locked = render(shadowHeader({ onInsertFunction: readOnly, disabled: true }));
    const lockedChips = openCategory(locked.container, "functions");
    const tag = lockedChips.querySelector('[data-function-tag="season_factor"]')!;
    expect(tag.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(tag);
    fireEvent.keyDown(tag, { key: "Enter" });
    expect(readOnly).not.toHaveBeenCalled();
  });
});

/** The layer may place a tooltip in the animation frame after it decides to show it. */
const FRAME = 16;
/** A mouse's pointer events, as the layer hears them. */
const MOUSE = { pointerType: "mouse", isPrimary: true, pointerId: 1, buttons: 0 };

/** The tooltips on screen. */
function shown(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[role="tooltip"]')).filter(
    (tip) => !tip.hidden && tip.getAttribute("aria-hidden") !== "true",
  );
}

/** Run the clock *ms* on, then whatever that started. */
async function advance(ms: number) {
  await act(async () => {
    jest.advanceTimersByTime(ms);
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

/** The mouse moves from the page onto *el* and rests there. */
function restOn(el: Element) {
  fireEvent.pointerEnter(el, { ...MOUSE, relatedTarget: document.body });
  fireEvent.mouseEnter(el, { relatedTarget: document.body });
  fireEvent.pointerMove(el, { ...MOUSE, clientX: 10, clientY: 10 });
  fireEvent.mouseMove(el, { clientX: 10, clientY: 10 });
}

/** The parts of the one tooltip on screen: its head, its lines and its foot. */
function partsOfTheTooltip(): { head: string; lines: string[]; foot: string } {
  expect(shown()).toHaveLength(1);
  const tip = shown()[0];
  expect(tip.querySelector('[data-chip-preview="function"]')).not.toBeNull();
  const text = (el: Element | null) => (el?.textContent ?? "").replace(/\s+/g, " ").trim();
  return {
    head: text(tip.querySelector("[data-preview-head]")),
    lines: Array.from(tip.querySelectorAll("[data-preview-line]")).map(text),
    foot: text(tip.querySelector("[data-preview-foot]")),
  };
}

describe("a function's hover", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    resetTooltipStore();
    closeEveryCategory();
  });

  afterEach(async () => {
    fireEvent.keyDown(document.body, { key: "Escape", code: "Escape" });
    await advance(1000);
    cleanup();
    jest.useRealTimers();
    document.body.innerHTML = "";
  });

  test("shows its call and its docstring's first paragraph in the Curio tooltip, as a chip's preview does", async () => {
    render(
      <>
        <TooltipLayer />
        {shadowHeader()}
      </>,
    );
    const chips = openCategory(document.body, "functions");
    restOn(chips.querySelector('[data-function-tag="season_factor"]')!);
    await advance(400 + FRAME);
    expect(shown()[0]?.querySelector("[data-preview-chip]")?.textContent).toBe("season_factor");
    expect(partsOfTheTooltip()).toEqual({
      head: "season_factor from deep_umbra",
      lines: ["season_factor(season)", SEASON_DOC],
      foot: FUNCTION_HOW_IMPORT,
    });
  });

  test("of one of Curio's says it needs no import", async () => {
    render(
      <>
        <TooltipLayer />
        {shadowHeader()}
      </>,
    );
    const chips = openCategory(document.body, "functions");
    restOn(chips.querySelector('[data-function-tag="curio_load_model"]')!);
    await advance(400 + FRAME);
    expect(partsOfTheTooltip()).toEqual({
      head: "curio_load_model Curio's, with no import",
      lines: ["curio_load_model(model_id)", "Loads a Model Catalog model."],
      foot: FUNCTION_HOW,
    });
  });
});
