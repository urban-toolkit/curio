/**
 * Which nodes are loaders, which view they open in, and the box the preview
 * takes (plans/data-loading-expressive-preview-memo.md, sections 3.4 to 3.6).
 */
import * as fs from "fs";
import * as path from "path";
import { faCircle } from "@fortawesome/free-solid-svg-icons";
import { Position } from "reactflow";

import { CURIO_UNIVERSAL_NODE_TYPE, NodeType, SupportedType } from "../../constants";
import { DATA_TYPE_VISUALS, dataTypeVisual, SOURCE_KIND_VISUALS } from "../../constants/dataTypeVisuals";
import { initialLoaderView, isLoaderTemplate } from "../../registry/loaderTemplates";
import { clearPackageNodes, registerNode } from "../../registry/nodeRegistry";
import type { NodeDescriptor, PortDef } from "../../registry/types";
import { DATASET_FORMAT_LABEL } from "../../services/datasetCatalog/datasetCatalogTypes";
import { buildDatasetLoaderNodeOptions } from "../../services/datasetCatalog/datasetApplication";
import { LOADER_PREVIEW_HEIGHT, resolveLoaderView } from "../../utils/loaderView";
import { resolveNodeBoxSize } from "../../utils/nodeBoxSize";

function descriptor(id: string, over: Partial<NodeDescriptor> = {}): NodeDescriptor {
  return {
    id: id as NodeType,
    category: "data",
    label: id,
    icon: faCircle,
    inputPorts: [],
    outputPorts: [{ types: [SupportedType.DATAFRAME] }],
    editor: "code",
    inPalette: true,
    description: "",
    hasCode: true,
    hasWidgets: false,
    hasGrammar: false,
    adapter: {
      handles: [{ id: "out", type: "source", position: Position.Right }],
      editor: { code: true, grammar: false, widgets: false },
      container: { nodeWidth: 320, nodeHeight: 380 },
      useNodeBehavior: () => ({}),
    },
    ...over,
  };
}

const anInput: PortDef[] = [{ types: [SupportedType.DATAFRAME] }];

describe("isLoaderTemplate", () => {
  it("is the built-in Data Loading, versioned or not", () => {
    expect(isLoaderTemplate(descriptor(NodeType.DATA_LOADING))).toBe(true);
    expect(isLoaderTemplate(descriptor(`${NodeType.DATA_LOADING}@1`))).toBe(true);
  });

  it("is a package's data node with code and no input", () => {
    expect(isLoaderTemplate(descriptor("curio.weather/mrt-load@1"))).toBe(true);
  });

  it("is not a data node with an input, a grammar node, a node without code, or another category", () => {
    expect(isLoaderTemplate(descriptor("curio.builtin/data-transformation", { inputPorts: anInput }))).toBe(false);
    expect(isLoaderTemplate(descriptor("x/grammar", { hasGrammar: true }))).toBe(false);
    expect(isLoaderTemplate(descriptor("curio.builtin/data-export", { hasCode: false }))).toBe(false);
    expect(isLoaderTemplate(descriptor("x/compute", { category: "computation" }))).toBe(false);
    expect(isLoaderTemplate(undefined)).toBe(false);
  });

  it("matches every shipped loader and nothing else in the shipped packages", () => {
    const root = path.resolve(__dirname, "../../../../../../packages");
    const loaders: string[] = [];
    for (const dir of fs.readdirSync(root)) {
      const file = path.join(root, dir, "manifest.json");
      if (!fs.existsSync(file)) continue;
      const manifest = JSON.parse(fs.readFileSync(file, "utf8"));
      for (const t of manifest.templates ?? []) {
        const shape = {
          id: `${manifest.id}/${t.id}`,
          category: t.category,
          hasCode: !!t.hasCode,
          hasGrammar: !!t.hasGrammar,
          inputPorts: t.inputPorts ?? [],
        } as any;
        if (isLoaderTemplate(shape)) loaders.push(shape.id);
      }
    }
    expect(loaders.sort()).toEqual(
      [
        "ai.utk.uhvi/uhvi-load",
        "ai.utk.uhvi/uhvi-zones",
        "curio.builtin/data-loading",
        "curio.weather/census-load",
        "curio.weather/mrt-load",
        "curio.weather/weather-load",
      ].sort(),
    );
  });
});

