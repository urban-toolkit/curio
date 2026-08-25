import React, { useState, useEffect } from "react";

/**
 * How node code is being executed, in the words the docs use.
 *
 * The backend reports the mode the sandbox *resolved*, not the one it was
 * asked for, so this reflects what is actually happening: `auto` resolves to
 * `off`, and a `fork` the platform cannot support degrades to `off`. Anything
 * unrecognised is treated as unknown rather than guessed at -- claiming a
 * boundary that is not there is the one failure mode worth avoiding here.
 */
const ISOLATION_LABELS: Record<string, { label: string; title: string }> = {
  fork: {
    label: "isolated",
    title:
      "Each node's Python runs in a confined child process: memory and CPU " +
      "capped, network denied, and no access to the user database or other " +
      "sessions' artifacts.",
  },
  off: {
    label: "in-process",
    title:
      "Node code runs inside the sandbox process with its full privileges. " +
      "This is the default for a local install; on a shared instance, treat " +
      "node-authoring rights as shell access.",
  },
  unavailable: {
    label: "isolation unavailable",
    title:
      "Isolation was requested but this platform cannot provide it, so node " +
      "code is running in-process.",
  },
};

const VersionBadge: React.FC = () => {
  const [version, setVersion] = useState<string>("");
  const [isolation, setIsolation] = useState<string>("");

  useEffect(() => {
    fetch(process.env.BACKEND_URL + "/version", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        setVersion(d.version);
        setIsolation(d.isolation ?? "");
      })
      .catch(() => {});
  }, []);

  if (!version) return null;

  const mode = ISOLATION_LABELS[isolation];

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
        zIndex: 9999,
        fontFamily: "monospace",
      }}
    >
      {version}
      {mode ? (
        <span
          title={mode.title}
          style={{ pointerEvents: "auto", cursor: "help" }}
        >
          {" · "}
          {mode.label}
        </span>
      ) : null}
    </div>
  );
};

export default VersionBadge;
