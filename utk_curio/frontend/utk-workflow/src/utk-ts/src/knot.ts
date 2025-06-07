import { Layer } from "./layer";
import { AuxiliaryShader } from './auxiliaryShader';
import { Shader } from './shader';
import { MapStyle } from "./map-style";
import { OperationType, InteractionType, LevelType, PlotArrangementType, RenderStyle } from './constants';

import { ShaderFlatColor } from "./shader-flatColor";
import { ShaderFlatColorMap } from "./shader-flatColorMap";
import { ShaderFlatColorPointsMap } from "./shader-flatColorPointsMap";
import { ShaderSmoothColor } from "./shader-smoothColor";
import { ShaderSmoothColorMap } from "./shader-smoothColorMap";
import { ShaderSmoothColorMapTex } from "./shader-smoothColorMapTex";
import { ShaderAbstractSurface } from "./shader-abstractSurface";
import { ShaderPicking } from "./shader-picking";
import { ShaderPickingTriangles } from "./shader-picking-triangles";
import { AuxiliaryShaderTriangles } from "./auxiliaryShaderTriangles";

import { BuildingsLayer } from "./layer-buildings";
import { TrianglesLayer } from "./layer-triangles";
import { IExKnot, IKnot, IMapGrammar } from "./interfaces";
import { LayerManager } from "./layer-manager";
import { ShaderColorPoints } from "./shader-colorPoints";
import { ShaderFlatColorPoints } from "./shader-flatColorPoints";
import { PointsLayer } from "./layer-points";
import { ShaderPickingPoints } from "./shader-picking-points";
import { Environment } from "./environment";

export class Knot {

    protected _physicalLayer: Layer; // the physical format the data will assume
    protected _thematicData: number[][] | null;
    protected _knotSpecification: IKnot | IExKnot;
    protected _id: string;
    protected _shaders: any = {};
    protected _visible: boolean;
    protected _grammarInterpreter: any;
    protected _maps: any = {};
    protected _cmap: string = 'interpolateReds';
    protected _range: number[] = [0, 1];
    protected _domain: number[] = [];
    protected _scale: string = 'scaleLinear';

    constructor(id: string, physicalLayer: Layer, knotSpecification: IKnot | IExKnot, grammarInterpreter: any, visible: boolean) {
        this._physicalLayer = physicalLayer;
        this._knotSpecification = knotSpecification;
        this._id = id;
        this._visible = visible;
        this._grammarInterpreter = grammarInterpreter;
    }

    get id(){
        return this._id;
    }

    get visible(){
        return this._visible;
    }

    get shaders(){
        return this._shaders;
    }

    get physicalLayer(){
        return this._physicalLayer;
    }

    get knotSpecification(){
        return this._knotSpecification;
    }

    get thematicData(){
        return this._thematicData;
    }

    get cmap(){
        return this._cmap;
    }

    get range(){
        return this._range;
    }

    get domain(){
        return this._domain;
    }

    get scale(){
        return this._scale;
    }

    set visible(visible: boolean){
        this._visible = visible;
    }

    set thematicData(thematicData: number[][] | null){
        this._thematicData = thematicData;
    }

    addMap(map: any, viewId: number) {
        this._maps[viewId] = map;
    }

    render(glContext: WebGL2RenderingContext, camera: any, viewId: number): void {
        if (!this._visible) { return; } 

        this._physicalLayer.camera = camera;
        this._physicalLayer.render(glContext, this._shaders[viewId]);
    }

    updateTimestep(timestep: number, viewId: number): void {
        for(const shader of this._shaders[viewId]){
            shader.updateShaderData(this._physicalLayer.mesh, this._knotSpecification, timestep);
        }
    }

    overwriteSelectedElements(externalSelected: number[], viewId: number){
        for(const shader of this._shaders[viewId]){
            if(shader instanceof ShaderFlatColorMap || shader instanceof ShaderFlatColorPointsMap || shader instanceof ShaderSmoothColorMap || shader instanceof ShaderSmoothColorMapTex){
                shader.overwriteSelectedElements(externalSelected);
            }
        }

    }