describe("the view a loader opens in", () => {
  it("is the editor for the bare Data Loading tool, which has no code yet", () => {
    expect(initialLoaderView(descriptor(NodeType.DATA_LOADING))).toBe("code");
  });

  it("is the preview for a package's loader, which brings its code", () => {
    expect(initialLoaderView(descriptor("curio.weather/mrt-load@1"))).toBe("preview");
  });

  it("is nothing for a node that is not a loader", () => {
    expect(initialLoaderView(descriptor("x/compute", { category: "computation" }))).toBeUndefined();
  });

  it("is the preview for a dataset dropped from the data palette", () => {
    const options = buildDatasetLoaderNodeOptions(
      { id: "data.x.y", datasetId: "data.x.y", title: "Y", format: "csv", origin: "imported" } as any,
      { x: 0, y: 0 },
    );
    expect(options.loaderView).toBe("preview");
  });
});

describe("resolveLoaderView", () => {
  it("follows the code when nothing is stored: preview with code, the editor without", () => {
    expect(resolveLoaderView(undefined, 'df = curio_load_data("x")')).toBe("preview");
    expect(resolveLoaderView(undefined, "")).toBe("code");
    expect(resolveLoaderView(undefined, "  \n# write a loader\n")).toBe("code");
  });

  it("keeps the stored view while there is code", () => {
    expect(resolveLoaderView("code", "df = 1")).toBe("code");
    expect(resolveLoaderView("preview", "df = 1")).toBe("preview");
  });

  it("shows the editor of an emptied loader, whatever is stored", () => {
    expect(resolveLoaderView("preview", "")).toBe("code");
  });

  it("ignores a stored value it does not know", () => {
    expect(resolveLoaderView("split", "df = 1")).toBe("preview");
  });
});

describe("the preview's box", () => {
  beforeEach(() => {
    clearPackageNodes();
    registerNode(descriptor("test.box/loader@1"));
  });

  const node = (data: Record<string, unknown>) => ({
    type: CURIO_UNIVERSAL_NODE_TYPE,
    data: { nodeType: "test.box/loader@1", ...data },
  });

  it("is smaller than the editor's, and keeps its own height", () => {
    expect(resolveNodeBoxSize(node({ code: "df = 1", nodeHeight: 400 })).height).toBe(LOADER_PREVIEW_HEIGHT);
    expect(resolveNodeBoxSize(node({ code: "df = 1", loaderPreviewHeight: 220 })).height).toBe(220);
  });

  it("is the editor's in code mode, or when the loader is empty", () => {
    expect(resolveNodeBoxSize(node({ code: "df = 1", loaderView: "code", nodeHeight: 400 })).height).toBe(400);
    expect(resolveNodeBoxSize(node({ code: "", nodeHeight: 400 })).height).toBe(400);
  });
});

describe("the visual table", () => {
  it("draws every dataset format, with a label, as the catalog names it or shorter", () => {
    for (const format of Object.keys(DATASET_FORMAT_LABEL)) {
      const visual = (DATA_TYPE_VISUALS as any)[format];
      expect(visual).toBeDefined();
      expect(visual.label).toBeTruthy();
    }
  });

  it("colours a format with its own tokens, and an unknown type with neutral ones", () => {
    expect(dataTypeVisual("geojson").bg).toBe("var(--curio-format-geojson-bg)");
    expect(dataTypeVisual("unknown")).toMatchObject({ label: "Data", glyph: null });
    expect(dataTypeVisual(undefined).label).toBe("Data");
  });

  it("names every source kind", () => {
    expect(Object.keys(SOURCE_KIND_VISUALS).sort()).toEqual(["api", "catalog", "disk", "inline", "unknown"]);
  });
});
