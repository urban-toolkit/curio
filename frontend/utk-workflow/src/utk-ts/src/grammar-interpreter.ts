/// <reference types="@types/webgl2" />

import { ICameraData, IConditionBlock, IMasterGrammar, IKnotVisibility, IKnot, IMapGrammar, IPlotGrammar, IComponentPosition, IGenericWidget, ILayerData, IExKnot, ILinkDescription, IExternalJoinedJson } from './interfaces';
import { PlotArrangementType, OperationType, SpatialRelationType, LevelType, ComponentIdentifier, WidgetType, GrammarType} from './constants';
import { Knot } from './knot';
import { MapView } from './mapview';
import { Environment } from './environment';
import { MapRendererContainer } from './reactComponents/MapRenderer';

import React, { ComponentType } from 'react';
import {Root, createRoot} from 'react-dom/client';

import Views from './reactComponents/Views';

// @ts-ignore 
import schema from './json-schema.json'; // master JSON
import schema_categories from './json-schema-categories.json';
import schema_map from './json-schema-maps.json';
import schema_plots from './json-schema-plots.json';

import Ajv2019 from "ajv/dist/2019" // https://github.com/ajv-validator/ajv/issues/1462
import { LayerManager } from './layer-manager';
import { KnotManager } from './knot-manager';
import { PlotManager } from './plot-manager';
import { Layer } from './layer';
import { DataApi } from './data-api';
import { ServerlessApi } from './serverless-api';

export class GrammarInterpreter {

    protected _grammar: IMasterGrammar;
    protected _preProcessedGrammar: IMasterGrammar;
    protected _components_grammar: {id: string, originalGrammar: (IMapGrammar | IPlotGrammar), grammar: (IMapGrammar | IPlotGrammar | undefined), position: (IComponentPosition | undefined)}[] = [];
    protected _lastValidationTimestep: number;
    protected _components: {id: string, type: ComponentIdentifier, obj: any, position: IComponentPosition}[] = [];
    protected _maps_widgets: {type: WidgetType, obj: any, grammarDefinition: IGenericWidget | undefined}[] = [];
    protected _frontEndCallback: any;
    protected _layerManager: LayerManager;
    protected _knotManager: KnotManager;
    protected _plotManager: PlotManager; // plot manager for all plots not attached to maps
    protected _mainDiv: HTMLElement;
    protected _url: string;
    protected _root: Root;
    protected _ajv: any;
    protected _ajv_map: any;
    protected _ajv_plots: any;
    protected _viewReactElem: any;
    protected _serverlessApi: ServerlessApi;
    protected _id: string;

    protected _cameraUpdateCallback: any;

    get id(): string{
        return this._id;
    }

    get layerManager(): LayerManager {
        return this._layerManager;
    }

    get knotManager(): KnotManager{
        return this._knotManager;
    }

    get mainDiv(): HTMLElement{
        return this._mainDiv;
    }

    get preprocessedGrammar(): IMasterGrammar{
        return this._preProcessedGrammar;
    }

    get plotManager(): PlotManager{
        return this._plotManager;
    }

    get serverlessApi(): ServerlessApi{
        return this._serverlessApi;
    }

    constructor(id: string, grammar: IMasterGrammar, mainDiv: HTMLElement, jsonLayers: ILayerData[] = [], joinedJsons: IExternalJoinedJson[] = [], components: {id: string, json: IMapGrammar | IPlotGrammar}[] = [], interactionCallbacks: {knotId: string, callback: any}[] = []) {
        this._id = id;
        
        this.resetGrammarInterpreter(grammar, mainDiv, jsonLayers, joinedJsons, components, interactionCallbacks);
    }

    resetGrammarInterpreter(grammar: IMasterGrammar, mainDiv: HTMLElement, jsonLayers: ILayerData[] = [], joinedJsons: IExternalJoinedJson[] = [], components: {id: string, json: IMapGrammar | IPlotGrammar}[] = [], interactionCallbacks: {knotId: string, callback: any}[] = []){
        if(Environment.serverless){
            this._serverlessApi = new ServerlessApi();
            this.setServerlessApi(jsonLayers, joinedJsons, components, interactionCallbacks);
        }

        this._components_grammar = [];
        this._components = [];
        this._maps_widgets = [];

        this._layerManager = new LayerManager(this);
        this._knotManager = new KnotManager();

        this._ajv = new Ajv2019({schemas: [schema, schema_categories]});
        this._ajv_map = new Ajv2019({schemas: [schema_map]});
        this._ajv_plots = new Ajv2019({schemas: [schema_plots]});

        this._url = <string>Environment.backend;

        this._preProcessedGrammar = grammar;

        this._frontEndCallback = null;
        this._mainDiv = mainDiv;
        this.processGrammar(grammar);
    }

