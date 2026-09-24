import React, { useState, useEffect } from "react";
import { backendUrl } from "../utils/backendUrl";

/**
 * How node code is being executed, in the words the docs use.
 *
 * The backend reports the mode the sandbox *resolved*, not the one it was
 * asked for: `auto` resolves to `off`, and a `fork` the platform cannot
 * support degrades to `off`. It also reports what execution actually did,
 * which is not the same question -- see `resolveIsolationKey` below. Anything
 * unrecognised is treated as unknown rather than guessed at -- claiming a
 * boundary that is not there is the one failure mode worth avoiding here.
 */
export const ISOLATION_LABELS: Record<string, { label: string; title: string }> = {
  fork: {
    label: "isolated",
    title:
      "Each node's Python runs in a confined child process: memory and CPU " +
      "capped, network denied, and no access to the user database or other " +
      "sessions' artifacts.",
  },
  off: {
    label: "not isolated",
    title:
      "Node code runs inside the sandbox process with its full privileges. " +
      "This is the default for a local install; on a shared instance, treat " +
      "node-authoring rights as shell access.",
  },
  // Same label, different reason. "isolation unavailable" would have been a
  // third state to interpret, when the fact a reader needs is the one they
  // already have from `off`: there is no boundary. Why there isn't one is a
  // tooltip's job.
  unavailable: {
    label: "not isolated",
    title:
      "Isolation was requested but this platform cannot provide it, so node " +
      "code is running with the sandbox's full privileges.",
  },
  // Configured for isolation, not delivering it. The confined child is started
  // on the first node run, and a failure there is not fatal -- the node still
  // has to execute -- so the sandbox falls back to running it in-process and
  // stays that way. `isolation` keeps reporting `fork`, which is why this
  // state cannot be read off it.
  degraded: {
    label: "not isolated",
    title:
      "This instance is configured for isolation, but the confined child " +
      "could not be started, so node code is running with the sandbox's full " +
      "privileges. Check the sandbox log for 'falling back to in-process " +
      "execution'.",
  },
};

/**
 * Which of the labels above to show, from the two fields `/version` reports.
 *
 * `isolation` is the mode the sandbox RESOLVED and `isolation_active` is what
 * execution actually did, so only the second can reveal a stack that resolved
 * `fork` and is running in-process anyway. An explicit `off` there overrides
 * the resolved mode; nothing else does.
 *
 * Deliberately narrow. `pending` means no node has run yet, which is the
 * normal state on a freshly loaded page and is not evidence of anything, and
 * an older sandbox or an unreachable one sends `unknown`. Treating either as
 * a downgrade would show "not isolated" on a perfectly isolated instance,
 * which is the mirror of the bug this exists to prevent and would teach
 * operators to distrust the badge.
 */
export const resolveIsolationKey = (
  isolation: string,
  isolationActive: string,
): string => (isolationActive === "off" ? "degraded" : isolation);

const VersionBadge: React.FC = () => {
  const [version, setVersion] = useState<string>("");
  const [isolation, setIsolation] = useState<string>("");
  const [isolationActive, setIsolationActive] = useState<string>("");

  useEffect(() => {
    fetch(backendUrl() + "/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        setVersion(d.version);
        setIsolation(d.isolation ?? "");
        setIsolationActive(d.isolation_active ?? "");
      })
      .catch(() => {});
  }, []);

  if (!version) return null;

  const mode = ISOLATION_LABELS[resolveIsolationKey(isolation, isolationActive)];

  return (
    <div
      style={{
        position: "fixed",
        bottom: 8,
        right: 12,
        fontSize: 11,
        color: "#666",
        // The mode carries a tooltip, so this element has to be hoverable --
        // the badge used to opt out of pointer events entirely.
        pointerEvents: "none",
        userSelect: "none",
        // On the layering scale (curioTokens.css), not a bare literal. The
        // badge is page furniture: below every drawer and modal, above the
        // page background. The full-page shells reserve
        // --curio-version-badge-reserve so nothing reaches under it (#236).
        zIndex: "var(--curio-z-version-badge)" as unknown as number,
        fontFamily: "monospace",
      }}
    >
      {version}
      {mode ? (
        <span
          title={mode.title}
          style={{ pointerEvents: "auto", cursor: "help" }}
        >
          {` (${mode.label})`}
        </span>
      ) : null}
    </div>
  );
};

export default VersionBadge;
