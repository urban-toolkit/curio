import React, { useEffect, useMemo, useRef, useState } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faCheck,
  faCopy,
  faTriangleExclamation,
} from "@fortawesome/free-solid-svg-icons";
import styles from "./AgentCodeBlock.module.css";

/**
 * Fenced code block with a copy affordance (memo dev/78). Rendered only
 * through SafeAgentContent's `pre` override, so inline code never gets a
 * button and the REQ-SEC-002 policy is untouched: the copied string is the
 * same inert text the block displays — no re-parse of the raw markdown.
 */

/**
 * Raw text of already-rendered markdown children. For a normal fence this is
 * one `<code>` element wrapping a string, but the recursive form costs
 * nothing and survives whatever child shape react-markdown emits.
 */
export function extractNodeText(node: React.ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string") return node;
  if (typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(extractNodeText).join("");
  if (React.isValidElement(node)) {
    return extractNodeText((node.props as { children?: React.ReactNode }).children);
  }
  return "";
}

type CopyStatus = "idle" | "copied" | "failed";

const FEEDBACK_MS = 1800;

export const AgentCodeBlock: React.FC<{ children?: React.ReactNode }> = ({
  children,
}) => {
  const [status, setStatus] = useState<CopyStatus>("idle");
  const timerRef = useRef<number | undefined>(undefined);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      window.clearTimeout(timerRef.current);
    };
  }, []);

  const code = useMemo(() => {
    // The parser supplies exactly one fence-terminating newline; interior
    // newlines and indentation are content and stay verbatim.
    const raw = extractNodeText(children);
    return raw.endsWith("\n") ? raw.slice(0, -1) : raw;
  }, [children]);

  const copy = async () => {
    window.clearTimeout(timerRef.current);
    let next: CopyStatus;
    try {
      await navigator.clipboard.writeText(code);
      next = "copied";
    } catch (err) {
      console.warn("Copying code block to clipboard failed", err);
      next = "failed";
    }
    if (!mountedRef.current) return;
    setStatus(next);
    timerRef.current = window.setTimeout(() => {
      if (mountedRef.current) setStatus("idle");
    }, FEEDBACK_MS);
  };

  const name =
    status === "copied" ? "Copied" : status === "failed" ? "Copy failed" : "Copy code";

  return (
    <div className={styles.block}>
      <pre>{children}</pre>
      {code.trim() ? (
        <button
          type="button"
          className={[
            styles.copyBtn,
            status !== "idle" ? styles.active : "",
            status === "failed" ? styles.failed : "",
          ]
            .filter(Boolean)
            .join(" ")}
          aria-label={name}
          title="Copy code"
          onClick={copy}
        >
          <FontAwesomeIcon
            icon={
              status === "copied"
                ? faCheck
                : status === "failed"
                  ? faTriangleExclamation
                  : faCopy
            }
            aria-hidden="true"
          />
          <span className={styles.feedback} aria-live="polite">
            {status === "copied" ? "Copied" : status === "failed" ? "Failed" : ""}
          </span>
        </button>
      ) : null}
    </div>
  );
};