    loadShaders(glContext: WebGL2RenderingContext, centroid:number[] | Float32Array = [0,0,0], viewId: number): void {
        this._shaders[viewId] = [];
        const color = MapStyle.getColor(this._physicalLayer.style);

        if(this._knotSpecification['color_map'] != undefined){
            this._cmap = <string>this._knotSpecification['color_map'];
        }

        if(this._knotSpecification['range'] != undefined){
            this._range = <number[]>this._knotSpecification['range'];
        }

        if(this._knotSpecification['domain'] != undefined){
            this._domain = <number[]>this._knotSpecification['domain'];
        }

        if(this._knotSpecification['scale'] != undefined){
            this._scale = <string>this._knotSpecification['scale'];
        }

        for (const type of this._physicalLayer.renderStyle) {
            let shader = undefined;
            switch (type) {
                case RenderStyle.FLAT_COLOR:
                    shader = new ShaderFlatColor(glContext, color, this._grammarInterpreter);
                break;
                case RenderStyle.FLAT_COLOR_MAP:
                    shader = new ShaderFlatColorMap(glContext, this._grammarInterpreter, this._cmap, this._range, this._domain, this._scale);
                break;
                case RenderStyle.FLAT_COLOR_POINTS_MAP:
                    shader = new ShaderFlatColorPointsMap(glContext, this._grammarInterpreter, this._cmap, this._range, this._domain, this._scale);
                break;
                case RenderStyle.SMOOTH_COLOR:
                    shader = new ShaderSmoothColor(glContext, color, this._grammarInterpreter);
                break;
                case RenderStyle.SMOOTH_COLOR_MAP:
                    shader = new ShaderSmoothColorMap(glContext, this._grammarInterpreter, this._cmap, this._range, this._domain, this._scale);
                break;
                case RenderStyle.SMOOTH_COLOR_MAP_TEX:
                    shader = new ShaderSmoothColorMapTex(glContext, this._grammarInterpreter, this._cmap, this._range, this._domain, this._scale);
                break;
                case RenderStyle.PICKING: 

                    if(this._physicalLayer instanceof TrianglesLayer || this._physicalLayer instanceof PointsLayer){
                        let auxShader = undefined;
    
                        if(this._shaders[viewId].length > 0){
                            auxShader = this._shaders[viewId][this._shaders[viewId].length-1];
                        }
    
                        if(auxShader && auxShader instanceof AuxiliaryShaderTriangles){

                            if(this._physicalLayer instanceof TrianglesLayer){
                                shader = new ShaderPickingTriangles(glContext, auxShader, this._grammarInterpreter);
                            }else{
                                shader = new ShaderPickingPoints(glContext, auxShader, this._grammarInterpreter);
                            }

                        }else{
                            throw new Error("The shader picking needs an auxiliary shader. The auxiliary shader is the one right before (order matters) shader picking in renderStyle array. SMOOTH_COLOR_MAP can be used as an auxiliary array");
                        }
                    }else if(this._physicalLayer instanceof BuildingsLayer){
                        let auxShader = undefined;

                        if(this._shaders[viewId].length > 0){
                            auxShader = this._shaders[viewId][this._shaders[viewId].length-1];
                        }
    
                        if(auxShader && auxShader instanceof AuxiliaryShader){
                            shader = new ShaderPicking(glContext, auxShader, this._grammarInterpreter);
                        }else{
                            throw new Error("The shader picking needs an auxiliary shader. The auxiliary shader is the one right before (order matters) shader picking in renderStyle array.");
                        }
                    }

                break;
                case RenderStyle.ABSTRACT_SURFACES:
                    shader = new ShaderAbstractSurface(glContext, this._grammarInterpreter);
                break;
                case RenderStyle.COLOR_POINTS:
                    shader = new ShaderColorPoints(glContext, this._grammarInterpreter, this._cmap, this._range, this._domain, this._scale);
                break;
                case RenderStyle.FLAT_COLOR_POINTS:
                    shader = new ShaderFlatColorPoints(glContext, color, this._grammarInterpreter);
                break;
                default:
                    shader = new ShaderFlatColor(glContext, color, this._grammarInterpreter);
                break;
            }

            this._shaders[viewId].push(<Shader | AuxiliaryShader>shader);

            // // load message
            // console.log("------------------------------------------------------");
            // console.log(`Layer ${this._id} of type ${this._type}.`);
            // console.log(`Render styles: ${this._renderStyle.join(", ")}`);
            // console.log(`Successfully loaded ${this._shaders.length} shader(s).`);
            // console.log("------------------------------------------------------");
        }

        this._physicalLayer.updateShaders(this._shaders[viewId], centroid, viewId); // send mesh data to the shaders

        this._physicalLayer.updateFunction(this._knotSpecification, this._shaders[viewId]);
    }

