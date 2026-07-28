import React from "react";
import ReactMarkdown from "react-markdown";
import { sanitizeAgentUrl } from "./sanitizeAgentContent";

/**
 * The ONLY renderer for agent/model rich content (memo dev/39; REQ-SEC-002,
 * the blueprint's `SafeAgentContent`). Policy, all enforced here and nowhere
 * else:
 *
 * - Markdown renders; **raw HTML never does** — no `rehype-raw`, so HTML in
 *   the source is treated as inert text/skipped by react-markdown, and event
 *   handlers or `<script>` can never reach the DOM.
 * - Link/image URLs pass through `sanitizeAgentUrl` (http(s)/mailto only);
 *   anything else is dropped.
 * - Links open in a new tab with `rel="noopener noreferrer"`.
 *
 * User bubbles stay plain text (the user's own words need no markdown); card
 * fields never pass through here either (cards are plain data by contract).
 */
export const SafeAgentContent: React.FC<{ text: string }> = ({ text }) => (
  <ReactMarkdown
    urlTransform={(url: string) => sanitizeAgentUrl(url) ?? ""}
    components={{
      a: ({ href, children }) =>
        href ? (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ) : (
          <>{children}</>
        ),
      // A sanitized-away image src must not leave an empty <img> behind.
      img: ({ src, alt }) => (src ? <img src={src} alt={alt ?? ""} /> : null),
    }}
  >
    {text}
  </ReactMarkdown>
);
