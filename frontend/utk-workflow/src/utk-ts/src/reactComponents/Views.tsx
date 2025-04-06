import React, { useEffect, useState, useRef } from 'react';
import { GrammarPanelContainer } from './GrammarPanel';
import { MapRendererContainer } from './MapRenderer';
import { faArrowRight, faArrowLeft } from '@fortawesome/free-solid-svg-icons'
import { Button } from "react-bootstrap";
import { ComponentIdentifier, GrammarType, WidgetType } from '../constants';
import { GrammarMethods } from '../grammar-methods';
import './Dragbox.css'
import * as d3 from "d3";
import { IComponentPosition, IGenericWidget, IMapGrammar, IMasterGrammar, IPlotGrammar, } from '../interfaces';
import './View.css';
import { GenericFixedPlotContainer } from './GenericFixedPlotContainer';
import { MasterWidgets } from './MasterWidgets';
import { faCode } from '@fortawesome/free-solid-svg-icons'
import { Row } from 'react-bootstrap';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome'

// declaring the types of the props
type ViewProps = {
    viewObjs: { id: string, type: ComponentIdentifier, obj: any, position: IComponentPosition }[] // each view has a an object representing its logic
    mapsWidgets: { type: WidgetType, obj: any, grammarDefinition: IGenericWidget | undefined }[] // each view has a an object representing its logic
    viewIds: string[]
    grammar: IMasterGrammar
    componentsGrammar: { id: string, originalGrammar: IMapGrammar | IPlotGrammar, grammar: IMapGrammar | IPlotGrammar | undefined, position: IComponentPosition | undefined }[]
    // mainDivSize: {width: number, height: number}
    mainDiv: any
    grammarInterpreter: any
}

