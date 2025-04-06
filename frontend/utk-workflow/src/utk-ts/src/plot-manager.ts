import { IComponentPosition, IMasterGrammar, IPlotArgs, IPlotGrammar } from './interfaces';
import { PlotInteractionType, PlotArrangementType, InteractionEffectType } from './constants';
import {radians} from './utils';

const vega = require('vega')
const lite = require('vega-lite')

import * as d3 from "d3";

class LockFlag {
  
    _flag: boolean;
    
    constructor(){
      this._flag = false;
    }
  
    set(){
      this._flag = true;
    }
  
    get flag(){
      return this._flag;
    }
  
}

export class PlotManager {

    protected _plots: {id: string, knotsByPhysical: any, originalGrammar: IPlotGrammar, grammar: IPlotGrammar, position: IComponentPosition | undefined, componentId: string}[];
    protected _filtered: any = {}; // which plots have filters active (plotNumber -> boolean)
    protected _updateStatusCallback: any;
    protected _setGrammarUpdateCallback: any;
    protected _plotsKnotsData: {knotId: string, physicalId: string, allFilteredIn: boolean, elements: {coordinates: number[], abstract: number[], highlighted: boolean, filteredIn: boolean, index: number}[]}[];
    protected _activeKnotPhysical: any = {}; // for each physicalId one knot is active at the time, according to users choice on the interface. (physicalId -> knotId)
    protected _setHighlightElementCallback: {function: any, arg: any};
    protected _plotsReferences: any[];
    protected _needToUnHighlight: boolean;
    protected _highlightedVegaElements: any[] = [];
    protected _id: string;

    /**
     * @param viewData 
     * @param setGrammarUpdateCallback Function that sets the callback that will be called in the frontend to update the grammar
     */
    constructor(id: string, plots: {id: string, knotsByPhysical: any, originalGrammar: IPlotGrammar, grammar: IPlotGrammar, position: IComponentPosition | undefined, componentId: string}[], plotsKnotsData: {knotId: string, physicalId: string, allFilteredIn: boolean, elements: {coordinates: number[], abstract: number[], highlighted: boolean, filteredIn: boolean, index: number}[]}[], setHighlightElementCallback: {function: any, arg: any}) {
        this._id = id;
        this._setHighlightElementCallback = setHighlightElementCallback;
        this._plotsReferences = new Array(plots.length);
        this._needToUnHighlight = false;
        this._plots = plots;
        this._plotsKnotsData = plotsKnotsData;
    }

    public physicalKnotActiveChannel(message: {physicalId: string, knotId: string}, _this: any){

        let physicals = Object.keys(_this._activeKnotPhysical)

        if(physicals.length > 0){
            for(const key of physicals){
                if(key == message.physicalId){
                    _this._activeKnotPhysical[key] = message.knotId;
                }
            }
    
            _this.updatePlotsActivePhysical();
            _this._updateStatusCallback("updateActiveKnotPhysical", _this._activeKnotPhysical);
        }
    }

    public init(updateStatusCallback: any){
        this._updateStatusCallback = updateStatusCallback;
        this._updateStatusCallback("subscribe", {id: this._id, callback: this.physicalKnotActiveChannel, channel: "physicalKnotActiveChannel", ref: this})
        this.updateGrammarPlotsData(this._plotsKnotsData);
    }

    async updateGrammarPlotsData(plotsKnotsData: {knotId: string, physicalId: string, allFilteredIn: boolean, elements: {coordinates: number[], abstract: number[], highlighted: boolean, filteredIn: boolean, index: number}[]}[]){
        
        this._plotsKnotsData = plotsKnotsData;

        let processedKnotData = this.proccessKnotData();

        this.attachPlots(processedKnotData);
    }

