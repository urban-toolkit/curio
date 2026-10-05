import fs from "fs";
import path from "path";

/**
 * The drawer half of "Reload from catalog" — since dev/143 F3/F4 the action
 * lives in THE catalog hook (`usePackageCatalog.reloadFromCatalog`), which the
 * Node Catalog page and drawer both render.
 *
 * `MyPackagesList.test.tsx` covers when the button is offered. What pressing it
 * *does* has two details that are easy to lose, and losing either makes the
 * authoring loop silently stop working:
 *
 *  - the install must pass `replace: true`. A plain install is a no-op once a
 *    copy exists in the user store, so the author's edits never arrive;
 *  - the page must be reloaded, not merely re-registered.
 *    `loadPackageBehaviorScripts` de-dupes injected bundles by package
 *    coordinate, so a rebuilt `scripts/behaviors.js` would be skipped for the
 *    rest of the session.
 *
 * Both are asserted against the source rather than a rendered drawer. Driving
 * the real button needs the drawer on its per-dataflow tab with a populated
 * lockfile, and the reload itself is unobservable anyway: jsdom's
 * `window.location` cannot be deleted, reassigned, spied on, or redefined, so
 * `reload()` can be called but never seen. The hook takes the reload as an
 * injectable `reloadWindow` (its own test observes the call); this file pins
 * the DEFAULT to the real page reload and the callback's shape. A structural
 * check still fails on the regression that matters (swapping the reload for a
 * registry refresh, or dropping `replace`), which is the point.
 *
 * If this file starts failing because the callback was refactored rather than
 * broken, replace it with a render test rather than loosening the match.
 */

const SOURCE = path.resolve(
  __dirname,
  "../../services/packages/usePackageCatalog.ts",
);

function hookSource(): string {
  return fs.readFileSync(SOURCE, "utf8");
}

function reloadCallbackSource(): string {
  const src = hookSource();
  const start = src.indexOf("const reloadFromCatalog");
  expect(start).toBeGreaterThan(-1);
  const body = src.slice(start);
  const end = body.indexOf("[reloadWindow, reportActionError]");
  expect(end).toBeGreaterThan(-1);
  return body.slice(0, end);
}

describe("usePackageCatalog.reloadFromCatalog", () => {
  test("re-copies the package with replace:true", () => {
    expect(reloadCallbackSource()).toMatch(
      /installFromCatalog\(\s*pkg\.dirName\s*,\s*\{\s*replace:\s*true\s*\}\s*\)/,
    );
  });

  test("reloads the page on success", () => {
    expect(reloadCallbackSource()).toContain("reloadWindow()");
    // ...and the page reload is what `reloadWindow` is unless a test injects one.
    expect(hookSource()).toMatch(
      /reloadWindow\s*=\s*\(\)\s*=>\s*window\.location\.reload\(\)/,
    );
  });

  test("reports a failure instead of reloading", () => {
    const callback = reloadCallbackSource();
    expect(callback).toMatch(/catch\b/);
    expect(callback).toContain("Couldn't reload");
    // The reload sits on the success path, before the catch.
    expect(callback.indexOf("reloadWindow()")).toBeLessThan(
      callback.indexOf("catch"),
    );
  });
});
