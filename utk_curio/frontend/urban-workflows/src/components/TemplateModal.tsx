import React, { useState } from "react";
import ModalShell from "./ModalShell";
import content from "./modal-content.module.css";
import { Template, useTemplateContext } from "../providers/TemplateProvider";
import { AccessLevelType, NodeType } from "../constants";
import { BACKEND_URL } from "../utils/backendUrl";

type TemplateModalProps = {
    templateId?: string;
    callBack: any;
    show: boolean;
    handleClose: any;
    nodeType: NodeType;
    code: string;
    newTemplateFlag: boolean;
};

function TemplateModal({
    templateId,
    callBack,
    show,
    handleClose,
    nodeType,
    code,
    newTemplateFlag,
}: TemplateModalProps) {
    const { createUserTemplate, editUserTemplate } = useTemplateContext();

    const [name, setName] = useState<string>("");
    const [accessLevel, setAccessLevel] = useState<string>("ANY");
    const [description, setDescription] = useState<string>("");

    if (!show) return null;

    const closeModal = (save: boolean = true) => {
        let template: any = {}

        if (save) {
            if (newTemplateFlag) {
                template = createUserTemplate(
                    nodeType,
                    name,
                    description,
                    accessLevel as AccessLevelType,
                    code
                );
                callBack(template);
            } else {
                template = {
                    id: templateId,
                    type: nodeType,
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

        if (Object.keys(template).length > 0) {
            fetch(BACKEND_URL + "/addTemplate", {
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
        <ModalShell onClose={() => closeModal(false)}>
            <div className={content.content}>
                <h2 className={content.title}>
                    {newTemplateFlag ? "New Template" : "Editing Template"}
                </h2>

                <div className={content.field}>
                    <label className={content.label} htmlFor="template-name">Name</label>
                    <input
                        id="template-name"
                        className={content.input}
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                    />
                </div>

                <div className={content.field}>
                    <label className={content.label} htmlFor="template-access">Access Level</label>
                    <select
                        id="template-access"
                        className={content.select}
                        value={accessLevel}
                        onChange={(e) => setAccessLevel(e.target.value)}
                    >
                        <option value="ANY">Any</option>
                    </select>
                </div>

                <div className={content.field}>
                    <label className={content.label} htmlFor="template-description">Description</label>
                    <textarea
                        id="template-description"
                        className={content.textarea}
                        value={description}
                        onChange={(e) => setDescription(e.target.value)}
                    />
                </div>

                <div className={content.buttonRow}>
                    <button className={content.secondaryButton} onClick={() => closeModal(false)}>
                        Close
                    </button>
                    <button className={content.primaryButton} onClick={() => closeModal(true)}>
                        Save
                    </button>
                </div>
            </div>
        </ModalShell>
    );
}

export default TemplateModal;