    proccessKnotData(){

        let processedKnotData: any = {};

        for(let i = 0; i < this._plotsKnotsData.length; i++){ 
            let knotData = this._plotsKnotsData[i];

            processedKnotData[knotData.knotId] = {'values': []}

            for(let j = 0; j < knotData.elements.length; j++){ // for each physical object
                let element = knotData.elements[j];

                for(let k = 0; k < element.abstract.length; k++){
                    let value: any = {};

                    value[knotData.knotId+"_index"] = element.index;
                    value[knotData.knotId+"_abstract"] = element.abstract[k];
                    value[knotData.knotId+"_timestep"] = k;
                    value[knotData.knotId+"_highlight"] = element.highlighted;
                    value[knotData.knotId+"_filteredIn"] = element.filteredIn;
    
                    value[knotData.physicalId+"_index"] = element.index;
                    value[knotData.physicalId+"_abstract"] = element.abstract[0];
                    value[knotData.physicalId+"_timestep"] = k;
                    value[knotData.physicalId+"_highlight"] = element.highlighted;
                    value[knotData.physicalId+"_filteredIn"] = element.filteredIn;

                    processedKnotData[knotData.knotId].values.push(value);
                }

                this._activeKnotPhysical[knotData.physicalId] = knotData.knotId;
            }
            
            this._updateStatusCallback("updateActiveKnotPhysical", this._activeKnotPhysical);
        }

        return processedKnotData;
    }

    clearFiltersLocally(knotsIds: string[]){

        let physicalIds: string[] = [];

        // update local data
        for(const plotKnotData of this._plotsKnotsData){

            // plotKnotData.allFilteredIn = true; // temp
            plotKnotData.allFilteredIn = false;

            if(knotsIds.includes(plotKnotData.knotId)){

                physicalIds.push(plotKnotData.physicalId);

                for(const element of plotKnotData.elements){
                    // element.filteredIn = true; // temp
                    element.filteredIn = false;
                }
            }
        }

        // update plots data
        for(let i = 0; i < this._plots.length; i++){
            let elem = this._plots[i].grammar;

            if(elem.plot.data != undefined){
                for(const value of elem.plot.data.values){  
                    for(const knotId of knotsIds){
                        if(value[knotId+"_index"] != undefined){
                            value[knotId+"_filteredIn"] = false;
                            // value[knotId+"_filteredIn"] = true; // temp
                        }
                    }

                    for(const physicalId of physicalIds){
                        if(value[physicalId+"_index"] != undefined){
                            value[physicalId+"_filteredIn"] = false;
                            // value[physicalId+"_filteredIn"] = true; // temp
                        }
                    }
                }
            }
        }

    }

    clearHighlightsLocally(knotsIds: string[]){

        let physicalIds: string[] = [];

        // update local data
        for(const plotKnotData of this._plotsKnotsData){
            if(knotsIds.includes(plotKnotData.knotId)){

                physicalIds.push(plotKnotData.physicalId);

                for(const element of plotKnotData.elements){
                    element.highlighted = false;
                }
            }
        }

        // update plots data
        for(let i = 0; i < this._plots.length; i++){
            let elem = this._plots[i].grammar;

            if(elem.plot.data != undefined){
                for(const value of elem.plot.data.values){  
                    for(const knotId of knotsIds){
                        if(value[knotId+"_index"] != undefined){
                            value[knotId+"_highlight"] = false;
                            value[knotId+"_filteredIn"] = false; // test
                        }
                    }

                    for(const physicalId of physicalIds){
                        if(value[physicalId+"_index"] != undefined){
                            value[physicalId+"_highlight"] = false;
                            value[physicalId+"_filteredIn"] = false; // test
                        }
                    }
                }
            }
        }
    }

    applyInteractionEffectsLocally(elements: any, truthValue: boolean, toggle: boolean = false, fromMap: boolean = false){
        
        this.setHighlightElementsLocally(elements, truthValue, toggle);
        if(fromMap){ // only filter elements if the interaction comes from map
            this.setFilterElementsLocally(elements, truthValue, toggle);
        }
        this.updatePlotsNewData();
    }

    // always called by a map
    clearInteractionEffectsLocally(knotsIds: string[]){
        this.clearHighlightsLocally(knotsIds);
        this.clearFiltersLocally(knotsIds);
        this.updatePlotsNewData();
    }