    setServerlessApi(jsonLayers: ILayerData[] = [], joinedJsons: IExternalJoinedJson[] = [], components: {id: string, json: IMapGrammar | IPlotGrammar}[] = [], interactionCallbacks: {knotId: string, callback: any}[] = []){
        if(jsonLayers.length > 0)
            this.serverlessApi.setLayers(jsonLayers);
        
        if(joinedJsons.length > 0)
            this.serverlessApi.setJoinedJsons(joinedJsons);
    
        if(components.length > 0)
            this.serverlessApi.setComponents(components);

        if(interactionCallbacks.length > 0){
            for(const interactionCallback of interactionCallbacks){
                this.serverlessApi.addInteractionCallback(interactionCallback.knotId, interactionCallback.callback)
            }
        }

    }
 
    /**
     * inits the window events
     */
    initWindowEvents(): void {

        const resizeHandler = (event: any) => {
            for(const component of this._components){
                if(component.type == ComponentIdentifier.MAP){
                    component.obj.render();
                }
            }

            // this.renderViews(this._mainDiv, this._preProcessedGrammar);
        }

        window.removeEventListener("resize", resizeHandler);
        window.addEventListener("resize", resizeHandler);
    }

    public initViews(mainDiv: HTMLElement, grammar: IMasterGrammar, originalGrammar: IMasterGrammar, components_grammar: {id: string, originalGrammar: (IMapGrammar | IPlotGrammar), grammar: (IMapGrammar | IPlotGrammar | undefined)}[]){

        const getComponentPosition = (grammar: IMasterGrammar, id: string) => {
            for(const component of grammar.components){
                if(component.id == id){
                    return component.position;
                }
            }
        }

        this._maps_widgets = [];

        let components_id = 0;

        for(const component of components_grammar){

            let comp_position = getComponentPosition(grammar, component.id);

            if(component.grammar != undefined && comp_position != undefined){
                if(component.grammar.grammar_type == "MAP"){

                    let new_map = new MapView(this, this._layerManager, this._knotManager, components_id, component.grammar as IMapGrammar);

                    this._components.push({id: component.id, type: ComponentIdentifier.MAP, obj: new_map, position: comp_position});
                    if((<IMapGrammar>component.grammar).widgets != undefined){
                        for(const widget of <IGenericWidget[]>(<IMapGrammar>component.grammar).widgets){
                            if(widget.type == WidgetType.TOGGLE_KNOT){
                                this._maps_widgets.push({type: WidgetType.TOGGLE_KNOT, obj: new_map, grammarDefinition: widget});
                            }else if(widget.type == WidgetType.SEARCH){
                                this._maps_widgets.push({type: WidgetType.SEARCH, obj: new_map, grammarDefinition: widget});
                            }
                            else if(widget.type == WidgetType.HIDE_GRAMMAR){
                                this._maps_widgets.push({type: WidgetType.HIDE_GRAMMAR, obj: new_map, grammarDefinition: widget});
                            }
                        }
                    }
                }else if(component.grammar.grammar_type == "PLOT"){
                    this._components.push({id: component.id, type: ComponentIdentifier.PLOT, obj: {grammar: component.grammar.plot, init: () => {}}, position: comp_position});
                }
            }

            components_id += 1;
        }

        // if(grammar.grammar_position != undefined){
        this._components.push({id: "grammar", type: ComponentIdentifier.GRAMMAR, obj: {init: () => {}}, position: {width: [], height: []}});
        // }
        
        this.renderViews(mainDiv, originalGrammar);
    }

    public validateMasterGrammar(grammar: IMasterGrammar){
        // TODO: checking conflicting types of interactions for the knots. One knot cannot be in plots with different arrangements

        // TODO: ensure that the widgets have all the attributes they should have

        // TODO: check if the knots references in the categories are correct

        // TODO: enforce that if a knot is groupped it can only be referenced by its group name in the categories

        // TODO: one knot cannot be in more than one category at the same time

        // TODO: cannot have two categories with the same name

        const validate = this._ajv.getSchema("https://urbantk.org/grammar")

        const valid = validate(grammar);

        if(!valid){
            for(const error of validate.errors){

                alert("Invalid grammar: "+error.message+"at "+error.dataPath);
            }

            return false;
        }

        this._lastValidationTimestep = Date.now();

        let allKnotsIds: string[] = [];
    
        if(!Environment.serverless){

            if(grammar.ex_knots != undefined)
                throw Error("External knots (ex_knots) can only be used in the serverless mode");

            for(const knot of grammar.knots){
                if(allKnotsIds.includes(knot.id)){
                    throw Error("Duplicated knot id");
                }else{
                    if(knot.knot_op != true)
                        allKnotsIds.push(knot.id);
                }
            }
    
            for(const knot of grammar.knots){
                if(knot.knot_op == true){
                    for(const integration_scheme of knot.integration_scheme){
    
                        let operation = integration_scheme.operation;
    
                        if(operation != OperationType.NONE){
                            throw Error("All operation for knots with knot_op = true should be NONE");
                        }
                    }
                    
                    for(const scheme of knot.integration_scheme){
                        
                        if(scheme.in == undefined){
                            throw Error("in must be defined when knot_op = true");
                        }
    
                        if(!allKnotsIds.includes(scheme.out.name) || !allKnotsIds.includes(scheme.in.name)){
                            throw Error("When using knot_op out and in must make reference to the id of other knots (that doesnt have knot_op = true)");
                        }
    
                        if(scheme.op == undefined){
                            throw Error("If knot_op = true each step of the integration_scheme must have a defined op");
                        }
    
                        if((scheme.maxDistance != undefined || scheme.defaultValue != undefined) && (scheme.spatial_relation != "NEAREST" || scheme.abstract != true)){
                            throw Error("The maxDistance and defaultValue fields can only be used with the NEAREST spatial_relation in abstract links");
                        }
    
                        if(scheme.maxDistance != undefined && scheme.defaultValue == undefined){
                            throw Error("If maxDistance is used defaultValue must be specified")
                        }
    
                    }
    
                }
            }
        }else{
            if(grammar.knots != undefined && grammar.knots.length > 0)
                throw Error("Internal knots (knots) can not be used in the serverless mode");
        }
    
        return true;
    }

