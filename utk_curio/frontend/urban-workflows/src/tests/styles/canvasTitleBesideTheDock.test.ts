import fs from "fs";
import path from "path";
import { DOCK_LEFT_PROPERTY } from "../../components/agents/attach/AgentDock";

/**
 * The canvas title stops before the agents' dock on its row.
 *
 * The title sits at the top left and the dock at the top middle; a long
 * dataflow name was drawn over the dock, its Goal label and the start of the
 * goal. The title is now one line, cut short with an ellipsis where the dock
 * starts, the edge the dock publishes (AgentDock.test.tsx), as a node's title
 * is cut in its header.
 *
 * Source-read for the reason agentDockGoalGeometry.test.ts gives: Jest maps
 * CSS modules to identity-obj-proxy, and jsdom lays nothing out; and UpMenu
 * needs the whole provider stack to mount, as upMenuRename.test.ts says.
 * test_canvas_title_beside_the_dock_e2e.py measures it in a browser and
 * hovers it.
 */
const CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/menus/top/UpMenu.module.css"),
  "utf8",
);
const UP_MENU = fs.readFileSync(
  path.resolve(__dirname, "../../components/menus/top/UpMenu.tsx"),
  "utf8",
);
const NODE_TITLE_CSS = fs.readFileSync(
  path.resolve(__dirname, "../../components/packages/editing/EditableNodeHeaderLabel.module.css"),
  "utf8",
);

function ruleBody(css: string, selector: string): string | null {
  const at = css.indexOf("\n" + selector + " {");
  if (at === -1) return null;
  const open = css.indexOf("{", at);
  const close = css.indexOf("}", open);
  return close === -1 ? null : css.slice(open + 1, close);
}

const CUT_SHORT = ["overflow: hidden;", "text-overflow: ellipsis;", "white-space: nowrap;"];

describe("the canvas title beside the agents' dock", () => {
  it("is one line, cut short with an ellipsis as a node's title is", () => {
    const title = ruleBody(CSS, ".workflowNameStyle") ?? "";
    const nodeTitle = ruleBody(NODE_TITLE_CSS, ".labelText") ?? "";
    for (const declaration of CUT_SHORT) {
      expect(nodeTitle).toContain(declaration);
      expect(title).toContain(declaration);
    }
  });

  it("stops before the left edge the dock publishes", () => {
    expect(DOCK_LEFT_PROPERTY).toBe("--curio-canvas-dock-left");
    const maxWidth = (ruleBody(CSS, ".workflowNameStyle") ?? "").match(/\n\s*max-width:([^;]*);/);
    expect(maxWidth?.[1]).toContain(`var(${DOCK_LEFT_PROPERTY})`);
  });

  it("keeps the window's width with no dock on its row, the edge's default", () => {
    // What the title reads once the dock takes its edge off the page's root.
    const tokens = fs.readFileSync(path.resolve(__dirname, "../../styles/curioTokens.css"), "utf8");
    expect(tokens).toMatch(new RegExp(`\\n\\s*${DOCK_LEFT_PROPERTY}:\\s*100vw;`));
  });

  it("gives the whole name as its tooltip", () => {
    // The title's own element: the heading drawn with the style above.
    const heading = UP_MENU.slice(
      UP_MENU.indexOf("className={styles.workflowNameStyle}"),
      UP_MENU.indexOf("</h1>", UP_MENU.indexOf("className={styles.workflowNameStyle}")),
    );
    expect(heading).toContain("data-tooltip={workflowName}");
  });
});