    // if toggle is activated ignore the truth value and just toggle the highlight
    setHighlightElementsLocally(elements: any, truthValue: boolean, toggle: boolean = false){

        // update local data
        for(const plotKnotData of this._plotsKnotsData){
            if(elements[plotKnotData.knotId] != undefined){
                for(const element of plotKnotData.elements){
                    if(element.index == elements[plotKnotData.knotId]){
                        if(toggle){
                            element.highlighted = !element.highlighted;
                        }else{
                            element.highlighted = truthValue;
                        }
                        break;
                    }
                }
            }
        }

        let invertedDict: any = {};

        for(const key of Object.keys(this._activeKnotPhysical)){
            invertedDict[this._activeKnotPhysical[key]] = key;
        }

        // update plots data
        for(let i = 0; i < this._plots.length; i++){
            let elem = this._plots[i].grammar

            if(elem.plot.data != undefined){
                for(const value of elem.plot.data.values){
                    
                    let elementsKeys = Object.keys(elements);

                    for(const knotId of elementsKeys){
                        if(value[knotId+"_index"] != undefined && value[knotId+"_index"] == elements[knotId]){
                            if(toggle){
                                value[knotId+"_highlight"] = !value[knotId+"_highlight"];
                                value[knotId+"_highlight"] = value[knotId+"_filteredIn"];
                                if(invertedDict[knotId] != undefined){
                                    value[invertedDict[knotId]+"_highlight"] = value[knotId+"_highlight"];
                                    value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_highlight"];
                                }
                            }else{
                                value[knotId+"_highlight"] = truthValue;
                                value[knotId+"_filteredIn"] = truthValue;
                                if(invertedDict[knotId] != undefined){
                                    value[invertedDict[knotId]+"_highlight"] = value[knotId+"_highlight"];
                                    value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_filteredIn"];
                                }
                            }
                        }
                    }
                }
            }
        }

    }

    setFilterElementsLocally(elements: any, truthValue: boolean, toggle: boolean = false){

        // temp
        // let allFilteredInDict: any = {}; // knotId -> filteredIn
        // let allFilteredOutDict: any = {};

        // update local data
        // for(const plotKnotData of this._plotsKnotsData){
        //     if(elements[plotKnotData.knotId] != undefined){

        //         // temp
        //         // allFilteredInDict[plotKnotData.knotId] = plotKnotData.allFilteredIn;

        //         // if(plotKnotData.allFilteredIn){ // no object is selected (all are filtered in)
        //         //     for(const element of plotKnotData.elements){
        //         //         element.filteredIn = false;
        //         //     }

        //         //     plotKnotData.allFilteredIn = false;
        //         // }

        //         // let allFilteredOut = true;

        //         for(const element of plotKnotData.elements){
        //             if(element.index == elements[plotKnotData.knotId]){
        //                 if(toggle){
        //                     element.filteredIn = !element.filteredIn;
        //                 }else{
        //                     element.filteredIn = truthValue;
        //                 }
        //             }
        //             // temp
        //             // if(element.filteredIn)
        //             //     allFilteredOut = false;
        //         }

        //         // temp
        //         // allFilteredOutDict[plotKnotData.knotId] = allFilteredOut;

        //         // if(allFilteredOut){ // if no object is selected then include all (all are filtered in)
        //         //     for(const element of plotKnotData.elements){
        //         //         if(element.index == elements[plotKnotData.knotId]){
        //         //             element.filteredIn = true;
        //         //         }
        //         //     }
        //         //     plotKnotData.allFilteredIn = true;
        //         // } 
        //     }
        // }

        let invertedDict: any = {};

        for(const key of Object.keys(this._activeKnotPhysical)){
            invertedDict[this._activeKnotPhysical[key]] = key;
        }

        // update plots data
        for(let i = 0; i < this._plots.length; i++){
            let elem = this._plots[i].grammar;

            if(elem.plot.data != undefined){

                this._filtered[i] = false;

                for(const value of elem.plot.data.values){
                    
                    let elementsKeys = Object.keys(elements);

                    for(const knotId of elementsKeys){

                        if(elem.knots.includes(knotId)){

                            // temp
                            // if(allFilteredInDict[knotId]){ // if every object is filtered in no object is selected therefore filteredIn should be reset because the next interaction will filter in the object
                            //     value[knotId+"_filteredIn"] = false;
                            //     if(invertedDict[knotId] != undefined){
                            //         value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_filteredIn"];
                            //     }    
                            // }
    
                            if(value[knotId+"_index"] != undefined && value[knotId+"_index"] == elements[knotId]){
                                
                                if(toggle){
                                    value[knotId+"_filteredIn"] = !value[knotId+"_filteredIn"];
                                    if(invertedDict[knotId] != undefined){
                                        value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_filteredIn"];
                                    }
                                }else{
                                    value[knotId+"_filteredIn"] = truthValue;
                                    if(invertedDict[knotId] != undefined){
                                        value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_filteredIn"];
                                    }
                                }
                            }
    
                            // temp
                            // if(allFilteredOutDict[knotId]){
                            //     value[knotId+"_filteredIn"] = true;
                            //     if(invertedDict[knotId] != undefined){
                            //         value[invertedDict[knotId]+"_filteredIn"] = value[knotId+"_filteredIn"];
                            //     }
                            // }
    
                            if(!value[knotId+"_filteredIn"]){
                                this._filtered[i] = true;
                            }
                        }

                    }
                }
            }
        }

    }