    public validateComponentGrammar(grammar: IMapGrammar | IPlotGrammar){

        let valid = false;
        let validate = this._ajv_map.getSchema("https://urbantk.org/grammar_maps")

        if(grammar.grammar_type == GrammarType.MAP){
            valid = validate(grammar);
        }else{
            validate = this._ajv_plots.getSchema("https://urbantk.org/grammar_plots")
            valid = validate(grammar);
        }

        if(!valid){
            for(const error of validate.errors){
                alert("Invalid grammar: "+error.message+"at "+error.dataPath);
            }

            return false;
        }

        return true;
    }

    // Overwrites selected elements of specific physical layer
    // externalSelected has elements selected in the OBJECT level. 
    public overwriteSelectedElements(externalSelected: number[], layerId: string){  
        for(let i = 0; i < this._components.length; i++){
            let component = this._components[i];

            if(component.type == ComponentIdentifier.MAP){
                let map = component.obj;
                this.knotManager.overwriteSelectedElements(externalSelected, layerId, i);
                map.render();
            }
        }
    }

    public async processGrammar(grammar: IMasterGrammar){
        if(this.validateMasterGrammar(grammar)){

            this._preProcessedGrammar = grammar;

            // changing grammar to be the processed grammar
            let aux = JSON.stringify(grammar);
            if(grammar.variables != undefined){
                for(let variable of grammar.variables) {
                    aux = aux.replaceAll("$"+variable.name+"$", variable.value);
                }
            }
            let processedGrammar = JSON.parse(aux);
            this._grammar = processedGrammar;

            if(!Environment.serverless)
                await this.createSpatialJoins(this._url, processedGrammar);

            Environment.setEnvironment({backend: `http://localhost:5001` as string});
            
            for(const component of grammar.components){

                let component_grammar = <IMapGrammar | IPlotGrammar> await DataApi.getComponentData(component.id, this._serverlessApi);

                this.updateComponentGrammar(component_grammar, component);
            }
            
            await this.replaceVariablesAndInitViews();
        }

        this.initWindowEvents();
    }

    public updateComponentGrammar(component_grammar: IMapGrammar | IPlotGrammar, componentInfo: any = undefined){
        if(this.validateComponentGrammar(component_grammar)){
            let replace = false;

            for(let i = 0; i < this._components_grammar.length; i++){
                let component = this._components_grammar[i];

                if(component.id == componentInfo.id){
                    replace = true;
                    this._components_grammar[i] = {id: <string>componentInfo.id, originalGrammar: component_grammar, grammar: <IMapGrammar | IPlotGrammar | undefined>undefined, position: <IComponentPosition | undefined>componentInfo.position};
                    break;
                }
            }

            if(!replace){
                this._components_grammar.push({id: <string>componentInfo.id, originalGrammar: component_grammar, grammar: <IMapGrammar | IPlotGrammar | undefined>undefined, position: <IComponentPosition | undefined>componentInfo.position});
            }
        }
    }

    public async replaceVariablesAndInitViews(){
        for(const component_grammar of this._components_grammar){
            let aux = JSON.stringify(component_grammar.originalGrammar);
            if(component_grammar.originalGrammar.variables != undefined){
                for(let variable of component_grammar.originalGrammar.variables) {
                    aux = aux.replaceAll("$"+variable.name+"$", variable.value);
                }
            }
            component_grammar.grammar = JSON.parse(aux);
        }            

        await this.initLayers();
    
        this.initViews(this._mainDiv, this._grammar, this._preProcessedGrammar , this._components_grammar); 
    }

