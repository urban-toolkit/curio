import React, { createContext, useContext, useState, ReactNode } from 'react';

interface GlobalContextType {
    globalVariable: string;
    setGlobalVariable: React.Dispatch<React.SetStateAction<string>>;
}

const GlobalContext = createContext<GlobalContextType | undefined>(undefined);

export const GlobalProvider = ({ children }: { children: ReactNode }) => {
    const [globalVariable, setGlobalVariable] = useState<string>("");

    return (
        <GlobalContext.Provider value={{ globalVariable, setGlobalVariable }}>
            {children}
        </GlobalContext.Provider>
    );
};

export const useGlobalContext = () => {
    const context = useContext(GlobalContext);
    if (!context) {
        throw new Error("useGlobalContext must be used within a GlobalProvider");
    }
    return context;
};
