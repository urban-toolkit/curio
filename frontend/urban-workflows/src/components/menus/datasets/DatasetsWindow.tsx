import React, { useEffect, useState } from "react";
import styles from "./DatasetsWindow.module.css";

export default function DatasetsWindow({
    open,
    closeModal
} : {
    open: boolean;
    closeModal: any;
}) {
   
    const [datasetNames, setDatasetNames] = useState<string[]>([]);

    useEffect(() => {
        fetch(process.env.BACKEND_URL + "/listDatasets", {
            method: "GET",
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error('Error in retrieving datasets: ' + response.statusText);
                }
                return response.json();
            })
            .then(data => {
                console.log('List of files:', data);
                setDatasetNames(data);
            })
            .catch(error => {
                console.error('Error fetching files:', error);
            });
    }, [open]);

    return (
        <>
            {open ? 
                <div>
                    <div className={styles.modalBackground}></div>
                    <div className={styles.modal}>
                        <span className={styles.closeX} onClick={closeModal}>X</span>
                        <div className={styles.datasetContainer}>
                            <h2>Available Datasets</h2>
                            <div className={styles.tableWrapper}>
                                <table className={styles.datasetTable}>
                                    <thead>
                                    <tr>
                                        <th>Name</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                        {datasetNames.map((dataset, index) => (
                                            <tr key={index}>
                                            <td>{dataset}</td>
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
