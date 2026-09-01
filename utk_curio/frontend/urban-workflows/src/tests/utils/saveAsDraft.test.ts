/**
 * The pure draft-shaping functions behind Save As - none of which had a test.
 *
 * These decide the wire payload for `/api/packages/factory/{build,install}`, so
 * a mistake here silently ships a malformed package rather than failing loudly:
 * the backend validates the manifest it *receives*, and cannot know a key was
 * dropped on the way out.
 *
 * The two shapes worth pinning hardest:
 *   - `toApiPayload` emits several keys only when truthy. Emitting `null`/`false`
 *     instead would change what the backend stores (and `readOnly` must never be
 *     emitted at all - `factory/install` rejects a draft that carries it).
 *   - `buildFactoryInstallEnvelope` *omits* `replace` rather than sending
 *     `false`, because the route reads `bool(draft.get("replace", False))` and a
 *     literal `false` is fine - but an accidental `true` overwrites an installed
 *     package directory.
 */
import {
  normalizePackageIdLeaf,
  buildFactoryInstallEnvelope,
  normalizeTemplateLabel,
  saveAsWouldReplaceByLabel,
  SAVE_AS_NEW_PACK,
} from "../../utils/palettePackageFactoryDraft";
import {
  makeDraft,
  makeTemplate,
  toApiPayload,
  depsToMap,
  type Draft,
} from "../../pages/nodes/factoryDraftModel";
import type { PackagePayload } from "../../api/packagesApi";

