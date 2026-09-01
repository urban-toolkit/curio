import fs from "fs";
import path from "path";

/**
 * The drawer half of "Reload from catalog".
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
 * `reload()` can be called but never seen. A structural check still fails on
 * the regression that matters (swapping the reload for a registry refresh, or
 * dropping `replace`), which is the point.
 *
 * If this file starts failing because the callback was refactored rather than
 * broken, replace it with a render test rather than loosening the match.
 */

const SOURCE = path.resolve(
  __dirname,
  "../../components/packages/publishing/NodeCatalogDrawer.tsx",
);

function reloadCallbackSource(): string {
  const src = fs.readFileSync(SOURCE, "utf8");
  const start = src.indexOf("const onReloadFromCatalog");
  expect(start).toBeGreaterThan(-1);
  const body = src.slice(start);
  const end = body.indexOf("[reportActionError]");
  expect(end).toBeGreaterThan(-1);
  return body.slice(0, end);
}

describe("NodeCatalogDrawer.onReloadFromCatalog", () => {
  test("re-copies the package with replace:true", () => {
    expect(reloadCallbackSource()).toMatch(
      /installFromCatalog\(\s*pkg\.dirName\s*,\s*\{\s*replace:\s*true\s*\}\s*\)/,
    );
  });

  test("reloads the page on success", () => {
    expect(reloadCallbackSource()).toContain("window.location.reload()");
  });

  test("reports a failure instead of reloading", () => {
    const callback = reloadCallbackSource();
    expect(callback).toMatch(/catch\b/);
    expect(callback).toContain("Couldn't reload");
    // The reload sits on the success path, before the catch.
    expect(callback.indexOf("window.location.reload()")).toBeLessThan(
      callback.indexOf("catch"),
    );
  });
});
