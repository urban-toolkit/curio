import React, { useEffect, useState } from "react";
import CSS from "csstype";

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
                    <div style={modalBackground}></div>
                    <div style={modal}>
                        <span style={{position: "absolute", right: "15px", top: "10px", cursor: "pointer", fontWeight: "bold", fontSize: "19px"}} onClick={closeModal}>X</span>
                        <div className="dataset-container">
                            <h2>Available Datasets</h2>
                            <div className="table-wrapper">
                                <table className="dataset-table">
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

const modal: CSS.Properties = {
    position: "fixed",
    display: "flex",
    justifyContent: "center",
    flexDirection: "column",
    alignItems: "center",
    top: "calc(50% - 20%)",
    left: "40%",
    width: "20%",
    height: "40%",
    backgroundColor: "white",
    boxShadow: "rgba(0, 0, 0, 0.35) 0px 5px 15px",
    borderRadius: "10px",
    zIndex: 500
};

const modalBackground: CSS.Properties = {
    position: "fixed",
    top: 0,
    left: 0,
    width: "100vw",
    height: "100vh",
    backgroundColor: "black",
    opacity: "50%",
    zIndex: 400
};