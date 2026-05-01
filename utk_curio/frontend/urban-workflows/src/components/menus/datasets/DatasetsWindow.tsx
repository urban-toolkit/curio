import React, { useEffect, useRef, useState } from "react";
import styles from "./DatasetsWindow.module.css";

export default function DatasetsWindow({
    open,
    closeModal
}: {
    open: boolean;
    closeModal: () => void;
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
        if (open) fetchDatasets();
    }, [open]);

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
        <>
            <div className={styles.modalBackground}></div>
            <div className={styles.modal}>
                <span className={styles.closeX} onClick={closeModal}>X</span>
                <div className={styles.container}>
                    <h2 className={styles.title}>Datasets</h2>
                    <p className={styles.subtitle}>files available in the sandbox</p>

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

                    <div className={styles.datasetList}>
                        {datasetNames.length === 0 ? (
                            <p className={styles.empty}>No datasets available.</p>
                        ) : (
                            datasetNames.map((name, i) => (
                                <div key={i} className={styles.datasetRow}>
                                    <span className={styles.datasetName}>{name}</span>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>
        </>
    );
}
