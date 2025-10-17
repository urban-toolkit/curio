import React, { useState, useEffect, useRef } from "react";
import CSS from "csstype";
import { useLLMContext } from "../../../providers/LLMProvider";
import { useFlowContext } from "../../../providers/FlowProvider";
import { TrillGenerator } from "../../../TrillGenerator";
import { useCode } from "../../../hook/useCode";
import "./WorkflowGoal.css";

export default function WorkflowGoal({ }: { }) {
    const { openAIRequest, setCurrentEventPipeline } = useLLMContext();
    const { nodes, edges, workflowNameRef, suggestionsLeft, workflowGoal, updateWarnings, updateSubtasks, setWorkflowGoal, eraseWorkflowSuggestions, flagBasedOnKeyword, cleanCanvas, updateKeywords } = useFlowContext();
    const { loadTrill } = useCode();
    const [isEditing, setIsEditing] = useState(false);
    const [segments, setSegments] = useState<any>([]);
    const [highlights, setHighlights] = useState<any>({});

    const [tooltip, setTooltip] = useState({ visible: false, text: "", x: 0, y: 0, color: "" });
    const [loading, setLoading] = useState(false);
    const [tempWorkflowGoal, setTempWorkflowGoal] = useState(workflowGoal);

    const workflowGoalRef = useRef("");

    useEffect(() => {
        workflowGoalRef.current = workflowGoal;
    }, [workflowGoal]);

    const highlightsRef = useRef({});

    useEffect(() => {
        highlightsRef.current = highlights;
    }, [highlights]);

    const nodesRef = useRef<any>([]);

    useEffect(() => {
        nodesRef.current = nodes;
    }, [nodes]);

    const edgesRef = useRef<any>([]);

    useEffect(() => {
        edgesRef.current = edges;
    }, [edges]);

    const lastParsedGoalRef = useRef<string>("");
    const lastBindedGoalRef = useRef<string>("");
    const lastDecomposedGoalRef = useRef<string>("");
    const lastSubtasksNewTaskRef = useRef<Set<string>>(new Set([]));
    const lastSubtasksWarningRef = useRef<Set<string>>(new Set([]));

    const typeColors: any = {
        Action: "#e6b1b1",
        Dataset: "#b1b5e6",
        Where: "#b1e6c0",
        About: "#e6e6b1",
        Interaction: "#d7b1e6",
        Source: "#e6cdb1",
        Connection: "#e6b1d3",
        Content: "#dedede"
    };

    const generateSuggestion = async (skipConfirmation?: boolean) => {

        let isConfirmed = false;

        if(!skipConfirmation)
            isConfirmed = window.confirm("Are you sure you want to proceed? This will clear your entire board.");
        
        if (isConfirmed || skipConfirmation) {
            setLoading(true);

            cleanCanvas();

            let trill_spec = TrillGenerator.generateTrill(nodes, edges, workflowNameRef.current, workflowGoal);
    
            try {
    
                let result = await openAIRequest("default_preamble", "workflow_suggestions_prompt", "Target dataflow: " + JSON.stringify(trill_spec) + "\n" + "The user goal is: "+workflowGoal+" ");
    
                console.log("generateSuggestion result", result);
    
                let clean_result = result.result.replaceAll("```json", "");
                clean_result = clean_result.replaceAll("```", "");
    
                let parsed_result = JSON.parse(clean_result);
                parsed_result.dataflow.name = workflowNameRef.current;
    
                loadTrill(parsed_result, "workflow");
            } catch (error) {
                console.error("Error communicating with LLM", error);
                alert("Error communicating with LLM");
            } finally {
                setLoading(false);
            }
        }
    }

    const getNewHighlightsBinding = async (nodes: any, edges:any, workflowName: string, workflowGoal: string, current_keywords: any) => {
        let trill_spec = TrillGenerator.generateTrill(nodes, edges, workflowName, workflowGoal);

        let copy_trill = {...trill_spec};

        if(copy_trill.dataflow && copy_trill.dataflow.nodes){
            for(const node of copy_trill.dataflow.nodes){
                if(node.metadata && node.metadata.keywords)
                    delete node.metadata.keywords
            }
        }

        if(copy_trill.dataflow && copy_trill.dataflow.edges){
            for(const edge of copy_trill.dataflow.edges){
                if(edge.metadata && edge.metadata.keywords)
                    delete edge.metadata.keywords
            }
        }

        setLoading(true);

        try {
            let result = await openAIRequest("default_preamble", "keywords_binding_prompt", " Current keywords: " + JSON.stringify(current_keywords) + "\n" + "Trill specification: " + JSON.stringify(trill_spec));

            console.log("getNewHighlightsBinding result", result, workflowGoal);

            let clean_result = result.result.replaceAll("```json", "");
            clean_result = clean_result.replaceAll("```", "");

            let parsed_result = JSON.parse(clean_result);
            parsed_result.dataflow.name = workflowNameRef.current;

            updateKeywords(parsed_result); // Update keywords on the nodes and edges
        } catch (error) {
            console.error("Error communicating with LLM", error);
            alert("Error communicating with LLM");
        } finally {
            setLoading(false);
        }

    }

    const cancelSuggestions = () => {
        eraseWorkflowSuggestions();
    }

    const parseKeywords = async (goal: string) => {
        try {

            if(goal == "")
                return

            let result = await openAIRequest("syntax_analysis_preamble", "syntax_analysis_prompt", goal);

            console.log("parseKeywords result", result);

            let highlights = JSON.parse(result.result);

            const regex = new RegExp(`(${Object.keys(highlights).join("|")})`, "gi");
            const parts = goal.split(regex);

            let highlights_with_index: any = {};

            let keywords = Object.keys(highlights);

            for(let i = 0; i < keywords.length; i++){
                highlights_with_index[keywords[i]] = {
                    type: highlights[keywords[i]],
                    index: i
                };
            }

            setHighlights(highlights_with_index);
            setSegments(parts);

        } catch (error) {
            console.error("Error communicating with LLM", error);
            alert("Error communicating with LLM");
        }
    }

    // Based on the current state of the workflow generates a new task that better reflects what is being done by the user
    const getNewTask = async (current_task: string, current_keywords: any) => {

        try {
            let trill_spec = TrillGenerator.generateTrill(nodesRef.current, edgesRef.current, workflowNameRef.current, workflowGoalRef.current);

            let trill_spec_string = JSON.stringify(trill_spec);
            
            let subtasks = new Set<string>([]);

            for(const node of trill_spec.dataflow.nodes){
                subtasks.add(node.goal);
            }
            
            let difference_1 = new Set([...lastSubtasksNewTaskRef.current].filter((x) => !subtasks.has(x)));
            let difference_2 = new Set([...subtasks].filter((x) => !lastSubtasksNewTaskRef.current.has(x)));

            if(difference_1.size == 0 && difference_2.size == 0){
                console.log("Not generating new task - subtasks did not change");
                return;
            }

            lastSubtasksNewTaskRef.current = subtasks;
            
            let result = await openAIRequest("default_preamble", "task_refresh_prompt", "Current Task: " + current_task + "\n" + " Current keywords: " + JSON.stringify(current_keywords) + "\n" + "Trill specification: " + trill_spec_string);

            console.log("getNewTask result", result);

            setWorkflowGoal(result.result);

        } catch (error) {
            console.error("Error communicating with LLM", error);
            alert("Error communicating with LLM");
        }

    }

    const handleGoalChange = (e: any) => {
        setTempWorkflowGoal(e.target.value);
    };

    const handleNameBlur = () => {

        setIsEditing(false);

        setCurrentEventPipeline("Directly editing a Task");
        setTempWorkflowGoal(tempWorkflowGoal);

        if(tempWorkflowGoal != workflowGoal){
            setWorkflowGoal(tempWorkflowGoal);
            parseKeywords(tempWorkflowGoal);
            getNewSubtasks(tempWorkflowGoal);
        }
    };

    const getNewSubtasks = async (current_task: string) => { // Based on the changes that the user made on the task reflect it to the subtasks

        try {

            if(nodesRef.current.length != 0){
                let trill_spec = TrillGenerator.generateTrill(nodesRef.current, edgesRef.current, workflowNameRef.current, current_task);

                let result = await openAIRequest("default_preamble", "new_subtasks_prompt", "Current Task: " + current_task + "\n" + "Trill specification: " + JSON.stringify(trill_spec));
    
                console.log("getNewSubtasks", result);

                let clean_result = result.result.replaceAll("```json", "");
                clean_result = clean_result.replaceAll("```", "");
    
                let parsed_result = JSON.parse(clean_result);
                parsed_result.dataflow.name = workflowNameRef.current;
    
                updateSubtasks(parsed_result);
            }

        } catch (error) {
            console.error("Error communicating with LLM", error);
            alert("Error communicating with LLM");
        }

    }

    useEffect(() => {

        const decomposeGoalInterval = setInterval(() => { 
            if(lastDecomposedGoalRef.current != workflowGoalRef.current){
                getNewSubtasks(workflowGoalRef.current);
                lastDecomposedGoalRef.current = workflowGoalRef.current;
            }
        }, 120000);

        const higlightsMatchingInterval = setInterval(() => { 
            if(lastBindedGoalRef.current != workflowGoalRef.current){
                getNewHighlightsBinding(nodesRef.current, edgesRef.current, workflowNameRef.current, workflowGoalRef.current, highlightsRef.current);
                lastBindedGoalRef.current = workflowGoalRef.current;
            }
        }, 90000);

        const goalParsingInterval = setInterval(() => { 
            if(lastParsedGoalRef.current != workflowGoalRef.current){
                parseKeywords(workflowGoalRef.current);
                lastParsedGoalRef.current = workflowGoalRef.current;
            }
        }, 60000);

        const warningsInterval = setInterval(() => { 
            // getNewTask(workflowGoalRef.current, highlightsRef.current);
            generateWarnings(workflowGoalRef.current, nodesRef.current, edgesRef.current, workflowNameRef.current);
        }, 60000);

        const getNewTaskInterval = setInterval(() => { 
            getNewTask(workflowGoalRef.current, highlightsRef.current);
        }, 30000);

        // Cleanup interval on unmount
        return () => {
            clearInterval(goalParsingInterval);
            clearInterval(getNewTaskInterval);
            clearInterval(higlightsMatchingInterval);
            clearInterval(decomposeGoalInterval);
            clearInterval(warningsInterval);
        };
    }, []);

    const generateWarnings = async (goal: string, nodes: any, edges: any, workflowNameRef: any) => {
        try{

            let trill_spec = TrillGenerator.generateTrill(nodes, edges, workflowNameRef.current, workflowGoal);

            let subtasks = new Set<string>([]);

            for(const node of trill_spec.dataflow.nodes){
                subtasks.add(node.goal);
            }
            
            let difference_1 = new Set([...lastSubtasksWarningRef.current].filter((x) => !subtasks.has(x)));
            let difference_2 = new Set([...subtasks].filter((x) => !lastSubtasksWarningRef.current.has(x)));

            if(difference_1.size == 0 && difference_2.size == 0){
                console.log("Not generating warnings - subtasks did not change");
                return;
            }

            lastSubtasksWarningRef.current = subtasks;

            let result_warnings = await openAIRequest("default_preamble", "evaluate_coherence_subtasks_prompt", "Task: " + goal + " \n Current Trill: " + JSON.stringify(trill_spec));

            console.log("warnings result", result_warnings);

            let clean_result_warnings = result_warnings.result.replaceAll("```json", "").replaceAll("```python", "");
            clean_result_warnings = clean_result_warnings.replaceAll("```", "");

            let parsed_result_warnings = JSON.parse(clean_result_warnings);

            updateWarnings(parsed_result_warnings);

        }catch(error){
            console.error("Error communicating with LLM", error);
            alert("Error communicating with LLM");
        }
    }

    const clickGenerateSuggestion = () => {
        setCurrentEventPipeline("Generating suggestions from Task");
        generateSuggestion(false);
    }

    return (
        <>
            {/* Editable Workflow Goal */}
            <div style={workflowGoalContainer}>
                
                <div style={{boxShadow: "rgba(0, 0, 0, 0.1) 0px 0px 50px", borderRadius: "4px", width: "800px", overflowY: "auto", height: "200px", padding: "5px", display: "flex", justifyContent: "center", alignItems: "center", scrollbarColor: "#1d3853 transparent"}}>
                    {workflowGoal == "" && !isEditing ?
                        <p style={{marginBottom: "0px", opacity: 0.7, color: "#1E1F23", fontSize: "20px", cursor: "pointer"}} onClick={() => {
                            setIsEditing(true)
                        }}>Click here or interact with the LLM to define your task</p> : 
                        <p style={goalStyle} onClick={() => {
                            setIsEditing(true)
                        }}>
                            {/* {segments.map((item: any, index: any) => (
                                item
                            ))} */}
                            {isEditing ? 
                                <textarea style={{width: "100%", height: "100%", resize: "none", border: "none", backgroundColor: "rgb(251, 252, 246)", color: "#1E1F23", fontFamily: "Rubik", padding: "10px"}} autoFocus placeholder="Specify your task..." value={tempWorkflowGoal} onChange={handleGoalChange} onBlur={handleNameBlur}></textarea>
                            : 
                                segments.map((part: any, index: any) =>
                                    highlights[part] ? (
                                        <span key={index+"_span_text_goal"} style={{ backgroundColor: typeColors[highlights[part]["type"]], fontWeight: "bold", fontFamily: "Rubik", fontSize: "18px", padding: "2px", marginRight: "4px", borderRadius: "5px", cursor: "default", color: "#1E1F23"}}
                                            onMouseEnter={(e) => {
                                                setTooltip({
                                                    visible: true,
                                                    text: highlights[part]["type"],
                                                    x: e.clientX + 10,
                                                    y: e.clientY + 10,
                                                    color: typeColors[highlights[part]["type"]]
                                                });

                                                flagBasedOnKeyword(highlights[part]["index"]);
                                            }}
                                            onMouseMove={(e) => {
                                                setTooltip(prev => ({ ...prev, x: e.clientX + 10, y: e.clientY + 10, color: typeColors[highlights[part]["type"]]}));
                                            }}
                                            onMouseLeave={(e) => {
                                                setTooltip({ visible: false, text: "", x: 0, y: 0, color: "" });
                                            
                                                flagBasedOnKeyword();
                                            }}
                                        >
                                            {part}
                                            
                                        </span>
                                    ) : (
                                    <span key={index+"_span_text_goal"} style={{fontWeight: "bold", fontFamily: "Rubik", fontSize: "18px", cursor: "default", color: "#1E1F23"}}>{part}</span>
                                    )
                                )}
                        </p>
                    }   
                </div>
                {!loading ?
                    workflowGoal != "" ?
                        suggestionsLeft > 0 ? 
                            <button style={button} onClick={cancelSuggestions}>Cancel suggestions</button> :
                            <button style={button} onClick={clickGenerateSuggestion}>Generate suggestions</button>
                        : null : <button style={button}>...</button>
                }

                {tooltip.visible && (
                    <div style={{...{
                        position: "relative",
                        padding: "5px",
                        border: "1px solid #ccc",
                        borderRadius: "4px",
                        boxShadow: "0px 0px 5px rgba(0,0,0,0.2)",
                        zIndex: 1000
                    }, ...(tooltip.color != "" ? {backgroundColor: tooltip.color} : {})}}>
                        {tooltip.text}
                    </div>
                )}

                
            </div>
        </>

    );
}

const workflowGoalContainer: CSS.Properties = {
    top: "90px",
    textAlign: "center",
    zIndex: 100,
    left: "50%",
    transform: "translateX(-50%)",
    position: "fixed",
    display: "flex",
    flexDirection: "column",
    backgroundColor: "rgb(251, 252, 246)"
};

const goalStyle: CSS.Properties = {
    width: "100%",
    height: "100%",
    fontSize: "16px",
    marginBottom: "0",
    fontWeight: "bold",
    textAlign: "center",
    borderRadius: "4px",
    padding: "5px",
    lineHeight: "1.9"
};

const button: CSS.Properties = {
    backgroundColor: "#1E1F23",
    border: "none",
    color: "rgb(251, 252, 246)",
    fontFamily: "Rubik",
    fontWeight: "bold",
    padding: "6px 10px",
    borderRadius: "5px"
};
 

