import React, { useState, useEffect } from "react";
import { useLLMContext } from "../providers/LLMProvider";
import { useFlowContext } from "../providers/FlowProvider";
import CSS from "csstype";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
    faAnglesUp,
    faBroom,
    faArrowUp
} from "@fortawesome/free-solid-svg-icons";
import ReactMarkdown from "react-markdown";
import "./LLMChat.css";

const ChatComponent = () => {
    const { openAIRequest, setCurrentEventPipeline } = useLLMContext();
    const { setWorkflowGoal, cleanCanvas } = useFlowContext();
    const [messages, setMessages] = useState<{ role: string; text: string }[]>([]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);
    const [isOpen, setIsOpen] = useState(true);

    const handleSendMessage = async () => {
        if (!input.trim()) return;

        const userMessage = { role: "user", text: input };
        setMessages((prev) => [...prev, userMessage]);
        setInput("");
        setLoading(true);

        try {

            const response = await openAIRequest("default_preamble", "chat_prompt", input, "ChatComponent");
            const aiMessage = { role: "ai", text: response.result };
            setMessages((prev) => [...prev, aiMessage]);
        } catch (error) {
            console.error("Error fetching response:", error);
        } finally {
            setLoading(false);
        }
    };

    // Check if the goal was already output by the LLM. Return undefined if goal is not there or the goal itself.
    const checkForGoal = (message: string) => {
        const regex = /\*\*(.*?)\*\*/g;

        if(message.toLowerCase().includes("task")){
            const matches = [...message.matchAll(regex)].map(match => match[1]);

            if(matches.length > 0)
                return matches [0]

            return null;
        }

        return null;
    }

    const cleanOpenAIChat = () => {
        setLoading(false);
        setMessages([]);
            
        fetch(process.env.BACKEND_URL+"/cleanOpenAIChat?chatId=ChatComponent", {
            method: "GET"
        });
    }

    const applyGoal = (task: string) => {
        const isConfirmed = window.confirm("Are you sure you want to proceed? This will clear your entire board.");

        if (isConfirmed) {
            setCurrentEventPipeline("Applying Task from LLM");

            cleanCanvas();
            setWorkflowGoal(checkForGoal(task) as string);
        }
    }

    useEffect(() => {
        let messagesDiv = document.getElementById("messagesDiv");

        if (messagesDiv) {
            messagesDiv.scrollTop = messagesDiv.scrollHeight;
        }
    }, [messages]); // Scrolls when messages update

    useEffect(() => {
        cleanOpenAIChat();
    }, []);

    return (
        <div>
            {/* Toggle Button */}
            <button style={{...toggleButton, ...(isOpen ? openButton : {})}} onClick={() => setIsOpen(!isOpen)}>
                LLM <FontAwesomeIcon icon={faAnglesUp} style={{...(isOpen ? {transform: "rotate(90deg)"} : {transform: "rotate(270deg)"})}} />
            </button>
            {/* Sidebar */}
            <div style={{...sidebar, ...(isOpen ? openSidebar : {})}}>
                <div style={{display: "flex", width: "100%", height: "50px", justifyContent: "center", alignItems: "center", borderBottom: "1px solid rgba(29, 56, 83, 0.1)", flexDirection: "row", marginTop: "15px", paddingBottom: "20px"}}>
                    <p style={{margin: 0, fontWeight: "bold", marginRight: "10px", color: "#1E1F23", fontFamily: "Rubik", fontSize: "25px"}}>LLM Assistant</p>
                    <FontAwesomeIcon icon={faBroom} style={{cursor: "pointer", fontSize: "20px", color: "#1E1F23"}} title={"Clean chat"} onClick={cleanOpenAIChat} />
                </div>
                <div id={"messagesDiv"} style={{overflowY: "auto", height: "100%", width: "100%", padding: "15px"}}>
                    {messages.map((msg, index) => (
                        <div key={index} style={{...messagesBackground, ...(msg.role === "user" ? {marginLeft: "auto"} : {})}} className={`mb-2 p-2 rounded ${msg.role === "user" ? "bg-blue-100 text-right" : "bg-gray-200"}`}>
                            <ReactMarkdown>{msg.text}</ReactMarkdown>
                            {msg.role != "user" && checkForGoal(msg.text)?
                                <button style={applyGoalStyle} onClick={() => {applyGoal(msg.text)}}>Apply task</button> : null
                            }
                        </div>
                    ))}
                </div>
                <div style={inputDiv}>
                    <input
                        type="text"
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) => {
                            if(e.key === "Enter"){
                                handleSendMessage();
                            }}}
                        placeholder="Type your message..."
                        disabled={loading}
                        style={inputStyle}
                    />
                    <button
                        onClick={handleSendMessage}
                        disabled={loading}
                        style={sendButtonStyle}
                    >
                        {loading ? "..." : <FontAwesomeIcon icon={faArrowUp}/>}
                    </button>
                </div>
            </div>
        </div>
    );
};

const inputDiv: CSS.Properties =  {
    display: "flex",
    justifyContent: "center",
    marginBottom: "10px",
    backgroundColor: "#1E1F23",
    width: "90%",
    borderRadius: "10px",
    padding: "15px"
}

const inputStyle: CSS.Properties =  {
    padding: "5px",
    border: "none",
    backgroundColor: "#1E1F23",
    color: "#fbfcf6",
    width: "80%"
}

const sendButtonStyle: CSS.Properties =  {
    border: "none",
    marginLeft: "5px",
    backgroundColor: "rgb(251, 252, 246)",
    padding: "6px 10px",
    color: "#1E1F23",
    fontWeight: "bold",
    borderRadius: "50%",
    width: "40px",
    height: "40px"
}

const applyGoalStyle: CSS.Properties =  {
    border: "none",
    marginLeft: "5px",
    marginTop: "3px",
    marginBottom: "5px",
    backgroundColor: "#fbfcf6",
    color: "#1E1F23",
    fontWeight: "bold",
    borderRadius: "4px"
}

const sidebar: CSS.Properties =  {
    position: "fixed",
    top: "65px",
    right: "-450px",
    width: "450px",
    height: "calc(100% - 65px)",
    zIndex: 200,
    padding: "5px",
    backgroundColor: "#fbfcf6",
    boxShadow: "-10px 0px 50px rgba(0, 0, 0, 0.1)",
    transition: "right 0.3s ease-in-out",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "space-between",
    scrollbarColor: "#1E1F23 transparent"
}
  
const openSidebar: CSS.Properties = {
    right: 0
}

const openButton: CSS.Properties = {
    right: "450px"
}
  
const toggleButton: CSS.Properties = {
    position: "fixed",
    top: "65px",
    right: 0,
    padding: "10px 20px",
    zIndex: 200,
    backgroundColor: "#1E1F23",
    color: "rgb(251, 252, 246)",
    fontWeight: "bold",
    border: "none",
    cursor: "pointer",
    transition: "right 0.3s ease-in-out"
}

const messagesBackground: CSS.Properties = {
    borderRadius: "4px",
    backgroundColor: "#1E1F23",
    width: "75%",
    padding: "5px",
    color: "white"
}

export default ChatComponent;