    updatePlotsActivePhysical(){

        const getPhysical = (knotId: string) => {
            for(const knotData of this._plotsKnotsData){
                if(knotId == knotData.knotId){
                    return knotData.physicalId;
                }
            }
        }

        for(let i = 0; i < this._plots.length; i++){
            let elem = this._plots[i].grammar;

            if(elem.plot.data != undefined){
                for(const value of elem.plot.data.values){
                    for(const physicalId of Object.keys(this._activeKnotPhysical)){
                        let knotId = this._activeKnotPhysical[physicalId];
                        if(physicalId == getPhysical(elem.knots[0]) && elem.knots.includes(knotId)){ // TODO: all the knots of the plot need to have the same physical
                            value[physicalId+"_index"] = value[knotId+"_index"];
                            value[physicalId+"_abstract"] = value[knotId+"_abstract"];
                            value[physicalId+"_timestep"] = value[knotId+"_timestep"];
                            value[physicalId+"_highlight"] = value[knotId+"_highlight"];
                            value[physicalId+"_filteredIn"] = value[knotId+"_filteredIn"];
                        }
                    }
                }
            }
        }

        this.updatePlotsNewData();
    }

    updatePlotsNewData(){

        // update plots data
        for(let i = 0; i < this._plots.length; i++){

            let elem = this._plots[i].grammar

            if(elem.plot.data != undefined){
                let valuesCopy = [];
    
                for(const value of elem.plot.data.values){
                    let valueCopy: any = {};
    
                    let valueKeys = Object.keys(value);

                    let include = false;

                    for(const key of valueKeys){
                        if(key != "Symbol(vega_id)"){
                            valueCopy[key] = value[key];
                        }

                        // if(key.includes("_filteredIn") && !value[key] && elem.interaction_effect == InteractionEffectType.FILTER){
                        //     include = false;
                        // }

                        if(key.includes("_highlight") && value[key] && elem.interaction_effect == InteractionEffectType.FILTER){
                            include = true;
                        }else if(elem.interaction_effect != InteractionEffectType.FILTER){
                            include = true;
                        }

                    }
    
                    // if filter is activated do not include filtered out elements
                    if(include)
                        valuesCopy.push(valueCopy);
                }
                
                let changeset = vega.changeset().remove(() => true).insert(valuesCopy);
                
                if(this._plotsReferences[i] != undefined){
                    this._plotsReferences[i].change('source_0', changeset).runAsync();
                }
            }
        }
    }

