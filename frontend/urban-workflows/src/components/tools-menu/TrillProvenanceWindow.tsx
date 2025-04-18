import React, { useState } from "react";
import CSS from "csstype";
import { GraphCanvas } from 'reagraph';
import { TrillGenerator } from "../../TrillGenerator";
import { useCode } from "../../hook/useCode";

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
                    <div style={modalBackground}></div>
                    <div style={modal}>
                        <span style={{position: "absolute", right: "15px", top: "10px", cursor: "pointer", fontWeight: "bold", fontSize: "19px"}} onClick={closeModal}>X</span>
                        <p style={{fontWeight: "bold", fontSize: "22px"}}>Provenance for {workflowName}</p>
                        <div style={{width: "85%", height: "85%", position: "relative", border: "1px solid black"}}>
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

const modal: CSS.Properties = {
    position: "fixed",
    display: "flex",
    justifyContent: "center",
    flexDirection: "column",
    alignItems: "center",
    top: "calc(50% - 35%)",
    left: "25%",
    width: "50%",
    height: "70%",
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