    initKnots(){
        if(!Environment.serverless){
            for(const knotGrammar of this.getKnots()){
                let layerId = this.getKnotOutputLayer(knotGrammar);
                let layer = this._layerManager.searchByLayerId(layerId);
                let knot = this._knotManager.createKnot(knotGrammar.id, <Layer>layer, knotGrammar, this, true);
                knot.processThematicData(this._layerManager); // send thematic data to the mesh of the physical layer TODO: put this inside the constructor of Knot
                for(let i = 0; i < this._components_grammar.length; i++){
                    if(this._components_grammar[i].grammar != undefined && this._components_grammar[i].grammar?.grammar_type == GrammarType.MAP){
                        let mapview = this._components[i].obj;
                        knot.loadShaders(mapview.glContext, mapview.camera.getWorldOrigin(), i); // instantiate the shaders inside the knot
                    }
                }
            }
        }else{
            let premadeKnots = this.getPremadeKnots();

            if(premadeKnots != undefined){
                for(const premadeKnot of premadeKnots){
                    let layerId = premadeKnot.out_name;
                    let layer = this._layerManager.searchByLayerId(layerId);
                    let knot = this._knotManager.createKnot(premadeKnot.id, <Layer>layer, premadeKnot, this, true);
                    knot.processThematicData(this._layerManager); // send thematic data to the mesh of the physical layer TODO: put this inside the constructor of Knot
                    for(let i = 0; i < this._components_grammar.length; i++){
                        if(this._components_grammar[i].grammar != undefined && this._components_grammar[i].grammar?.grammar_type == GrammarType.MAP){
                            let mapview = this._components[i].obj;
                            knot.loadShaders(mapview.glContext, mapview.camera.getWorldOrigin(), i); // instantiate the shaders inside the knot
                        }
                    }
                }
            }
        }
    }

    /**
     * Add layer geometry and function
     */
    async addLayer(layerData: ILayerData, joined: boolean): Promise<void> {

        // gets the layer data if available
        const features = 'data' in layerData ? layerData.data : undefined;

        if (!features) { return; }

        // loads the layers data
        const layer = this._layerManager.createLayer(layerData, features);

        // not able to create the layer
        if (!layer) { return; }

        if(joined){
            let joinedJson = await DataApi.getJoinedJson(layer.id, this._serverlessApi);
            if(joinedJson)
                layer.setJoinedJson(joinedJson);
        }

        // this.render();
    }

    async initLayers(): Promise<void> {

        let layers: string[] = [];
        let joinedList: boolean[] = [];
        // let centroid = this.camera.getWorldOrigin();

        if(!Environment.serverless){
            for(const knot of this.getKnots()){
                if(!knot.knot_op){
                    // load layers from knots if they dont already exist
                    for(let i = 0; i < knot.integration_scheme.length; i++){
    
                        let joined = false // if the layers was joined with another layer
    
                        if(knot.integration_scheme[i].in != undefined && knot.integration_scheme[i].in?.name != knot.integration_scheme[i].out.name){
                            joined = true;
                        }
    
                        if(!layers.includes(knot.integration_scheme[i].out.name)){
                            layers.push(knot.integration_scheme[i].out.name);
                            joinedList.push(joined);
                        }else if(joined){
                            joinedList[layers.indexOf(knot.integration_scheme[i].out.name)] = joined;
                        }
                    }
                }
            }
    
            for (let i = 0; i < layers.length; i++) {
    
                let element = layers[i];
    
                // loads from file if not provided
                const layer = await DataApi.getLayer(element, this._serverlessApi);
    
                // adds the new layer
                await this.addLayer(layer, joinedList[i]);
            }
        }else{ // serverless mode
            let premadeKnots = this.getPremadeKnots();

            if(premadeKnots != undefined){
                for(const premadeKnot of premadeKnots){
                    let joined = (premadeKnot.in_name != undefined);
       
                    if(!layers.includes(premadeKnot.out_name)){
                        layers.push(premadeKnot.out_name);
                        joinedList.push(joined);
                    }else if(joined){
                        joinedList[layers.indexOf(premadeKnot.out_name)] = joined;
                    }
                }
        
                for (let i = 0; i < layers.length; i++) {
        
                    let element = layers[i];
        
                    const layer = await DataApi.getLayer(element, this._serverlessApi);
        
                    // adds the new layer
                    await this.addLayer(layer, joinedList[i]);
                }
            }
        }
    }

    // Called by Views.tsx
    async init(updateStatus: any){

        this.initKnots();

        let knotsGroups: any = {};

        for(const knot of this._knotManager.knots){
            
            let knotSpecification = knot.knotSpecification;
            
            if(knotSpecification.group != undefined){
                if(!(knotSpecification.group.group_name in knotsGroups)){
                    knotsGroups[knotSpecification.group.group_name] = [{
                        id: knot.id,
                        position: knotSpecification.group.position,
                        cmap: knot.cmap,
                        domain: knot.domain,
                        scale: knot.scale,
                        range: knot.range,
                        timesteps: knot.thematicData?.length
                    }];
                }else{
                    knotsGroups[knotSpecification.group.group_name].push({
                        id: knot.id,
                        position: knotSpecification.group.position,
                        cmap: knot.cmap,
                        domain: knot.domain,
                        scale: knot.scale,
                        range: knot.range,
                        timesteps: knot.thematicData?.length
                    });
                }
            }else{
                knotsGroups[knot.id] = [{
                    id: knot.id,
                    cmap: knot.cmap,
                    domain: knot.domain,
                    scale: knot.scale,
                    range: knot.range,
                    timesteps: knot.thematicData?.length
                }]; // group of single knot
            }
            
        }

        for(const group of Object.keys(knotsGroups)){
            if(knotsGroups[group].length > 1){
                knotsGroups[group].sort((a: any,b: any) => {a.position - b.position});
                let ids = [];
                for(const element of knotsGroups[group]){
                    ids.push(element.id);
                }
                knotsGroups[group] = ids;
            }
        }
        
        updateStatus("listLayers", knotsGroups);

        for(let i = 0; i < this._components_grammar.length; i++){
            if(this._components_grammar[i].grammar != undefined && this._components_grammar[i].grammar?.grammar_type == GrammarType.MAP){
                let map = this._components[i].obj;

                for(const knot of this._knotManager.knots){ // adding the maps on the track list of the knots that are rendered in that map (used to sync interactions)
                    if(this._components_grammar[i].grammar?.knots.includes(knot.id)){
                        knot.addMap(map, i);
                    }
                }

                // this._maps.push(map);
                map.render() 
            }
        }

        let plotsKnotData = this.parsePlotsKnotData(); // parse all plots knots

        const setHighlightElementForAll = (knotId: string, elementIndex: number, value: boolean, _this: any) => {
            let components_id = 0;

            for(const component of _this._components_grammar){
                if(component.grammar?.grammar_type == GrammarType.MAP){
                    let map = component.obj;

                    if(component.grammar?.knots.includes(knotId)){
                        map.setHighlightElement(knotId, elementIndex, value, map);
                    }
                }
                components_id += 1;
            }
        }

        this._plotManager = new PlotManager("PlotManagerGrammarInterpreter", this.getPlots(), plotsKnotData, {"function": setHighlightElementForAll, "arg": this}); 

        this._layerManager.init(updateStatus);
        this._knotManager.init(updateStatus);
        this._plotManager.init(updateStatus);
    }

