import fs from "fs";
import path from "path";

import { declaredValue } from "../_support/cssRules";

/**
 * The chat header's one row as its stylesheet draws it (the Main board): what
 * the agent is attached to ("on the canvas", "on Load buildings", "from Load
 * buildings to Join blocks") reads whole beside the conversation's title. The
 * title gives way first: it shrinks and is cut short with an ellipsis, while
 * the target keeps its words up to 45% of the row and is cut only past that.
 * When both shrank, the header read "Node Builder: This is a scripted test…
 * on the can…".
 *
 * Source-read: Jest maps CSS modules to `identity-obj-proxy`, so a rendered
 * assertion cannot see which rules apply. The header's words are read in
 * AgentChatPanel.test.tsx.
 */
const PANEL = fs.readFileSync(
  path.resolve(__dirname, "../../components/agents/attach/AgentChatPanel.module.css"),
  "utf8",
);
const value = (selector: string, property: string) => declaredValue(PANEL, selector, property);

describe("the chat header's title and target", () => {
  test("the title gives way before the target, whose words stay whole up to 45% of the row", () => {
    // The title shrinks, cut short on one line.
    expect(value(".title", "flex")).toBe("0 1 auto");
    expect(value(".title", "min-width")).toBe("0");
    expect(value(".title", "white-space")).toBe("nowrap");
    expect(value(".title", "overflow")).toBe("hidden");
    expect(value(".title", "text-overflow")).toBe("ellipsis");
    // The target does not shrink below its words, up to its cap...
    expect(value(".headerTarget", "flex")).toBe("none");
    expect(value(".headerTarget", "max-width")).toBe("45%");
    // ...and past the cap it is cut short on one line too.
    expect(value(".headerTarget", "white-space")).toBe("nowrap");
    expect(value(".headerTarget", "overflow")).toBe("hidden");
    expect(value(".headerTarget", "text-overflow")).toBe("ellipsis");
  });
});
