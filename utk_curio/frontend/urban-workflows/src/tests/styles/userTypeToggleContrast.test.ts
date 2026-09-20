import fs from "fs";
import path from "path";

/**
 * The selected toggle in the first-login dialog must stay readable under the
 * cursor (#351).
 *
 * `.toggleBtnActive` paints `background: #1E1F23` with white text.
 * `.toggleBtn:hover` sets `color: #1E1F23` and, at (0,2,0), outranks
 * `.toggleBtnActive` at (0,1,0) - so hovering the toggle you had already
 * selected left #1E1F23 text on the #1E1F23 fill the active rule still owns.
 * That is 1:1: not low contrast, but an invisible label. `UserTypeForm` opens
 * with "programmer" selected, so one of the two buttons is in that state from
 * first paint and the very first hover hits it.
 *
 * Same family as the catalog chips fixed in #244/#252, inverted colours, on a
 * component that fix never touched.
 *
 * Source-read rather than rendered, for the reason `chipHoverContrast.test.ts`
 * records: jest maps CSS modules to `identity-obj-proxy`, so a render assertion
 * cannot see a specificity conflict at all - `styles.toggleBtn` is just a
 * string either way.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/login/UserTypeForm.module.css"),
  "utf8",
);

/**
 * The declarations inside the rule whose selector is exactly `selector`.
 *
 * Anchored on a newline so `.toggleBtn:hover` cannot match inside
 * `.toggleBtn:hover:not(...)`, which is the exact distinction under test.
 */
function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  const close = CSS.indexOf("}", open);
  return close === -1 ? null : CSS.slice(open + 1, close);
}

describe("the first-login professional toggles", () => {
  it("does not restyle the toggle that is already selected on hover", () => {
    // The fix, and the thing to keep: the hover rule must exclude the active
    // state rather than merely re-declaring the light text after it.
    expect(ruleBody(".toggleBtn:hover:not(.toggleBtnActive)")).not.toBeNull();
    expect(ruleBody(".toggleBtn:hover")).toBeNull();
  });

  it("still gives an unselected toggle hover feedback", () => {
    // Removing the conflict must not remove the affordance.
    const hover = ruleBody(".toggleBtn:hover:not(.toggleBtnActive)") ?? "";
    expect(hover).toContain("color");
    expect(hover).toContain("border-color");
  });

  it("keeps the selected toggle's dark fill and light text together", () => {
    // If either half is dropped the contrast argument above stops holding.
    const active = ruleBody(".toggleBtnActive") ?? "";
    expect(active).toContain("background: #1E1F23");
    expect(active).toContain("color: #fff");
  });

  it("keeps the :not() guard load-bearing rather than incidental", () => {
    // The hover colour and the active background ARE the same value today, so
    // an unguarded `.toggleBtn:hover` would collide again immediately. Stating
    // that here means a refactor that drops the guard cannot look harmless.
    const hover = ruleBody(".toggleBtn:hover:not(.toggleBtnActive)") ?? "";
    const active = ruleBody(".toggleBtnActive") ?? "";
    const hoverColor = /(?:^|[^-])color:\s*([^;]+);/.exec(hover)?.[1]?.trim();
    const activeBg = /background:\s*([^;]+);/.exec(active)?.[1]?.trim();
    expect(hoverColor).toBe(activeBg);
  });
});
