import React, { useEffect, useState } from "react";
import styles from "./DatasetsWindow.module.css";
import { pyodideExecutor } from '../../../services/PyodideExecutor';
import { getAllFiles } from '../../../services/IndexedDBFiles';

export default function DatasetsWindow({
    open,
    closeModal,
    uploadVersion = 0,
} : {
    open: boolean;
    closeModal: any;
    uploadVersion?: number;
}) {

    const [datasetNames, setDatasetNames] = useState<string[]>([]);

    useEffect(() => {
        if (process.env.PYODIDE_ENABLED === 'true') {
            // Read from IndexedDB directly rather than the virtual FS.
            // listFiles() returns [] when Pyodide hasn't finished loading yet,
            // but IndexedDB is always available immediately after a refresh.
            getAllFiles()
                .then(files => setDatasetNames(files.map(f => f.name)))
                .catch(() => setDatasetNames(pyodideExecutor.listFiles()));
            return;
        }
        fetch(process.env.BACKEND_URL + "/datasets", {
            method: "GET",
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Error in retrieving datasets: ' + response.statusText);
                }
                return response.json();
            })
            .then(data => {
                setDatasetNames(data);
            })
            .catch(error => {
                console.error('Error fetching files:', error);
            });
    }, [open, uploadVersion]);

    return (
        <>
            {open ?
                <div>
                    <div className={styles.modalBackground}></div>
                    <div className={styles.modal}>
                        <span className={styles.closeX} onClick={closeModal}>X</span>
                        <div className={styles.datasetContainer}>
                            <h2>Available Datasets</h2>
                            {process.env.PYODIDE_ENABLED === 'true' && datasetNames.length > 0 && (
                                <button
                                    onClick={async () => {
                                        await pyodideExecutor.clearFiles();
                                        setDatasetNames([]);
                                    }}
                                    style={{ marginBottom: '8px', cursor: 'pointer' }}
                                >
                                    Clear All Files
                                </button>
                            )}
                            <div className={styles.tableWrapper}>
                                <table className={styles.datasetTable}>
                                    <thead>
                                    <tr>
                                        <th>Name</th>
                                        {process.env.PYODIDE_ENABLED === 'true' && <th>Path</th>}
                                    </tr>
                                    </thead>
                                    <tbody>
                                        {datasetNames.map((dataset, index) => (
                                            <tr key={index}>
                                                <td>{dataset}</td>
                                                {process.env.PYODIDE_ENABLED === 'true' && (
                                                    <td><code>/data/{dataset}</code></td>
                                                )}
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    </div>
                </div> : null
            }
        </>

    );
}
