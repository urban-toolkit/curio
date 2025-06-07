import React, { useState } from "react";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";

import Button from "react-bootstrap/Button";
import Modal from "react-bootstrap/Modal";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { AccessLevelType, BoxType } from "../constants";

type TemplateModalProps = {
    templateId?: string;
    callBack: any;
    show: boolean;
    handleClose: any;
    boxType: BoxType;
    code: string;
    newTemplateFlag: boolean;
};

function TemplateModal({
    templateId,
    callBack,
    show,
    handleClose,
    boxType,
    code,
    newTemplateFlag,
}: TemplateModalProps) {
    const { createUserTemplate, editUserTemplate } = useTemplateContext();

    const [name, setName] = useState<string>("");
    const [accessLevel, setAccessLevel] = useState<string>("ANY");
    const [description, setDescription] = useState<string>("");

    const closeModal = (save: boolean = true) => {
        let template: any = {}

        if (save) {
            if (newTemplateFlag) {
                // creating new template
                template = createUserTemplate(
                    boxType,
                    name,
                    description,
                    accessLevel as AccessLevelType,
                    code
                );

                callBack(template);
            } else {
                // updating existing template

                template = {
                    id: templateId,
                    type: boxType,
                    name,
                    description,
                    accessLevel,
                    code,
                    custom: true,
                };

                editUserTemplate({ ...template } as Template);
                callBack(template);
            }
        }

        if(Object.keys(template).length > 0){ // If there is a template
            fetch(process.env.BACKEND_URL + "/addTemplate", {
                method: "POST",
                body: JSON.stringify(template),
                headers: {
                    "Content-type": "application/json; charset=UTF-8",
                },
            });
        }

        handleClose();
    };

    return (
        <>
            <Modal show={show} onHide={closeModal}>
                <Modal.Header closeButton>
                    {newTemplateFlag ? (
                        <Modal.Title>New Template</Modal.Title>
                    ) : (
                        <Modal.Title>Editing Template</Modal.Title>
                    )}
                </Modal.Header>
                <Modal.Body>
                    <label htmlFor="name">Name: </label>
                    <input
                        value={name}
                        onChange={(event) => {
                            setName(event.target.value);
                        }}
                        type="text"
                        name="name"
                        style={{ marginLeft: "5px" }}
                    />
                    <br />
                    <label htmlFor="accessLevel">Access Level: </label>
                    <select
                        value={accessLevel}
                        onChange={(event) => {
                            setAccessLevel(event.target.value);
                        }}
                        name="accessLevel"
                    >
                        {/* <option value="PROGRAMMER">Programmer</option> */}
                        {/* <option value="EXPERT">Expert</option> */}
                        <option value="ANY">Any</option>
                    </select>
                    <br />
                    <label htmlFor="description">Description: </label>
                    <textarea
                        value={description}
                        onChange={(event) => {
                            setDescription(event.target.value);
                        }}
                        name="description"
                        style={{
                            marginLeft: "5px",
                            marginTop: "5px",
                            resize: "none",
                        }}
                    ></textarea>
                </Modal.Body>
                <Modal.Footer>
                    <Button
                        variant="secondary"
                        onClick={() => {
                            closeModal(false);
                        }}
                    >
                        Close
                    </Button>
                    <Button
                        variant="primary"
                        onClick={() => {
                            closeModal();
                        }}
                    >
                        Save
                    </Button>
                </Modal.Footer>
            </Modal>
        </>
    );
}

export default TemplateModal;