describe("normalizePackageIdLeaf", () => {
  it("lowercases and strips characters the backend id regex rejects", () => {
    expect(normalizePackageIdLeaf("My Package!")).toBe("mypackage");
    expect(normalizePackageIdLeaf("Hello-World")).toBe("hello-world");
  });

  it("collapses and trims dash runs", () => {
    expect(normalizePackageIdLeaf("a---b")).toBe("a-b");
    expect(normalizePackageIdLeaf("--lead-and-trail--")).toBe("lead-and-trail");
  });

  it("prefixes a leading non-letter, since the segment must start with one", () => {
    expect(normalizePackageIdLeaf("123")).toBe("d123");
    expect(normalizePackageIdLeaf("9lives")).toBe("d9lives");
  });

  it("falls back for input that normalises to nothing", () => {
    expect(normalizePackageIdLeaf("")).toBe("palette");
    expect(normalizePackageIdLeaf("!!!")).toBe("palette");
    expect(normalizePackageIdLeaf("___")).toBe("palette");
  });

  it("truncates to the backend's 63-character segment limit", () => {
    const leaf = normalizePackageIdLeaf("a".repeat(200));
    expect(leaf).toHaveLength(63);
    expect(leaf).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it("never leaves a trailing dash after truncating", () => {
    // 62 letters then a dash: slicing at 63 would end on the dash.
    const leaf = normalizePackageIdLeaf(`${"a".repeat(62)}-bbbb`);
    expect(leaf.endsWith("-")).toBe(false);
    expect(leaf).toMatch(/^[a-z][a-z0-9-]*$/);
  });

  it("always produces something the backend id regex accepts", () => {
    for (const raw of ["", "!", "-", "9", "A B C", "x".repeat(300), "ünïcodé"]) {
      expect(normalizePackageIdLeaf(raw)).toMatch(/^[a-z][a-z0-9-]{0,62}$/);
    }
  });
});

describe("buildFactoryInstallEnvelope", () => {
  const draft = (): Draft => {
    const d = makeDraft();
    d.packageId = "me.demo";
    d.templates = [makeTemplate("demo")];
    return d;
  };

  it("omits `replace` entirely when it is not requested", () => {
    for (const arg of [undefined, false]) {
      const envelope = buildFactoryInstallEnvelope(draft(), arg as boolean | undefined);
      expect("replace" in envelope).toBe(false);
    }
  });

  it("sets replace only when explicitly asked", () => {
    expect(buildFactoryInstallEnvelope(draft(), true).replace).toBe(true);
  });

  it("carries the full api payload through unchanged", () => {
    const d = draft();
    expect(buildFactoryInstallEnvelope(d)).toEqual({ ...toApiPayload(d) });
  });
});

describe("toApiPayload", () => {
  const withTemplate = (over: Partial<ReturnType<typeof makeTemplate>> = {}) => {
    const d = makeDraft();
    d.packageId = "me.demo";
    d.templates = [{ ...makeTemplate("demo"), ...over }];
    return d;
  };

  it("emits the manifest fields the backend loader requires", () => {
    const { manifest } = toApiPayload(withTemplate());
    expect(manifest.id).toBe("me.demo");
    expect(manifest.compatibility).toEqual({
      curioRuntime: expect.any(String),
      major: expect.any(Number),
    });
    expect(manifest.dependencies).toEqual({ packages: {}, python: {}, js: {} });
    expect(Array.isArray(manifest.templates)).toBe(true);
  });

  it("never emits readOnly", () => {
    // factory/install refuses a draft carrying readOnly, and the frontend has no
    // business claiming it - the flag belongs to the installed manifest.
    const { manifest } = toApiPayload(withTemplate());
    expect("readOnly" in manifest).toBe(false);
  });

  it("omits createdAt when the draft has none, so the backend stamps it", () => {
    const d = withTemplate();
    d.createdAt = "";
    expect("createdAt" in toApiPayload(d).manifest).toBe(false);
  });

  it("passes a pinned createdAt through, trimmed", () => {
    const d = withTemplate();
    d.createdAt = "  2000-01-01T00:00:00Z  ";
    expect(toApiPayload(d).manifest.createdAt).toBe("2000-01-01T00:00:00Z");
  });

  it("omits per-template optional keys rather than sending falsy values", () => {
    const [entry] = toApiPayload(
      withTemplate({ behavior: "", iconRef: "", paletteOrder: undefined, sourceFilename: "" }),
    ).manifest.templates as Record<string, unknown>[];
    for (const key of ["behavior", "iconRef", "paletteOrder", "source"]) {
      expect(key in entry).toBe(false);
    }
  });

  it("emits the optional per-template keys when set", () => {
    const [entry] = toApiPayload(
      withTemplate({
        behavior: "column-filter",
        iconRef: "fa-solid:cube",
        paletteOrder: 3,
        sourceFilename: "default.py",
      }),
    ).manifest.templates as Record<string, unknown>[];
    expect(entry.behavior).toBe("column-filter");
    expect(entry.iconRef).toBe("fa-solid:cube");
    expect(entry.paletteOrder).toBe(3);
    // The manifest stores a package-relative path, not the bare filename.
    expect(entry.source).toBe("sources/default.py");
  });

  it("keeps paletteOrder 0, which is a valid order and not an absence", () => {
    const [entry] = toApiPayload(withTemplate({ paletteOrder: 0 })).manifest
      .templates as Record<string, unknown>[];
    expect(entry.paletteOrder).toBe(0);
  });
});

describe("depsToMap", () => {
  it("turns the wizard's entry rows into the manifest's map form", () => {
    // A blank range becomes "*", not "" - the same "any version" spelling the
    // backend dependency scanner emits, so hand-entered and auto-detected deps
    // are indistinguishable downstream.
    expect(
      depsToMap([
        { pkg: "numpy", range: ">=1.26" },
        { pkg: "pandas", range: "" },
      ]),
    ).toEqual({ numpy: ">=1.26", pandas: "*" });
  });

  it("is empty for no entries", () => {
    expect(depsToMap([])).toEqual({});
  });
});

describe("label matching", () => {
  it("normalises case and surrounding space", () => {
    expect(normalizeTemplateLabel("  Column Filter ")).toBe("column filter");
  });

  const pkg = (labels: string[]): PackagePayload =>
    ({
      dirName: "me.demo@1",
      packageId: "me.demo",
      name: "Demo",
      templates: labels.map((label, i) => ({ id: `me.demo/t${i}`, label })),
    } as unknown as PackagePayload);

  it("detects that saving would replace an existing template", () => {
    // This drives the modal's "Replace existing node" warning and its
    // Save-vs-Replace button label, so a false negative silently clobbers.
    expect(saveAsWouldReplaceByLabel(pkg(["Column Filter"]), "column filter")).toBe(true);
    expect(saveAsWouldReplaceByLabel(pkg(["Column Filter"]), "Something Else")).toBe(false);
    expect(saveAsWouldReplaceByLabel(pkg([]), "Column Filter")).toBe(false);
  });
});

describe("SAVE_AS_NEW_PACK", () => {
  it("is the sentinel the destination <select> uses for a brand-new package", () => {
    // The e2e test selects this value by string; a rename here must break a test
    // rather than silently export into an existing package.
    expect(SAVE_AS_NEW_PACK).toBe("__save_as_new__");
  });
});