    // send function values to the mesh of the layer
    addMeshFunction(layerManager: LayerManager){
        let functionValues: number[][] | null = null;
        
        if((<IKnot>this._knotSpecification).integration_scheme != null){
            functionValues = layerManager.getAbstractDataFromLink((<IKnot>this._knotSpecification).integration_scheme)
        }

        this._thematicData = functionValues;

        let distributedValues = this._physicalLayer.distributeFunctionValues(functionValues);

        this._physicalLayer.mesh.loadFunctionData(distributedValues, (<IKnot>this._knotSpecification).id);
    }

    processThematicData(layerManager: LayerManager){

        if(!Environment.serverless){
            if((<IKnot>this._knotSpecification).knot_op != true){
                this.addMeshFunction(layerManager);
            }else{ // TODO: knot should not have to retrieve the subknots they should be given
                let functionsPerKnot: any = {};
    
                for(const scheme of (<IKnot>this._knotSpecification).integration_scheme){
                    if(functionsPerKnot[scheme.out.name] == undefined){
                        let knot = this._grammarInterpreter.getKnotById(scheme.out.name);
    
                        if(knot == undefined){
                            throw Error("Could not retrieve knot that composes knot_op "+this._knotSpecification.id);
                        }
    
                        functionsPerKnot[scheme.out.name] = layerManager.getAbstractDataFromLink(knot.integration_scheme);
                    }
    
                    if(scheme.in != undefined && functionsPerKnot[<string>scheme.in.name] == undefined){
                        let knot = this._grammarInterpreter.getKnotById(<string>scheme.in.name);
    
                        if(knot == undefined){
                            throw Error("Could not retrieve knot that composes knot_op "+this._knotSpecification.id);
                        }
    
                        functionsPerKnot[<string>scheme.in.name] = layerManager.getAbstractDataFromLink(knot.integration_scheme);
                    }
    
                }
    
                let functionSize = -1;
    
                let functionsPerKnotsKeys = Object.keys(functionsPerKnot);
    
                for(const key of functionsPerKnotsKeys){
                    if(functionSize == -1){
                        functionSize = functionsPerKnot[key][0].length;
                    }else if(functionSize != functionsPerKnot[key][0].length){
                        throw Error("All knots used in knot_op must have the same length");
                    }
                }
    
                if(functionSize == -1){
                    throw Error("Could not retrieve valid function values for knot_op "+this._knotSpecification.id);
                }
    
                let prevResult: number[][] = [];
    
                // let prevResult: number[] = new Array(functionSize);
    
                let linkIndex = 0;
    
                for(const scheme of (<IKnot>this._knotSpecification).integration_scheme){
                    if(linkIndex == 0 && (<string>scheme.op).includes("prevResult")){
                        throw Error("It is not possible to access a previous result (prevResult) for the first link");
                    }
    
                    let functionValue0 = functionsPerKnot[scheme.out.name];
                    let functionValue1 = functionsPerKnot[(<{name: string, level: string}>scheme.in).name];
                
                    for(let k = 0; k < functionValue0.length; k++){ // iterating over timesteps
    
                        prevResult.push(new Array(functionSize));
    
                        let currentFunctionValue0 = functionValue0[k];
                        let currentFunctionValue1 = functionValue1[k];
    
                        for(let j = 0; j < currentFunctionValue0.length; j++){
        
                            let operation = (<string>scheme.op).replaceAll(scheme.out.name, currentFunctionValue0[j]+'').replaceAll((<{name: string, level: string}>scheme.in).name, currentFunctionValue1[j]+''); 
                            
                            if(linkIndex != 0){
                                operation = operation.replaceAll("prevResult", prevResult[k][j]+'');
                            }
        
                            prevResult[k][j] = eval(operation); // TODO deal with security problem
                        }
                    }
    
                    linkIndex += 1;
                }
    
                this._physicalLayer.directAddMeshFunction(prevResult, this._knotSpecification.id);
    
            }
        }else{
            let result: number[][] = [];

            if((<IExKnot>this._knotSpecification).in_name != undefined){
                result = layerManager.getValuesExKnot((<IExKnot>this._knotSpecification).out_name, <string>(<IExKnot>this._knotSpecification).in_name);
            }
            this._physicalLayer.directAddMeshFunction(result, this._knotSpecification.id);
        }
    }

