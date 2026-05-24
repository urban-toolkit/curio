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
import {
    AccessLevelType,
    NodeType,
    EdgeType,
    VisInteractionType,
} from "../constants";
import { NodeKindId } from "../registry/types";
import useTemplates from "./templates";
import { v4 as uuid } from "uuid";

export interface Template {
    id: string;
    /**
     * Dispatch key — either a built-in `NodeType` enum value or a pack canonical
     * id `<packId>/<kindId>@<major>` (e.g. `"ai.urbanlab.uhvi/uhvi-load@1"`).
     */
    type: NodeKindId;
    name: string;
    description: string;
    accessLevel: AccessLevelType;
    code: string; // grammar or python
    custom: boolean;
}

interface TemplateContextProps {
    getTemplates: (type: NodeKindId, custom: boolean) => Template[];
    createUserTemplate: (
        type: NodeKindId,
        name: string,
        description: string,
        accessLevel: AccessLevelType,
        code: string
    ) => Template | null;
    editUserTemplate: (template: Template) => void;
    deleteTemplate: (templateId: string) => void;
    fetchTemplates: () => void;
}

export const TemplateContext = createContext<TemplateContextProps>({
    getTemplates: () => [],
    createUserTemplate: () => null,
    editUserTemplate: () => {},
    deleteTemplate: () => {},
    fetchTemplates: () => {}
});

const TemplateProvider = ({ children }: { children: ReactNode }) => {
    const [defaultTemplates, setDefaultTemplates] =
        useState<Template[]>([]);
    const [userTemplates, setUserTemplates] = useState<Template[]>([]);

    const fetchTemplates = useCallback(async () => {
        try {
            const templates = await useTemplates();
            setDefaultTemplates(templates);
        } catch {
            /* keep previous default templates */
        }
    }, []);

    useEffect(() => {
        void fetchTemplates();
    }, [fetchTemplates]);

    // ``refreshPackRegistry`` calls this after pack install/load so new pack
    // template bodies merge into GET /templates before palette nodes inject code.
    useEffect(() => {
        const w = (window as unknown as { curio?: Record<string, unknown> }).curio ?? {};
        (window as unknown as { curio: Record<string, unknown> }).curio = {
            ...w,
            fetchTemplates,
        };
    }, [fetchTemplates]);

    const createUserTemplate = (
        type: NodeKindId,
        name: string,
        description: string,
        accessLevel: AccessLevelType,
        code: string
    ) => {
        let template = {
            id: uuid(),
            type,
            name,
            description,
            accessLevel,
            code,
            custom: true,
        };

        let newTemplates: Template[] = [];

        for (const template of userTemplates) {
            newTemplates.push({ ...template });
        }

        newTemplates.push({ ...template });

        setUserTemplates(newTemplates);

        return { ...template };
    };

    const editUserTemplate = (templateNew: Template) => {
        // No-op since Phase B: user-custom templates were saved to the legacy
        // ``<CURIO_LAUNCH_CWD>/templates/`` directory which no longer exists.
        // Pack-source files are now the only source of starter code; users
        // wanting to ship their own should publish a pack.
        let newTemplates: Template[] = [];

        for (const template of userTemplates) {
            if (template.id == templateNew.id){
                newTemplates.push({ ...templateNew });
            }else{
                newTemplates.push({ ...template });
            }
        }

        setUserTemplates(newTemplates);
    };

    const getTemplates = (type: NodeKindId, custom: boolean) => {
        let returnedTemplates = [];
        let templates = [];

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
        let newTemplates: Template[] = [];

        for (const template of userTemplates) {
            if (template.id != templateId) newTemplates.push({ ...template });
        }

        setUserTemplates(newTemplates);
    };

    return (
        <TemplateContext.Provider
            value={{
                getTemplates,
                createUserTemplate,
                editUserTemplate,
                deleteTemplate,
                fetchTemplates
            }}
        >
            {children}
        </TemplateContext.Provider>
    );
};

export const useTemplateContext = () => {
    const context = useContext(TemplateContext);

    if (!context) {
        throw new Error(
            "useTemplateContext must be used within a TemplateProvider"
        );
    }

    return context;
};

export default TemplateProvider;
