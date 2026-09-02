/**
 * The PACKAGE pill appears only where it leads somewhere (#218).
 *
 * The report says the pill shows on "nodes that do not come from a package".
 * That premise is wrong -- ``curio.builtin@1`` IS a package, and
 * ``packagesClient.buildDescriptor`` stamps ``source: 'package'`` on every
 * template -- but the conclusion is right, for a different reason: the pill's
 * entire effect is to reveal its package in the Packages palette, and that
 * palette lists only third-party packages. On a built-in it was a control for
 * an action that could not happen.
 */
import fs from "fs";
import path from "path";
import React from "react";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

import { PackageMetaHeader } from "../../components/packages/editing/PackageMetaHeader";
import { PackagePaletteProvider } from "../../providers/PackagePaletteContext";
import { BUILTIN_PACKAGE_ID } from "../../registry/packageKeys";
import type { NodeCategory, NodePackageMeta } from "../../registry/types";

function pkg(packageId: string): NodePackageMeta {
  return {
    packageId,
    major: 1,
    version: "1.0.0",
    name: packageId,
  } as unknown as NodePackageMeta;
}

function renderHeader(packageId: string) {
  return render(
    <PackagePaletteProvider>
      <PackageMetaHeader
        pkg={pkg(packageId)}
        category={"computation" as NodeCategory}
        suggestionActive={false}
      />
    </PackagePaletteProvider>,
  );
}

const pill = () => screen.queryByRole("button", { name: /Open package .* in Packages palette/ });

describe("the PACKAGE pill", () => {
  test("is offered on a third-party package node", () => {
    // Guards the negative below: if the pill were gone for everyone, that test
    // would pass while proving nothing.
    renderHeader("acme.widgets");
    expect(pill()).not.toBeNull();
  });

  test("is withheld on a built-in node", () => {
    renderHeader(BUILTIN_PACKAGE_ID);
    expect(pill()).toBeNull();
  });
});

describe("the category pill", () => {
  // Informational rather than an action, so it is not part of the rule above.
  // Dropping it for built-ins would take away the one thing on the header that
  // names what kind of node this is.
  test.each([["third-party", "acme.widgets"], ["built-in", BUILTIN_PACKAGE_ID]])(
    "still renders on a %s node",
    (_label, packageId) => {
      const { container } = renderHeader(packageId);
      // Two pills for a package node, one for a built-in — either way the
      // category one is present.
      expect(container.querySelector("span[title]")).not.toBeNull();
    },
  );
});

// ── The fix that would have looked simpler ──────────────────────────────────

describe("the gate lives in the pill, not in its caller", () => {
  const read = (rel: string) =>
    fs.readFileSync(path.join(path.resolve(__dirname, "../.."), rel), "utf8");

  test("hasPackageMetaHeader still admits built-ins", () => {
    // The one-line version of this fix is to narrow `hasPackageMetaHeader` in
    // styles.tsx so PackageMetaHeader is never rendered for a built-in. It
    // removes the pill, and it also removes node renaming and the settings cog
    // from every built-in node -- the same flag feeds `showPackageNodeActions`
    // into EditableNodeHeaderLabel's `editable` / `showConfig`, and that is the
    // only route to either. Gating inside the component keeps the two apart.
    const src = read("components/styles.tsx");
    expect(src).toContain(
      'const hasPackageMetaHeader = packageDescriptor?.source === "package" && !!packageDescriptor.package;',
    );
    expect(src).toContain("const showPackageNodeActions = hasPackageMetaHeader && !dashboardOn;");
    expect(src).toContain("editable={showPackageNodeActions}");
    expect(src).toContain("showConfig={showPackageNodeActions}");
  });
});