    async attachPlots(processedKnotData: any){
        function mergeKnotData(values1: any, values2: any){
            let values3: any = [];

            if(values1.length != values2.length){
                throw Error("The knots of a plot must have the same number of elements"); // TODO: enforce that knots of the same plot must end in the same layer and geometry level
            }

            for(let i = 0; i < values1.length; i++){
                let currentObj: any = {};

                let values1Keys = Object.keys(values1[0]);

                for(const key of values1Keys){
                    currentObj[key] = values1[i][key];
                }   

                let values2Keys = Object.keys(values2[0]);

                for(const key of values2Keys){
                    currentObj[key] = values2[i][key];
                }   

                values3.push(currentObj);
            }

            return {"values": values3};
        }

        let linkedPlots = [];
        let names = [];
        let floating_values = []; // which plots are fixed on the screen or floating on top of it
        let positions: (IComponentPosition | undefined)[] = []; // positions of each plot (undefined if it is floating)
        let componentIds: string[] = [];
        let knotsByPhysicalList: any[] = [];

        for(let i = 0; i < this._plots.length; i++){
            if(this._plots[i].grammar.arrangement == PlotArrangementType.LINKED){
                linkedPlots.push(this._plots[i].grammar);
                
                if(this._plots[i].grammar.name != undefined){
                    names.push(this._plots[i].grammar.name);
                }else{
                    names.push('');
                }

                if(this._plots[i].position != undefined){
                    floating_values.push(false); // has a fixed position on the screen
                }else{
                    floating_values.push(true);
                }

                positions.push(this._plots[i].position);

                componentIds.push(this._plots[i].componentId);

                knotsByPhysicalList.push(this._plots[i].knotsByPhysical);
            }
        }

        let ids = await this._updateStatusCallback("containerGenerator", {n: linkedPlots.length, names: names, floating_values: floating_values, positions: positions, componentIds: componentIds, knotsByPhysicalList: knotsByPhysicalList}); 

        for(let i = 0; i < linkedPlots.length; i++){

            // TODO: this checking can be done earlier to avoid unecesary calculations
            if(linkedPlots[i].arrangement != PlotArrangementType.LINKED){
                continue;
            }

            let elem = linkedPlots[i];
            let plotId = ids[i]; 
            
            let mergedKnots = processedKnotData[<string>elem.knots[0]];

            for(let j = 1; j < elem.knots.length; j++){

                let currentProcessedKnotData = processedKnotData[<string>elem.knots[j]];

                mergedKnots = mergeKnotData(mergedKnots.values, currentProcessedKnotData.values);
                
            }

            elem.plot.data = mergedKnots;

            let vegaspec = lite.compile(elem.plot).spec;

            var view = new vega.View(vega.parse(vegaspec))
                .logLevel(vega.Warn) // set view logging level
                .renderer('svg')
                .initialize("#"+plotId)
                .hover();

            this._plotsReferences[i] = view;

            if(elem.interaction != undefined){

                if(elem.interaction == PlotInteractionType.HOVER){
                    let _this = this

                    view.addEventListener('mouseover', function(event: any, item: any) {

                        if(item != undefined && item.datum != undefined){ // the plot needs to be unfiltered

                            if(elem.interaction_effect != InteractionEffectType.FILTER || !_this._filtered[i]){
                                let elementsToHighlight: any = {};
        
                                for(const key of elem.knots){
                                    if(item.datum[key+'_highlight'] == false){
                                        _this._setHighlightElementCallback.function(key, item.datum[key+'_index'], true, _this._setHighlightElementCallback.arg);
                                        elementsToHighlight[<string>key] = item.datum[key+"_index"];
                                    }
                                }
    
                                if(Object.keys(elementsToHighlight).length > 0){
                                    _this.setHighlightElementsLocally(elementsToHighlight, true);
                                    _this._needToUnHighlight = true;
                                    _this._highlightedVegaElements.push(item);
                                    _this.updatePlotsNewData();
    
                                }
                            }
                        }

                    });
        
                    view.addEventListener('mouseout', function(event: any, item: any) {

                        if(elem.interaction_effect != InteractionEffectType.FILTER || !_this._filtered[i]){
                            
                            if(item != undefined && item.datum != undefined){
                                let elementsToUnHighlight: any = {};
            
                                for(const key of elem.knots){
                                    _this._setHighlightElementCallback.function(key, item.datum[key+'_index'], false, _this._setHighlightElementCallback.arg);
                                    elementsToUnHighlight[<string>key] = item.datum[key+"_index"];
                                }
    
                                _this.setHighlightElementsLocally(elementsToUnHighlight, false);
                                _this.updatePlotsNewData();
                            }
    
                            for(const highlightedItem of _this._highlightedVegaElements){
                                let elementsToUnHighlight: any = {};
            
                                for(const key of elem.knots){
                                    _this._setHighlightElementCallback.function(key, highlightedItem.datum[key+'_index'], false, _this._setHighlightElementCallback.arg);
                                    elementsToUnHighlight[<string>key] = highlightedItem.datum[key+"_index"];
                                }
    
                                _this.setHighlightElementsLocally(elementsToUnHighlight, false);
                                _this.updatePlotsNewData();
                            }
    
                            _this._highlightedVegaElements = [];
                        
                        }

                    });
                }

                if(elem.interaction == PlotInteractionType.BRUSH){
                    throw Error("Plot "+PlotInteractionType.BRUSH+" not implemented yet");
                }

                if(elem.interaction == PlotInteractionType.CLICK){
                    let _this = this

                    view.addEventListener('click', function(event: any, item: any) {

                        if(elem.interaction_effect != InteractionEffectType.FILTER || !_this._filtered[i]){
                        
                            if(item == undefined || item.datum == undefined){
    
                                let elementsToUnHighlight: any = {};
            
                                for(const key of elem.knots){
                                    // unhighlight all elements of this plot
                                    for(const value of elem.plot.data.values){
                                        if(value[key+'_index'] != undefined){
                                            _this._setHighlightElementCallback.function(key, value[key+'_index'], false, _this._setHighlightElementCallback.arg);
                                            elementsToUnHighlight[<string>key] = value[key+'_index'];
                                        }
                                    }
                                }
        
                                _this.setHighlightElementsLocally(elementsToUnHighlight, false);
                                _this.updatePlotsNewData();
    
                            }else{
    
                                let unhighlight = false;
    
                                for(const key of elem.knots){
                                    if(item.datum[key+"_highlight"] == true){
                                        unhighlight = true;
                                        break;
                                    }
                                }
    
                                if(unhighlight){
                                    let elementsToUnHighlight: any = {};
    
                                    // highlight the clicked element
                                    for(const key of elem.knots){
                                        _this._setHighlightElementCallback.function(key, item.datum[key+'_index'], false, _this._setHighlightElementCallback.arg);
                                        elementsToUnHighlight[<string>key] = item.datum[key+"_index"];
                                    }
    
                                    _this.setHighlightElementsLocally(elementsToUnHighlight, false);
                                    _this.updatePlotsNewData();
                                }else{
                                    let elementsToHighlight: any = {};
    
                                    // highlight the clicked element
                                    for(const key of elem.knots){
                                        _this._setHighlightElementCallback.function(key, item.datum[key+'_index'], true, _this._setHighlightElementCallback.arg);
                                        elementsToHighlight[<string>key] = item.datum[key+"_index"];
                                    }
    
                                    _this.setHighlightElementsLocally(elementsToHighlight, true);
                                    _this.updatePlotsNewData();
                                }
    
                            }
                        
                        }


                    });
                }

            }

            view.runAsync();

            d3.select("#"+plotId).style("background-color", "white");

        }

        this.updatePlotsNewData();

    }