    private _getPickingArea(glContext: WebGL2RenderingContext, x: number, y: number, anchorX: number, anchorY: number): {pixelAnchorX: number, pixelAnchorY: number, width: number, height: number}{
        if(!glContext.canvas || !(glContext.canvas instanceof HTMLCanvasElement)){
            return {
                pixelAnchorX: 0,
                pixelAnchorY: 0,
                width: 0,
                height: 0
            };
        }
        
        // Converting mouse position in the CSS pixels display into pixel coordinate
        let pixelX = x * glContext.canvas.width / glContext.canvas.clientWidth;
        let pixelY = glContext.canvas.height - y * glContext.canvas.height / glContext.canvas.clientHeight - 1;

        let pixelAnchorX = anchorX * glContext.canvas.width / glContext.canvas.clientWidth;
        let pixelAnchorY = glContext.canvas.height - anchorY * glContext.canvas.height / glContext.canvas.clientHeight - 1;

        let width: number = 0;
        let height: number = 0;

        if(pixelX - pixelAnchorX > 0 && pixelY - pixelAnchorY < 0){ //bottom right
            width = Math.abs(pixelX - pixelAnchorX); 
            height = Math.abs(pixelY - pixelAnchorY);    
            
            pixelAnchorY = pixelY; // shift the anchor point for the width and height be always positive
        }else if(pixelX - pixelAnchorX < 0 && pixelY - pixelAnchorY < 0){ //  bottom left
            width = Math.abs(pixelX - pixelAnchorX); 
            height = Math.abs(pixelY - pixelAnchorY); 
            
            pixelAnchorY = pixelY; // shift the anchor point for the width and height be always positive
            pixelAnchorX = pixelX; // shift the anchor point for the width and height be always positive
        }else if(pixelX - pixelAnchorX > 0 && pixelY - pixelAnchorY > 0){ // top right
            width = Math.abs(pixelX - pixelAnchorX); 
            height = Math.abs(pixelY - pixelAnchorY);
        }else if(pixelX - pixelAnchorX < 0 && pixelY - pixelAnchorY > 0){ // top left
            width = Math.abs(pixelX - pixelAnchorX); 
            height = Math.abs(pixelY - pixelAnchorY);

            pixelAnchorX = pixelX; // shift the anchor point for the width and height be always positive
        }

        return {
            pixelAnchorX: pixelAnchorX,
            pixelAnchorY: pixelAnchorY,
            width: width,
            height: height
        }
    }

