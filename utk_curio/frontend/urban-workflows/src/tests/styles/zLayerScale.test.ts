import fs from "fs";
import path from "path";

/**
 * Guard the overlay / layering scale defined in curioTokens.css.
 *
 * The reported bug was that dataset action toasts (z 10000) rendered
 * BEHIND the Dataset Catalog drawer (z 10045). This test locks in the
 * invariant that the toast layer sits strictly above every overlay tier,
 * so a future edit to the scale cannot silently re-bury toasts.
 */

const TOKENS_CSS = path.join(__dirname, "../../styles/curioTokens.css");

function readZLayers(): Record<string, number> {
  const css = fs.readFileSync(TOKENS_CSS, "utf8");
  const layers: Record<string, number> = {};
  const re = /--curio-z-([a-z-]+):\s*(\d+);/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(css)) !== null) {
    layers[m[1]] = Number(m[2]);
  }
  return layers;
}

describe("overlay / layering scale (curioTokens.css)", () => {
  const layers = readZLayers();

  it("defines every tier in the scale", () => {
    expect(Object.keys(layers).sort()).toEqual(
      [
        // Base tier: a modal opened from a page, with no canvas overlays under
        // it. ModalShell used to hard-code 499/500 for this while reading the
        // scale for its overlay tier, so half the component sat outside it.
        "modal-base",
        "modal-base-backdrop",
        // High band: anything that can stack over the canvas.
        "agent-drawer",
        "dataset-drawer",
        "dialog",
        "modal",
        "modal-backdrop",
        "node-drawer",
        "toast",
      ].sort(),
    );
  });

  it("keeps the base modal tier below the whole overlay band", () => {
    // A page modal must not outrank a canvas drawer: they never coexist, and
    // the day one does, the drawer is the thing that was opened last.
    expect(layers["modal-base-backdrop"]).toBeLessThan(layers["modal-base"]);
    expect(layers["modal-base"]).toBeLessThan(layers["node-drawer"]);
  });

  it("keeps toasts strictly above the entire overlay band", () => {
    const overlayBand = [
      layers["node-drawer"],
      layers["dataset-drawer"],
      layers["modal-backdrop"],
      layers["modal"],
      layers["dialog"],
    ];
    for (const tier of overlayBand) {
      expect(layers["toast"]).toBeGreaterThan(tier);
    }
  });

  it("preserves the relative ordering of the overlay tiers", () => {
    // Modals/dialogs stack above the drawers; the dataset drawer sits above
    // the node drawer. (DatasetDetailModal opens on top of the drawer.)
    expect(layers["node-drawer"]).toBeLessThan(layers["dataset-drawer"]);
    expect(layers["dataset-drawer"]).toBeLessThan(layers["modal-backdrop"]);
    expect(layers["modal-backdrop"]).toBeLessThan(layers["modal"]);
    expect(layers["modal"]).toBeLessThan(layers["dialog"]);
  });
});