    private createSpatialJoins = async (url: string, grammar: IMasterGrammar) => {
        for(const knot of grammar.knots){
            if(knot.knot_op != true){
                for(let i = 0; i < knot.integration_scheme.length; i++){
                    if(knot.integration_scheme[i].spatial_relation != 'INNERAGG' && knot.integration_scheme[i].in != undefined){
                        let spatial_relation = (<SpatialRelationType>knot.integration_scheme[i].spatial_relation).toLowerCase();
                        let out = knot.integration_scheme[i].out.name;
                        let outLevel = knot.integration_scheme[i].out.level.toLowerCase();
                        let inLevel = (<{name: string, level: LevelType}>knot.integration_scheme[i].in).level.toLowerCase();
                        let maxDistance = knot.integration_scheme[i].maxDistance;
                        let defaultValue = knot.integration_scheme[i].defaultValue;

                        let operation = (<OperationType>knot.integration_scheme[i].operation).toLowerCase();

                        if(operation == 'none'){
                            operation = 'avg'; // there must be an operation to solve conflicts in the join
                        }

                        let inData = (<{name: string, level: LevelType}>knot.integration_scheme[i].in).name;
                        let abstract = knot.integration_scheme[i].abstract;

                        // addNewMessage("Joining "+out+" with "+inData, "red");

                        if(maxDistance != undefined){
                            await fetch(url+"/linkLayers?spatial_relation="+spatial_relation+"&out="+out+"&operation="+operation+"&in="+inData+"&abstract="+abstract+"&outLevel="+outLevel+"&inLevel="+inLevel+"&maxDistance="+maxDistance+"&defaultValue="+defaultValue);
                        }else{
                            await fetch(url+"/linkLayers?spatial_relation="+spatial_relation+"&out="+out+"&operation="+operation+"&in="+inData+"&abstract="+abstract+"&outLevel="+outLevel+"&inLevel="+inLevel).catch(error => {
                                // Handle any errors here
                                console.error(error);
                            });
                        }

                        // addNewMessage("Join finished in " +(elapsed/1000)+" seconds", "green");

                    }
                }
            }
        }
    }

    // private processConditionBlocks(grammar: IMasterGrammar){

    //     let _this = this;

    //     const replaceConditionBlocks = (obj: any) => {
    //         const recursiveSearch = (obj: any) => {
    //             if (!obj || typeof obj !== 'object') {return};
                
    //             Object.keys(obj).forEach(function (k) {
    //                 if(obj && typeof obj === 'object' && obj[k].condition != undefined){ // it is a condition block
    //                     obj[k] = _this.processConditionBlock(obj[k]); // replace the condition block with its evaluation
    //                 }else{
    //                     recursiveSearch(obj[k]);
    //                 }
    //             });
    //         } 
    //         recursiveSearch(obj);
    //     } 
        
    //     replaceConditionBlocks(grammar);

    //     return grammar;
    // }

    // private processConditionBlock(conditionBlock: IConditionBlock){
        
    //     let zoom = this._map.camera.getZoomLevel();
    //     let timeElapsed = Date.now() - this._lastValidationTimestep;

    //     for(let i = 0; i < conditionBlock.condition.length; i++){
    //         let conditionElement = conditionBlock.condition[i];

    //         if(conditionElement.test == undefined) // there is no test to evaluate
    //             return conditionElement.value

    //         let testString = conditionElement.test;

    //         testString = testString.replaceAll("zoom", zoom+'');
    //         testString = testString.replaceAll("timeElapsed", timeElapsed+'');

    //         let testResult = eval(testString);

    //         if(testResult == true){
    //             return conditionElement.value;
    //         }
    //     }

    //     throw Error("Condition block does not have a default value");

