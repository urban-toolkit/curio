/// <reference types="@types/webgl2" />

import { Camera } from './camera';

import { MapStyle } from './map-style';

import { KeyEvents } from './key-events';
import { MouseEvents } from './mouse-events';

import { DataApi } from './data-api';
import { LayerManager } from './layer-manager';

import { ICameraData, IExKnot, IKnot, ILinkDescription, IMapGrammar } from './interfaces';

import { LevelType } from './constants';

import { ShaderPicking } from "./shader-picking";
import { ShaderPickingTriangles } from "./shader-picking-triangles";

import { PlotManager } from "./plot-manager";
import { KnotManager } from './knot-manager';
import { Environment } from './environment';

export class MapView {
    // Html div that will host the map
    protected _mapDiv: HTMLElement;
    // Html canvas used to draw the map
    protected _canvas: HTMLCanvasElement;
    // WebGL context of the canvas
    public _glContext: WebGL2RenderingContext;

    protected _layerManager: LayerManager;
    protected _knotManager: KnotManager;

    // Manages the view configuration loaded (including plots and its interactions)
    protected _plotManager: PlotManager; // plot manager for local embedded plots

    protected _grammarInterpreter: any;

    protected _updateStatusCallback: any;

    // interaction variables
    private _camera: any;
    // mouse events
    private _mouse: any;
    // keyboard events
    private _keyboard: any;

    private _knotVisibilityMonitor: any;

    // private _mapViewData: IGrammar;

    protected _embeddedKnots: Set<string>;
    protected _linkedKnots: Set<string>;

    public _viewId: number; // the view to which this map belongs
    public _mapGrammar: IMapGrammar;

    constructor(grammarInterpreter: any, layerManager: LayerManager, knotManager: KnotManager, viewId:number, mapGrammar: IMapGrammar){
        this.resetMap(grammarInterpreter, layerManager, knotManager, viewId, mapGrammar);
    }

    resetMap(grammarInterpreter: any, layerManager: LayerManager, knotManager: KnotManager, viewId:number, mapGrammar: IMapGrammar): void {
        this._grammarInterpreter = grammarInterpreter;
        this._layerManager = layerManager;
        this._knotManager = knotManager;
        this._viewId = viewId;
        this._mapGrammar = mapGrammar;
    }

    get layerManager(): LayerManager {
        return this._layerManager;
    }

    get mapGrammar(): IMapGrammar{
        return this._mapGrammar;
    }

    get knotManager(): KnotManager{
        return this._knotManager;
    }

    get mouse(): any{
        return this._mouse;
    }

    get viewId(): number{
        return this._viewId;
    }

    /**
     * gets the map div
     */
    get div(): HTMLElement {
        return this._mapDiv;
    }

    /**
     * gets the canvas element
     */
    get canvas(): HTMLCanvasElement {
        return this._canvas;
    }

    /**
     * gets the opengl context
     */
    get glContext(): WebGL2RenderingContext {
        return this._glContext;
    }

    /**
     * gets the camera object
     */
    get camera(): any {
        return this._camera;
    }

    get plotManager(): PlotManager{
        return this._plotManager;
    }

    updateTimestep(message: any, _this: any): void {
        for(const knot of _this._knotManager.knots){
            if(knot.id == message.knotId){
                knot.updateTimestep(message.timestep, message.mapId);
            }
        }

        _this.render();
    }

    /**
     * Map initialization function
     */
    async init(mapDivId: string, updateStatusCallback: any): Promise<void> {

        let mapDiv: any = <HTMLElement>document.getElementById(mapDivId)

        if(mapDiv == null){
            return;
        }

        mapDiv.innerHTML = "";

        this._mapDiv = mapDiv;
        this._canvas = document.createElement('canvas');
        this._canvas.id = mapDiv.id+"_mapCanvas_"+this._grammarInterpreter.id;
        this._canvas.className = "mapView";
        this._glContext = <WebGL2RenderingContext>this._canvas.getContext('webgl2', {preserveDrawingBuffer: true, stencil: true}); // preserve drawing buffer is used to generate valid blobs for the cave
        this._mapDiv.appendChild(this._canvas);

        this._updateStatusCallback = updateStatusCallback;

        if(this._knotVisibilityMonitor){
            clearInterval(this._knotVisibilityMonitor);
        }

        // inits the mouse events
        this.initMouseEvents();

        // inits the keyboard events
        this.initKeyboardEvents();

        this.monitorKnotVisibility();

        await this.initCamera(this._grammarInterpreter.getCamera(this._viewId));

        // resizes the canvas
        this.resize();

        this.initPlotManager();

        if(this._grammarInterpreter.getFilterKnots(this._viewId) != undefined){
            this._layerManager.filterBbox = this._grammarInterpreter.getFilterKnots(this._viewId);
        }else{
            this._layerManager.filterBbox = [];
        }

        updateStatusCallback("subscribe", {id: "mapview"+this._viewId, channel: "updateTimestepKnot", callback: this.updateTimestep, ref: this});

        this.render();
    }

