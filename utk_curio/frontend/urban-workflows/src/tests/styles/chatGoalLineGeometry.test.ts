import fs from "fs";
import path from "path";
import { GOAL_EMPTY, GOAL_PLACEHOLDER } from "../../components/agents/attach/chat/GoalLine";

/**
 * The CSS that keeps the chat's Goal line readable at the panel's narrowest
 * (#227/#355). The goal shares its row with its label and its Edit button, or,
 * while it is edited, the field shares it with Save and Cancel; the panel is
 * 560px wide, and at most 92% of the window's width.
 *
 * Source-read: Jest maps CSS modules to ``identity-obj-proxy``, so a rendered
 * assertion cannot see which declarations a class carries, and jsdom has no
 * layout engine to measure a crop. The walkthrough ``dataflow-goal-is-readable`` measures the
 * line in a browser, in a narrow window too.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/AgentChatPanel.module.css"),
  "utf8",
);

function ruleBody(selector: string): string | null {
  const at = CSS.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = CSS.indexOf("{", at);
  const close = CSS.indexOf("}", open);
  return close === -1 ? null : CSS.slice(open + 1, close);
}

const CUT_SHORT = ["min-width: 0;", "overflow: hidden;", "text-overflow: ellipsis;", "white-space: nowrap;"];

describe("the chat's Goal line geometry", () => {
  it("cuts a long goal short with an ellipsis, on one line, rather than mid-word", () => {
    // A goal longer than the line is the normal case, so the ellipsis is part
    // of the line rather than decoration.
    const text = ruleBody(".goalText") ?? "";
    for (const declaration of CUT_SHORT) expect(text).toContain(declaration);
  });

  it("gives the goal the room its label and Edit button leave, and never squeezes them", () => {
    // Without min-width: 0 (above) a flex item refuses to shrink below its
    // content, which is what pushed the dock's goal field past its row (#227).
    expect(ruleBody(".goalText")).toMatch(/\n\s*flex: 1;/);
    expect(ruleBody(".goalLabel")).toMatch(/\n\s*flex: none;/);
    expect(ruleBody(".goalEdit")).toMatch(/\n\s*flex: none;/);
    expect(ruleBody(".goalAdd")).toMatch(/\n\s*flex: none;/);
  });

  it("sizes the field to the room Save and Cancel leave, not to its content", () => {
    // `min-width: 260px` with no width made the dock's field size to its
    // CONTENT inside a flex row, so a placeholder longer than the box was
    // clipped (#355).
    const input = ruleBody(".goalInput") ?? "";
    expect(input).toMatch(/\n\s*flex: 1;/);
    expect(input).toContain("min-width: 0;");
    expect(input).toContain("text-overflow: ellipsis;");
  });

  it("keeps its own height, so the conversation below gives way rather than the line", () => {
    expect(ruleBody(".goalLine")).toMatch(/\n\s*flex: none;/);
  });

  it("says what to add, and what the field is for, in words short enough to read whole", () => {
    // The dock's placeholder was "What is this dataflow for? (shared with your
    // agents)" in a field that could be 260px wide (#227).
    expect(GOAL_EMPTY).toBe("Add what this dataflow is for");
    expect(GOAL_PLACEHOLDER).toBe("What is this dataflow for?");
    for (const words of [GOAL_EMPTY, GOAL_PLACEHOLDER]) expect(words.length).toBeLessThanOrEqual(30);
  });
});
