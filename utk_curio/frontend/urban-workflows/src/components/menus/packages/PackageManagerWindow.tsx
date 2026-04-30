import React, { useState } from "react";
import styles from "./PackageManagerWindow.module.css";
import ModalShell from "../../ModalShell";
import { useFlowContext } from "../../../providers/FlowProvider";
import { BACKEND_URL } from "../../../utils/backendUrl";

export default function PackageManagerWindow({
    open,
    closeModal,
}: {
    open: boolean;
    closeModal: () => void;
}) {
    const { packages, addPackage, removePackage } = useFlowContext();
    const [newPackage, setNewPackage] = useState("");
    const [installing, setInstalling] = useState(false);
    const [installLog, setInstallLog] = useState<{ package: string; success: boolean; output: string }[]>([]);

    const handleAdd = () => {
        const trimmed = newPackage.trim();
        if (trimmed) addPackage(trimmed);
        setNewPackage("");
    };

    const handleInstall = async () => {
        if (packages.length === 0) return;
        setInstalling(true);
        setInstallLog([]);
        try {
            const response = await fetch(BACKEND_URL + "/installPackages", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ packages }),
            });
            const data = await response.json();
            setInstallLog(
                data.results.map((r: any) => ({
                    package: r.package,
                    success: r.success,
                    output: [r.stdout, r.stderr].filter(Boolean).join("\n").trim(),
                }))
            );
        } catch (err) {
            setInstallLog([{ package: "error", success: false, output: String(err) }]);
        }
        setInstalling(false);
    };

    if (!open) return null;

    return (
        <ModalShell onClose={closeModal}>
            <div className={styles.container}>
                    <h2 className={styles.title}>Packages</h2>
                    <p className={styles.subtitle}>pip packages required by this dataflow</p>

                    <div className={styles.addRow}>
                        <input
                            className={styles.input}
                            type="text"
                            placeholder="e.g. numpy or scikit-learn==1.4.0"
                            value={newPackage}
                            onChange={(e) => setNewPackage(e.target.value)}
                            onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); }}
                        />
                        <button className={styles.addButton} onClick={handleAdd}>Add</button>
                    </div>

                    <div className={styles.packageList}>
                        {packages.length === 0 && (
                            <p className={styles.empty}>No packages added yet.</p>
                        )}
                        {packages.map((pkg, i) => (
                            <div key={i} className={styles.packageRow}>
                                <span className={styles.packageName}>{pkg}</span>
                                <button
                                    className={styles.removeButton}
                                    onClick={() => removePackage(pkg)}
                                >×</button>
                            </div>
                        ))}
                    </div>

                    <button
                        className={styles.installButton}
                        onClick={handleInstall}
                        disabled={installing || packages.length === 0}
                    >
                        {installing ? "Installing…" : "Install All"}
                    </button>

                    {installLog.length > 0 && (
                        <div className={styles.logContainer}>
                            {installLog.map((entry, i) => (
                                <div key={i} className={entry.success ? styles.logSuccess : styles.logError}>
                                    <strong>{entry.package}</strong> — {entry.success ? "installed" : "failed"}
                                    {entry.output && (
                                        <pre className={styles.logOutput}>{entry.output}</pre>
                                    )}
                                </div>
                            ))}
                        </div>
                    )}
            </div>
        </ModalShell>
    );
}
