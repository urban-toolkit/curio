import fs from "fs";
import path from "path";
import React from "react";
import { fireEvent, render } from "@testing-library/react";
import "@testing-library/jest-dom";
import { faUpload } from "@fortawesome/free-solid-svg-icons";

/**
 * Every drag source of the tool rail's palettes and of the catalog drawers
 * names what it carries: `data-palette` is its palette, the one of its catalog
 * for a drawer's card, and `data-palette-item` its item, the one its own drag
 * writes. An agent's drag of `{palette, item}` starts at the element that names
 * it (`providers/collab/agentDrags.ts`):
 *
 * - a Built-in tile and a package's row carry a node type;
 * - a dataset's row and card, and a layer group's row, the dataset's id;
 * - a model's row and card, the model's package id;
 * - a node package's card, its nodes' types, separated by spaces.
 *
 * When the palette is closed, the drag starts at the rail's edge beside its
 * root, which has the id `<palette>-palette`.
 */

jest.mock("reactflow", () => ({
    useReactFlow: () => ({ getNodes: () => [], setNodes: jest.fn(), setCenter: jest.fn() }),
}));
jest.mock("../../providers/ToastProvider", () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
}));
// It pulls in FlowProvider and, through it, vega.
jest.mock("../../components/datasets/catalog/DatasetConnectionBadge", () => ({
    DatasetConnectionBadge: () => null,
}));

import { BuiltinPaletteDropdown } from "../../components/menus/nodes/builtinPalette/BuiltinPaletteDropdown";
import { PackageTemplateRow } from "../../components/menus/nodes/toolsMenuPackagePalette/PackagePaletteRows";
import { DatasetGroupRow, DatasetRow } from "../../components/menus/nodes/datasetPalette/DatasetPaletteRows";
import { ModelPaletteRow } from "../../components/menus/nodes/modelsPalette/ModelPaletteRow";
import { DatasetCard } from "../../components/datasets/catalog/DatasetCard";
import { DatasetDetailsContext } from "../../components/datasets/catalog/datasetDetailsContext";
import { PackageCard } from "../../components/packages/publishing/PackageCard";
import type { NodeDescriptor } from "../../registry/types";
import type { DatasetCatalogItem, DatasetPaletteGroup } from "../../services/datasetCatalog";
import type { PackagePayload } from "../../services/packages";
import { ddrnetPackage, template } from "../_support/modelPackages";

/** What a drag of *element* writes, by type, its drag then ended. */
function dragWrites(element: Element | null): Record<string, string> {
    expect(element).not.toBeNull();
    const written: Record<string, string> = {};
    fireEvent.dragStart(element as Element, {
        dataTransfer: {
            setData: (type: string, value: string) => {
                written[type] = value;
            },
            effectAllowed: "",
        },
    });
    fireEvent.dragEnd(element as Element);
    return written;
}

const itemOf = (element: Element | null) => [element?.getAttribute("data-palette"), element?.getAttribute("data-palette-item")];
const dragHandle = () => document.querySelector('[draggable="true"]');

const dataset = (over: Partial<DatasetCatalogItem> = {}): DatasetCatalogItem =>
    ({
        id: "imported.bikes",
        title: "Bike Routes",
        origin: "imported",
        format: "csv",
        uri: "curio://datasets/imported.bikes",
        consumerNodeIds: [],
        updatedAt: "2026-07-14T00:00:00Z",
        tags: [],
        installed: true,
        ...over,
    }) as DatasetCatalogItem;

const shapes = (templates: ReturnType<typeof template>[]): PackagePayload =>
    ({
        dirName: "acme.shapes@1",
        packageId: "acme.shapes",
        name: "Shapes",
        version: "1.0.0",
        publisher: "Acme",
        description: "",
        templates,
        lineage: null,
        familyKey: "acme.shapes@1",
    }) as unknown as PackagePayload;

const cardProps = {
    isInstalled: false,
    hasUpdate: false,
    catalogRow: undefined,
    busy: false,
    onInstall: jest.fn(),
    onUpdate: jest.fn(),
};

