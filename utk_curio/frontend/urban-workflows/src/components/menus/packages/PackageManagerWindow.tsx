import React, { useCallback, useEffect, useMemo, useState } from "react";
import styles from "./PackageManagerWindow.module.css";
import ModalShell from "../../ModalShell";
import { packagesApi } from "../../../api/packagesApi";

/**
 * Installed libraries modal.
 *
 * Two populations sit side-by-side in a single flat list:
 *
 * - **Standalone** libraries the user adds here (pip-installed into
 *   Curio's interpreter — JS install is not yet supported but the data
 *   model already accepts the ``kind`` discriminator).
 * - **From packages** — libraries declared by an installed node
 *   package's ``manifest.dependencies.{python,js}``. Read-only here;
 *   uninstall the parent package from /catalog to drop them.
 *
 * Per-user persistence: see backend ``packages/libraries.py``.
 *
 * Install UX: pip is sync — the HTTP request blocks until done — so
 * progress is **indeterminate** (no % from pip itself). We track an
 * "installing" status per spec so the user gets:
 *   - the row appearing immediately with a striped progress bar,
 *   - a green check + "installed" badge for ~4 s on success,
 *   - an inline error if pip fails.
 */

type Kind = "python" | "js";

type Row = {
  name: string;
  spec: string;
  kind: Kind;
  source: string; // "standalone" or "<package>@<major>"
  // For package-declared python deps: whether it is actually present in the
  // interpreter (a package can declare a dep that was never installed or was
  // later pip-uninstalled). undefined/null for standalone + js rows.
  installed?: boolean | null;
};

type Status =
  | { kind: "installing"; spec: string; libKind: Kind }
  | { kind: "removing";   spec: string; libKind: Kind }
  | { kind: "success";    spec: string; libKind: Kind; alreadyInstalled?: boolean }
  | { kind: "error";      spec: string; libKind: Kind; message: string };

// Floor on the visible duration of the progress bar. Pip's "already
// satisfied" path returns in microseconds; without this gate the bar
// would flash too fast to register. 800 ms is short enough to not feel
// laggy but long enough that the user actually sees the install motion.
const MIN_PROGRESS_MS = 800;

function splitSpec(spec: string): { name: string; version: string } {
  const m = spec.match(/^([^=<>~!@]+)([=<>~!].*|@.*)?$/);
  if (!m) return { name: spec, version: "" };
  const v = m[2] || "";
  return { name: m[1], version: v.startsWith("@") ? v.slice(1) : v };
}

