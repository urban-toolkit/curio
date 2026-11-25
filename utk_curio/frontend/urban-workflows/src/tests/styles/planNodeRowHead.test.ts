import fs from "fs";
import path from "path";

import { declaredValue } from "../_support/cssRules";

/**
 * The head of a landed plan's node row, in the plan card of the Dataflow
 * Builder's chat (PlanNodeRow), as its stylesheet draws it: the row's Solve
 * and Run, and its chip ("Placed ✓"), keep their words whole on one line and
 * never shrink; the row's title and node type give way, cut short with an
 * ellipsis. With the agents rail beside the transcript, the reconstruction's
 * plan card wrapped a row's title, its chip, and its Solve into "Solv" and "e".
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot see which rules apply.
 */
const COMPONENTS = path.resolve(__dirname, "../../components/agents/content");
const CARD = fs.readFileSync(path.join(COMPONENTS, "AgentReviewCard.module.css"), "utf8");
const ROW = fs.readFileSync(path.join(COMPONENTS, "reviewCard/PlanNodeRow.tsx"), "utf8");
const value = (selector: string, property: string) => declaredValue(CARD, selector, property);

describe("a plan row's head", () => {
  test("its Solve, its Run and its chip keep their words whole, on one line, and never shrink", () => {
    for (const selector of [
      ".planNodeHead > .apply",
      ".planNodeHead > .run",
      ".planNodeHead > .planNodeCreated",
      ".planNodeHead > .planEdgeRefused",
    ]) {
      expect([selector, value(selector, "flex")]).toEqual([selector, "none"]);
      expect([selector, value(selector, "white-space")]).toEqual([selector, "nowrap"]);
    }
  });

  test("its title and node type give way, cut short with an ellipsis on one line", () => {
    expect(value(".planNodeTitle", "flex")).toBe("0 1 auto");
    expect(value(".planNodeType", "flex")).toBe("1");
    for (const selector of [".planNodeTitle", ".planNodeType"]) {
      expect([selector, value(selector, "min-width")]).toEqual([selector, "0"]);
      expect([selector, value(selector, "white-space")]).toEqual([selector, "nowrap"]);
      expect([selector, value(selector, "overflow")]).toEqual([selector, "hidden"]);
      expect([selector, value(selector, "text-overflow")]).toEqual([selector, "ellipsis"]);
    }
  });

  test("every class the row names is drawn by a rule of its own", () => {
    // identity-obj-proxy answers any name here, while in the app a class the
    // stylesheet lacks is undefined: the row's Run had no rule, and drew as
    // the browser's own button beside the card's Solve. A class named only
    // inside another selector (`.planNodeHead > .run`) is defined, yet draws
    // nothing of its own, so it does not count.
    const named = [...new Set([...ROW.matchAll(/\bstyles\.([A-Za-z_]\w*)/g)].map((m) => m[1]))];
    expect(named).toEqual(expect.arrayContaining(["planNodeHead", "apply", "run"]));
    const selectors = [...CARD.replace(/\/\*[\s\S]*?\*\//g, "").matchAll(/([^{}]+)\{[^{}]*\}/g)].flatMap((rule) =>
      rule[1].split(",").map((selector) => selector.trim()),
    );
    const ownRule = (name: string) =>
      selectors.some((selector) => selector === `.${name}` || selector.startsWith(`.${name}:`));
    expect(named.filter((name) => !ownRule(name))).toEqual([]);
  });
});
