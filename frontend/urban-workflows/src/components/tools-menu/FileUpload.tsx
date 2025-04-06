import React, { useState } from 'react';
import CSS from "csstype";

type FileUploadProps = {
    style: CSS.Properties,
}

const FileUpload = ({style}:FileUploadProps) => {

    const handleFileChange = async (e: any) => {
        const formData = new FormData();
        formData.append('file', e.target.files[0]);
        // @ts-ignore
        formData.append('name', e.target.files[0].name);

        try {
            await fetch(process.env.BACKEND_URL+"/upload", {
                method: "POST",
                body: formData
            })
        } catch (error) {
            console.error('Error uploading file:', error);
            alert('Error uploading file');
        }
    };

  return (
    <div style={{...style, paddingTop: "3px", paddingBottom: "3px"}} onClick={() => document.getElementById('uploadFile')?.click()}>
        <label htmlFor="uploadFile" style={{cursor: "pointer", margin: 0, pointerEvents: "none"}}>Upload Dataset</label>
        <input type="file" id="uploadFile" style={{visibility: "hidden", width: 0 }} onChange={handleFileChange} />
        {/* <button onClick={handleSubmit}>Upload</button> */}
    </div>
  );
};

export default FileUpload;
