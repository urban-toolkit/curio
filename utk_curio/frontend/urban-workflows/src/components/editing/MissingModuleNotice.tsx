import React from "react";
import type { MissingModuleNotice as Notice } from "../../types/nodeTypes";
import type { LibraryInstallVerdict } from "../../utils/libraryInstall";

/**
 * What the install is doing right now. Held by the OWNER (CodeEditor), not
 * here: if the user presses Run while pip is still working, the notice's own
 * props go away, and a child-owned state would unmount with the request still
 * in flight.
 */
export type InstallState =
  | { kind: "idle" }
  | { kind: "installing"; distribution: string }
  | { kind: "done"; distribution: string; verdict: LibraryInstallVerdict }
  | { kind: "failed"; distribution: string; message: string };

const WRAP: React.CSSProperties = {
  marginTop: 8,
  padding: "6px 8px",
  borderRadius: 6,
  border: "1px solid #d0a215",
  background: "#fffbeb",
  color: "#7a5c00",
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: 8,
  // The output pane is `white-space: pre-wrap` for the traceback; this notice
  // is prose and must not inherit that.
  whiteSpace: "normal",
};

const BUTTON: React.CSSProperties = {
  border: "1px solid #d0a215",
  borderRadius: 6,
  background: "#fff",
  color: "#7a5c00",
  fontFamily: "inherit",
  fontSize: 11,
  fontWeight: 700,
  padding: "3px 9px",
  cursor: "pointer",
};

/** Why an install cannot be offered, in the user's terms rather than the code's. */
function refusal(notice: Notice): string | null {
  switch (notice.reason) {
    case "stdlib":
      return (
        `${notice.module} is part of Python itself, so installing it is not the ` +
        `fix. This Python looks incomplete.`
      );
    case "curio-provided":
      return `${notice.module} is provided by Curio and cannot be installed separately.`;
    case "installed-but-broken":
      return (
        `${notice.distribution} is installed but cannot be imported, so ` +
        `installing it again would change nothing.` +
        (notice.detail ? ` ${notice.detail}` : "")
      );
    case "install-disabled":
      // Still name the library: knowing what is missing is useful even where
      // this instance will not install it for you (#309).
      return (
        `${notice.distribution ?? notice.module} is not installed.` +
        (notice.detail ? ` ${notice.detail}` : "")
      );
    case "installed-not-visible":
      return (
        `${notice.distribution} is installed here but the node could not import ` +
        `it. Restart Curio and run the node again; if it persists, the code that ` +
        `runs nodes is using a different Python.`
      );
    // "unsafe-name" deliberately says nothing: the module name came from the
    // traceback, which node code controls, so it is not echoed back to the UI.
    default:
      return null;
  }
}

/**
 * Names the library a node run was missing, and offers to install it (#299).
 *
 * Rendered beneath the traceback, never instead of it: the traceback is what a
 * user pastes into a bug report, and the issue asked for a signal alongside it.
 *
 * Installing is deliberately a click rather than automatic, matching
 * `UnresolvedNode` - a pip install can take minutes and reaches the Python
 * every node on this instance shares, which is not something a failed run
 * should start on its own. Re-running afterwards is also a click, for the same
 * reason in reverse: after a multi-minute install the user's attention has
 * moved on, and a node that fires by itself is a surprise.
 */
export const MissingModuleNotice: React.FC<{
  notice: Notice;
  state: InstallState;
  /** True once an install of this module has already been tried in this session. */
  retried: boolean;
  onInstall: (distribution: string) => void;
  onRunNode: () => void;
}> = ({ notice, state, retried, onInstall, onRunNode }) => {
  const distribution = notice.distribution;

  if (state.kind === "installing") {
    return (
      <div style={WRAP} data-curio-missing-module={notice.module}>
        <span>Installing {state.distribution}…</span>
        <button type="button" style={{ ...BUTTON, opacity: 0.6 }} disabled>
          Installing…
        </button>
      </div>
    );
  }

  if (state.kind === "failed") {
    return (
      <div style={WRAP} data-curio-missing-module={notice.module}>
        <span>Couldn&apos;t install {state.distribution}. {state.message}</span>
        <button type="button" style={BUTTON} onClick={() => onInstall(state.distribution)}>
          Try again
        </button>
      </div>
    );
  }

  if (state.kind === "done") {
    if (state.verdict.kind === "cannot-import") {
      // Not "couldn't install": it installed. Same wording as the Installed
      // libraries modal, because it is the same failure.
      return (
        <div style={WRAP} data-curio-missing-module={notice.module}>
          <span>
            {state.distribution} installed, but it cannot be imported.{" "}
            {state.verdict.reason}
          </span>
        </div>
      );
    }
    return (
      <div style={WRAP} data-curio-missing-module={notice.module}>
        <span>
          {state.verdict.kind === "already-installed"
            ? `${state.distribution} was already installed.`
            : `Installed ${state.distribution}.`}
        </span>
        <button type="button" style={BUTTON} onClick={onRunNode}>
          Run node
        </button>
      </div>
    );
  }

  // Idle. A module installed once in this session that is STILL missing is not
  // an install problem, and offering the same button again would just repeat
  // itself. One sentence covers every cause - a stale worker, a version change,
  // a different interpreter - without the UI having to know which.
  if (retried && distribution) {
    return (
      <div style={WRAP} data-curio-missing-module={notice.module}>
        <span>
          {distribution} was installed, but this node still cannot import{" "}
          {notice.module}. Restart Curio and run the node again. If it persists,
          the code that runs nodes is using a different Python — check Installed
          libraries.
        </span>
      </div>
    );
  }

  if (!notice.installable || !distribution) {
    const message = refusal(notice);
    if (!message) return null;
    return (
      <div style={WRAP} data-curio-missing-module={notice.module}>
        <span>{message}</span>
      </div>
    );
  }

  return (
    <div style={WRAP} data-curio-missing-module={notice.module}>
      <span>
        <strong>{distribution}</strong> is not installed.
      </span>
      <button
        type="button"
        style={BUTTON}
        title={`pip install ${distribution} into Curio's Python environment, which is shared by everyone on this instance`}
        onClick={() => onInstall(distribution)}
      >
        Install {distribution}
      </button>
    </div>
  );
};

export default MissingModuleNotice;