export default function PackageManagerWindow({
  open,
  closeModal,
}: {
  open: boolean;
  closeModal: () => void;
}) {
  const [standalone, setStandalone] = useState<{ python: string[]; js: string[] }>({ python: [], js: [] });
  const [fromPackages, setFromPackages] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newSpec, setNewSpec] = useState("");
  const [newKind, setNewKind] = useState<Kind>("python");
  // Per-row status. Keyed by `${kind}::${spec}` so the install/remove of
  // one row doesn't lock out actions on every other row simultaneously.
  const [statuses, setStatuses] = useState<Record<string, Status>>({});

  const statusKey = (kind: Kind, spec: string) => `${kind}::${spec}`;
  const setStatus = useCallback((kind: Kind, spec: string, s: Status | null) => {
    setStatuses((prev) => {
      const next = { ...prev };
      const k = statusKey(kind, spec);
      if (s === null) delete next[k]; else next[k] = s;
      return next;
    });
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await packagesApi.listLibraries();
      setStandalone(data.standalone);
      setFromPackages(data.fromPackages);
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) void reload();
  }, [open, reload]);

  const rows: Row[] = useMemo(() => {
    const out: Row[] = [];
    for (const spec of standalone.python) {
      const { name, version } = splitSpec(spec);
      out.push({ name, spec: version, kind: "python", source: "standalone" });
    }
    for (const spec of standalone.js) {
      const { name, version } = splitSpec(spec);
      out.push({ name, spec: version, kind: "js", source: "standalone" });
    }
    out.push(...fromPackages);
    return out.sort((a, b) =>
      a.name.localeCompare(b.name) || a.kind.localeCompare(b.kind),
    );
  }, [standalone, fromPackages]);

  // An "in-flight" row that isn't in the rows list yet — drawn at the top
  // with the striped progress bar so the user sees their install land
  // immediately (before the POST returns).
  const optimisticInstalls: Status[] = useMemo(
    () => Object.values(statuses).filter((s) => s.kind === "installing"),
    [statuses],
  );

  const installRows = useMemo(() => {
    const known = new Set<string>();
    for (const r of rows) {
      const fullSpec = r.spec
        ? `${r.name}${r.kind === "js" ? "@" : ""}${r.spec}`
        : r.name;
      known.add(`${r.kind}::${fullSpec}`);
    }
    return optimisticInstalls.filter(
      (s) => s.kind === "installing" && !known.has(`${s.libKind}::${s.spec}`),
    );
  }, [optimisticInstalls, rows]);

  const handleAdd = useCallback(async () => {
    const spec = newSpec.trim();
    if (!spec) return;
    setStatus(newKind, spec, { kind: "installing", spec, libKind: newKind });
    setError(null);
    setNewSpec(""); // clear input so the user can queue another while pip runs
    const startedAt = Date.now();
    try {
      const data = await packagesApi.addLibrary(newKind, spec);
      // Hold the "Installing…" bar visible for at least MIN_PROGRESS_MS so
      // already-satisfied deps (pip skip path: <50 ms) still register
      // visually. Subtract the elapsed real wait — a slow pip install
      // sees no extra delay.
      const elapsed = Date.now() - startedAt;
      if (elapsed < MIN_PROGRESS_MS) {
        await new Promise((r) => window.setTimeout(r, MIN_PROGRESS_MS - elapsed));
      }
      setStandalone(data.standalone);
      const alreadyInstalled = (data.installed?.length ?? 0) === 0 && (data.skipped?.length ?? 0) > 0;
      setStatus(newKind, spec, {
        kind: "success", spec, libKind: newKind, alreadyInstalled,
      });
      // Auto-clear the success badge after 4 s so the row settles back
      // to the default state without lingering visual chrome.
      window.setTimeout(() => setStatus(newKind, spec, null), 4000);
    } catch (e: any) {
      setStatus(newKind, spec, {
        kind: "error", spec, libKind: newKind,
        message: e?.message || String(e),
      });
    }
  }, [newSpec, newKind, setStatus]);

  const handleRemove = useCallback(async (kind: Kind, fullSpec: string) => {
    setStatus(kind, fullSpec, { kind: "removing", spec: fullSpec, libKind: kind });
    setError(null);
    try {
      const data = await packagesApi.removeLibrary(kind, fullSpec);
      setStandalone(data.standalone);
      setStatus(kind, fullSpec, null);
    } catch (e: any) {
      setStatus(kind, fullSpec, {
        kind: "error", spec: fullSpec, libKind: kind,
        message: e?.message || String(e),
      });
    }
  }, [setStatus]);

  const dismissStatus = useCallback((kind: Kind, spec: string) => {
    setStatus(kind, spec, null);
  }, [setStatus]);

  if (!open) return null;

  const renderStatusCell = (kind: Kind, fullSpec: string) => {
    const s = statuses[statusKey(kind, fullSpec)];
    if (!s) return null;
    if (s.kind === "installing") {
      return (
        <div className={styles.statusInstalling} title="Installing…">
          <div className={styles.progressBar}><div className={styles.progressStripe} /></div>
          <span>Installing…</span>
        </div>
      );
    }
    if (s.kind === "removing") {
      return (
        <div className={styles.statusInstalling} title="Removing…">
          <div className={styles.progressBar}><div className={styles.progressStripe} /></div>
          <span>Removing…</span>
        </div>
      );
    }
    if (s.kind === "success") {
      return (
        <span className={styles.statusSuccess}>
          {s.alreadyInstalled ? "✓ Already installed" : "✓ Installed"}
        </span>
      );
    }
    return (
      <div className={styles.statusErrorInline}>
        <span title={s.message}>⚠ Failed</span>
        <button
          type="button"
          className={styles.statusDismiss}
          onClick={() => dismissStatus(kind, fullSpec)}
          title="Dismiss"
        >×</button>
      </div>
    );
  };

  const errorStatuses = Object.values(statuses).filter(
    (s): s is Extract<Status, { kind: "error" }> => s.kind === "error",
  );

  return (
    <ModalShell onClose={closeModal}>
      <div className={styles.container}>
        <h2 className={styles.title}>Installed libraries</h2>
        <p className={styles.subtitle}>
          Python and JavaScript libraries available to Curio — added directly here, or pulled in by installed node packages.
        </p>

        <div className={styles.addRow}>
          <select
            className={styles.input}
            style={{ width: 110, flex: "0 0 auto" }}
            value={newKind}
            onChange={(e) => setNewKind(e.target.value as Kind)}
          >
            <option value="python">Python</option>
            <option value="js">JavaScript</option>
          </select>
          <input
            className={styles.input}
            type="text"
            placeholder={newKind === "python" ? "e.g. numpy or scikit-learn==1.4.0" : "e.g. lodash@^4.17 (coming soon)"}
            value={newSpec}
            onChange={(e) => setNewSpec(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleAdd(); }}
          />
          <button
            className={styles.addButton}
            onClick={() => void handleAdd()}
            disabled={!newSpec.trim()}
          >
            Add
          </button>
        </div>

        {error && (
          <div className={styles.logError}>
            <strong>Error:</strong>
            <pre className={styles.logOutput}>{error}</pre>
          </div>
        )}

        {errorStatuses.length > 0 && (
          <div className={styles.errorList}>
            {errorStatuses.map((s) => (
              <div key={`err-${s.libKind}-${s.spec}`} className={styles.logError}>
                <div className={styles.errorHeader}>
                  <strong>Couldn't install {s.spec}</strong>
                  <button
                    type="button"
                    className={styles.statusDismiss}
                    onClick={() => dismissStatus(s.libKind, s.spec)}
                  >×</button>
                </div>
                <pre className={styles.logOutput}>{s.message}</pre>
              </div>
            ))}
          </div>
        )}

        <div className={styles.packageList}>
          {loading && <p className={styles.empty}>Loading…</p>}
          {!loading && rows.length === 0 && installRows.length === 0 && (
            <p className={styles.empty}>No libraries installed.</p>
          )}
          {!loading && (rows.length > 0 || installRows.length > 0) && (
            <table className={styles.libraryTable}>
              <thead>
                <tr>
                  <th>Library</th>
                  <th>Version</th>
                  <th>Kind</th>
                  <th>Source</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {installRows.map((s) => {
                  const { name, version } = splitSpec(s.spec);
                  return (
                    <tr key={`pending-${s.libKind}-${s.spec}`} className={styles.rowPending}>
                      <td className={styles.cellName}>{name}</td>
                      <td className={styles.cellSpec}>{version || "—"}</td>
                      <td>{s.libKind === "python" ? "Python" : "JavaScript"}</td>
                      <td className={styles.cellSource}>
                        <span className={styles.sourceStandalone}>standalone</span>
                      </td>
                      <td>{renderStatusCell(s.libKind, s.spec)}</td>
                      <td />
                    </tr>
                  );
                })}
                {rows.map((r, i) => {
                  const fullSpec = r.spec
                    ? `${r.name}${r.kind === "js" ? "@" : ""}${r.spec}`
                    : r.name;
                  const status = statuses[statusKey(r.kind, fullSpec)];
                  return (
                    <tr key={`${r.kind}:${r.source}:${r.name}:${i}`}>
                      <td className={styles.cellName}>{r.name}</td>
                      <td className={styles.cellSpec}>{r.spec || "—"}</td>
                      <td>{r.kind === "python" ? "Python" : "JavaScript"}</td>
                      <td className={styles.cellSource}>
                        {r.source === "standalone" ? (
                          <span className={styles.sourceStandalone}>standalone</span>
                        ) : (
                          <span className={styles.sourcePackage}>{r.source}</span>
                        )}
                        {r.installed === false && (
                          <span
                            className={styles.notInstalled}
                            title="Declared by this package but not currently installed in the environment"
                          >not installed</span>
                        )}
                      </td>
                      <td>{renderStatusCell(r.kind, fullSpec)}</td>
                      <td>
                        {r.source === "standalone" ? (
                          <button
                            className={styles.removeButton}
                            disabled={status?.kind === "installing" || status?.kind === "removing"}
                            onClick={() => void handleRemove(r.kind, fullSpec)}
                            title="Remove from your library list"
                          >×</button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </ModalShell>
  );
}
