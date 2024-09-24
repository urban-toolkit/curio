import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useEffect,
} from "react";
import {
    Connection,
    Edge,
    EdgeChange,
    Node,
    NodeChange,
    addEdge,
    useNodesState,
    useEdgesState,
    useReactFlow,
    getOutgoers,
    MarkerType,
} from "reactflow";
import { ConnectionValidator } from "../ConnectionValidator";
import { AccessLevelType, BoxType, EdgeType, VisInteractionType } from "../constants";
import { GetTemplates } from "./templates";
import { v4 as uuid } from "uuid";

export interface Template {
    id: string;
    type: BoxType;
    name: string;
    description: string;
    accessLevel: AccessLevelType;
    code: string; // grammar or python
    custom: any;
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
    const [defaultTemplates, setDefaultTemplates] = useState<Template[]>();
    const [userTemplates, setUserTemplates] = useState<Template[]>([]);

    useEffect(() => {
        GetTemplates().then(data => {
            console.log("oi")
            setDefaultTemplates(data);
            console.log("foi")
        }).catch(error => {
            console.error("Erro ao carregar templates:", error);
        });
    }, []);

    // const createUserTemplate = (type: BoxType, name: string, description: string, accessLevel: AccessLevelType, code: string) => {
    //     let template = {
    //         id: uuid(),
    //         type,
    //         name,
    //         description,
    //         accessLevel,
    //         code,
    //         custom: true
    //     }

    //     let newTemplates: Template[] = [];

    //     for(const template of userTemplates){
    //         newTemplates.push({...template});
    //     }

    //     newTemplates.push({...template});

    //     setUserTemplates(newTemplates);

    //     return {...template};
    // }

    const createUserTemplate = (type: BoxType, name: string, description: string, accessLevel: AccessLevelType, code: string) => {
        const template = {
            id: uuid(),
            type,
            name,
            description,
            accessLevel,
            code,
            custom: 1
        };

        const newTemplates = [...(defaultTemplates||[]), template];
        setDefaultTemplates(newTemplates);

        fetch('http://localhost:5002/registerTemplate', {
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
                console.error('Erro ao registrar template:', error);
            });

        return template;
    };

    const editUserTemplate = (templateNew: Template) => {
        let newTemplates: Template[] = [];

        for (const template of userTemplates) {
            if (template.id == templateNew.id)
                newTemplates.push({ ...templateNew });
            else
                newTemplates.push({ ...template });
        }

        setUserTemplates(newTemplates);
    }

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
    }

    const deleteTemplate = (templateId: string) => {
        let newTemplates: Template[] = [];

        for (const template of userTemplates) {
            if (template.id != templateId)
                newTemplates.push({ ...template });
        }

        setUserTemplates(newTemplates);
    }

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