// Render components
// function Views({viewObjs, mapsWidgets, viewIds, grammar, componentsGrammar, mainDivSize, grammarInterpreter}: ViewProps) {
function Views({ viewObjs, mapsWidgets, viewIds, grammar, componentsGrammar, mainDiv, grammarInterpreter }: ViewProps) {

    const [camera, setCamera] = useState<{ position: number[], direction: { right: number[], lookAt: number[], up: number[] } }>({ position: [], direction: { right: [], lookAt: [], up: [] } }); // TODO: if we have multiple map instances we have multiple cameras
    const [filterKnots, setFilterKnots] = useState<number[]>([]);
    const [systemMessages, setSystemMessages] = useState<{ text: string, color: string }[]>([]);
    // knotsByPhysical: how many knots correspond to each physical layer (physical_id -> [list_of_knots])
    const [genericPlots, setGenericPlots] = useState<{ id: number, knotsByPhysical: any, hidden: boolean, svgId: string, label: string, checked: boolean, edit: boolean, floating: boolean, position: IComponentPosition | undefined, componentId: string }[]>([]);
    const [knotVisibility, setKnotVisibility] = useState<any>({});
    const [currentPlotId, setCurrentPlotId] = useState(0);
    const [listLayers, setListLayers] = useState<any>({});
    const [activeGrammar, setActiveGrammar] = useState("grammar"); // store active component id
    const [activeGrammarType, setActiveGrammarType] = useState(GrammarType.MASTER); // type of active grammar
    const [activeKnotPhysical, setActiveKnotPhysical] = useState<any>({}); // object that, for each physical, stores the knotId of the activated knot

    const [refreshView, setRefreshView] = useState<boolean>(false);

    const [subscribers, _setSubscribers] = useState<any>({}); // each key represent a channel that stores objects of type {id: string, callback: any, ref: any}
    const subscribersRef = useRef(subscribers);
    const setSubscribers = (data: string) => {
        subscribersRef.current = data;
        _setSubscribers(data);
    };

    let inputBarId = "searchBar";

    const nodeRef = useRef(null);

    const addNewMessage = (msg: string, color: string) => {
        setSystemMessages([{ text: msg, color: color }]);
    }

    const linkedContainerGenerator = (n: number, names: string[] = [], floating_values: boolean[], positions: (IComponentPosition | undefined)[], componentIds: string[], knotsByPhysicalList: any[]) => {

        let createdIds: number[] = [];

        if (n == 0) {
            return [];
        }

        createdIds = addNewGenericPlot(n, names, floating_values, positions, componentIds, knotsByPhysicalList);

        // promise is only resolved when the container is created
        return new Promise(async function (resolve, reject) {

            let checkContainer = async () => {

                let allContainersCreated = true;

                for (const id of createdIds) {
                    if (d3.select("#" + "genericPlotSvg" + id).empty()) {
                        allContainersCreated = false;
                        break;
                    }
                }

                if (!allContainersCreated) { // the container was not create yet or the state still needs to be updated
                    await new Promise(r => setTimeout(r, 100));
                    checkContainer();
                }
            }

            await checkContainer();

            let returnIds = [];

            for (const id of createdIds) {
                returnIds.push("genericPlotSvg" + id);
            }

            resolve(returnIds);

        });

    }

    const setActiveGrammarAndType = (grammar: string, grammarType: GrammarType) => {
        setActiveGrammar(grammar);
        setActiveGrammarType(grammarType);
    }

    const addNewGenericPlot = (n: number = 1, names: string[] = [], floating_values: boolean[], positions: (IComponentPosition | undefined)[], componentIds: string[], knotsByPhysicalList: any[]) => {

        let createdIds = [];
        let tempPlots = [];

        let tempId = 0;

        for (let i = 0; i < n; i++) {
            if (names.length > 0 && names[i] != '' && names[i] != undefined) {
                tempPlots.push({ id: tempId, knotsByPhysical: knotsByPhysicalList[i], hidden: true, svgId: "genericPlotSvg" + tempId, label: names[i], checked: false, edit: false, floating: floating_values[i], position: positions[i], componentId: componentIds[i] });
            } else {
                tempPlots.push({ id: tempId, knotsByPhysical: knotsByPhysicalList[i], hidden: true, svgId: "genericPlotSvg" + tempId, label: "Plot " + tempId, checked: false, edit: false, floating: floating_values[i], position: positions[i], componentId: componentIds[i] });
            }
            createdIds.push(tempId);
            tempId += 1;
        }

        setGenericPlots(tempPlots);
        setCurrentPlotId(tempId);
        return createdIds;
    }

    const toggleGenericPlot = (plotId: number) => {
        let modifiedPlots = [];
        for (const plot of genericPlots) {
            if (plot.id == plotId) {
                modifiedPlots.push({ id: plot.id, knotsByPhysical: plot.knotsByPhysical, hidden: !plot.hidden, svgId: plot.svgId, label: plot.label, checked: plot.checked, edit: plot.edit, floating: plot.floating, position: plot.position, componentId: plot.componentId });
            } else {
                modifiedPlots.push({ id: plot.id, knotsByPhysical: plot.knotsByPhysical, hidden: plot.hidden, svgId: plot.svgId, label: plot.label, checked: plot.checked, edit: plot.edit, floating: plot.floating, position: plot.position, componentId: plot.componentId });
            }
        }
        setGenericPlots(modifiedPlots);
    }

    const toggleAllPlots = () => {
        let modifiedPlots = [];

        for (const plot of genericPlots) {
            modifiedPlots.push({ id: plot.id, knotsByPhysical: plot.knotsByPhysical, hidden: !plot.hidden, svgId: plot.svgId, label: plot.label, checked: plot.checked, edit: plot.edit, floating: plot.floating, position: plot.position, componentId: plot.componentId });
        }

        setGenericPlots(modifiedPlots);
    }

    const updateSubscribers = (id: string, callback: any, channel: string, ref: any) => {
        let foundChannel = false;
        let newSubscribers: any = {};

        for (const currentChannel of Object.keys(subscribersRef.current)) {
            newSubscribers[currentChannel] = [];

            if (currentChannel == channel) {
                foundChannel = true;
                let exists = false;

                for (const participant of subscribersRef.current[currentChannel]) {
                    if (participant.id == id) {
                        newSubscribers[currentChannel].push({ id: participant.id, callback: callback, ref: ref });
                    } else {
                        newSubscribers[currentChannel].push({ id: participant.id, callback: participant.callback, ref: participant.ref });
                    }
                }

                if (!exists) {
                    newSubscribers[currentChannel].push({ id: id, callback: callback, ref: ref });
                }
            } else {
                for (const participant of subscribersRef.current[currentChannel]) {
                    newSubscribers[currentChannel].push({ id: participant.id, callback: participant.callback, ref: participant.ref });
                }
            }
        }

        if (!foundChannel) {
            newSubscribers[channel] = [{ id: id, callback: callback, ref: ref }];
        }

        setSubscribers(newSubscribers);

    }

    // id: participant that sent the message
    const broadcastMessage = (id: string, channel: string, message: any) => {
        for (const currentChannel of Object.keys(subscribersRef.current)) {
            if (currentChannel == channel) {
                for (const participant of subscribersRef.current[currentChannel]) {
                    if (participant.id != id) {
                        participant.callback(message, participant.ref);
                    }
                }
            }
        }
    }

    /**
     * Summarize callbacks
     */
    const updateStatus = (state: string, value: any) => {
        if (state == "camera") {
            setCamera(value);
        } else if (state == "filterKnots") {
            setFilterKnots(value);
        } else if (state == "systemMessages") {
            setSystemMessages(value);
        } else if (state == "genericPlots") {
            setGenericPlots(value);
        } else if (state == "listLayers") {
            setListLayers(value);
        } else if (state == "knotVisibility") {
            setKnotVisibility(value);
        } else if (state == "containerGenerator") {
            return linkedContainerGenerator(value.n, value.names, value.floating_values, value.positions, value.componentIds, value.knotsByPhysicalList);
        } else if (state == "updateActiveKnotPhysical") {
            setActiveKnotPhysical(value);
        } else if (state == "subscribe") {
            updateSubscribers(value.id, value.callback, value.channel, value.ref); // callback will be called when channel has new message from any of its participants
        } else if (state == "broadcastChannel") { // broadcast a message to the whole channel
            broadcastMessage(value.id, value.channel, value.message);
        }
    }

    const getSizes = (position: IComponentPosition) => {
        let widthPercentage = (position.width[1] + 1 - position.width[0]) / grammar.grid.width;
        let heightPercentage = (position.height[1] + 1 - position.height[0]) / grammar.grid.height;

        let margin = 14;

        return { width: widthPercentage * mainDiv.offsetWidth - margin, height: heightPercentage * mainDiv.offsetHeight - margin };
    }

    const getTopLeft = (position: IComponentPosition) => {

        let leftPercentange = (position.width[0] - 1) / grammar.grid.width;
        let topPercentange = (position.height[0] - 1) / grammar.grid.height;

        let margin = 14;

        return { top: topPercentange * mainDiv.offsetHeight + (margin / 2), left: leftPercentange * mainDiv.offsetWidth + (margin / 2) }
    }

    // Executes after component rendered
    useEffect(() => {

        for (let i = 0; i < viewObjs.length; i++) {
            let viewObj = viewObjs[i].obj;
            let viewId = viewIds[i];

            viewObj.init(viewId, updateStatus);
        }

        grammarInterpreter.init(updateStatus);

        window.addEventListener("resize", () => {
            setRefreshView(!refreshView);
        });

        d3.select("#toggleSideBar").on("click", (event) => {
            let currentClassed = d3.select(".sidebarGrammar").classed("sidebarGrammar--isHidden");
            d3.select(".sidebarGrammar").classed("sidebarGrammar--isHidden", !currentClassed);
            d3.select("#toggleSideBar").classed("sidebarGrammar--isOpen", currentClassed);
            d3.select("#rightArrow").classed("hidden", currentClassed);
            d3.select("#leftArrow").classed("hidden", !currentClassed);
        });

    }, []);

    useEffect(() => {
        GrammarMethods.updateGrammar(grammar);
    }, [grammar]);

    const formatLayers = (layers: string[]) => {
        let newObject: any = {};

        for (const key of layers) {
            newObject[key] = true;
        }

        return newObject;
    }

    return (
        <React.Fragment>
            {
                <MasterWidgets
                    width={mainDiv.offsetWidth}
                    height={mainDiv.offsetHeight}
                    genericPlots={genericPlots}
                    togglePlots={toggleAllPlots}
                    activeKnotPhysical={activeKnotPhysical}
                    updateStatus={updateStatus}
                />
            }
            <div style={{ backgroundColor: "#EAEAEA", height: "100%", width: "100%", position: "relative" }}>
                {
                    viewObjs.map((component, index) => {
                        if (component.type == ComponentIdentifier.MAP) {
                            return <React.Fragment key={component.type + index}>
                                {/* <div className='component' style={{padding: 0, position: "absolute", left: getTopLeft(component.position).left, top: getTopLeft(component.position).top, width: getSizes(component.position).width, height: getSizes(component.position).height}}> */}
                                <div className='component' style={{ padding: 0, position: "absolute", left: getTopLeft(component.position).left, top: getTopLeft(component.position).top, width: getSizes(component.position).width, height: getSizes(component.position).height }}>
                                    <MapRendererContainer
                                        obj={component.obj}
                                        viewId={viewIds[index]}
                                        mapWidgets={mapsWidgets}
                                        x={getTopLeft(component.position).left}
                                        y={getTopLeft(component.position).top}
                                        width={getSizes(component.position).width}
                                        height={getSizes(component.position).height}
                                        listLayers={listLayers}
                                        knotVisibility={knotVisibility}
                                        inputBarId={inputBarId}
                                        genericPlots={genericPlots}
                                        togglePlots={toggleAllPlots}
                                        componentId={component.id}
                                        editGrammar={setActiveGrammarAndType}
                                        broadcastMessage={broadcastMessage}
                                    />
                                </div>
                            </React.Fragment>
                        } else if (component.type == ComponentIdentifier.GRAMMAR && grammar.grammar != false) {
                            // return <></>
                            return <React.Fragment key={component.type + index}>
                                <button id={"toggleSideBar"}>
                                    <FontAwesomeIcon id={"rightArrow"} size="2x" style={{ color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px" }} icon={faArrowRight} />
                                    <FontAwesomeIcon id={"leftArrow"} className='hidden' size="2x" style={{ color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px" }} icon={faArrowLeft} />
                                </button>
                                <div className='component sidebarGrammar sidebarGrammar--isHidden'>
                                    <GrammarPanelContainer
                                        obj={grammarInterpreter}
                                        viewId={viewIds[index]}
                                        initialGrammar={grammar}
                                        camera={camera}
                                        filterKnots={filterKnots}
                                        inputId={inputBarId}
                                        setCamera={setCamera}
                                        addNewMessage={addNewMessage}
                                        applyGrammarButtonId={"applyGrammarButton"}
                                        linkMapAndGrammarId={"linkMapAndGrammar"}
                                        activeGrammar={activeGrammar}
                                        activeGrammarType={activeGrammarType}
                                        componentsGrammar={componentsGrammar}
                                        editGrammar={setActiveGrammarAndType}
                                    />
                                </div>
                            </React.Fragment>
                        }
                    })
                }
                {
                    genericPlots.map((item: any) => {
                        if (!item.floating) {
                            return (
                                <div className='component' style={{ position: "absolute", left: getTopLeft(item.position).left, top: getTopLeft(item.position).top, width: getSizes(item.position).width, height: getSizes(item.position).height }}>
                                    <div style={{ zIndex: 5, backgroundColor: "white", width: "75px", position: "absolute", left: "10px", top: "10px", padding: "5px", borderRadius: "8px", border: "1px solid #dadce0", opacity: 0.9, boxShadow: "0 2px 8px 0 rgba(99,99,99,.2)" }}>
                                        <Row>
                                            <FontAwesomeIcon size="2x" style={{ color: "#696969", padding: 0, marginTop: "5px", marginBottom: "5px" }} icon={faCode} onClick={() => setActiveGrammarAndType(item.componentId, GrammarType.PLOT)} />
                                        </Row>
                                    </div>
                                    <GenericFixedPlotContainer
                                        id={item.id}
                                        svgId={item.svgId}
                                        knotsByPhysical={item.knotsByPhysical}
                                        activeKnotPhysical={activeKnotPhysical}
                                        updateStatus={updateStatus}
                                    />
                                </div>
                            )
                        } else {
                            return null;
                        }
                    })
                }
            </div>
        </React.Fragment>
    );
}

export default Views;

