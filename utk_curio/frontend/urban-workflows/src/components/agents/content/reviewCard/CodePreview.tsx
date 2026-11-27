import React, { useId, useState } from "react";

import styles from "../AgentReviewCard.module.css";

/** How many of its lines a change's code shows before Show all. */
export const PREVIEW_LINES = 8;

/** A change's code, model output rendered inert (REQ-SEC-002): its first
 * lines, then Show all, which shows the rest in place; short code shows
 * whole. */
export const CodePreview: React.FC<{ text: string }> = ({ text }) => {
  const [whole, setWhole] = useState(false);
  const id = useId();
  const lines = text.split("\n");
  // One line over the cut is shown rather than folded behind a button.
  const long = lines.length > PREVIEW_LINES + 1;
  const shown = long && !whole ? lines.slice(0, PREVIEW_LINES).join("\n") : text;
  return (
    <>
      <div id={id} className={`${styles.preview} ${whole ? styles.previewWhole : ""}`}>
        {shown}
      </div>
      {long ? (
        <button
          type="button"
          className={styles.codeToggle}
          aria-expanded={whole}
          aria-controls={id}
          onClick={() => setWhole((open) => !open)}
        >
          {whole ? "Show less" : `Show all ${lines.length} lines`}
        </button>
      ) : null}
    </>
  );
};
