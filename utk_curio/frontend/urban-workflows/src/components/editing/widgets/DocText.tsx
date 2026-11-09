import React from "react";
import { docParts } from "../../../contracts/docMarkup";
import styles from "./DocText.module.css";

/**
 * What a function does, as the first paragraph of its docstring or the page
 * that lists Curio's functions says it, with its marks shown and never
 * written out: code in the code font, emphasis in italics, strong in bold
 * (`docParts`, contracts/docMarkup.json). Where a hover under Functions, a
 * package's details and New node from a Python function show it.
 */
export function DocText({ doc }: { doc: string }) {
  return (
    <>
      {docParts(doc).map((part, i) => {
        if (part.kind === "code") {
          return (
            <code key={i} className={styles.code}>
              {part.text}
            </code>
          );
        }
        if (part.kind === "strong") return <strong key={i}>{part.text}</strong>;
        if (part.kind === "emphasis") return <em key={i}>{part.text}</em>;
        return <React.Fragment key={i}>{part.text}</React.Fragment>;
      })}
    </>
  );
}
