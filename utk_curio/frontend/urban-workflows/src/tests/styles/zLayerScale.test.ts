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
        // Page furniture: the fixed version badge, below everything that can
        // open over a page. It used to hard-code a bare 9999 (#236).
        "version-badge",
        // Base tier: a modal opened from a page, with no canvas overlays under
        // it. ModalShell used to hard-code 499/500 for this while reading the
        // scale for its overlay tier, so half the component sat outside it.
        "modal-base",
        "modal-base-backdrop",
        // High band: anything that can stack over the canvas.
        "agent-drawer",
        // An agent's drag on the canvas, from the rail or a drawer's card.
        "agent-drags",
        "dataset-drawer",
        "header-drawer",
        "dialog",
        "modal",
        "modal-backdrop",
        "node-drawer",
        "toast",
        // Over everything, toasts included: the one Curio tooltip.
        "tooltip",
      ].sort(),
    );
  });

  it("keeps the version badge below every tier that can open over a page", () => {
    // The badge is decoration in a corner; anything the user deliberately
    // opened outranks it. #236 was the badge painting OVER the catalog
    // drawer's own content, which a bare 9999 made inevitable.
    for (const tier of Object.entries(layers)) {
      const [name, z] = tier;
      if (name === "version-badge") continue;
      expect(layers["version-badge"]).toBeLessThan(z);
    }
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
      layers["header-drawer"],
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
    // API Settings opens over any catalog drawer, and under any modal.
    for (const drawer of ["node-drawer", "dataset-drawer", "agent-drawer"]) {
      expect(layers[drawer]).toBeLessThan(layers["header-drawer"]);
    }
    expect(layers["header-drawer"]).toBeLessThan(layers["modal-backdrop"]);
    expect(layers["modal-backdrop"]).toBeLessThan(layers["modal"]);
    expect(layers["modal"]).toBeLessThan(layers["dialog"]);
  });

  it("keeps an agent's drag over the catalog drawers and under API Settings", () => {
    // A drag starts at a drawer's card or in the tool rail, so its cursor and
    // ghost draw over both; API Settings and every modal still cover it.
    for (const drawer of ["node-drawer", "dataset-drawer", "agent-drawer"]) {
      expect(layers["agent-drags"]).toBeGreaterThan(layers[drawer]);
    }
    expect(layers["agent-drags"]).toBeLessThan(layers["header-drawer"]);
  });

  it("keeps the tooltip above every other tier, toasts included", () => {
    // The one Curio tooltip shows over whatever the pointer rests on: a
    // drawer, a modal, a toast. At z 1080, Bootstrap's tooltips drew under
    // Curio's drawers.
    expect(layers["tooltip"]).toBeDefined();
    expect(layers["tooltip"]).toBeGreaterThan(layers["toast"]);
    for (const [name, z] of Object.entries(layers)) {
      if (name === "tooltip") continue;
      expect(layers["tooltip"]).toBeGreaterThan(z);
    }
  });
});