    updateGrammarPlotsData(){

        let plotsKnotData = this._grammarInterpreter.parsePlotsKnotData(this._viewId); // only parse plots knot data that belongs to this mapview

        this._plotManager.updateGrammarPlotsData(plotsKnotData);

    }
 
    // if clear == true, elements and level are ignored and all selections are deactivated
    updateGrammarPlotsHighlight(layerId: string, level: LevelType | null, elements: number[] | null, clear: boolean = false){

        if(!clear && elements != null){
            for(const elementIndex of elements){
                let elementsObject: any = {};
            
                if(!Environment.serverless){
                    for(const knot of this._grammarInterpreter.getKnots()){
                        let lastLink = this._grammarInterpreter.getKnotLastLink(knot);
            
                        if(lastLink.out.name == layerId && lastLink.out.level == level){
                            elementsObject[knot.id] = elementIndex;
                        }
    
                    }
                }else{
                    for(const knot of this._grammarInterpreter.getPremadeKnots()){
                        if(knot.out_name == layerId && LevelType.OBJECTS == level){
                            elementsObject[knot.id] = elementIndex;
                        }
    
                    }
                }

                this.plotManager.applyInteractionEffectsLocally(elementsObject, true, true, true); // apply to the local plot manager
                this._grammarInterpreter.plotManager.applyInteractionEffectsLocally(elementsObject, true, true, true); // apply to the global plot manager
                // this.plotManager.setHighlightElementsLocally(elements, true, true);
                // this.plotManager.setFilterElementsLocally(elements)
            }
        }else{
            let knotsToClear: string[] = [];

            if(!Environment.serverless){
                for(const knot of this._grammarInterpreter.getKnots()){
                    let lastLink = this._grammarInterpreter.getKnotLastLink(knot);
        
                    if(lastLink.out.name == layerId){
                        knotsToClear.push(knot.id);
                    }
                }
            }else{
                for(const knot of this._grammarInterpreter.getPremadeKnots()){
                    if(knot.out_name == layerId){
                        knotsToClear.push(knot.id);
                    }
                }
            }

            // this.plotManager.clearHighlightsLocally(knotsToClear);
            this.plotManager.clearInteractionEffectsLocally(knotsToClear); // apply to the local plot manager
            this._grammarInterpreter.plotManager.clearInteractionEffectsLocally(knotsToClear);  // apply to the global plot manager
        }

    }

    initPlotManager(){
        this._plotManager = new PlotManager("PlotManagerMap"+this._viewId, this._grammarInterpreter.getPlots(this._viewId), this._grammarInterpreter.parsePlotsKnotData(this._viewId), {"function": this.setHighlightElement, "arg": this});
        this._plotManager.init(this._updateStatusCallback);
    }

    //TODO: not sure if mapview should contain this logic
    setHighlightElement(knotId: string, elementIndex: number, value: boolean, _this: any){

        let knot: IKnot | IExKnot | undefined = _this._grammarInterpreter.getKnotById(knotId);

        if(knot == undefined){
            throw Error("Cannot highlight element knot not found");
        }

        let layerId = _this._grammarInterpreter.getKnotOutputLayer(knot);

        let lastLink: ILinkDescription | null = null;

        if(!Environment.serverless){
            lastLink = _this._grammarInterpreter.getKnotLastLink(knot);
            if((<ILinkDescription>lastLink).out.level == undefined)
                return;
        }

        let knotObject = _this.knotManager.getKnotById(knotId);

        let shaders = knotObject.shaders[_this.viewId];

        // not sure if layer should be accessed directly or knot.ts be used
        for(const layer of _this._layerManager.layers){
            if(layer.id == layerId){
                if(!Environment.serverless)
                    layer.setHighlightElements([elementIndex], <LevelType>(<ILinkDescription>lastLink).out.level, value, shaders, _this._camera.getWorldOrigin(), _this.viewId);
                else
                    layer.setHighlightElements([elementIndex], LevelType.OBJECTS, value, shaders, _this._camera.getWorldOrigin(), _this.viewId);

                break;
            }
        }

        _this.render();

    }

    toggleKnot(id:string, value: boolean | null = null){
        this._knotManager.toggleKnot(id, value);
        this.render();
    }

