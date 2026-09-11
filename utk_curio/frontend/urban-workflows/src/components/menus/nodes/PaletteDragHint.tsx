import React from "react";
import styles from "./PaletteDragHint.module.css";

export interface PaletteDragHintProps {
  /** What the rows in this palette are, singular: "dataset", "node", "agent". */
  item: string;
  /**
   * Whether these rows can be dropped ON a node, or only onto the canvas.
   *
   * Only agents attach to a node - that is what an agent IS, a thing bound to a
   * node's hook. A dataset or a package dropped on a node does nothing; both
   * become new nodes on the canvas. Saying "onto a node or the canvas" for all
   * three would have been consistent and wrong for two of them.
   */
  attachesToNode?: boolean;
}

/**
 * The one-line "how do I use these rows" note, shared by all three palettes.
 *
 * Every palette lists draggable rows and none of them said so. The Agent one
 * mentioned dragging in a source comment ("drag to attach - handled in
 * MainCanvas"), which is exactly the wrong audience: the person who needs to
 * know is looking at the panel, not the file.
 *
 * One component rather than three strings, because three strings is how the
 * catalogs ended up with three of everything else.
 */
export const PaletteDragHint: React.FC<PaletteDragHintProps> = ({
  item,
  attachesToNode = false,
}) => (
  <p className={styles.hint}>
    {attachesToNode
      ? `Drag ${aOrAn(item)} ${item} onto a node or the canvas to attach it.`
      : `Drag ${aOrAn(item)} ${item} onto the canvas to add it.`}
  </p>
);

/** "a dataset", "an agent" - the article the word actually takes. */
function aOrAn(word: string): string {
  return /^[aeiou]/i.test(word) ? "an" : "a";
}

export default PaletteDragHint;
