import React, { useEffect, useState, useRef } from "react";

// Bootstrap
import "bootstrap/dist/css/bootstrap.min.css";
import { WidgetType } from "../../constants";

import './WidgetsEditor.css';

type WidgetsEditorProps = {
    userCode: any // grammar or python
    sendReplacedCode: any // bubble up the code (python or grammar) with the marks resolved
    nodeId: string
    markersDirty: boolean // changes on this prop will make markers be replaced in the code
    customWidgetsCallback?: any
}

function WidgetsEditor({ userCode, sendReplacedCode, nodeId, markersDirty, customWidgetsCallback }: WidgetsEditorProps) {

    // const [currentWidgetsValues, setCurrentWidgetsValues] = useState<any>({}); // validated // {[variable]: {widget: string, value: string}}
    const [nonValidatedValues, setNonValidatedValues] = useState<any>({});

    const markersDirtyBypass = useRef(false);

    // returns {widget: string, value: string} with converted value if valid or {} if invalid
    const validateWidgetValue = (widget: string, value: string) => {
        const isANumber = (elem: string) => {
            let num = parseFloat(elem);
            if(!isNaN(num))
                return true;

            num = parseInt(elem);
            if(!isNaN(num))
                return true;

            return false
        }

        let valid = false;
        let convertedValue = value;

        if(widget == WidgetType.CHECKBOX){
            if(value == "True" || value == "False"){
                valid = true;
            }
        }else if(widget == WidgetType.INPUT_VALUE){
            valid = isANumber(value);
        }else if(widget == WidgetType.INPUT_TEXT){ // anything can be used as text
            valid = true;
            convertedValue = "\""+value.replaceAll("\"", "")+"\""; // surrounding the value in quotes to be understood as a string
        }else if(widget == WidgetType.INPUT_LIST_VALUE || widget == WidgetType.INPUT_LIST_TEXT){
            try {
                JSON.parse(value); // checking if it is a valid array
                valid = true;
            } catch (error) {
                console.log("error", error);
                valid = false;
            }
        }else if(widget == WidgetType.RANGE){
            try {
                let list = JSON.parse(value); // checking if it is a valid array
                
                if(list.length == 2 && isANumber(list[0]) && isANumber(list[1]) && list[0] <= list[1])
                    valid = true;
            } catch (error) {
                valid = false;
            }
        }else if(widget == WidgetType.SELECTION){ // anything can be used as text
            valid = true;
            convertedValue = "\""+value.replaceAll("\"","")+"\""; // surrounding the value in quotes to be understood as a string
        }else if(widget == WidgetType.FILE){ // anything can be used as text
            valid = true;
            convertedValue = "\""+value+"\""; // surrounding the value in quotes to be understood as a string
        }

        if(valid){
            return {widget: widget, value: convertedValue};
        }else{
            return {};
        }
    }

    // look for markers in this format [!! variable$widget$default !!]
    const resolveMarks = (userCode: string, currentWidgetsValues: any) => {
        const computeMark = (content: string, prevWidgetsValues: any) => {
            let config = content.split('$');

            if (config.length < 3 || config.length > 4) {
                alert("Invalid marker [!! " + content + " !!]. Markers must follow [!! variable$widget$default$arg1;arg2;arg3 !!]");
                return {}
            }

            let args = undefined;

            if(config.length == 4){
                args = config[3].split(";");
            }

            if(prevWidgetsValues[config[0]] != undefined && prevWidgetsValues[config[0]].widget == config[1]){ // this is not a new marker, carry the previous value of the widget
                
                if(args != undefined)
                    return {[config[0]]: {widget: config[1], value: prevWidgetsValues[config[0]].value, args: args}};
                else
                    return {[config[0]]: {widget: config[1], value: prevWidgetsValues[config[0]].value, args: undefined}};
            }else{
                let resolvedMark = validateWidgetValue(config[1], config[2]); // validate what comes from default values in the marks

                if(Object.keys(resolvedMark).length == 0){
                    alert("Invalid widget and default value combination for [!! "+content+" !!]");
                    return {}
                }

                if(args != undefined)
                    return {[config[0]]: {widget: resolvedMark.widget, value: resolvedMark.value, args: args}}; 
                else
                    return {[config[0]]: {widget: resolvedMark.widget, value: resolvedMark.value, args: undefined}}; 
            }
        }

        // Regular expression to match the content inside [!! !!] markers globally
        // @ts-ignore
        const regex = /\[\!\!\s*(.*?)\s*\!\!\]/g;

        let widgetsValues: any = {}

        let errorReplacing = false;

        const replacedCode = userCode.replace(regex, (match, content) => {
            const param = computeMark(content, currentWidgetsValues);
            const atribs = Object.keys(param);

            if(atribs.length == 0){
                errorReplacing = true;
                return ""
            }else{
                const variable = atribs[0];
                widgetsValues[variable] = {widget: param[variable].widget, value: param[variable].value, args: param[variable].args};
                
                return param[variable].value as string;
            }
        });

        if(errorReplacing){
            alert("Could not resolve marks");
            return {}
        }else{
            sendReplacedCode(replacedCode);
            return widgetsValues;
        }
    }

    const updateCurrentWidgets = () => {
        // Update currentWidgets (the user pressed exec)
        let div = document.getElementById("widgetsEditor"+nodeId) as HTMLElement;

        let inputs = div.querySelectorAll("input");
        let selects = div.querySelectorAll("select");

        let newCurrentWidgetsValues: any = {};

        let validation = true; // flag to indicate if the input from the user was validated sucessfully

        // computing user input
        setNonValidatedValues((prev: any) => {

            let variables = Object.keys(prev);

            for(const elem of variables){
                inputs.forEach(function(input) {

                    let splitId = input.id.split(";");

                    let widget = splitId[0];
                    let variable = splitId[1];

                    if(elem == variable){

                        let validatedValue = validateWidgetValue(widget, prev[elem].value);

                        if(Object.keys(validatedValue).length != 0){ // correctly validated
                            newCurrentWidgetsValues[elem] = {widget: widget, value: validatedValue.value, args: prev[elem].args}
                        }else{
                            validation = false;
                            return prev;
                        }
                    }
                });

                selects.forEach(function(select) {

                    let splitId = select.id.split(";");

                    let widget = splitId[0];
                    let variable = splitId[1];

                    if(elem == variable){
                        let validatedValue = validateWidgetValue(widget, prev[elem].value);

                        if(Object.keys(validatedValue).length != 0){ // correctly validated
                            newCurrentWidgetsValues[elem] = {widget: widget, value: validatedValue.value, args: prev[elem].args}
                        }else{
                            validation = false;
                            return prev;
                        }
                    }
                });

            }

            // setCurrentWidgetsValues({...newCurrentWidgetsValues});

            return prev;
        });

        if(validation){
            // computing marks and considering defaults
            let newWidgetsValues = resolveMarks(userCode, newCurrentWidgetsValues);
        
            setNonValidatedValues({...newWidgetsValues});
        }else{
            alert("Invalid input(s) for widget(s)");
        }
    }

    useEffect(() => {
        if(markersDirtyBypass.current){
            updateCurrentWidgets();
        }

        markersDirtyBypass.current = true;
    }, [markersDirty]);

    useEffect(() => {
        if(customWidgetsCallback != undefined){
            const div = document.getElementById("widgetsEditor"+nodeId);

            customWidgetsCallback(div);
        }
    }, []);

    const inputChanged = (event: any) => {

        let splitId = event.target.id.split(";");

        let widget = splitId[0];
        let variable = splitId[1];

        let variables = Object.keys(nonValidatedValues);

        let newNonValidatedValues: any = {};

        for(const elem of variables){
            if(elem == variable){ // updating the value of the interacted variable
                if(widget == WidgetType.CHECKBOX){
                    if(nonValidatedValues[variable].value == "True")
                        newNonValidatedValues[variable] = {widget: widget, value: "False", args: nonValidatedValues[elem].args}
                    else
                        newNonValidatedValues[variable] = {widget: widget, value: "True", args: nonValidatedValues[elem].args}
                }else{
                    // TODO: implement file input
                    newNonValidatedValues[elem] = {widget: widget, value: event.target.value, args: nonValidatedValues[elem].args}
                }
            }else{
                newNonValidatedValues[elem] = {widget: nonValidatedValues[elem].widget, value: nonValidatedValues[elem].value, args: nonValidatedValues[elem].args};
            }
        }

        setNonValidatedValues(newNonValidatedValues);
    }

    const getHTMLWidget = (data: {widget: string, value: string, args: string[] | undefined}, key: number, variable: string) => {
        if(data.widget == WidgetType.CHECKBOX){
            if(data.value == "True")
                return <input onChange={(event) => inputChanged(event)} type="checkbox" key={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} checked={true} />
            else
                return <input onChange={(event) => inputChanged(event)} type="checkbox" key={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} checked={false} />
        }else if(data.widget == WidgetType.INPUT_VALUE){
            return <input onChange={(event) => inputChanged(event)} type="number" key={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} step="any" value={data.value} />
        }else if(data.widget == WidgetType.INPUT_TEXT){
            return <input onChange={(event) => inputChanged(event)} type="text" key={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} value={data.value.replaceAll("\"", "")} />
        }else if(data.widget == WidgetType.INPUT_LIST_TEXT || data.widget == WidgetType.RANGE || data.widget == WidgetType.INPUT_LIST_VALUE){
            return <input onChange={(event) => inputChanged(event)} type="text" key={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} value={data.value} />
        }else if(data.widget == WidgetType.SELECTION){
            return <select onChange={(event) => inputChanged(event)} key={data.widget+key+"_widget_"+nodeId} name={data.widget+key+"_widget_"+nodeId} id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} value={data.value.replaceAll("\"","")}>
                {
                    data.args != undefined ?
                    data.args.map((option: string, key2: number) => {
                        return <option key={data.widget+key+"_widget_"+nodeId+key2} value={option}>{option}</option>
                    }) : null
                }
            </select>
        }else if(data.widget == WidgetType.FILE){
            return <div key={data.widget+key+"_widget_"+nodeId}>
                <input onChange={(event) => inputChanged(event)} type="file" id={data.widget+";"+variable+";"+key+"_widget_"+nodeId} accept=".txt, .csv, .json" />
            </div>
        }
    }

    // when user interacts with widgets currentWidgetsValues must be updated. Make sure to convert the input to the right type
    // validate input on the widgets every time the focus is out

    return (
        <div id={"widgetsEditor"+nodeId} style={{ height: "100%", padding:"10px", fontSize: "10px", overflowY: "auto"}} className="nowheel nodrag">
            {
                Object.keys(nonValidatedValues).length != 0 ?
                Object.keys(nonValidatedValues).map((variable: string, key: number) => {
                    return <div style={{marginBottom: "5px"}} key={nonValidatedValues[variable].widget+key+"_widget_"+nodeId+"div"}>
                        <label style={{fontWeight: "bold"}} key={nonValidatedValues[variable].widget+key+"_widget_"+nodeId+"label"} htmlFor={nonValidatedValues[variable].widget+key+"_widget_"+nodeId}>{variable}:</label>
                        {getHTMLWidget(nonValidatedValues[variable], key, variable)}
                    </div>
                }) : customWidgetsCallback == undefined ? <div><span>No widgets found</span></div> : null
            }
        </div>
    );
}

export default WidgetsEditor;