    // handles map interaction with the knot
    async interact(glContext: WebGL2RenderingContext, eventName: string, mapGrammar: IMapGrammar, cursorPosition: number[] | null = null, brushingPivot: number[] | null = null, eventObject: any | null = null){

        if(!this._visible || !this._physicalLayer.supportInteraction(eventName)){return;}

        let interaction = '';

        for(let i = 0; i < mapGrammar.knots.length; i++){
            if(mapGrammar.knots[i] == this._id){
                interaction = mapGrammar.interactions[i] as InteractionType;
                break;
            }
        }

        if(interaction == ''){return;}

        let plotsGrammar = this._grammarInterpreter.getPlots();
        let plotArrangements = [];

        for(const plot of plotsGrammar){
            if(plot.grammar.knots.includes(this._id)){
                plotArrangements.push(plot.grammar.arrangement);
            }
        }

        let embedFootInteraction = false;
        let highlightCellInteraction = false;
        let highlightBuildingInteraction = false;
        let embedSurfaceInteraction = false;
        let highlightTriangleObject = false;

        let areaHighlightTriangleObjects = false;
        let areaHighlightBuildingInteraction = false;

        if(interaction == InteractionType.BRUSHING){
            highlightCellInteraction = true;

            if(plotArrangements.includes(PlotArrangementType.SUR_EMBEDDED)){
                embedSurfaceInteraction = true;
            }
        }

        if(interaction == InteractionType.PICKING){
            if(plotArrangements.includes(PlotArrangementType.FOOT_EMBEDDED)){ 
                embedFootInteraction = true;
            }

            if(plotArrangements.includes(PlotArrangementType.LINKED)){
                highlightBuildingInteraction = true;
                highlightTriangleObject = true;
            }

            if(plotArrangements.length == 0){
                highlightBuildingInteraction = true;
                highlightTriangleObject = true;
            }
        }

        if(interaction == InteractionType.AREA_PICKING){

            if(plotArrangements.includes(PlotArrangementType.FOOT_EMBEDDED)){ 
                throw new Error("FOOT_EMBEDDED plots are not compatible with AREA_PICKING");
            }

            if(plotArrangements.includes(PlotArrangementType.LINKED)){
                areaHighlightBuildingInteraction = true;
                areaHighlightTriangleObjects = true;
            }

            if(plotArrangements.length == 0){
                areaHighlightBuildingInteraction = true;
                areaHighlightTriangleObjects = true;
            }
        }

        // mouse down
        if(eventName == "left+ctrl" && cursorPosition != null){

            let result = this._getPickingArea(glContext, cursorPosition[0], cursorPosition[1], cursorPosition[0], cursorPosition[1]);

            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                        shader.clearPicking();
                        if(highlightCellInteraction)
                            shader.updatePickPosition(result.pixelAnchorX, result.pixelAnchorY, result.width, result.height);
                    }
                }
            }

        }

        if(eventName == 'right-alt'){
            
            let keysShaders = Object.keys(this._shaders);

            for(let i = 0; i < keysShaders.length; i++){
                let key = keysShaders[i];
                let shaders = this._shaders[parseInt(key)];
                for(let j = 0; j < shaders.length; j++){
                    let shader = shaders[j];
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles || shader instanceof ShaderPickingPoints){
                        shader.clearPicking();
                    }
                }
            }
            for(const key of Object.keys(this._maps)){
                let map = this._maps[parseInt(key)];
                map.updateGrammarPlotsHighlight(this._physicalLayer.id, null, null, true); // letting plots manager know that this knot was interacted with
            }

        }

        // mouse move
        if(eventName == "left+drag+alt-brushing" && cursorPosition != null && highlightCellInteraction){
            let result = this._getPickingArea(glContext, cursorPosition[0], cursorPosition[1], cursorPosition[0], cursorPosition[1]);

            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                        shader.updatePickPosition(result.pixelAnchorX, result.pixelAnchorY, result.width, result.height);
                    }
                }
            }
        }

        if(eventName == "left+drag+alt+brushing" && cursorPosition != null && brushingPivot != null){
            let result = this._getPickingArea(glContext, cursorPosition[0], cursorPosition[1], brushingPivot[0], brushingPivot[1]);

            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                        shader.updatePickPosition(result.pixelAnchorX, result.pixelAnchorY, result.width, result.height);
                    }
                }
            }
        }

        if(eventName == "left+drag-alt+brushing" || eventName == "-drag-alt+brushing"){
            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking){
                        shader.applyBrushing();
                    }
                }
            }
        }

        if(eventName == "right+drag-brushingFilter" && cursorPosition != null){
            let result = this._getPickingArea(glContext, cursorPosition[0], cursorPosition[1], cursorPosition[0], cursorPosition[1]);

            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                        shader.updatePickFilterPosition(result.pixelAnchorX, result.pixelAnchorY, result.width, result.height);
                    }
                }
            }
        }

        if(eventName == "right+drag+brushingFilter" && cursorPosition != null && brushingPivot != null){
            let result = this._getPickingArea(glContext, cursorPosition[0], cursorPosition[1], brushingPivot[0], brushingPivot[1]);

            for(const key of Object.keys(this._shaders)){
                let shaders = this._shaders[parseInt(key)];
                for(const shader of shaders){
                    if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                        shader.updatePickFilterPosition(result.pixelAnchorX, result.pixelAnchorY, result.width, result.height);
                    }
                }
            }
        }

        // mouse wheel
        if(eventName == "wheel+alt" && cursorPosition != null && embedFootInteraction){
            if(this._physicalLayer instanceof BuildingsLayer){ // TODO: generalize this
                for(const key of Object.keys(this._maps)){
                    let map = this._maps[parseInt(key)]
                    this._physicalLayer.createFootprintPlot(map.glContext, cursorPosition[0], cursorPosition[1], true, this._shaders[parseInt(key)]);
                    map.render(); // TODO: get rid of the need to render the map
                    await this._physicalLayer.updateFootprintPlot(map.glContext, map.plotManager, -1, eventObject.deltaY * 0.02, 'vega', this._shaders[parseInt(key)]);
                }
            }
        }

        if(eventName == "enter" && highlightCellInteraction && embedSurfaceInteraction){
            if(this._physicalLayer instanceof BuildingsLayer){ // TODO: generalize this
                for(const key of Object.keys(this._maps)){
                    let map = this._maps[parseInt(key)];
                    let shaders = this._shaders[parseInt(key)];
                    await this._physicalLayer.applyTexSelectedCells(map.glContext, map.plotManager, 'vega', shaders);
                }
            }
        }

        if(eventName == "r"){
            if(this._physicalLayer instanceof BuildingsLayer){ // TODO: generalize this
                for(const key of Object.keys(this._shaders)){
                    let shaders = this._shaders[parseInt(key)];
                    this._physicalLayer.clearAbsSurface(shaders);
                }
            }
        }

        // keyUp
        if(eventName == "t"){
            if(highlightTriangleObject || areaHighlightTriangleObjects){

                //triangles layer interactions
                if(this._physicalLayer instanceof TrianglesLayer || this._physicalLayer instanceof PointsLayer){ // TODO: generalize this
                    for(const key of Object.keys(this._maps)){
                        let map = this._maps[parseInt(key)];
                        let currentPoint = map.mouse.currentPoint;
                        for(const key of Object.keys(this._shaders)){
                            let shaders = this._shaders[parseInt(key)];

                            if(highlightTriangleObject){
                                this._physicalLayer.highlightElement(map.glContext, currentPoint[0], currentPoint[1], shaders);
                            }else if(areaHighlightTriangleObjects){
                                this._physicalLayer.highlightElementsInArea(map.glContext, currentPoint[0], currentPoint[1], shaders, 50); // 50 pixels of radius
                            }

                        }
                    }
                }

                for(const key of Object.keys(this._maps)){
                    let map = this._maps[parseInt(key)]
                    map.render();
                    map.render();
                }

                if(this._physicalLayer instanceof TrianglesLayer || this._physicalLayer instanceof PointsLayer){ // TODO: generalize this
                    for(const key of Object.keys(this._shaders)){
                        let shaders = this._shaders[parseInt(key)];
                        let objectIds = this._physicalLayer.getIdLastHighlightedElement(shaders);
                        let map = this._maps[parseInt(key)]

                        let level = LevelType.OBJECTS;

                        if(this._physicalLayer instanceof PointsLayer){
                            level = LevelType.COORDINATES3D;
                        }

                        if(objectIds != undefined){
                            if(objectIds.length > 1){ // if more than one id is being highlighted at the same time that is an area interaction
                                map.updateGrammarPlotsHighlight(this._physicalLayer.id, level, null, true); // clear
                            }
                            map.updateGrammarPlotsHighlight(this._physicalLayer.id, level, objectIds);
                        }
                    }
                }
            }

            if(embedFootInteraction && cursorPosition != null){ // TODO: simplify this footprint plot application
                let elementsIndex = [];
    
                if(this._physicalLayer instanceof BuildingsLayer){

                    for(const key of Object.keys(this._maps)){
                        let map = this._maps[parseInt(key)]
                        this._physicalLayer.createFootprintPlot(map.glContext, cursorPosition[0], cursorPosition[1], false, this._shaders[parseInt(key)]);
                        map.render();
                        let buildingId = await this._physicalLayer.applyFootprintPlot(map.glContext, map.plotManager, 1, 'vega', this._shaders[parseInt(key)]);
                        elementsIndex.push(buildingId);
                    }

                }
                for(const key of Object.keys(this._maps)){
                    let map = this._maps[parseInt(key)]
                    map.render();
                }
            }

            if((highlightBuildingInteraction || areaHighlightBuildingInteraction) && cursorPosition != null){
                // call functions to highlight building
                
                if(this._physicalLayer instanceof BuildingsLayer){
                    for(const key of Object.keys(this._maps)){
                        let map = this._maps[parseInt(key)]
                        for(const key of Object.keys(this._shaders)){
                            let shaders = this._shaders[parseInt(key)];

                            if(highlightBuildingInteraction){
                                this._physicalLayer.highlightBuilding(map.glContext, cursorPosition[0], cursorPosition[1], shaders);
                            }else{
                                this._physicalLayer.highlightBuildingsInArea(map.glContext, cursorPosition[0], cursorPosition[1], shaders, 50);
                            }

                        }
                    }
                }

                for(const key of Object.keys(this._maps)){
                    let map = this._maps[parseInt(key)]
                    // the two renderings are required
                    map.render();
                    map.render();
                }
    
                if(this._physicalLayer instanceof BuildingsLayer){
                    for(const key of Object.keys(this._shaders)){
                        let shaders = this._shaders[parseInt(key)];
                        let buildingIds = this._physicalLayer.getIdLastHighlightedBuilding(shaders);
                        let map = this._maps[parseInt(key)]

                        if(buildingIds != undefined){
                            if(buildingIds.length > 1){ // if more than one id is being highlighted at the same time that is an area interaction
                                map.updateGrammarPlotsHighlight(this._physicalLayer.id, LevelType.OBJECTS, null, true); // clear
                            }
                            map.updateGrammarPlotsHighlight(this._physicalLayer.id, LevelType.OBJECTS, buildingIds); // letting plots manager know that this knot was interacted with
                        }
                    }
                }
            }

        }
        for(const key of Object.keys(this._maps)){
            let map = this._maps[parseInt(key)]
            map.render(); 
        }
    }   

}