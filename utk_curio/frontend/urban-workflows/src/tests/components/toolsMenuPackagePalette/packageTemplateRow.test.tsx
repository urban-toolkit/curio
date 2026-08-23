import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";

/**
 * Pins the drag contract of a package palette row.
 *
 * The row is the only way to put a package's node on the canvas, and until now
 * nothing identified it: the palette carries a package-level
 * ``data-pkg-palette-coords`` anchor, but the per-kind rows inside it were
 * anonymous, so an e2e test could not say "drag *this* kind".
 *
 * ``data-pkg-template-id`` fixes that, and the invariant worth guarding is not
 * that the attribute exists but that it stays EQUAL to the descriptor id the row
 * writes into ``dataTransfer``. A test that drags the row addressed by the
 * attribute and a canvas that creates the node from the payload must agree, or
 * the e2e helper silently drops the wrong node type on the pane.
 */

jest.mock("reactflow", () => ({
    useReactFlow: () => ({ setNodes: jest.fn() }),
}));

import { PackageTemplateRow } from "../../../components/menus/nodes/toolsMenuPackagePalette/PackagePaletteRows";

const descriptor = (overrides: Record<string, any> = {}) =>
    ({
        id: "acme.shapes/hexbin@1",
        label: "Hexbin",
        description: "Bin points into hexagons",
        icon: "circle",
        category: "computation",
        ...overrides,
    }) as any;

const dragHandle = (templateId: string) =>
    document.querySelector(`[data-pkg-template-id="${templateId}"]`) as HTMLElement | null;

describe("PackageTemplateRow drag identity", () => {
    test("the drag handle is addressable by its descriptor id", () => {
        render(<PackageTemplateRow desc={descriptor()} />);
        const handle = dragHandle("acme.shapes/hexbin@1");
        expect(handle).not.toBeNull();
        expect(handle).toHaveAttribute("draggable");
    });

    test("the attribute and the dataTransfer payload carry the same id", () => {
        // The whole point of the attribute: address the row by X, and the canvas
        // receives X. Asserting both halves in one test is what keeps them from
        // drifting apart.
        render(<PackageTemplateRow desc={descriptor()} />);
        const handle = dragHandle("acme.shapes/hexbin@1")!;

        const written: Record<string, string> = {};
        fireEvent.dragStart(handle, {
            dataTransfer: {
                setData: (type: string, value: string) => {
                    written[type] = value;
                },
            },
        });

        expect(written["application/reactflow"]).toBe(
            handle.getAttribute("data-pkg-template-id"),
        );
        expect(written["application/reactflow"]).toBe("acme.shapes/hexbin@1");
    });

    test("the label stays on the meta button, not the drag handle", () => {
        // Two rows of the same package differ only by descriptor id, so a test
        // must not fall back to matching on label text.
        render(<PackageTemplateRow desc={descriptor()} />);
        expect(dragHandle("acme.shapes/hexbin@1")).not.toHaveTextContent("Hexbin");
        expect(screen.getByText("Hexbin")).toBeInTheDocument();
    });
});
