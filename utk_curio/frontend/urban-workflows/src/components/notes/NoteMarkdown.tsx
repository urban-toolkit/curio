import React from "react";
import ReactMarkdown from "react-markdown";

/**
 * A Note's text, drawn as simple markdown: headings, paragraphs, lists, bold,
 * italics, code, quotes and links. The policy, enforced here:
 *
 * - HTML in the text never renders (`skipHtml`, and no rehype-raw), so no tag,
 *   event handler or script reaches the page.
 * - Only an https URL survives (`httpsOnly`). Any other link draws its text
 *   alone, and a link opens in a new tab with `rel="noopener noreferrer"` and
 *   the arrow every new-tab link carries.
 * - An image draws its alt text and fetches nothing.
 * - Any other element draws its text (`unwrapDisallowed`).
 */

/** The elements a note draws. */
const NOTE_ELEMENTS = [
  "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "strong", "em",
  "ul", "ol", "li", "a", "code", "pre", "blockquote", "hr", "img",
];

/** *url* when it is an https URL, else nothing: the link or image loses it. */
export function httpsOnly(url: string): string | undefined {
  try {
    return new URL(url).protocol === "https:" ? url : undefined;
  } catch {
    return undefined;
  }
}

export function NoteMarkdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      skipHtml
      allowedElements={NOTE_ELEMENTS}
      unwrapDisallowed
      urlTransform={(url) => httpsOnly(url)}
      components={{
        a: ({ href, children }) =>
          href ? (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children} ↗
            </a>
          ) : (
            <>{children}</>
          ),
        img: ({ alt }) => (alt ? <>{alt}</> : null),
      }}
    >
      {text}
    </ReactMarkdown>
  );
}
