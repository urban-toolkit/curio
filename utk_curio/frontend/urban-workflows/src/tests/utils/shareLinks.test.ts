/**
 * A dataflow and its dashboard are one project under two routes.
 *
 * The share-link test decides whether a visitor with no cookie is signed in as a
 * guest or shown a login form (`UserProvider`), so a link shape it fails to
 * recognise is a link that does not work for the person it was sent to. It runs
 * against `window.location.pathname`, which carries the router's basename, so a
 * deployment under a sub-path has to match too.
 */
import {
  SHARE_UUID_RE,
  absoluteUrl,
  dashboardPath,
  dataflowPath,
  isShareLinkPath,
} from "../../utils/shareLinks";

const UUID = "11111111-2222-3333-4444-555555555555";

describe("isShareLinkPath", () => {
  test.each([
    [`/dataflow/${UUID}`, "a dataflow link"],
    [`/dashboard/${UUID}`, "a dashboard link"],
    [`/curio/dashboard/${UUID}`, "a link under a PUBLIC_PATH prefix"],
    [`/dataflow/${UUID.toUpperCase()}`, "uppercase hex"],
    [`/dashboard/${UUID}/`, "a trailing slash"],
    [`/dashboard/${UUID}?from=email`, "a query string"],
    [`/dashboard/${UUID}#tile`, "a fragment"],
  ])("%s is a share link (%s)", (path) => {
    expect(isShareLinkPath(path)).toBe(true);
  });

  test.each([
    ["/dataflow/new", "the unsaved canvas"],
    ["/dataflow", "no id at all"],
    ["/dashboard/", "an empty id"],
    ["/projects", "the gallery"],
    [`/dashboards/${UUID}`, "a path that merely starts the same way"],
    [`/dataflow/${UUID.slice(0, 20)}`, "a truncated id"],
    ["", "an empty pathname"],
  ])("%s is not a share link (%s)", (path) => {
    expect(isShareLinkPath(path)).toBe(false);
  });

  test("a missing pathname is not a link", () => {
    expect(isShareLinkPath(undefined)).toBe(false);
    expect(isShareLinkPath(null)).toBe(false);
  });
});

describe("the paths and the ids", () => {
  test("both routes are built from one id", () => {
    expect(dataflowPath(UUID)).toBe(`/dataflow/${UUID}`);
    expect(dashboardPath(UUID)).toBe(`/dashboard/${UUID}`);
  });

  test("the id pattern accepts a project id and rejects `new`", () => {
    expect(SHARE_UUID_RE.test(UUID)).toBe(true);
    expect(SHARE_UUID_RE.test("new")).toBe(false);
    // Anchored: a longer string that merely contains one is not an id.
    expect(SHARE_UUID_RE.test(`x${UUID}`)).toBe(false);
  });
});

describe("absoluteUrl", () => {
  test("it prefixes the origin and keeps the basename it was given", () => {
    // The href argument is what `useHref` returns, i.e. already prefixed.
    expect(absoluteUrl(`/curio/dashboard/${UUID}`, "https://curio.example"))
      .toBe(`https://curio.example/curio/dashboard/${UUID}`);
  });

  test("a relative href still comes out absolute", () => {
    expect(absoluteUrl("dashboard/x", "https://curio.example"))
      .toBe("https://curio.example/dashboard/x");
  });
});
