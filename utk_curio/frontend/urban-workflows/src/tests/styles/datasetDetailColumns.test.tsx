import fs from "fs";
import path from "path";
import React from "react";
import { render, screen } from "@testing-library/react";
import { DatasetSchemaPanel } from "../../components/datasets/catalog/DatasetSchemaPanel";

/**
 * The dataset details columns show what they hold (#500, #501).
 *
 * The CSS half is source-read, as in planEdgeNames.test.ts: jest maps CSS
 * modules to `identity-obj-proxy`, so a rendered assertion cannot see which
 * rules apply.
 */
const catalogCss = (name: string) =>
  fs.readFileSync(
    path.resolve(__dirname, "../../components/datasets/catalog", name),
    "utf8",
  );

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  return css.slice(open + 1, css.indexOf("}", open));
}

describe("the dataset reference row (#500)", () => {
  const css = catalogCss("DatasetDetailPanel.module.css");

  it("wraps, so the Copy button does not squeeze the code", () => {
    expect(ruleBody(css, ".referenceRow")).toMatch(/flex-wrap:\s*wrap;/);
  });

  it("gives the code the whole row", () => {
    expect(ruleBody(css, ".referenceCode")).toMatch(/flex:\s*1 1 100%;/);
  });
});

describe("the schema field column (#501)", () => {
  const css = catalogCss("DatasetSchemaPanel.module.css");

  it("pads only the row's own cells", () => {
    // A descendant rule also padded the icon, the name and the PK badge
    // inside the Field cell, which left the name two or three letters.
    expect(css).not.toMatch(/\.(headRow|fieldRow) span[\s,{]/);
    expect(ruleBody(css, ".headRow > span,\n.fieldRow > span")).toMatch(/padding:\s*0 16px;/);
  });

  it("keeps the PK badge's own padding", () => {
    expect(ruleBody(css, ".pkBadge")).toMatch(/padding:\s*0 6px;/);
  });

  it("names a cut-off field on hover", () => {
    render(
      <DatasetSchemaPanel
        schema={{
          fields: [{ name: "median_household_income", type: "float64", nullable: true }],
          geometryType: null,
          fetching: false,
          unsupportedMessage: null,
        }}
      />,
    );
    expect(screen.getByText("median_household_income")).toHaveAttribute(
      "title",
      "median_household_income",
    );
  });
});