    // }
    
    public getCamera(mapId: number = 0): ICameraData{

        let currentMapId = 0;

        for(const component of this._components_grammar){
            if(component.grammar != undefined && component.grammar.grammar_type == GrammarType.MAP){
                if(currentMapId == mapId){
                    return (<IMapGrammar>component.grammar).camera
                }
                
                currentMapId += 1;
            }
        }

        throw new Error("There is no map with that id");
    }

    // If mapId is specified get all the plots that are embedded in that map
    public getPlots(mapId: number | null = null) : {id: string, knotsByPhysical: any, originalGrammar: IPlotGrammar, grammar: IPlotGrammar, position: IComponentPosition | undefined, componentId: string}[] {
        let plots: {id: string, knotsByPhysical: any, originalGrammar: IPlotGrammar, grammar: IPlotGrammar, position: IComponentPosition | undefined, componentId: string}[] = [];
        let map_component: any = null;
        let currentComponentId = 0;

        for(const component of this._components_grammar){
            if(component.grammar != undefined && component.grammar.grammar_type == GrammarType.PLOT){

                let allKnotsByPhysical: any = {};

                for(const knotId of component.grammar.knots){
                    if(!Environment.serverless){
                        let knotObjs = this.getKnots(<string>knotId);
    
                        if(knotObjs.length == 1){
                            let physicalId = this.getKnotLastLink(knotObjs[0]).out.name;
                        
                            if(allKnotsByPhysical[physicalId] == undefined){
                                allKnotsByPhysical[physicalId] = [knotId];
                            }else{
                                allKnotsByPhysical[physicalId].push(knotId);
                            }
                        }
                    }else{
                        let knotObjs = this.getPremadeKnots(<string>knotId);

                        if(knotObjs == undefined){
                            knotObjs = [];
                        }

                        if(knotObjs.length == 1){
                            let physicalId = knotObjs[0].out_name;
                        
                            if(allKnotsByPhysical[physicalId] == undefined){
                                allKnotsByPhysical[physicalId] = [knotId];
                            }else{
                                allKnotsByPhysical[physicalId].push(knotId);
                            }
                        }
                    }

                }

                plots.push({
                    componentId: component.id,
                    knotsByPhysical: allKnotsByPhysical,
                    ...<{id: string, originalGrammar: IPlotGrammar, grammar: IPlotGrammar, position: IComponentPosition | undefined}>component
                });
            }

            if(component.grammar != undefined && mapId != null && component.grammar.grammar_type == GrammarType.MAP){
                if(currentComponentId == mapId){
                    map_component = component;
                }

            }

            currentComponentId += 1;
        }

        if(mapId != null && map_component != null){
            if(map_component.grammar.plot != undefined){
                plots = plots.filter((plot) => {return plot.id == map_component.grammar.plot.id}); // TODO: give support to more than one embedded plots per map
            }else{
                plots = [];
            }
        }

        return plots;
    }

    public getKnots(knotId: string | null = null){
        
        if(knotId != null){
            for(const knot of this._grammar.knots){
                if(knot.id == knotId)
                    return [knot];
            }
        }

        return this._grammar.knots;
    }

    public getPremadeKnots(knotId: string | null = null){

        if(knotId != null && this._grammar.ex_knots != undefined){
            for(const knot of this._grammar.ex_knots){
                if(knot.id == knotId)
                    return [knot];
            }
        }

        return this._grammar.ex_knots;
    }

    public getMap(mapId: number = 0){
        let currentComponentId = 0;

        for(const component of this._components_grammar){
            if(component.grammar != undefined && component.grammar.grammar_type == GrammarType.MAP){
                if(currentComponentId == mapId){
                    return (<IMapGrammar>component.grammar)
                }
                
            }
            currentComponentId += 1;
        }

        throw new Error("There is no map with that id");
    }

    public getFilterKnots(mapId: number = 0){
        return this.getMap(mapId).filterKnots;
    }

    public getProcessedGrammar(){
        return this._grammar;
    }

    public evaluateLayerVisibility(layerId: string, mapId:number): boolean{

        let components_id = 0;

        for(const component of this._components_grammar){
            if(component.grammar != undefined && component.grammar.grammar_type == GrammarType.MAP){
                if(components_id == mapId){
                
                    if((<IMapGrammar>component.grammar).knotVisibility == undefined)
                        return true;
            
                    let map = this._components[components_id].obj;

                    let zoom = map.camera.getZoomLevel();
                    let timeElapsed = Date.now() - this._lastValidationTimestep;
            
                    let knotId = ''; // TODO: the layer could appear in more than one Knot. Create knot structure
            
                    if(!Environment.serverless){
                        for(const knot of this._grammar.knots){
                            if(this.getKnotOutputLayer(knot) == layerId){
                                knotId = knot.id;
                                break;
                            }
                        }
                    }else{
                        if(this._grammar.ex_knots != undefined){
                            for(const ex_knot of this._grammar.ex_knots){
                                if(ex_knot.out_name == layerId){
                                    knotId = ex_knot.id;
                                    break;
                                }
                            }
                        }
                    }
            
                    for(const visibility of <IKnotVisibility[]>(<IMapGrammar>component.grammar).knotVisibility){
                        if(visibility.knot == knotId){
                            let testString = visibility.test;
            
                            testString = testString.replaceAll("zoom", zoom+'');
                            testString = testString.replaceAll("timeElapsed", timeElapsed+'');
                        
                            let testResult = eval(testString);
            
                            return testResult;
                        }
                    }
            
                    return true;
                
                
                }
            }

            components_id += 1;
        }

        throw new Error("There is no map with that id");

    }

