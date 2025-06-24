import React, { useState } from "react";
import CSS from "csstype";
import { GraphCanvas } from 'reagraph';
import { TrillGenerator } from "../../../TrillGenerator";
import { useCode } from "../../../hook/useCode";
import styles from "./TrillProvenanceWindow.module.css"

export default function TrillProvenanceWindow({
    open,
    closeModal,
    workflowName
} : {
    open: boolean;
    closeModal: any;
    workflowName: string
}) {
   
    const { loadTrill } = useCode();

    const onNodeClick = (nodeData: any) => {
        TrillGenerator.switchProvenanceTrill(nodeData.id, loadTrill);
    }

    return (
        <>
            {open ? 
                <div>
                    <div className={styles.modalBackground}></div>
                    <div className={styles.modal}>
                        <span className={styles.closeX} onClick={closeModal}>X</span>
                        <p className={styles.title}>Provenance for {workflowName}</p>
                        <div className={styles.graphDiv}>
                            <GraphCanvas
                                nodes={TrillGenerator.provenanceJSON.nodes}
                                edges={TrillGenerator.provenanceJSON.edges}
                                onNodeClick={onNodeClick}
                                labelType={"all"}
                                layoutType={"treeTd2d"}
                            />
                        </div>
                    </div>
                </div> : null
            }
        </>

    );
}