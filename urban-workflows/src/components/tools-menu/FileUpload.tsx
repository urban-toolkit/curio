import React, { useState } from "react";
import CSS from "csstype";

type FileUploadProps = {
    style: CSS.Properties;
};

const FileUpload = ({ style }: FileUploadProps) => {
    const handleFileChange = async (e: any) => {
        const formData = new FormData();
        formData.append("file", e.target.files[0]);
        // @ts-ignore
        formData.append("name", e.target.files[0].name);

        try {
            await fetch(process.env.BACKEND_URL + "/upload", {
                method: "POST",
                body: formData,
            });
        } catch (error) {
            console.error("Error uploading file:", error);
            alert("Error uploading file");
        }
    };

    return (
        <div style={{ ...style, boxShadow: "0px 0px 5px 0px black" }}>
            <label
                htmlFor="uploadFile"
                style={{ cursor: "pointer", margin: 0 }}
            >
                Upload file
            </label>
            <input
                type="file"
                id="uploadFile"
                style={{ visibility: "hidden" }}
                onChange={handleFileChange}
            />
            {/* <button onClick={handleSubmit}>Upload</button> */}
        </div>
    );
};

export default FileUpload;
