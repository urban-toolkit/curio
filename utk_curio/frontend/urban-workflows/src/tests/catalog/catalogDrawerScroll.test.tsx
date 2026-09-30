import fs from "fs";
import path from "path";
import React from "react";
import { render, screen } from "@testing-library/react";
import { CatalogBrowseDrawerBody } from "../../pages/catalog/CatalogBrowseDrawerBody";

/**
 * The details drawer keeps its header and its actions in place (#526).
 *
 * The whole drawer was one scroll box, so the header scrolled away with the
 * content and the action row sat at the very end, below the fold whenever the
 * content was taller than the drawer: about 220 px down for a dataset. Now only
 * a body between the two scrolls.
 *
 * The markup half renders the shared body every browse drawer uses. The CSS
 * half is source-read, as in catalogDrawerParity.test.ts: jest maps CSS
 * modules to `identity-obj-proxy`.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../pages/catalog/CatalogBrowseLayout.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  return CSS.slice(open + 1, CSS.indexOf("}", open));
}

function renderDrawer() {
  return render(
    <CatalogBrowseDrawerBody
      kind="dataset"
      headerTitle="Dataset details"
      onClose={() => {}}
      hero={<div data-testid="hero" />}
      title="ACS Neighborhood Profile"
      badges={null}
      subtitle="data.utk.acs"
      metaLeft="csv"
      metaRight="today"
      fresh
      description="A long description."
      infoLabel="Dataset info"
      infoRows={[{ label: "Rows", value: 77 }]}
      tags={["census"]}
      sections={<div data-testid="extra-section" />}
      primaryAction={<button type="button">Add to all projects</button>}
      secondaryAction={<button type="button">View details</button>}
    />,
  );
}

describe("the browse drawer's scroll", () => {
  it("scrolls a body, not the drawer", () => {
    expect(ruleBody(".browseDrawer")).not.toMatch(/overflow-y:\s*auto/);
    expect(ruleBody(".browseDrawer")).toMatch(/overflow:\s*hidden;/);
    const body = ruleBody(".drawerBody") ?? "";
    expect(body).toMatch(/overflow-y:\s*auto;/);
    // Without min-height: 0 a flex item will not shrink below its content, and
    // the body would push the actions out of the drawer again.
    expect(body).toMatch(/min-height:\s*0;/);
    expect(body).toMatch(/flex:\s*1 1 auto;/);
  });

  it("puts the content in the body and the header and actions outside it", () => {
    const { container } = renderDrawer();
    const body = container.querySelector('[data-curio-drawer-body="true"]');
    expect(body).not.toBeNull();

    for (const inside of [
      screen.getByTestId("hero"),
      screen.getByRole("heading", { name: "ACS Neighborhood Profile" }),
      screen.getByText("A long description."),
      screen.getByText("census"),
      screen.getByTestId("extra-section"),
    ]) {
      expect(body!.contains(inside)).toBe(true);
    }

    const ctas = container.querySelector('[data-curio-drawer-ctas="true"]');
    expect(ctas).not.toBeNull();
    expect(body!.contains(ctas)).toBe(false);
    expect(body!.contains(screen.getByRole("button", { name: "Close" }))).toBe(false);
    expect(ctas!.contains(screen.getByRole("button", { name: "Add to all projects" }))).toBe(true);
  });
});
