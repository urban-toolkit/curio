import React from "react";
import type { PackagePayload, ResolveConflict } from "../../../api/packagesApi";
import styles from "./InstallPermissionsDialog.module.css";

export interface InstallPermissionsDialogProps {
  package: PackagePayload;
  conflicts: ResolveConflict[];
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

export const InstallPermissionsDialog: React.FC<InstallPermissionsDialogProps> = ({
  pkg,
  conflicts,
  busy,
  onCancel,
  onConfirm,
}) => {
  const hasConflicts = conflicts.length > 0;
  const pythonDeps = Object.entries(pkg.dependencies.python);
  const jsDeps = Object.entries(pkg.dependencies.js);

  return (
    <div className={styles.backdrop} role="dialog" aria-modal="true">
      <div className={styles.modal}>
        <h2 className={styles.title}>Install &quot;{pkg.name}&quot;</h2>
        <p className={styles.subtitle}>
          {pkg.publisher} · v{pkg.version}
        </p>

        {pkg.permissions.length > 0 && (
          <>
            <p className={styles.depsTitle}>Permissions requested</p>
            <ul className={styles.permList}>
              {pkg.permissions.map((perm) => (
                <li key={perm} className={styles.permItem}>
                  <span className={styles.permIcon}>●</span>
                  {perm}
                </li>
              ))}
            </ul>
          </>
        )}

        {(pythonDeps.length > 0 || jsDeps.length > 0) && (
          <div className={styles.depsBox}>
            <p className={styles.depsTitle}>Dependencies</p>
            {pythonDeps.map(([pkg, range]) => (
              <div key={`py:${pkg}`} className={styles.depRow}>
                <code>python · {pkg}</code>
                <code>{range}</code>
              </div>
            ))}
            {jsDeps.map(([pkg, range]) => (
              <div key={`js:${pkg}`} className={styles.depRow}>
                <code>js · {pkg}</code>
                <code>{range}</code>
              </div>
            ))}
          </div>
        )}

        {hasConflicts && (
          <div className={styles.conflictsBox}>
            <p className={styles.conflictTitle}>Dependency conflicts with installed packages</p>
            {conflicts.map((c) => (
              <div key={c.package}>
                <p>
                  <strong>{c.package}</strong>
                </p>
                <ul style={{ margin: "4px 0", paddingLeft: 18 }}>
                  {c.ranges.map((r) => (
                    <li key={r.packageDir}>
                      <code>{r.packageDir}</code>: <code>{r.range}</code>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            <p className={styles.conflictHint}>
              Uninstall one of the conflicting packages before installing this one.
            </p>
          </div>
        )}

        <div className={styles.footer}>
          <button type="button" className={styles.ghostButton} onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            type="button"
            className={styles.actionButton}
            onClick={onConfirm}
            disabled={busy || hasConflicts}
          >
            {busy ? "Installing…" : "Install"}
          </button>
        </div>
      </div>
    </div>
  );
};
