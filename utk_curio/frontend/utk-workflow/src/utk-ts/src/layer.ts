/// <reference types="@types/webgl2" />

import { Shader } from './shader';
// import { Camera } from './camera';
import { Mesh } from "./mesh";

import { ILayerFeature, IMapStyle, IJoinedLayer, IJoinedObjects, IKnot, IJoinedJson, IExternalJoinedJson, IExKnot } from './interfaces';
import { LayerType, RenderStyle, OperationType, LevelType } from './constants';
import { AuxiliaryShader } from './auxiliaryShader';
import { Environment } from './environment';

export abstract class Layer {
    // layer id
    protected _id: string;
    // layer type
    protected _type: LayerType;

    // style key used to color the layer
    protected _styleKey: keyof IMapStyle;

    // render styles available
    protected _renderStyle: RenderStyle[];

    // store link information with other layers
    protected _joinedLayers: IJoinedLayer[];
    protected _joinedObjects: IJoinedObjects[];

    protected _externalJoinedJson: IExternalJoinedJson;

    // layer's camera
    protected _camera: any;

    protected _mesh: Mesh;

    constructor(id: string, type: LayerType, styleKey: keyof IMapStyle, renderStyle: RenderStyle[] = [], dimension: number, zOrder: number) {
        this._id = id;
        this._type = type;
        this._styleKey = styleKey;
        // this._colorMap = colorMap;
        this._renderStyle = renderStyle;
        this._mesh = new Mesh(dimension, zOrder);
    }

    setJoinedJson(joinedJson: IJoinedJson | IExternalJoinedJson){
        if(Environment.serverless){ // IExternalJoinedJson 
            this._externalJoinedJson = <IExternalJoinedJson>joinedJson;
        } else { // IJoinedJson
            this._joinedLayers = (<IJoinedJson>joinedJson).joinedLayers;
            this._joinedObjects = (<IJoinedJson>joinedJson).joinedObjects;
        } 
    }

    /**
     * Accessor for the layer id
     */
    get id(): string {
        return this._id;
    }

    /**
     * Accessor for the layer style
     */
    get style(): keyof IMapStyle {
        return this._styleKey;
    }

    get joinedLayers(): IJoinedLayer[] {
        return this._joinedLayers;
    }

    get externalJoinedJson(): IExternalJoinedJson {
        return this._externalJoinedJson;
    }

    get joinedObjects(): IJoinedObjects[] {
        return this._joinedObjects;
    }

    /**
     * Sends the camera to the layer
     */
    set camera(camera: any) {
        this._camera = camera;
    }

    get mesh(): Mesh {
        return this._mesh;
    }

    set mesh(mesh: Mesh) {
        this._mesh = mesh;
    }

    get renderStyle(){
        return this._renderStyle;
    }

    /**
     * Data update signature
     */
    // abstract updateFeatures(data: ILayerFeature[], knot: IKnot, layerManager: LayerManager): void;

    abstract updateMeshGeometry(data: ILayerFeature[]): void;

    abstract updateShaders(shaders: (Shader|AuxiliaryShader)[], centroid:number[] | Float32Array, viewId: number): void;

    abstract updateFunction(knot: IKnot | IExKnot, shaders: (Shader|AuxiliaryShader)[]): void;

    abstract render(glContext: WebGL2RenderingContext, shaders: (Shader|AuxiliaryShader)[]): void;

    /**
     * Distributes the function values inside the layer according to its semantics so it can be rendered. (i.e. function values of coordinates in building cells are averaged)
     * This function is called as the last step of the rendering pipeline (after all the joins and operations with the abstract data)
     * @param functionValues function values per coordinate per timestep
     */
    abstract distributeFunctionValues(functionValues: number[][] | null): number[][] | null;

    /**
     * Aggregates the function values to a more coarse level 
     * @param functionValues function values per coordinate (but all the coordinates that compose a basic struct at the start level have the same values). If the start level is building, for instance, all coordinates of a specific building have the same value.
     * 
     */
    abstract innerAggFunc(functionValues: number[] | null, startLevel: LevelType, endLevel: LevelType, operation: OperationType): number[] | null;

    /**
     * Given the id of an element that is in a specific level, returns the function value index that should be used to 
     * retrieve the representative function value of that element
     */
    abstract getFunctionValueIndexOfId(id: number, level: LevelType): number | null;

    abstract getCoordsByLevel(level: LevelType, centroid:number[] | Float32Array, viewId: number): number[][];

    abstract getFunctionByLevel(level: LevelType, knotId: string): number[][][];

    abstract getHighlightsByLevel(level: LevelType, shaders: (Shader|AuxiliaryShader)[]): boolean[];

    abstract supportInteraction(eventName: string): boolean;

    /**
     * 
     * @param elements array of elements indices (follow the order they appear in the layer json file)
     */
    abstract setHighlightElements(elements: number[], level: LevelType, value: boolean, shaders: (Shader|AuxiliaryShader)[], centroid:number[] | Float32Array, viewId: number): void;

    // bypass the data extraction from link and data directly into the mesh
    abstract directAddMeshFunction(functionValues: number[][], knotId: string): void;

    abstract getSelectedFiltering(shaders: (Shader|AuxiliaryShader)[]): number[] | null;
}
