/**
 * A legend titled by its layerRef's `legendTitle`, not by the table the
 * layer's input became (`input_0`).
 */
import { legendTitles, titleLegends } from "../../../adapters/node/autkLegendTitles";

// autk-map's UI as titleLegends uses it: the active layer, the legend and
// updateLegendContent, which writes the title from the layer's id.
function fakeMap(activeId: string) {
  const legend = document.createElement("div");
  const ui: any = {
    _activeLayer: { layerInfo: { id: activeId } },
    _legend: legend,
    updateLegendContent: jest.fn(() => {
      legend.innerHTML = "";
      const heading = document.createElement("div");
      heading.textContent = ui._activeLayer.layerInfo.id;
      legend.appendChild(heading);
    }),
  };
  return { ui, legend };
}

describe("legendTitles", () => {
  test("reads each layerRef's title by its dataRef, trimmed, and skips the rest", () => {
    expect(legendTitles({
      map: [
        { layerRefs: [{ dataRef: "input_0", legendTitle: " Building height " }, { dataRef: "input_1" }] },
        { layerRefs: [{ dataRef: "input_2", legendTitle: "" }, { dataRef: "input_3", legendTitle: 3 }] },
      ],
    })).toEqual(new Map([["input_0", "Building height"]]));
    expect(legendTitles({ plot: {} }).size).toBe(0);
  });
});

describe("titleLegends", () => {
  test("the legend is titled as the layerRef says, and stays so when autk-map writes it again", () => {
    const map = fakeMap("input_0");
    const grammar = { _mapRegistry: new Map([["input_0", map]]) };
    titleLegends(grammar, {
      map: { layerRefs: [{ dataRef: "input_0", legendTitle: "Accumulated shadow (minutes)" }] },
    });
    expect(map.legend.firstElementChild?.textContent).toBe("Accumulated shadow (minutes)");

    map.ui.updateLegendContent();
    expect(map.legend.firstElementChild?.textContent).toBe("Accumulated shadow (minutes)");
  });

  test("a layer with no title keeps autk-map's", () => {
    const map = fakeMap("input_0");
    titleLegends({ _mapRegistry: new Map([["input_0", map]]) }, { map: { layerRefs: [{ dataRef: "input_0" }] } });
    expect(map.ui.updateLegendContent).not.toHaveBeenCalled();
  });

  test("a layerRef with legend false hides its legend, and keeps it hidden when autk-map shows it again", () => {
    const map = fakeMap("input_1");
    titleLegends({ _mapRegistry: new Map([["input_1", map]]) }, {
      map: { layerRefs: [{ dataRef: "input_1", getFnv: "duration_minutes", legend: false }] },
    });
    expect(map.legend.style.visibility).toBe("hidden");

    // syncLegendVisibility: visible for a color-mapped layer, then the content.
    map.legend.style.visibility = "visible";
    map.ui.updateLegendContent();
    expect(map.legend.style.visibility).toBe("hidden");
  });

  test("a hidden legend belongs to its own layer: another active layer shows its legend", () => {
    const map = fakeMap("input_1");
    titleLegends({ _mapRegistry: new Map([["input_1", map]]) }, {
      map: { layerRefs: [{ dataRef: "input_1", legend: false }] },
    });
    map.ui._activeLayer = { layerInfo: { id: "input_0" } };
    map.legend.style.visibility = "visible";
    map.ui.updateLegendContent();
    expect(map.legend.style.visibility).toBe("visible");
  });

  test("a map registry or UI that is not there is no error", () => {
    const spec = { map: { layerRefs: [{ dataRef: "input_0", legendTitle: "Height" }] } };
    expect(() => titleLegends({}, spec)).not.toThrow();
    expect(() => titleLegends({ _mapRegistry: new Map([["input_0", {}]]) }, spec)).not.toThrow();
  });
});
