/**
 * Icon-only nodes keep a way to remove themselves.
 *
 * `merge-flow` is the only template with `containerStyle.noContent: true`
 * (`spatial-join` left the set in #262, when it gained a body). They start minimized (`useState(!!noContent)`),
 * both un-minimize paths are gated by `if (!noContent)` so they can never be
 * expanded, and the whole header band — pin, comments, delete — is gated on
 * `{!noContent && !dashboardOn ? …}`. The result was a node with no on-node
 * control of any kind: drop a Merge Flow by mistake and the only way to remove
 * it is the Delete key, which nothing on screen suggests. The stress run found
 * it by trying to clear its own canvas — ten of twelve nodes deleted, these two
 * had no control to press.
 *
 * Asserted against the source rather than a render, the same approach and for
 * the same reason as `catalog/catalogDrawerParity.test.ts`: `styles.tsx` is a
 * 1000-line component whose container pulls in the whole provider stack, and
 * what needs pinning here is a small structural fact — that the minimized
 * branch carries a delete control gated on `noContent`, and that the two
 * templates it applies to have not quietly grown.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

const BUILTIN_MANIFEST = path.resolve(
  __dirname, "../../../../../../packages/curio.builtin@1/manifest.json",
);

describe("noContent nodes", () => {
  it("are still only the template this control exists for", () => {
    const manifest = JSON.parse(fs.readFileSync(BUILTIN_MANIFEST, "utf8"));
    const noContent = manifest.templates
      .filter((t: any) => t?.containerStyle?.noContent)
      .map((t: any) => t.id)
      .sort();
    // A third one arriving should send someone back to this test, not silently
    // inherit a control nobody checked against it.
    expect(noContent).toEqual(["merge-flow"]);
  });

  it("render a delete control on the minimized chip", () => {
    const source = read("components/styles.tsx");
    const minimizedBranch = source.slice(source.indexOf("{minimized ? ("));
    expect(minimizedBranch).toContain("noContent && !dashboardOn");
    expect(minimizedBranch).toContain('title="Delete node"');
    expect(minimizedBranch).toContain("onActivate={onDelete}");
  });

  it("keeps the header band gated off for them, so the chip is the only route", () => {
    // If this ever stops being true the chip control becomes a duplicate and
    // this whole special case can go.
    expect(read("components/styles.tsx")).toContain("{!noContent && !dashboardOn ?");
  });
});
