/**
 * A legend titled by its layerRef's `legendTitle`, not by the table the
 * layer's input became (`input_0`).
 */
import { legendTitles, titleLegends } from "../../../adapters/node/autkLegendTitles";
import { grammarThatRan } from "../../_support/autkGrammarMaps";

/** Title the legends of the grammar that ran *spec* and drew *maps*. */
const title = (spec: any, ...maps: any[]) => titleLegends(grammarThatRan(spec, ...maps), spec);

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
    title({
      map: { layerRefs: [{ dataRef: "input_0", legendTitle: "Accumulated shadow (minutes)" }] },
    }, map);
    expect(map.legend.firstElementChild?.textContent).toBe("Accumulated shadow (minutes)");

    map.ui.updateLegendContent();
    expect(map.legend.firstElementChild?.textContent).toBe("Accumulated shadow (minutes)");
  });

  test("a layer with no title keeps autk-map's", () => {
    const map = fakeMap("input_0");
    title({ map: { layerRefs: [{ dataRef: "input_0" }] } }, map);
    expect(map.ui.updateLegendContent).not.toHaveBeenCalled();
  });

  // #771: a map of a node's input whose layerRef names no legendTitle read
  // `input_0`; it reads the column the layer is coloured by instead.
  test("a layer of an input with no title is titled with the column it maps, not input_k", () => {
    const first = fakeMap("input_0");
    const second = fakeMap("input_1");
    title({
      map: [
        { layerRefs: [{ dataRef: "input_0", getFnv: "area_km2", getFnvType: "quantitative" }] },
        { layerRefs: [{ dataRef: "input_1", getFnv: "properties.mean" }] },
      ],
    }, first, second);
    expect(first.legend.firstElementChild?.textContent).toBe("area_km2");
    expect(second.legend.firstElementChild?.textContent).toBe("mean");

    first.ui.updateLegendContent();
    expect(first.legend.firstElementChild?.textContent).toBe("area_km2");
  });

  test("a layer's own legendTitle wins over the column it maps", () => {
    const map = fakeMap("input_0");
    title({
      map: { layerRefs: [{ dataRef: "input_0", getFnv: "area_km2", legendTitle: "Area (km2)" }] },
    }, map);
    expect(map.legend.firstElementChild?.textContent).toBe("Area (km2)");
  });

  test("a legend the document hides, and a table the document names, keep autk-map's title", () => {
    const hidden = fakeMap("input_0");
    const roads = fakeMap("table_osm_roads");
    title({
      map: [
        { layerRefs: [{ dataRef: "input_0", getFnv: "band_1", isColorMap: false }] },
        { layerRefs: [{ dataRef: "table_osm_roads", getFnv: "sunlight" }] },
      ],
    }, hidden, roads);
    expect(hidden.ui.updateLegendContent).not.toHaveBeenCalled();
    expect(roads.ui.updateLegendContent).not.toHaveBeenCalled();
  });

  test("a grammar that drew no map, or a map with no UI, is no error", () => {
    const spec = { map: { layerRefs: [{ dataRef: "input_0", legendTitle: "Height" }] } };
    expect(() => titleLegends({}, spec)).not.toThrow();
    expect(() => title(spec, {})).not.toThrow();
  });

  test("each of two maps that draw one table titles its legend from its own layerRef", () => {
    const first = fakeMap("input_0");
    const second = fakeMap("input_0");
    title({
      map: [
        { layerRefs: [{ dataRef: "input_0", getFnv: "shape_area" }] },
        { layerRefs: [{ dataRef: "input_0", getFnv: "shape_leng" }] },
      ],
    }, first, second);
    expect(first.legend.firstElementChild?.textContent).toBe("shape_area");
    expect(second.legend.firstElementChild?.textContent).toBe("shape_leng");
  });
});
