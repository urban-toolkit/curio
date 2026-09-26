import React from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router-dom";
import { agentLinkAppPath, sanitizeAgentUrl } from "./sanitizeAgentContent";
import { AgentCodeBlock } from "./AgentCodeBlock";

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
 * - A link to a Curio page goes through the router in the same tab, and
 *   `onInternalLink` decides how (the chat panel asks before leaving unsaved
 *   work). Any other link opens in a new tab with `rel="noopener noreferrer"`
 *   and the "↗" every new-tab link carries.
 *
 * User bubbles stay plain text (the user's own words need no markdown); card
 * fields never pass through here either (cards are plain data by contract).
 */
export const SafeAgentContent: React.FC<{
  text: string;
  /** Follows a link to a Curio page. Left out, it navigates like any in-app
   *  link. */
  onInternalLink?: (path: string) => void;
}> = ({ text, onInternalLink }) => (
  <ReactMarkdown
    urlTransform={(url: string) => sanitizeAgentUrl(url) ?? ""}
    components={{
      a: ({ href, children }) => {
        if (!href) return <>{children}</>;
        const appPath = agentLinkAppPath(href);
        if (appPath) {
          return (
            <Link
              to={appPath}
              onClick={(event) => {
                if (!onInternalLink) return;
                if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
                event.preventDefault();
                onInternalLink(appPath);
              }}
            >
              {children}
            </Link>
          );
        }
        if (href.startsWith("mailto:")) return <a href={href}>{children}</a>;
        return (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children} ↗
          </a>
        );
      },
      // A sanitized-away image src must not leave an empty <img> behind.
      img: ({ src, alt }) => (src ? <img src={src} alt={alt ?? ""} /> : null),
      // Fenced code gets the copy affordance (dev/78); inline code has no
      // <pre> parent and stays untouched.
      pre: ({ children }) => <AgentCodeBlock>{children}</AgentCodeBlock>,
    }}
  >
    {text}
  </ReactMarkdown>
);