    getAbstractValues(functionIndex: number, knotsId: string[], plotsKnotsData: {knotId: string, elements: {coordinates: number[], abstract: number[], highlighted: boolean, index: number}[]}[]){
        let abstractValues: any = {};
        
        for(const knotId of knotsId){
            for(const knotData of plotsKnotsData){
                if(knotId == knotData.knotId){
                    let readCoords = 0;
                    for(let i = 0; i < knotData.elements.length; i++){
                        if(functionIndex >= readCoords && functionIndex < (knotData.elements[i].coordinates.length/3)+readCoords){
                            abstractValues[knotId] = knotData.elements[i].abstract[0]; // TODO: support multiple timesteps
                            break;
                        }
                        readCoords += knotData.elements[i].coordinates.length/3;
                    }
                    break;
                }
            }
        }

        return abstractValues;
    }

    async getHTMLFromVega(plot: any){
        // generate HTMLImageElement from vega-spec
        let vegaspec = lite.compile(plot).spec;

        let view = new vega.View(vega.parse(vegaspec), { renderer: 'none' }); // create a Vega view based on the spec

        if(view == undefined){
            throw Error("There is no plot defined for this embedding interaction");
        }

        let svgStringElement = await view.toSVG();

        let parser = new DOMParser();
        let svgElement = parser.parseFromString(svgStringElement, "image/svg+xml").querySelector('svg');

        if(svgElement == null) 
            throw Error("Error while creating svg element from vega-lite plot spec");

        // creating a blob object
        let outerHTML = svgElement.outerHTML;

        let blob = new Blob([outerHTML],{type:'image/svg+xml;charset=utf-8'});
        
        // creating URL from the blob Object
        let urlCreator = window.URL || window.webkitURL || window;
        let blobURL = urlCreator.createObjectURL(blob);

        let lockFlag = new LockFlag(); // flag to indicate if the image was loaded
        
        // loading image to html image element
        let image = new Image();
        image.addEventListener('load', function() {
            
            urlCreator.revokeObjectURL(blobURL);

            lockFlag.set();

        });

        image.src = blobURL;

        let checkFlag = async () => {
            if(lockFlag.flag == false) {
                await new Promise(r => setTimeout(r, 100));
                checkFlag();
            }
        }
        
        await checkFlag();

        return image;
    }

