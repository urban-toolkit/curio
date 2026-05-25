import React, {
    createContext,
    useState,
    useContext,
    ReactNode,
    useCallback,
    useEffect,
} from "react";
import { AccessLevelType } from "../constants";
import { NodeTemplateId } from "../registry/types";
import useStarters from "./starters";
import { v4 as uuid } from "uuid";

export interface Starter {
    id: string;
    /**
     * Dispatch key — either a built-in `NodeType` enum value or a package canonical
     * id `<packageId>/<templateId>@<major>` (e.g. `"ai.urbanlab.uhvi/uhvi-load@1"`).
     */
    type: NodeTemplateId;
    name: string;
    description: string;
    accessLevel: AccessLevelType;
    code: string; // grammar or python
    custom: boolean;
}

interface StarterContextProps {
    getStarters: (type: NodeTemplateId, custom: boolean) => Starter[];
    createUserStarter: (
        type: NodeTemplateId,
        name: string,
        description: string,
        accessLevel: AccessLevelType,
        code: string
    ) => Starter | null;
    editUserStarter: (starter: Starter) => void;
    deleteStarter: (starterId: string) => void;
    fetchStarters: () => void;
}

export const StarterContext = createContext<StarterContextProps>({
    getStarters: () => [],
    createUserStarter: () => null,
    editUserStarter: () => {},
    deleteStarter: () => {},
    fetchStarters: () => {},
});

const StarterProvider = ({ children }: { children: ReactNode }) => {
    const [defaultStarters, setDefaultStarters] = useState<Starter[]>([]);
    const [userStarters, setUserStarters] = useState<Starter[]>([]);

    const fetchStarters = useCallback(async () => {
        try {
            const starters = await useStarters();
            setDefaultStarters(starters);
        } catch {
            /* keep previous default starters */
        }
    }, []);

    useEffect(() => {
        void fetchStarters();
    }, [fetchStarters]);

    // ``refreshPackageRegistry`` calls this after package install/load so new
    // package starter bodies merge into GET /starters before palette nodes
    // inject code.
    useEffect(() => {
        const w = (window as unknown as { curio?: Record<string, unknown> }).curio ?? {};
        (window as unknown as { curio: Record<string, unknown> }).curio = {
            ...w,
            fetchStarters,
        };
    }, [fetchStarters]);

    const createUserStarter = (
        type: NodeTemplateId,
        name: string,
        description: string,
        accessLevel: AccessLevelType,
        code: string
    ) => {
        const starter = {
            id: uuid(),
            type,
            name,
            description,
            accessLevel,
            code,
            custom: true,
        };

        const next: Starter[] = [];
        for (const s of userStarters) next.push({ ...s });
        next.push({ ...starter });

        setUserStarters(next);
        return { ...starter };
    };

    const editUserStarter = (starterNew: Starter) => {
        // No-op since Phase B: user-custom starters were saved to the legacy
        // ``<CURIO_LAUNCH_CWD>/templates/`` directory which no longer exists.
        // Package-source files are now the only source of starter code; users
        // wanting to ship their own should publish a package.
        const next: Starter[] = [];
        for (const s of userStarters) {
            if (s.id === starterNew.id) next.push({ ...starterNew });
            else next.push({ ...s });
        }
        setUserStarters(next);
    };

    const getStarters = (type: NodeTemplateId, custom: boolean) => {
        const pool = custom ? userStarters : defaultStarters;
        const out: Starter[] = [];
        for (const s of pool) {
            if (s.type === type) out.push({ ...s });
        }
        return out;
    };

    const deleteStarter = (starterId: string) => {
        const next: Starter[] = [];
        for (const s of userStarters) {
            if (s.id !== starterId) next.push({ ...s });
        }
        setUserStarters(next);
    };

    return (
        <StarterContext.Provider
            value={{
                getStarters,
                createUserStarter,
                editUserStarter,
                deleteStarter,
                fetchStarters,
            }}
        >
            {children}
        </StarterContext.Provider>
    );
};

export const useStarterContext = () => {
    const context = useContext(StarterContext);

    if (!context) {
        throw new Error(
            "useStarterContext must be used within a StarterProvider"
        );
    }

    return context;
};

export default StarterProvider;
