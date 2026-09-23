import React, { useMemo, useState } from "react";
import type { MonitorError, MonitorErrorSource } from "../../api/monitorApi";
import styles from "./ErrorLogPanel.module.css";

const SOURCES: MonitorErrorSource[] = ["node", "sandbox", "backend", "client"];

const SOURCE_TONE: Record<MonitorErrorSource, string> = {
  node: styles.sourceNode,
  sandbox: styles.sourceSandbox,
  backend: styles.sourceBackend,
  client: styles.sourceClient,
};

/**
 * Recent failures, newest first.
 *
 * SECURITY, and this is not incidental. `summary` and `detail` are rendered as
 * TEXT and must stay that way. Client entries arrive from
 * `POST /api/monitor/errors/client`, which is public and unauthenticated, so
 * an attacker chooses those strings exactly. React escapes children by
 * default, which is the whole defence; nothing in this file may reach for
 * dangerouslySetInnerHTML, a markdown renderer, or any "just linkify the
 * paths" helper. This is the one place where treating a log line as harmless
 * would be a stored XSS on a page operators open.
 *
 * The entries themselves are raw by product decision: absolute paths, node
 * code fragments and traceback values all appear here. See
 * `utk_curio/backend/app/monitor/errors.py`.
 */
export const ErrorLogPanel: React.FC<{
  errors: MonitorError[];
  droppedClient: number;
  loading: boolean;
}> = ({ errors, droppedClient, loading }) => {
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const counts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const source of SOURCES) out[source] = 0;
    for (const entry of errors) {
      out[entry.source] = (out[entry.source] ?? 0) + 1;
    }
    return out;
  }, [errors]);

  const visible = errors.filter((entry) => !hidden.has(entry.source));

  const toggleSource = (source: string) => {
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(source)) next.delete(source);
      else next.add(source);
      return next;
    });
  };

  const toggleRow = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className={styles.panel}>
      <div className={styles.filters}>
        {SOURCES.map((source) => (
          <button
            key={source}
            type="button"
            onClick={() => toggleSource(source)}
            aria-pressed={!hidden.has(source)}
            className={[
              styles.filter,
              hidden.has(source) ? styles.filterOff : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {source} ({counts[source] ?? 0})
          </button>
        ))}
        {droppedClient > 0 ? (
          <span className={styles.dropped}>
            {droppedClient} browser report{droppedClient === 1 ? "" : "s"} dropped
          </span>
        ) : null}
      </div>

      {visible.length === 0 ? (
        <p className={styles.empty}>
          {loading
            ? "Loading…"
            : errors.length === 0
            ? "No errors since launch."
            : "No errors from the selected sources."}
        </p>
      ) : (
        <ul className={styles.list}>
          {visible.map((entry, index) => {
            const key = `${entry.at}-${entry.source}-${index}`;
            const isOpen = expanded.has(key);
            return (
              <li key={key} className={styles.row}>
                <button
                  type="button"
                  className={styles.rowHead}
                  onClick={() => toggleRow(key)}
                  aria-expanded={isOpen}
                >
                  <span className={styles.time}>{entry.at}</span>
                  <span
                    className={[styles.source, SOURCE_TONE[entry.source]]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {entry.source}
                  </span>
                  <span className={styles.summary}>{entry.summary}</span>
                  {entry.count > 1 ? (
                    <span className={styles.count}>x{entry.count}</span>
                  ) : null}
                </button>
                {isOpen && entry.detail ? (
                  <pre className={styles.detail}>{entry.detail}</pre>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default ErrorLogPanel;
