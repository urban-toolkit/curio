import fs from "fs";
import path from "path";

import { declaredValue } from "../_support/cssRules";

/**
 * The agents rail's labels as its stylesheet draws them (the Main,
 * EmptyBuilder and RailGroup boards): an entry's name is its agent's, wrapped
 * onto at most two lines within the rail's width ("Dataflow Builder", "Node
 * Builder") and cut only past them; what it is attached to is one line in
 * smaller type, cut short with an ellipsis. Held to one line, the names read
 * "Dataflo…" and "Node Bui…" in the rail's 78px.
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
    // Within the rail's width: a word longer than the entry breaks inside it
    // rather than spill past the rail.
    expect(value(".name", "max-width")).toBe("100%");
    expect(value(".name", "overflow-wrap")).toBe("anywhere");
  });

  test("what it is attached to stays on one line, cut short with an ellipsis", () => {
    expect(value(".sub", "max-width")).toBe("100%");
    expect(value(".sub", "white-space")).toBe("nowrap");
    expect(value(".sub", "overflow")).toBe("hidden");
    expect(value(".sub", "text-overflow")).toBe("ellipsis");
  });
});