describe("a rail palette's drag source names its item", () => {
    test("a Built-in tile: its node type, the one its drag writes", () => {
        const dataLoading = {
            id: "curio.builtin/data-loading@1",
            label: "Data Loading",
            category: "data",
            icon: faUpload,
        } as unknown as NodeDescriptor;
        render(<BuiltinPaletteDropdown nodeTypes={[dataLoading]} open setOpen={jest.fn()} />);
        const tile = document.getElementById("tile-data-loading");
        expect(itemOf(tile)).toEqual(["builtin", "curio.builtin/data-loading@1"]);
        expect(dragWrites(tile)["application/reactflow"]).toBe("curio.builtin/data-loading@1");
    });

    test("a package's row: its node type, on the drag handle, the one its drag writes", () => {
        const hexbin = { id: "acme.shapes/hexbin@1", label: "Hexbin", description: "", icon: faUpload, category: "computation" };
        render(<PackageTemplateRow desc={hexbin as unknown as NodeDescriptor} />);
        const handle = document.querySelector('[data-pkg-template-id="acme.shapes/hexbin@1"]');
        expect(itemOf(handle)).toEqual(["packages", "acme.shapes/hexbin@1"]);
        expect(dragWrites(handle)["application/reactflow"]).toBe("acme.shapes/hexbin@1");
    });

    test("a dataset's row: its dataset's id, on the drag handle, the one its drag writes", () => {
        render(
            <DatasetDetailsContext.Provider value={{ openDatasetDetails: jest.fn() }}>
                <DatasetRow dataset={dataset()} />
            </DatasetDetailsContext.Provider>,
        );
        const handle = dragHandle();
        expect(itemOf(handle)).toEqual(["datasets", "imported.bikes"]);
        expect(JSON.parse(dragWrites(handle)["application/x-curio-dataset"]).datasetId).toBe("imported.bikes");
    });

    test("a layer group's row: the group's id, the one its drag writes", () => {
        const group: DatasetPaletteGroup = {
            kind: "group",
            groupId: "osm.nyc",
            title: "NYC",
            members: [
                dataset({ id: "osm.nyc.roads", title: "NYC (roads)", format: "geojson" }),
                dataset({ id: "osm.nyc.parks", title: "NYC (parks)", format: "geojson" }),
            ],
            updatedAt: null,
        };
        render(<DatasetGroupRow group={group} />);
        const handle = dragHandle();
        expect(itemOf(handle)).toEqual(["datasets", "osm.nyc"]);
        expect(JSON.parse(dragWrites(handle)["application/x-curio-dataset"]).datasetId).toBe("osm.nyc");
    });

    test("a model's row: its model's package id, the one its drag writes", () => {
        render(<ModelPaletteRow model={ddrnetPackage()} onOpenDetails={jest.fn()} />);
        const handle = dragHandle();
        expect(itemOf(handle)).toEqual(["models", "model.curio.ddrnet23-slim"]);
        expect(JSON.parse(dragWrites(handle)["application/x-curio-model"]).modelId).toBe("model.curio.ddrnet23-slim");
    });
});

describe("a catalog drawer's card names its item", () => {
    test("a dataset's card: its dataset's id, the one it shares with the palette's row", () => {
        render(<DatasetCard dataset={dataset()} isInstalled={false} busy={false} onInstall={jest.fn()} />);
        const card = document.querySelector("article");
        expect(itemOf(card)).toEqual(["datasets", "imported.bikes"]);
        expect(card).toHaveAttribute("data-dataset-id", "imported.bikes");
    });

    test("a node package's card: its nodes' types, in the order its drag lists them", () => {
        const pkg = shapes([
            template({ id: "acme.shapes/hexbin@1", label: "Hexbin", paletteOrder: 2 }),
            template({ id: "acme.shapes/heatmap@1", label: "Heatmap", paletteOrder: 1 }),
        ]);
        render(<PackageCard {...cardProps} pkg={pkg} />);
        const card = document.querySelector('article[data-pkg-dir="acme.shapes@1"]');
        expect(card).toHaveAttribute("data-palette", "packages");
        const items = (card!.getAttribute("data-palette-item") ?? "").split(" ");
        expect(items).toEqual(["acme.shapes/heatmap@1", "acme.shapes/hexbin@1"]);
        const written = JSON.parse(dragWrites(card)["application/x-curio-package-card"]);
        expect(items).toEqual(written.nodes.map((node: { nodeType: string }) => node.nodeType));
    });

    test("a node package's card with no node names none, as it drags none", () => {
        render(<PackageCard {...cardProps} pkg={shapes([])} />);
        const card = document.querySelector('article[data-pkg-dir="acme.shapes@1"]');
        expect(card).not.toHaveAttribute("draggable");
        expect(card).not.toHaveAttribute("data-palette");
        expect(card).not.toHaveAttribute("data-palette-item");
    });

    test("a model's card: its model's package id, the one its drag writes", () => {
        render(<PackageCard {...cardProps} pkg={ddrnetPackage()} />);
        const card = document.querySelector('article[data-model-id="model.curio.ddrnet23-slim"]');
        expect(itemOf(card)).toEqual(["models", "model.curio.ddrnet23-slim"]);
        expect(JSON.parse(dragWrites(card)["application/x-curio-model"]).modelId).toBe("model.curio.ddrnet23-slim");
    });
});

describe("a closed palette's root", () => {
    test.each([
        ["builtin", "builtinPalette/BuiltinPaletteDropdown.tsx"],
        ["packages", "toolsMenuPackagePalette/PackagesPaletteDropdown.tsx"],
        ["datasets", "datasetPalette/DatasetsPaletteDropdown.tsx"],
        ["models", "modelsPalette/ModelsPaletteDropdown.tsx"],
    ])("of %s has the id an agent's drag starts beside", (palette, file) => {
        const source = fs.readFileSync(path.resolve(__dirname, "../../components/menus/nodes", file), "utf8");
        expect(source).toContain(`id="${palette}-palette"`);
    });
});
