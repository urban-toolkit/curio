/**
 * The palette is scoped to the open dataflow, and the scope is read, not baked in.
 *
 * #204: a brand-new dataflow listed the packages of whichever dataflow was open
 * before it. #220: the same leak across projects, plus no way to remove an
 * imported package.
 *
 * The shared cause was that ``projectId === undefined`` meant BOTH "no dataflow
 * is open" and "a dataflow is open but unsaved", and both resolved to *no
 * filter at all*. The scope was also applied when descriptors were REGISTERED,
 * so the registry held one dataflow's view and any path that changed dataflow
 * without refetching left the previous one's packages on the palette.
 *
 * These tests pin the two properties that make that unrepresentable:
 *   1. an unsaved dataflow filters like any other dataflow, and
 *   2. changing the scope changes the palette with no refetch.
 */
import {
  clearCurrentProject,
  setCurrentProject,
  setCurrentProjectPackages,
  setUnsavedDataflow,
  getCurrentProjectPackages,
} from "../../registry/projectPackagesStore";
import {
  registerNode,
  getPaletteNodeTypes,
  getAllNodeTypes,
  clearPackageNodes,
} from "../../registry/nodeRegistry";
import { BUILTIN_PACKAGE_ID } from "../../registry/packageKeys";
import type { NodeDescriptor } from "../../registry/types";

function descriptor(packageId: string, major: number, templateId: string): NodeDescriptor {
  return {
    id: `${packageId}/${templateId}@${major}`,
    source: "package",
    package: { packageId, major, version: `${major}.0.0`, name: packageId },
    label: templateId,
    inPalette: true,
    paletteOrder: 1,
  } as unknown as NodeDescriptor;
}

const ACME = descriptor("acme.widgets", 1, "widget");
const OTHER = descriptor("other.tools", 2, "tool");
const BUILTIN = descriptor(BUILTIN_PACKAGE_ID, 1, "data-loading");

function paletteIds(): string[] {
  return getPaletteNodeTypes().map((d) => d.id).sort();
}

beforeEach(() => {
  clearPackageNodes();
  clearCurrentProject();
  // Every package the ACCOUNT has installed is registered, unconditionally.
  // The dataflow scope is applied on read.
  [ACME, OTHER, BUILTIN].forEach(registerNode);
});

afterEach(() => {
  clearPackageNodes();
  clearCurrentProject();
});

describe("no dataflow open", () => {
  test("nothing is filtered", () => {
    // The project list and the catalog pages: there is no lockfile to intersect
    // with, so everything installed shows.
    expect(getCurrentProjectPackages()).toBeNull();
    expect(paletteIds()).toEqual([ACME.id, BUILTIN.id, OTHER.id].sort());
  });
});

describe("a saved dataflow", () => {
  test("shows only its own lockfile, plus the builtin package", () => {
    setCurrentProject("proj-1", ["acme.widgets@1"]);
    expect(paletteIds()).toEqual([ACME.id, BUILTIN.id].sort());
  });

  test("switching dataflow changes the palette with no refetch", () => {
    // The property that makes the leak unrepresentable. Registration is
    // untouched between these two reads — only the scope moved.
    setCurrentProject("proj-1", ["acme.widgets@1"]);
    expect(paletteIds()).toEqual([ACME.id, BUILTIN.id].sort());

    setCurrentProject("proj-2", ["other.tools@2"]);
    expect(paletteIds()).toEqual([BUILTIN.id, OTHER.id].sort());
  });
});

describe("an unsaved dataflow", () => {
  test("filters like a saved one rather than showing everything", () => {
    // The #204 regression, stated directly: before the fix this fell through to
    // "no project, show everything" and listed the previous dataflow's packages.
    setCurrentProject("proj-1", ["acme.widgets@1", "other.tools@2"]);
    setUnsavedDataflow([]);
    expect(paletteIds()).toEqual([BUILTIN.id]);
  });

  test("widens to the account defaults when they arrive", () => {
    // ProjectLoader seeds the scope empty on the same tick the route changes,
    // then fills it from GET /api/packages/defaults. Both states are scoped.
    setUnsavedDataflow([]);
    expect(paletteIds()).toEqual([BUILTIN.id]);

    setCurrentProjectPackages(["acme.widgets@1"]);
    expect(paletteIds()).toEqual([ACME.id, BUILTIN.id].sort());
  });

  test("is a dataflow, so the scope is a set and not null", () => {
    // What ``if (!projectId)`` guards keyed on. Returning null here is what made
    // the drawer hide Remove and the palette drop its filter (#220).
    setUnsavedDataflow(["acme.widgets@1"]);
    expect(getCurrentProjectPackages()).not.toBeNull();
    expect(Array.from(getCurrentProjectPackages()!)).toEqual(["acme.widgets@1"]);
  });
});

describe("the builtin package", () => {
  test("survives a lockfile that does not name it", () => {
    // It is never in a lockfile the user edits, so the filter must let it
    // through on identity rather than membership.
    setCurrentProject("proj-1", []);
    expect(paletteIds()).toEqual([BUILTIN.id]);
  });
});

describe("registration is unscoped", () => {
  test("every installed package is registered, whatever the open dataflow", () => {
    // The half that makes read-time filtering work: descriptors for packages
    // outside this dataflow are still REGISTERED, so a canvas node belonging to
    // one resolves its descriptor instead of rendering as an unknown kind. The
    // scope decides what the palette OFFERS, not what exists.
    setCurrentProject("proj-1", []);
    expect(paletteIds()).toEqual([BUILTIN.id]);
    expect(getAllNodeTypes().map((d) => d.id).sort()).toEqual(
      [ACME.id, BUILTIN.id, OTHER.id].sort(),
    );
  });
});
