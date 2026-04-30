import React, {
    createContext,
    useContext,
    ReactNode,
    useState,
    useRef,
    useEffect
} from "react";
import { getToken } from "../utils/authApi";
import { BACKEND_URL } from "../utils/backendUrl";

interface LLMContextProps {
    llmRequest: (preamble_file: string, prompt_file: string, text: string, chatId?: string) => any;
    setCurrentEventPipeline: (eventName: string) => void;
    currentEventPipeline: string;
    AIModeRef: React.MutableRefObject<boolean>;
    setAIMode: (value: boolean) => void;
}

export const LLMContext = createContext<LLMContextProps>({
    llmRequest: () => {},
    setCurrentEventPipeline: () => {},
    currentEventPipeline: "",
    AIModeRef: { current: false },
    setAIMode: () => {}
});

const LLMProvider = ({ children }: { children: ReactNode }) => {

    const [currentEventPipeline, setCurrentEventPipeline] = useState("");

    const [AIMode, _setAIMode] = useState<boolean>(false);
    const AIModeRef = React.useRef(AIMode);
    const setAIMode = (data: any) => {
        AIModeRef.current = data;
        _setAIMode(data);
    };

    const authHeader = (): Record<string, string> => {
        const token = getToken();
        return token ? { "Authorization": `Bearer ${token}` } : {};
    };

    const llmRequest = async (preamble_file: string, prompt_file: string, text: string, chatId?: string) => {

        let message: any = {preamble: preamble_file, prompt: prompt_file, text: text};

        if(chatId)
            message.chatId = chatId;

        const response_usage = await fetch(`${BACKEND_URL}/llm/check`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...authHeader(),
            },
            body: JSON.stringify(message),
        });

        if (!response_usage.ok) {
            const body = await response_usage.json().catch(() => ({}));
            throw new Error(body.description || body.error || "LLM request failed.");
        }

        const result_usage = await response_usage.json();

        if(result_usage.result != "yes")
            await new Promise(resolve => setTimeout(resolve, (result_usage.result + 15) * 1000));

        const response = await fetch(`${BACKEND_URL}/llm/chat`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              ...authHeader(),
            },
            body: JSON.stringify(message),
        });

        if (!response.ok) {
            const body = await response.json().catch(() => ({}));
            throw new Error(body.description || body.error || "LLM request failed.");
        }

        const result = await response.json();
        return result;
    }

    return (
        <LLMContext.Provider
            value={{
                llmRequest,
                setCurrentEventPipeline,
                currentEventPipeline,
                AIModeRef,
                setAIMode
            }}
        >
            {children}
        </LLMContext.Provider>
    );
};

export const useLLMContext = () => {
    const context = useContext(LLMContext);

    if (!context) {
        throw new Error("useLLMContext must be used within a LLMProvider");
    }

    return context;
};

export default LLMProvider;
