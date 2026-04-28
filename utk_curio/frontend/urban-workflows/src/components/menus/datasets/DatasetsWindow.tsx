import React, { useEffect, useRef, useState } from "react";
import styles from "./DatasetsWindow.module.css";
import ModalShell from "../../ModalShell";
import { pyodideExecutor } from '../../../services/PyodideExecutor';
import { getAllFiles } from '../../../services/IndexedDBFiles';

export default function DatasetsWindow({
    open,
    closeModal,
    uploadVersion = 0,
}: {
    open: boolean;
    closeModal: () => void;
    /** Incremented by the upload handler each time a new file is added so the
      * effect re-runs and the list refreshes without requiring a modal reopen. */
    uploadVersion?: number;
}) {
    const [datasetNames, setDatasetNames] = useState<string[]>([]);
    const [uploadStatus, setUploadStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
    const fileInputRef = useRef<HTMLInputElement>(null);

    const fetchDatasets = () => {
        fetch(process.env.BACKEND_URL + "/datasets", { method: "GET" })
            .then(res => {
                if (!res.ok) throw new Error('Error retrieving datasets: ' + res.statusText);
                return res.json();
            })
            .then(data => setDatasetNames(data))
            .catch(err => console.error('Error fetching datasets:', err));
    };

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
        if (open) fetchDatasets();
    }, [open, uploadVersion]);

    useEffect(() => {
        if (uploadStatus === 'success' || uploadStatus === 'error') {
            const t = setTimeout(() => setUploadStatus('idle'), 2000);
            return () => clearTimeout(t);
        }
    }, [uploadStatus]);

    const handleUploadClick = () => fileInputRef.current?.click();

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);
        formData.append('fileName', file.name);

        setUploadStatus('uploading');
        try {
            const res = await fetch(`${process.env.BACKEND_URL}/upload`, {
                method: 'POST',
                body: formData,
            });
            if (!res.ok) throw new Error('Upload failed');
            await res.text();
            setUploadStatus('success');
            fetchDatasets();
        } catch (err) {
            console.error('Error uploading file:', err);
            setUploadStatus('error');
        }

        e.target.value = '';
    };

    if (!open) return null;

    return (
        <ModalShell onClose={closeModal}>
            <div className={styles.container}>
                    <h2 className={styles.title}>Datasets</h2>
                    <p className={styles.subtitle}>files available in the sandbox</p>

                    {process.env.PYODIDE_ENABLED !== 'true' && (
                        <div className={styles.uploadRow}>
                            <input
                                type="file"
                                ref={fileInputRef}
                                style={{ display: 'none' }}
                                onChange={handleFileChange}
                                disabled={uploadStatus === 'uploading'}
                            />
                            <button
                                className={styles.uploadButton}
                                onClick={handleUploadClick}
                                disabled={uploadStatus === 'uploading'}
                            >
                                {uploadStatus === 'uploading' ? (
                                    <>
                                        <span className="spinner-border spinner-border-sm" role="status" aria-hidden="true" />
                                        {' '}Uploading…
                                    </>
                                ) : uploadStatus === 'success' ? 'Uploaded!' : uploadStatus === 'error' ? 'Upload failed' : 'Upload Dataset'}
                            </button>
                        </div>
                    )}

                    {process.env.PYODIDE_ENABLED === 'true' && datasetNames.length > 0 && (
                        <button
                            className={styles.uploadButton}
                            onClick={async () => {
                                await pyodideExecutor.clearFiles();
                                setDatasetNames([]);
                            }}
                            style={{ marginBottom: '8px' }}
                        >
                            Clear All Files
                        </button>
                    )}

                    <div className={styles.datasetList}>
                        {datasetNames.length === 0 ? (
                            <p className={styles.empty}>No datasets available.</p>
                        ) : (
                            datasetNames.map((name, i) => (
                                <div key={i} className={styles.datasetRow}>
                                    <span className={styles.datasetName}>{name}</span>
                                    {process.env.PYODIDE_ENABLED === 'true' && (
                                        <code className={styles.datasetPath}>/data/{name}</code>
                                    )}
                                </div>
                            ))
                        )}
                    </div>
            </div>
        </ModalShell>
    );
}
