import React, { useState, useEffect, useRef } from "react";
import { Form } from "react-bootstrap";
import Slider from '@mui/material/Slider';
import {Row, Col} from 'react-bootstrap';
import { ICategory } from "../interfaces";

// declaring the types of the props
type ToggleKnotsWidgetProps = {
    obj: any // map 
    listLayers: any
    knotVisibility: any
    viewId: string
    grammarDefinition: any
    broadcastMessage: any
    toggleColorScaleVisibility: any
}

export const ToggleKnotsWidget = ({obj, listLayers, knotVisibility, viewId, grammarDefinition, broadcastMessage, toggleColorScaleVisibility}:ToggleKnotsWidgetProps) =>{
   
    // Animation ====================================================

    const [initialTime, setInitialTime] = useState<number>(Date.now());

    const [maxTimestep, setMaxTimestep] = useState<number>(0);
    const [minTimestep, setMinTimestep] = useState<number>(0);

    const [sliderValue, setSliderValue] = useState<number[]>([0,1]);

    const [fps, _setFps] = useState<number>(5);

    const fpsRef = useRef(fps);
    const setFps = (data: any) => {
        fpsRef.current = data;
        _setFps(data);
    };

    // current ranges
    const [range, _setRange] = useState<any>({});

    const rangeRef = useRef(range);
    const setRange = (data: any) => {
        rangeRef.current = data;
        _setRange(data);
    };

    // persisting listLayers to get inside interval
    const [listLayersState, _setListLayersState] = useState<any>({});

    const listLayersStateRef = useRef(listLayersState);
    const setListLayersState = (data: any) => {
        listLayersStateRef.current = data;
        _setListLayersState(data);
    };

    // const [colorScales, setColorScales] = useState<{range: number[], domain: number[], cmap: string, id: string, scale: string}[]>([]);
    
    useEffect(() => {

        const intervalId = window.setInterval(function(){

            let div = document.getElementById("toggle_widget_"+viewId);

            if(div == null || Object.keys(listLayersStateRef.current).length == 0)
                return;

            let children = div.childNodes;

            let groupsToAnimate = [];

            for (let i = 0; i < children.length; i++) {
                const child = children[i] as HTMLElement;
            
                let inputs = child.querySelectorAll("div input");

                for(let j = 0; j < inputs.length; j++){
                    let input = inputs[j] as HTMLInputElement;

                    if(input.checked && listLayersStateRef.current[input.id] != undefined && listLayersStateRef.current[input.id].length > 1){
                        groupsToAnimate.push(input.id);
                    }
                }   
            }

            for(const group of groupsToAnimate){

                let knotsToConsider = [];
                let range = 0 ? rangeRef.current[group] == undefined : rangeRef.current[group];

                knotsToConsider = listLayersStateRef.current[group].slice(0,range+1);

                if(knotsToConsider.length == 0) // should not do any animation
                    return
    
                let elapsedTime = Date.now() - initialTime;
    
                let changeEvery = 1000/fpsRef.current;
    
                let indexLayer = Math.round((elapsedTime%(changeEvery*(knotsToConsider.length)))/changeEvery);

                if(indexLayer > knotsToConsider.length-1){
                    indexLayer = 0;
                }

                let layerToShow = knotsToConsider[indexLayer];
    
                for(let i = 0; i < listLayersStateRef.current[group].length; i++){
                    let key = listLayersStateRef.current[group][i];
    
                    if(key == layerToShow){
                        obj.toggleKnot(layerToShow, true);
                    }else{
                        obj.toggleKnot(key, false);
                    }
                }
            }
                
        }, 50);

        return () => {
            window.clearInterval(intervalId);
        };

    }, [listLayersState]);

    useEffect(() => {

        setListLayersState(listLayers);

    }, [listLayers]);

    // =================================================

    const groupVisibility = (groupedList:any, visibilityList: any, id: string) => {
        for(const layer of groupedList[id]){
            if(visibilityList[layer.id]){
                return true;
            }
        }

        return false
    }

    // if activated uncheck all elements of the group. If not activated activate the first element
    const toggleGroup = (groupedList:any, visibilityList: any, id: string, value: boolean | null = null) => {
        if(value == null){
            let activated = false;
    
            for(const layer of groupedList[id]){ // deactivate all activated sub knots
                if(visibilityList[layer.id]){
                    obj.toggleKnot(layer.id, false);
                    activated = true;
                }
            }
    
            if(!activated){ // activate the first sub knot if no sub knot was activated
                obj.toggleKnot(groupedList[id][0].id, true);
            }
        }else{
            for(let i = 0; i < groupedList[id].length; i++){
                let layer = groupedList[id][i]
                if(value){
                    if(i == 0)
                        obj.toggleKnot(layer.id, true);
                    else
                        obj.toggleKnot(layer.id, false);
                }else{
                    obj.toggleKnot(layer.id, false);
                }
            }
        }
    }

    useEffect(() => {

        let minMaxTimesteps = getMinMaxTimesteps(listLayers);

        setMinTimestep(minMaxTimesteps[0]);
        setMaxTimestep(minMaxTimesteps[1]);

        setSliderValue([0,Math.round((1/(minTimestep+1))*100)]);

    }, [listLayers]);

    const getMarks = (layers: any) => {
        let marks = [];
        
        for(let i = 0; i < layers.length; i++){

            let mark = {
                value: Math.round((i/layers.length)*100),
                label: ''+i
            };

            marks.push(mark);
        }

        return marks;
    }

    const getMarksTimesteps = (layer: any, totalSteps: number) => {
        let marks = [];
        
        for(let i = 0; i < layer.timesteps; i++){
            let mark = {
                value: Math.round((i/totalSteps)*100),
                label: ''+i
            };

            marks.push(mark);
        }

        return marks;
    }

    const handleChangeSlides = (e: any, group: string, step: number) => {

        let newObj: any = {};

        let exists = false;

        for(const key of Object.keys(rangeRef.current)){
            if(key != group){
                newObj[key] = rangeRef.current[key];
            }else{
                exists = true;
                newObj[key] = Math.round(e.target.value/step);
            }
        }

        if(!exists){
            newObj[group] = Math.round(e.target.value/step);
        }
        
        setRange(newObj);
    }

    const handleChangeSlidesTimesteps = (sliderValue: number[], layer: any, step: number) => {

        // even though it is a range of values the timestep shown is always the first
        let currentTimestep = Math.round(sliderValue[0]/step);

        if(currentTimestep <= layer.timesteps-1){ // TODO: add lower boundary
            broadcastMessage("", "updateTimestepKnot", {knotId: layer.id, timestep: currentTimestep, mapId: obj.viewId});
        }
    }

    useEffect(() => {
        for(const item of Object.keys(listLayers)){
            if(listLayers[item].length == 1){
                handleChangeSlidesTimesteps(sliderValue, listLayers[item][0], getSlideSteps(listLayers))
            }
        }
    }, [sliderValue]);

    const [collapsedItems, setCollapsedItems] = useState<string[]>([]);

    const toggleCollapse = (item: string) => {
        if (collapsedItems.includes(item)) {
          setCollapsedItems(collapsedItems.filter((id) => id !== item));
        } else {
          setCollapsedItems([...collapsedItems, item]);
        }
    };

    const getCategoryHtml = (category: ICategory, listLayers: any, knotVisibility: any) => {
        if(Object.keys(listLayers).length == 0 || knotVisibility.length == 0)
            return

        
        return<li key={category.category_name+"_li"}>
            <div key={category.category_name+"_span"} style={{margin: "5px", fontWeight: "bold", cursor: "pointer", color: collapsedItems.includes(category.category_name) ? 'black' : '#009687' }} onClick={() => toggleCollapse(category.category_name)}>
                {category.category_name}
            </div>
            <ul key={category.category_name+"_ul"} style={{listStyleType: "none", display: collapsedItems.includes(category.category_name) ? 'none' : 'block' }}>
                {
                    category.elements.map((element: string | ICategory, index: any) => (
                        typeof element === 'string' ? <li key={element+"_li"+"_"+index}>{getGroupHtml(element, listLayers, knotVisibility)}</li> : getCategoryHtml(element, listLayers, knotVisibility)
                    ))
                }
            </ul>
        </li>
    }

    const getNotInCategoriesHtml = (args: any, listLayers: any, knotVisibility: any) => {

        let categories: ICategory[] | undefined;

        if(args != undefined)
            categories = args.categories;

        if(Object.keys(listLayers).length == 0 || knotVisibility.length == 0)
            return

        let categorizedKnots: any[] = [];

        const getKnotsFromCategory = (category: ICategory) => {
            let knots: any = [];

            for(const element of category.elements){
                if(typeof element === 'string'){
                    knots.push(element);
                }else{
                    knots = knots.concat(getKnotsFromCategory(element));
                }
            }

            return knots;
        }

        if(categories != undefined){
            for(const category of categories){
                categorizedKnots = categorizedKnots.concat(getKnotsFromCategory(category));
            }
        }


        return Object.keys(listLayers).map((item: any, index: any) => (
                !categorizedKnots.includes(item) ? <li key={item+"_li_"+"_non_cat"}>{getGroupHtml(item, listLayers, knotVisibility)}</li> : <span key={item+"_empty"}></span>
            ))
    }

    const getMinMaxTimesteps = (listLayers: any) => {

        let maxTimesteps = 0;

        for(const item of Object.keys(listLayers)){
            if(listLayers[item].length == 1){
                if(listLayers[item][0].timesteps >= maxTimesteps){
                    maxTimesteps = listLayers[item][0].timesteps;
                }
            }
        }

        // let minTimesteps = maxTimesteps;

        // for(const item of Object.keys(listLayers)){
        //     if(listLayers[item].length == 1){
        //         if(listLayers[item][0].timesteps <= minTimesteps){
        //             minTimesteps = listLayers[item][0].timesteps;
        //         }
        //     }
        // }

        return [0, maxTimesteps];
    }

    const getSlideSteps = (listLayers: any) => {
        let minMaxTimesteps = getMinMaxTimesteps(listLayers);

        return Math.round((1/(minMaxTimesteps[1] - minMaxTimesteps[0]))*100);
    }

    const getGroupHtml = (item:string, listLayers: any, knotVisibility: any) => {

        return <React.Fragment key={item+"_fragment"}>
            <Row style={{paddingTop: "5px", paddingBottom: "5px"}} className="align-items-center">
                <Col md={3}>
                    <Row>
                        <Col md={9}>
                            <Form.Check key={item+"_check"} checked={groupVisibility(listLayers, knotVisibility, item)} type="checkbox" label={item} id={item} onChange={() => {toggleGroup(listLayers, knotVisibility, item)}}/> 
                        </Col>
                        <Col md={3}>
                            <Form.Check key={item+"_check_color"} type="checkbox" onChange={(event) => {toggleColorScaleVisibility(item)}}/> 
                        </Col>
                    </Row>
                </Col>
                {
                    listLayers[item].length > 1 ?
                    <Col>
                        <Row style={{padding: 0}} className="align-items-center">
                            <Col md={12}>
                                <Slider
                                    key={item+"_slider"}
                                    defaultValue={0}
                                    valueLabelDisplay="off"
                                    step={Math.round((1/listLayers[item].length)*100)}
                                    marks = {getMarks(listLayers[item])}
                                    onChange={(e) => {handleChangeSlides(e, item, Math.round((1/listLayers[item].length)*100))}}
                                    disabled = {!groupVisibility(listLayers, knotVisibility, item)}
                                />
                            </Col>
                            {/* <Col md={3} style={{paddingLeft: 0}}>
                                <Form.Control placeholder="FPS" type="text" onChange={(e) => {if(e.target.value != ''){setFps(parseInt(e.target.value))}}}/>
                            </Col> */}
                    </Row></Col> : listLayers[item][0].timesteps != undefined && listLayers[item][0].timesteps > 1 ?
                        <Col>
                        <Row style={{padding: 0}} className="align-items-center">
                            <Col md={12}>
                                <Slider
                                    key={item+"_slider_timestep"}
                                    // defaultValue={[0,0+Math.round((1/maxTimestep)*100)]}
                                    value={sliderValue}
                                    valueLabelDisplay="off"
                                    step={Math.round((1/(maxTimestep - minTimestep))*100)}
                                    min={0}
                                    max={Math.round((1/maxTimestep)*100)*(maxTimestep-1)}
                                    marks = {getMarksTimesteps(listLayers[item][0], maxTimestep - minTimestep)}
                                    onChange={(e: any) => {
                                        if(e != null && e.target != null){
                                            setSliderValue(e.target.value);
                                        }
                                    }}
                                    disabled = {!groupVisibility(listLayers, knotVisibility, item)}
                                />
                            </Col>
                    </Row></Col>: <></>
                }
            </Row>
        </React.Fragment>
    }

    return(
      <React.Fragment>
        {/* <div className="d-flex align-items-center justify-content-center"> */}
        <div style={{overflowY: "auto", overflowX: "clip", height: "73%", padding: "10px"}} id={"toggle_widget_"+viewId}>
            <ul style={{listStyleType: "none", padding: 10, margin: 0}}>
                {
                    // Object.keys(listLayers).map((item, index) => (
                        // <React.Fragment key={item+"_fragment"}>
                        //     <Row style={{paddingTop: "10px", paddingBottom: "10px", borderBottom: '1px solid #e2e1e6'}} className="align-items-center">
                        //         <Col>
                        //             <Form.Check key={item+"_check"} checked={groupVisibility(listLayers, knotVisibility, item)} type="checkbox" label={item} id={item} onChange={() => {toggleGroup(listLayers, knotVisibility, item)}}/> 
                        //         </Col>
                        //         {
                        //             listLayers[item].length > 1 ?
                        //             <Col>
                        //                 <Row style={{padding: 0}} className="align-items-center">
                        //                     <Col md={9}>
                        //                         <Slider
                        //                             key={item+"_slider"}
                        //                             defaultValue={0}
                        //                             valueLabelDisplay="off"
                        //                             step={Math.round((1/listLayers[item].length)*100)}
                        //                             marks = {getMarks(listLayers[item])}
                        //                             onChange={(e) => {handleChangeSlides(e, item, Math.round((1/listLayers[item].length)*100))}}
                        //                             disabled = {!groupVisibility(listLayers, knotVisibility, item)}
                        //                         />
                        //                     </Col>
                        //                     <Col md={3} style={{paddingLeft: 0}}>
                        //                         <Form.Control placeholder="FPS" type="text" onChange={(e) => {if(e.target.value != ''){setFps(parseInt(e.target.value))}}}/>
                        //                     </Col>
                        //             </Row></Col> : <></>
                        //         }
                        //     </Row>
                        // </React.Fragment>
                    // ))
                    grammarDefinition.args != undefined && grammarDefinition.args.categories != undefined ? 
                    grammarDefinition.args.categories.map((category: ICategory) => (
                        getCategoryHtml(category, listLayers, knotVisibility)
                    )) : <></>
                }
                {getNotInCategoriesHtml(grammarDefinition.args, listLayers, knotVisibility)}
            </ul>
        </div>
            
      </React.Fragment>
    )
}