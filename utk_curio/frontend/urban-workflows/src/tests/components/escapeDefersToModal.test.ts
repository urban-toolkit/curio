/**
 * Every `window` Escape listener defers to an open modal.
 *
 * ModalShell routes Escape through a bubble-phase `window` listener, and
 * `stopPropagation` cannot silence a peer listener registered on the same
 * target first. So each surface that closes itself on Escape has to stand down
 * on its own, by asking `modalStackDepth()`.
 *
 * Two of the four already did. The agent chat panel and the fork picker did
 * not, and a modal opened over either one took it down too: AI Settings closed
 * the chat panel behind it, and the fork picker collapsed under any dialog
 * raised from the node dock.
 *
 * Read from disk rather than rendered, the same approach
 * `catalog/canvasDrawerParity.test.ts` takes and for the same reason: rendering
 * AgentChatPanel or ForkFamilyPicker for real needs most of the provider tree,
 * while the assertion is only about a guard being present in the source.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const read = (rel: string) => fs.readFileSync(path.join(SRC, rel), "utf8");

/** Every file that closes something on a `window` keydown Escape. */
const WINDOW_ESCAPE_LISTENERS = [
  "components/packages/publishing/NodeCatalogDrawer.tsx",
  "providers/AgentCatalogDrawerProvider.tsx",
  "components/agents/attach/AgentChatPanel.tsx",
  "components/packages/ForkFamilyPicker.tsx",
];

describe("window Escape listeners defer to an open modal", () => {
  test.each(WINDOW_ESCAPE_LISTENERS)(
    "%s stands down while a modal is open",
    (file) => {
      expect(read(file)).toContain("if (modalStackDepth() > 0) return;");
    },
  );

  test.each(WINDOW_ESCAPE_LISTENERS)(
    "%s still listens on window for Escape",
    (file) => {
      // If one of these moves off window, or stops handling Escape, the guard
      // above is guarding nothing and this list has gone stale.
      const source = read(file);
      expect(source).toContain('window.addEventListener("keydown"');
      expect(source).toContain('"Escape"');
    },
  );

  test("ModalShell still exports the depth the guards read", () => {
    // Two competing Escape implementations reached main in parallel and only
    // one exports this. If the other ever comes back, every guard above
    // silently stops compiling against it.
    expect(read("components/ModalShell.tsx")).toContain(
      "export function modalStackDepth()",
    );
  });
});
