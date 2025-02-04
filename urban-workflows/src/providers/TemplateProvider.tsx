import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useEffect,
} from "react";
import { v4 as uuid } from "uuid";
import { BoxType, AccessLevelType } from "../constants";
import { GetTemplates } from "./templates";

export interface Template {
    id: string;
    type: BoxType;
    name: string;
    description: string;
    accessLevel: AccessLevelType;
    code: string; // grammar or python
    custom: boolean;
}

interface TemplateContextProps {
    getTemplates: (type: BoxType, custom: boolean) => Template[];
    createUserTemplate: (type: BoxType, name: string, description: string, accessLevel: AccessLevelType, code: string) => Template | null;
    editUserTemplate: (template: Template) => void;
    deleteTemplate: (templateId: string) => void;
}

export const TemplateContext = createContext<TemplateContextProps>({
    getTemplates: () => [],
    createUserTemplate: () => null,
    editUserTemplate: () => { },
    deleteTemplate: () => { }
});

const TemplateProvider = ({ children }: { children: ReactNode }) => {
    const [defaultTemplates, setDefaultTemplates] = useState<Template[] | undefined>();
    const [userTemplates, setUserTemplates] = useState<Template[]>([]);

    useEffect(() => {
        GetTemplates()
            .then(data => {
                const defaultTemplate = data.filter((item: Template) => item.custom === false);
                setDefaultTemplates(defaultTemplate);
                const customTemplate = data.filter((item: Template) => item.custom === true);
                setUserTemplates(customTemplate);
            })
            .catch(error => {
                console.error("Error loading templates:", error);
            });
    }, []);

    const createUserTemplate = (type: BoxType, name: string, description: string, accessLevel: AccessLevelType, code: string) => {
        const template = {
            id: uuid(),
            type,
            name,
            description,
            accessLevel,
            code,
            custom: true 
        };

        const newUserTemplates = [...userTemplates, template];
        setUserTemplates(newUserTemplates); 

        fetch(process.env.BACKEND_URL + '/registerTemplate', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(template),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .catch((error) => {
                console.error('Error registering template:', error);
            });

        return template;
    };

    const editUserTemplate = (templateNew: Template) => {
        const updatedTemplates = (defaultTemplates || []).map(template =>
            template.id === templateNew.id ? templateNew : template
        );

        fetch(`${process.env.BACKEND_URL}/updateTemplate/${templateNew.id}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(templateNew),
        })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(() => {
                setDefaultTemplates(updatedTemplates);
            })
            .catch((error) => {
                console.error('Error updating template:', error);
            });
    };

    const getTemplates = (type: BoxType, custom: boolean) => {
        let returnedTemplates = [];
        let templates: any = [];

        if (custom) {
            templates = userTemplates;  
        } else {
            templates = defaultTemplates;
        }

        for (const template of templates) {
            if (template.type == type) {
                returnedTemplates.push({ ...template });
            }
        }

        return returnedTemplates;
    };

    const deleteTemplate = (templateId: string) => {
        fetch(`${process.env.BACKEND_URL}/deleteTemplate/${templateId}`, {
            method: 'DELETE',
        })
            .then(response => {
                if (response.ok) {
                    const newTemplates: Template[] = userTemplates.filter(template => template.id !== templateId);
                    setUserTemplates(newTemplates);
                } else {
                    return response.text().then(text => {
                        throw new Error(text || 'Error excluding template');
                    });
                }
            })
    };

    return (
        <TemplateContext.Provider
            value={{
                getTemplates,
                createUserTemplate,
                editUserTemplate,
                deleteTemplate
            }}
        >
            {children}
        </TemplateContext.Provider>
    );
};

export const useTemplateContext = () => {
    const context = useContext(TemplateContext);

    if (!context) {
        throw new Error("useTemplateContext must be used within a TemplateProvider");
    }

    return context;
};

export default TemplateProvider;
