import fs from "fs";
import path from "path";

import { declaredValue } from "../_support/cssRules";

/**
 * The agents rail's labels as its stylesheet draws them (the Main,
 * EmptyBuilder and RailGroup boards): an entry's name is its agent's, wrapped
 * onto at most two lines within the rail's width ("Dataflow Builder", "Node
 * Builder") and cut only past them; what it is attached to is one line in
 * smaller type, cut short with an ellipsis. Held to one line, the names read
 * "Dataflo…" and "Node Bui…" in the rail's 78px. A name wraps between its
 * words only: breaking inside one cut "Researcher" into "Research / er"
 * (the leaner chat's boards, A1).
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot see which rules apply. What each label says is read in
 * AgentChatPanel.test.tsx ("labels each entry with its agent's name").
 */
const RAIL = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/chat/AgentRail.module.css"),
  "utf8",
);
const value = (selector: string, property: string) => declaredValue(RAIL, selector, property);

describe("the agents rail's labels", () => {
  test("an entry's name wraps onto two lines at most, and is cut only past them", () => {
    expect(value(".name", "white-space")).not.toBe("nowrap");
    expect(value(".name", "display")).toBe("-webkit-box");
    expect(value(".name", "-webkit-box-orient")).toBe("vertical");
    expect(value(".name", "-webkit-line-clamp")).toBe("2");
    expect(value(".name", "overflow")).toBe("hidden");
    // Within the rail's width, which clips what could not fit.
    expect(value(".name", "max-width")).toBe("100%");
  });

  test("an entry's name wraps between its words only, never inside one", () => {
    expect(value(".name", "overflow-wrap")).toBe("normal");
    expect(value(".name", "word-break")).toBe("normal");
    // In a size at which "Researcher", the shipped agents' longest word,
    // fits the entry, as the boards draw it.
    expect(value(".name", "font-size")).toBe("10px");
  });

  test("what it is attached to stays on one line, cut short with an ellipsis", () => {
    expect(value(".sub", "max-width")).toBe("100%");
    expect(value(".sub", "white-space")).toBe("nowrap");
    expect(value(".sub", "overflow")).toBe("hidden");
    expect(value(".sub", "text-overflow")).toBe("ellipsis");
  });
});
