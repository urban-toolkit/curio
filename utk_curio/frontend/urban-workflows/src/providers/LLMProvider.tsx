import React, {
    createContext,
    useContext,
    ReactNode,
    useState,
    useRef,
    useEffect
} from "react";

interface LLMContextProps {
    openAIRequest: (preamble_file: string, prompt_file: string, text: string, chatId?: string) => any;
    setCurrentEventPipeline: (eventName: string) => void;
    currentEventPipeline: string;
    AIModeRef: React.MutableRefObject<boolean>;
    setAIMode: (value: boolean) => void;
}

export const LLMContext = createContext<LLMContextProps>({
    openAIRequest: () => {},
    setCurrentEventPipeline: () => {},
    currentEventPipeline: "",
    AIModeRef: { current: false },
    setAIMode: () => {}
});

const LLMProvider = ({ children }: { children: ReactNode }) => {

    const [currentEventPipeline, setCurrentEventPipeline] = useState("");
    // const [AIMode, setAIMode] = useState<boolean>(false);

    const [AIMode, _setAIMode] = useState<boolean>(false);
    const AIModeRef = React.useRef(AIMode);
    const setAIMode = (data: any) => {
        AIModeRef.current = data;
        _setAIMode(data);
    };

    const openAIRequest = async (preamble_file: string, prompt_file: string, text: string, chatId?: string) => {

        let message: any = {preamble: preamble_file, prompt: prompt_file, text: text};

        if(chatId)
            message.chatId = chatId;

        const response_usage = await fetch(`${process.env.BACKEND_URL}/checkUsageOpenAI`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(message),
        });

        if (!response_usage.ok) {
            throw new Error("Failed to submit data.");
        }

        const result_usage = await response_usage.json();

        if(result_usage.result != "yes") // There is no token left, have to wait
            await new Promise(resolve => setTimeout(resolve, (result_usage.result + 15) * 1000)); // add a 15 seconds margin

        console.log("message", {...message});

        const response = await fetch(`${process.env.BACKEND_URL}/openAI`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify(message),
        });
    
        if (!response.ok) {
            throw new Error("Failed to submit data.");
        }

        const result = await response.json();
        return result;
    }

    return (
        <LLMContext.Provider
            value={{
                openAIRequest,
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
