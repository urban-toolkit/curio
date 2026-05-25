import React, { useCallback, useEffect, useState } from "react";
import ModalShell from "../../ModalShell";
import { packagesApi, refreshPackageRegistry } from "../../../api/packagesApi";
import type { PackageMetadataUpdate, PackagePayload } from "../../../api/packagesApi";
import { useToastContext } from "../../../providers/ToastProvider";
import styles from "./PackageMetadataModal.module.css";

export interface PackageMetadataModalProps {
    /** Installed-package directory name (``packageId@major``). */
    dirName: string;
    onClose: () => void;
    /** Called with the updated payload after a successful save. */
    onSaved?: (pkg: PackagePayload) => void;
}

/**
 * Per-package metadata editor opened from ``InstalledPackageAccordion``'s
 * header (pencil button). Edits human-authored fields (name, description,
 * publisher, license, README, permissions, ``compatibility.curioRuntime``);
 * dependencies are derived from source by the factory and shown read-only.
 */
export function PackageMetadataModal({ dirName, onClose, onSaved }: PackageMetadataModalProps) {
    const { showToast } = useToastContext();
    const [pkg, setPkg] = useState<PackagePayload | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [name, setName] = useState("");
    const [description, setDescription] = useState("");
    const [publisher, setPublisher] = useState("");
    const [license, setLicense] = useState("");
    const [readme, setReadme] = useState("");
    const [permissions, setPermissions] = useState("");
    const [curioRuntime, setCurioRuntime] = useState("");
    const [submitError, setSubmitError] = useState<string | null>(null);

    useEffect(() => {
        let cancelled = false;
        void (async () => {
            try {
                const { packages } = await packagesApi.listInstalled();
                if (cancelled) return;
                const found = packages.find((p) => p.dirName === dirName);
                if (!found) {
                    setLoadError(`Package "${dirName}" is no longer installed.`);
                    return;
                }
                setPkg(found);
                setName(found.name ?? "");
                setDescription(found.description ?? "");
                setPublisher(found.publisher ?? "");
                setLicense(found.license ?? "");
                setReadme(found.readme ?? "");
                setPermissions((found.permissions ?? []).join(", "));
                // ``curioRuntime`` lives under ``compatibility`` in the manifest
                // but isn't surfaced in PackagePayload today (advisory field).
                // Initialise blank; the PATCH still writes it through if set.
                setCurioRuntime("");
            } catch (err) {
                if (!cancelled) setLoadError((err as Error)?.message ?? "Failed to load metadata.");
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [dirName]);

    const onSave = useCallback(async () => {
        if (!pkg || busy) return;
        setBusy(true);
        setSubmitError(null);
        const updates: PackageMetadataUpdate = {
            name: name.trim() || undefined,
            description,
            publisher,
            license: license.trim() === "" ? null : license.trim(),
            readme,
            permissions: permissions
                .split(",")
                .map((s) => s.trim())
                .filter((s) => s.length > 0),
        };
        if (curioRuntime.trim()) {
            updates.compatibility = { curioRuntime: curioRuntime.trim() };
        }
        try {
            const { package: updated } = await packagesApi.updatePackageMetadata(dirName, updates);
            await refreshPackageRegistry();
            showToast(`Metadata updated for ${updated.name}.`, "success");
            onSaved?.(updated);
            onClose();
        } catch (err) {
            const body = (err as { body?: { error?: string } } | null)?.body;
            const detail = body?.error ?? (err as Error)?.message ?? "Update failed.";
            setSubmitError(detail);
        } finally {
            setBusy(false);
        }
    }, [busy, curioRuntime, description, dirName, license, name, onClose, onSaved, permissions, pkg, readme, showToast]);

    if (loadError) {
        return (
            <ModalShell preservePackagePaletteOpen onClose={onClose}>
                <div className={styles.content}>
                    <h2 className={styles.title}>Edit package metadata</h2>
                    <p className={styles.error} role="alert">{loadError}</p>
                    <div className={styles.footer}>
                        <button type="button" className={styles.ghostBtn} onClick={onClose}>Close</button>
                    </div>
                </div>
            </ModalShell>
        );
    }

    if (!pkg) {
        return (
            <ModalShell preservePackagePaletteOpen onClose={onClose}>
                <div className={styles.content}>
                    <h2 className={styles.title}>Edit package metadata</h2>
                    <p className={styles.subtitle}>Loading…</p>
                </div>
            </ModalShell>
        );
    }

    const pythonDeps = pkg.dependencies?.python ?? {};
    const jsDeps = pkg.dependencies?.js ?? {};
    const pythonEntries = Object.entries(pythonDeps);
    const jsEntries = Object.entries(jsDeps);

    return (
        <ModalShell preservePackagePaletteOpen onClose={busy ? () => {} : onClose}>
            <div className={styles.content}>
                <h2 className={styles.title}>Edit package metadata</h2>
                <p className={styles.subtitle}>
                    {pkg.packageId}@{pkg.major} · v{pkg.version}
                </p>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-name">Name</label>
                    <input
                        id="pkg-meta-name"
                        className={styles.input}
                        value={name}
                        disabled={busy}
                        onChange={(e) => setName(e.target.value)}
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-description">Description</label>
                    <textarea
                        id="pkg-meta-description"
                        className={styles.textarea}
                        value={description}
                        disabled={busy}
                        onChange={(e) => setDescription(e.target.value)}
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-publisher">Publisher</label>
                    <input
                        id="pkg-meta-publisher"
                        className={styles.input}
                        value={publisher}
                        disabled={busy}
                        onChange={(e) => setPublisher(e.target.value)}
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-license">License</label>
                    <input
                        id="pkg-meta-license"
                        className={styles.input}
                        value={license}
                        disabled={busy}
                        onChange={(e) => setLicense(e.target.value)}
                        placeholder="MIT"
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-permissions">
                        Permissions (comma separated)
                    </label>
                    <input
                        id="pkg-meta-permissions"
                        className={styles.input}
                        value={permissions}
                        disabled={busy}
                        onChange={(e) => setPermissions(e.target.value)}
                        placeholder="filesystem.read, network.fetch"
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-runtime">
                        Curio runtime range (advisory)
                    </label>
                    <input
                        id="pkg-meta-runtime"
                        className={styles.input}
                        value={curioRuntime}
                        disabled={busy}
                        onChange={(e) => setCurioRuntime(e.target.value)}
                        placeholder=">=0.5.0"
                    />
                </div>

                <div className={styles.field}>
                    <label className={styles.fieldLabel} htmlFor="pkg-meta-readme">README</label>
                    <textarea
                        id="pkg-meta-readme"
                        className={`${styles.textarea} ${styles.readme}`}
                        value={readme}
                        disabled={busy}
                        onChange={(e) => setReadme(e.target.value)}
                        placeholder="# Package title&#10;&#10;Describe what this package does…"
                    />
                </div>

                <div className={styles.depsBlock}>
                    <p className={styles.depsTitle}>Dependencies (auto-detected from source)</p>
                    {pythonEntries.length === 0 && jsEntries.length === 0 ? (
                        <p className={styles.depsEmpty}>No external imports detected in any template source.</p>
                    ) : (
                        <>
                            {pythonEntries.map(([dep, range]) => (
                                <div key={`py-${dep}`} className={styles.depsRow}>
                                    python: {dep} {range}
                                </div>
                            ))}
                            {jsEntries.map(([dep, range]) => (
                                <div key={`js-${dep}`} className={styles.depsRow}>
                                    js: {dep} {range}
                                </div>
                            ))}
                        </>
                    )}
                </div>

                {submitError ? (
                    <p className={styles.error} role="alert">{submitError}</p>
                ) : null}

                <div className={styles.footer}>
                    <button type="button" className={styles.ghostBtn} disabled={busy} onClick={onClose}>
                        Cancel
                    </button>
                    <button type="button" className={styles.primaryBtn} disabled={busy} onClick={() => void onSave()}>
                        {busy ? "Saving…" : "Save changes"}
                    </button>
                </div>
            </div>
        </ModalShell>
    );
}