    public evaluateKnotVisibility(knot: Knot, mapId:number): boolean{

        let components_id = 0;

        for(const component of this._components_grammar){
            if(component.grammar != undefined && component.grammar.grammar_type == GrammarType.MAP){
                if(components_id == mapId){
        
                    if((<IMapGrammar>component.grammar).knotVisibility != undefined && component.grammar.knots.includes(knot.id)){
                
                        let map = this._components[components_id].obj;

                        let zoom = map.camera.getZoomLevel();
                        let timeElapsed = Date.now() - this._lastValidationTimestep;
                
                        for(const visibility of <IKnotVisibility[]>(<IMapGrammar>component.grammar).knotVisibility){
                            if(visibility.knot == knot.id){
                                let testString = visibility.test;
                
                                testString = testString.replaceAll("zoom", zoom+'');
                                testString = testString.replaceAll("timeElapsed", timeElapsed+'');
                            
                                let testResult = eval(testString);
                
                                if(testResult && !knot.visible){
                                    this._knotManager.toggleKnot(knot.id, true);
                                }else if(!testResult && knot.visible){
                                    this._knotManager.toggleKnot(knot.id, false);
                                }

                                return testResult;
                            }
                        }

                    }else if(component.grammar.knots.includes(knot.id)){
                        return knot.visible;
                    }else{
                        return false; // the knot is not being rendered in this map
                    }   

                }
            }

            components_id += 1;
        }

        return false;
    }

    public getKnotById(knotId: string){

        let knots: IKnot[] | IExKnot[] = [];

        if(!Environment.serverless)
            knots = this.getKnots();
        else
            knots = <IExKnot[]>this.getPremadeKnots();

        for(let i = 0; i < knots.length; i++){

            let knot: IKnot | IExKnot = knots[i];

            if(knotId == knot.id){
                return knot;
            }
        }

    }

    public getKnotOutputLayer(knot: IKnot | IExKnot){

        if(!Environment.serverless){
            if((<IKnot>knot).knot_op == true){
    
                let lastKnotId = (<IKnot>knot).integration_scheme[(<IKnot>knot).integration_scheme.length-1].out.name;
    
                let lastKnot = <IKnot>this.getKnotById(lastKnotId);
    
                if(lastKnot == undefined){
                    throw Error("Could not process knot "+lastKnotId);
                }
    
                return lastKnot.integration_scheme[lastKnot.integration_scheme.length-1].out.name;
    
            }else{
                return (<IKnot>knot).integration_scheme[(<IKnot>knot).integration_scheme.length-1].out.name;
            }
        }else{
            return (<IExKnot>knot).out_name;
        }

    }

    public getKnotLastLink(knot: IKnot){
        if(knot.knot_op == true){
            
            let lastKnotId = knot.integration_scheme[knot.integration_scheme.length-1].out.name;

            let lastKnot = <IKnot>this.getKnotById(lastKnotId);
            
            if(lastKnot == undefined){
                throw Error("Could not process knot "+lastKnotId);
            }

            return lastKnot.integration_scheme[lastKnot.integration_scheme.length-1];

        }else{
            return knot.integration_scheme[knot.integration_scheme.length-1];
        }
    }