    /**
     * Camera initialization function
     * @param {string | ICameraData} data Object containing the camera. If data is a string, then it loads data from disk.
     */
    async initCamera(camera: ICameraData | string): Promise<void> {
        // load the index file and its layers
        const params = typeof camera === 'string' ? await DataApi.getCameraParameters(camera, this._grammarInterpreter.serverlessApi) : camera;

        // sets the camera
        this._camera = new Camera(params.position, params.direction.up, params.direction.lookAt, params.direction.right, this._updateStatusCallback);
    }

    /**
     * Inits the mouse events
     */
    initMouseEvents(): void {
        // creates the mouse events manager
        this._mouse = new MouseEvents();
        this._mouse.setMap(this);

        // binds the mouse events
        this._mouse.bindEvents();
    }

    /**
     * Inits the mouse events
     */
    initKeyboardEvents(): void {
        // creates the mouse events manager
        this._keyboard = new KeyEvents();
        this._keyboard.setMap(this);

        this._keyboard.bindEvents();
    }

    public setCamera(camera: {position: number[], direction: {right: number[], lookAt: number[], up: number[]}}): void{
        this._camera.setPosition(camera.position[0], camera.position[1]);
        this.render();
    }   

    /**
     * Renders the map
     */
    render(): void {
        // no camera defined
        if (!this._camera) { return; }

        this.resize(); // check if it needs to resize canvas

        // sky definition
        const sky = MapStyle.getColor('sky').concat([1.0]);
        this._glContext.clearColor(sky[0], sky[1], sky[2], sky[3]);

        // tslint:disable-next-line:no-bitwise
        this._glContext.clear(this._glContext.COLOR_BUFFER_BIT | this._glContext.DEPTH_BUFFER_BIT);

        this._glContext.clearStencil(0);
        this._glContext.clear(this._glContext.STENCIL_BUFFER_BIT);

        // updates the camera
        this._camera.update();

        this._camera.loadPosition(JSON.stringify(this.camera));

        // // render the layers
        // for (const layer of this._layerManager.layers) {
        //     // skips based on visibility
        //     if (!layer.visible) { continue; }

        //     if(this._grammarInterpreter.evaluateLayerVisibility(layer.id, this._viewId)){
        //         // sends the camera
        //         layer.camera = this.camera;
        //         // render
        //         // layer.render(this._glContext);
        //     }
        // }

        for(const knot of this._knotManager.knots){

            if(this._grammarInterpreter.evaluateKnotVisibility(knot, this._viewId)){
                knot.render(this._glContext, this.camera, this._viewId);
            }

            // if(this._grammarInterpreter.evaluateKnotVisibility(knot, this._viewId)){
            //     if(!knot.visible)
            //         this._knotManager.toggleKnot(knot.id, true);
            //     knot.render(this._glContext, this.camera, this._viewId);
            // }else{
            //     if(knot.visible)
            //         this._knotManager.toggleKnot(knot.id, false);
            // }
        }

    }

    private monitorKnotVisibility(){
        let previousKnotVisibility: boolean[] = [];

        for(const knot of this._knotManager.knots){
            previousKnotVisibility.push(knot.visible);
        }

        let _this = this;

        this._knotVisibilityMonitor = window.setInterval(function(){
            for(let i = 0; i < _this._knotManager.knots.length; i++){
                let currentVisibility = _this._grammarInterpreter.evaluateKnotVisibility(_this._knotManager.knots[i], _this._viewId);

                // if visibility of some knot changed need to rerender the map
                if(previousKnotVisibility[i] != currentVisibility){
                    previousKnotVisibility[i] = currentVisibility;
                    _this.render();
                }

            }
        }, 100);
    }

    /**
     * Resizes the html canvas
     */
    resize(): void {

        // Lookup the size the browser is displaying the canvas in CSS pixels.
        // const displayWidth = this._canvas.clientWidth;
        // const displayHeight = this._canvas.clientHeight;

        const displayWidth = this._mapDiv.clientWidth;
        const displayHeight = this._mapDiv.clientHeight;

        // Check if the canvas is not the same size.
        const needResize = this._canvas.width  !== displayWidth ||
                            this._canvas.height !== displayHeight;

        if (needResize) {
            // Make the canvas the same size
            this._canvas.width  = displayWidth;
            this._canvas.height = displayHeight;
        }

        const value = Math.max(displayWidth, displayHeight);

        this._glContext.viewport(0, 0, value, value);
        this._camera.setViewportResolution(this._canvas.width, this._canvas.height);

        for (const knot of this._knotManager.knots){
            if (!knot.visible) { continue; }

            for(const shader of knot.shaders[this._viewId]){
                if(shader instanceof ShaderPicking || shader instanceof ShaderPickingTriangles){
                    shader.resizeDirty = true;
                }
            }
        }
           
    }
}