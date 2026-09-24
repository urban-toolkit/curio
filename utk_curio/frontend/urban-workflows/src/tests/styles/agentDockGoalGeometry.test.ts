import fs from "fs";
import path from "path";

/**
 * The CSS that actually keeps the goal field from being cropped (#227/#355).
 *
 * ``AgentDock.test.tsx`` proves the placeholder is short and the tooltip says
 * who reads the goal - both proxies. Neither is the fix. The fix is three
 * declarations, and nothing asserted them: the walkthrough PNG is the only
 * thing that would notice them going, at a 0.20 diff ratio its own comment
 * admits is loose enough for re-clipped text to pass.
 *
 * Source-read for the reason ``chipHoverContrast.test.ts`` records: jest maps
 * CSS modules to ``identity-obj-proxy``, so a rendered assertion cannot see
 * which declarations a class carries - and jsdom has no layout engine, so it
 * could not measure the crop even if it could.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/AgentDock.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  const close = CSS.indexOf("}", open);
  return close === -1 ? null : CSS.slice(open + 1, close);
}

describe("the dataflow goal field's geometry", () => {
  it("lets the field shrink inside the dock's flex row", () => {
    // Without min-width:0 a flex item refuses to go below its content size, so
    // the input pushed past the dock's max-width and was cropped - #227's
    // reported symptom, and the half that avatars squeezing the row triggers.
    expect(ruleBody(".goalField")).toContain("min-width: 0");
  });

  it("keeps the field flexible rather than fixed", () => {
    const field = ruleBody(".goalField") ?? "";
    expect(field).toContain("flex: 1 1 auto");
    expect(field).toContain("max-width");
  });

  it("sizes the input to its box, not to its content", () => {
    // `min-width: 260px` with no width made the input size to its CONTENT
    // inside the flex row, so a placeholder longer than the box was clipped and
    // max-width never came into play.
    const input = ruleBody(".goalInput") ?? "";
    expect(input).toContain("width: 100%");
    expect(input).toContain("min-width: 0");
  });

  it("says a long value is cut rather than cutting a word in half", () => {
    // A goal longer than the field is the normal case, so the ellipsis is part
    // of the fix rather than decoration.
    expect(ruleBody(".goalInput")).toContain("text-overflow: ellipsis");
  });

  it("lets the dock wrap instead of forcing everything onto one row", () => {
    // The other half of "avatars squeeze the goal": with nowrap the row would
    // shrink every item to fit however many agents are attached.
    const dock = ruleBody(".dock") ?? "";
    expect(dock).toContain("flex-wrap: wrap");
    expect(dock).toContain("max-width");
  });
});