    public parsePlotsKnotData(viewId: number | null = null){

        let plotsKnots: string[] = [];

        let plots = (viewId != null) ? this.getPlots(viewId) : this.getPlots();

        for(const plotAttributes of plots){
            if(plotAttributes.grammar.arrangement == PlotArrangementType.LINKED && viewId != null){
                alert("A plot with Linked arrangement cannot be used in a map");
            }else{
                for(const knotId of plotAttributes.grammar.knots){
                    if(!plotsKnots.includes(knotId)){
                        plotsKnots.push(knotId);
                    }
                }
            }
        }

        let plotsKnotData: {knotId: string, physicalId: string, allFilteredIn: boolean, elements: {coordinates: number[], abstract: number[], highlighted: boolean, filteredIn: boolean, index: number}[]}[] = [];

        for(const knotId of plotsKnots){

            let allKnots: IKnot[] | IExKnot[] = [];

            if(!Environment.serverless){
                allKnots = this.getKnots();
            }else{
                allKnots = <IExKnot[]>this.getPremadeKnots();
            }

            for(const knot of allKnots){
                if(knotId == knot.id){


                    let left_layer = this._layerManager.searchByLayerId(this.getKnotOutputLayer(knot));

                    if(left_layer == null){
                        throw Error("Layer not found while processing knot");
                    }

                    let elements = [];

                    let lastLink: ILinkDescription | null = null;

                    if(!Environment.serverless){
                        lastLink = this.getKnotLastLink(<IKnot>knot);
                        if(lastLink.out.level == undefined){ // this is a pure knot
                            continue;
                        }
                    }else{
                        if((<IExKnot>knot).in_name == undefined)
                            continue;
                    }

                    // let centroid = this.camera.getWorldOrigin();

                    let coordinates: number[][] = [];

                    if(viewId != null){
                        let map = this._components[viewId].obj;

                        if(!Environment.serverless)
                            coordinates = left_layer.getCoordsByLevel((<ILinkDescription>lastLink).out.level, map.camera.getWorldOrigin(), viewId);
                        else
                            coordinates = left_layer.getCoordsByLevel(LevelType.OBJECTS, map.camera.getWorldOrigin(), viewId); // serverless is always on the OBJECTS level
                    }

                    let functionValues: number[][][] = [];

                    if(!Environment.serverless)
                        functionValues = left_layer.getFunctionByLevel((<ILinkDescription>lastLink).out.level, knotId);
                    else
                        functionValues = left_layer.getFunctionByLevel(LevelType.OBJECTS, knotId); // serverless is always on the OBJECTS level

                    let knotStructure = this._knotManager.getKnotById(knotId);

                    let highlighted: boolean[] = [];

                    for(let i = 0; i < this._components_grammar.length; i++){ // if one map higlighted something that will appear hilighted in every view that depends on that knot
                        if(this._components_grammar[i].grammar != undefined && this._components_grammar[i].grammar?.grammar_type == GrammarType.MAP){

                            let highlighted_map: boolean[] = [];

                            if(!Environment.serverless)
                                highlighted_map = left_layer.getHighlightsByLevel((<ILinkDescription>lastLink).out.level, (<Knot>knotStructure).shaders[i]); // getting higlights for the layer for each map
                            else
                                highlighted_map = [];

                            if(highlighted.length == 0){
                                highlighted = highlighted_map;
                            }else{
                                for(let j = 0; j < highlighted_map.length; j++){
                                    highlighted[j] = highlighted_map[j] || highlighted[j];
                                }
                            }
                        }
                    }

                    let readCoords = 0;

                    let filtered = left_layer.mesh.filtered;

                    for(let i = 0; i < highlighted.length; i++){

                        // if(elements.length >= 1000){ // preventing plot from having too many elements TODO: let the user know that plot is cropped
                        //     break;
                        // }

                        if(coordinates.length == 0 || filtered.length == 0 || filtered[readCoords] == 1){

                            if(coordinates.length > 0){
                                elements.push({
                                    coordinates: coordinates[i],
                                    abstract: functionValues[i][0], // array with timesteps
                                    highlighted: highlighted[i],
                                    // filteredIn: true, // temp
                                    filteredIn: false,
                                    index: i
                                });
                            }else{
                                elements.push({
                                    coordinates: [],
                                    abstract: functionValues[i][0], // array with timesteps
                                    highlighted: highlighted[i],
                                    // filteredIn: true, // temp
                                    filteredIn: false,
                                    index: i
                                });
                            }

                        }

                        if(coordinates.length > 0)
                            readCoords += coordinates[i].length/left_layer.mesh.dimension;
                    }

                    let physicalId = "";

                    if(!Environment.serverless)
                        physicalId = (<ILinkDescription>lastLink).out.name
                    else
                        physicalId = (<IExKnot>knot).out_name

                    let knotData = {
                        knotId: knotId,
                        physicalId: physicalId,
                        // allFilteredIn: true, // temp
                        allFilteredIn: false,
                        elements: elements
                    }

                    plotsKnotData.push(knotData);
                }
            }
        }   

        return plotsKnotData;
    }

    // TODO: more than one view should be rendered but inside a single div provided by the front end
    private renderViews(mainDiv: HTMLElement, grammar: IMasterGrammar){
        // mainDiv.innerHTML = ""; // empty all content

        // if(this._root == undefined){
        //     this._root = createRoot(mainDiv);
        // }else{
        //     this._root.unmount();
        //     mainDiv.innerHTML = "";
        //     this._root = createRoot(mainDiv);
        // }
        
        if(this._root == undefined){
            this._root = createRoot(mainDiv);
        }

        let viewIds: string[] = [];

        for(let i = 0; i < this._components.length; i++){
            viewIds.push(this._components[i].type+i+"_"+this._id);
        }

        // for(let i = 0; i < this._maps_widgets.length; i++){
        //     viewIds.push(this._maps_widgets[i].type+i);
        // }

        let grammars = [];

        for(const component of this._components_grammar){
            grammars.push(component);
        }
 
        // this._root.render(React.createElement(Views, {viewObjs: this._components, mapsWidgets: this._maps_widgets, viewIds: viewIds, grammar: grammar, componentsGrammar: grammars, mainDivSize: {width: mainDiv.offsetWidth, height: mainDiv.offsetHeight}, grammarInterpreter: this}));
        this._root.render(React.createElement(Views, {viewObjs: this._components, mapsWidgets: this._maps_widgets, viewIds: viewIds, grammar: grammar, componentsGrammar: grammars, mainDiv: mainDiv, grammarInterpreter: this}));
    }

}