    async getFootEmbeddedSvg(data: any, plotWidth: number, plotHeight: number){

        /**
         * @param {number} nBins total number of bins (circle is divided equally)
         */
        function defineBins(nBins: number){
            let binData: number[] = [];

            let increment = (2*Math.PI)/nBins; // the angles go from 0 to 2pi (radians)

            // adding the angles that define each bin
            for(let i = 0; i < nBins+1; i++){
                binData.push(i*increment);
            }

            return binData;
        }

        /**
         * Returns the index of the bin the angle belongs to
         * @param bins Array describing the beginning and end of all bins
         * @param angle angle in radians
         */
        function checkBin(bins: number[], angle: number){

            for(let i = 0; i < bins.length-1; i++){
                let start = bins[i];
                let end = bins[i+1];

                if(angle >= start && angle <= end){
                    return i;
                }

            }

            return -1; // returns -1 if it does not belong to any bin
        }

        let bins: number = 0;
        let selectedPlot: IPlotGrammar | null = null;

        for(let i = 0; i < this._plots.length; i++){ // TODO: support multiple embedded plots
            if(this._plots[i].grammar.arrangement == PlotArrangementType.FOOT_EMBEDDED){

                if(this._plots[i].grammar.args != undefined){
                    bins = <number>(<IPlotArgs>this._plots[i].grammar.args).bins;
                }

                selectedPlot = this._plots[i].grammar;
            }
        }

        if(selectedPlot != null){
            let data_arr = JSON.parse(data); 
    
            let vegaValues = [];
    
            let binsDescription: number[];
    
            if(bins == 0){
                binsDescription = [0,360];
            }else{
                binsDescription = defineBins(bins);
            }
    
            for(let i = 0; i < data_arr.pointData.length; i++){
                let point = data_arr.pointData[i];
    
                let value: any = {};
    
                value.x = point.pixelCoord[0];
                value.y = point.pixelCoord[1];
                value.bin = checkBin(binsDescription, radians(point.angle));
                value.normalX = point.normal[0];
                value.normalY = point.normal[1];
    
                let abstractValues = this.getAbstractValues(point.functionIndex, selectedPlot.knots, this._plotsKnotsData);
    
                let abstractValuesKeys = Object.keys(abstractValues);
    
                for(const key of abstractValuesKeys){
                    value[key+"_abstract"] = abstractValues[key];
                }
    
                vegaValues.push(value);
            }
    
            selectedPlot.plot.data = {"values": vegaValues};
            selectedPlot.plot.width = plotWidth;
            selectedPlot.plot.height = plotHeight;
    
            let image = await this.getHTMLFromVega(selectedPlot.plot);
    
            return image;
        }

        return null;
    }

    async getSurEmbeddedSvg(data: any, plotWidth: number, plotHeight: number){
        let selectedPlot: IPlotGrammar | null = null;
        
        for(let i = 0; i < this._plots.length; i++){ // TODO: support multiple embedded plots
            if(this._plots[i].grammar.arrangement == PlotArrangementType.SUR_EMBEDDED){

                selectedPlot = this._plots[i].grammar;
            }
        }

        if(selectedPlot != null){
            let data_arr = JSON.parse(data); 

            let vegaValues = [];
    
            for(let i = 0; i < data_arr.length; i++){
                let point = data_arr[i];
    
                let value: any = {};
    
                let abstractValues = this.getAbstractValues(point.functionIndex, selectedPlot.knots, this._plotsKnotsData);
    
                let abstractValuesKeys = Object.keys(abstractValues);
    
                for(const key of abstractValuesKeys){
                    value[key+"_abstract"] = abstractValues[key];
                    value[key+"_index"] = point.index;
                }
    
                vegaValues.push(value);
            }
    
            selectedPlot.plot.data = {"values": vegaValues};
            selectedPlot.plot.width = plotWidth;
            selectedPlot.plot.height = plotHeight;
    
            let image = await this.getHTMLFromVega(selectedPlot.plot);
    
            return image;
        }

        return null;

    }

}
