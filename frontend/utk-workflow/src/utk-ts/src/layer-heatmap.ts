import { OperationType, LevelType } from "./constants";
import { ILayerData, ILayerFeature, IKnot, IExKnot } from "./interfaces";

import { Layer } from "./layer";
import { ShaderAbstractSurface } from "./shader-abstractSurface";
import { LayerManager } from "./layer-manager";
import { AuxiliaryShader } from './auxiliaryShader';
import { Shader } from './shader';
import { ShaderSmoothColorMapTex } from "./shader-smoothColorMapTex";
import { ShaderPicking } from "./shader-picking";

export class HeatmapLayer extends Layer {
    protected _zOrder: number;
    protected _dimensions: number;
    protected _coordsByCOORDINATES: number[][] = [];
    protected _coordsByCOORDINATES3D: number[][] = [];
    protected _coordsByOBJECTS: number[][] = [];

    protected _highlightByCOORDINATES: boolean[][] = [];
    protected _highlightByCOORDINATES3D: boolean[][] = [];
    protected _highlightByOBJECTS: boolean[][] = [];

    constructor(info: ILayerData, zOrder: number = 0, geometryData: ILayerFeature[]) {

        super(
            info.id,
            info.type,
            info.styleKey,
            info.renderStyle !== undefined ? info.renderStyle : [],
            3,
            zOrder
        );

        this._zOrder = zOrder;
        this.updateMeshGeometry(geometryData);
    }

    updateMeshGeometry(data: ILayerFeature[]){
        this._mesh.load(data, false);
    }

    updateShaders(shaders: (Shader|AuxiliaryShader)[], centroid:number[] | Float32Array = [0,0,0], viewId: number){
        // updates the shader references
        for (const shader of shaders) {
            shader.updateShaderGeometry(this._mesh, centroid, viewId);
        }
    }

    directAddMeshFunction(functionValues: number[][], knotId: string): void{
        let distributedValues = this.distributeFunctionValues(functionValues);

        this._mesh.loadFunctionData(distributedValues, knotId);
    }

    getSelectedFiltering(): number[] | null {
        throw Error("Filtering not supported for heatmap layer");
    }

    updateFunction(knot: IKnot | IExKnot, shaders: (Shader|AuxiliaryShader)[]): void {
        // updates the shader references
        for (const shader of shaders) {
            shader.updateShaderData(this._mesh, knot);
        }
    }

    supportInteraction(interaction: string): boolean { // return true to the interactions the layer supports
        return true;
    }

    setHighlightElements(elements: number[], level: LevelType, value: boolean, shaders: (Shader|AuxiliaryShader)[], centroid:number[] | Float32Array = [0,0,0], viewId: number): void{
        throw Error("It is not possible to highlight a heatmap layer");
    }

    render(glContext: WebGL2RenderingContext, shaders: (Shader|AuxiliaryShader)[]): void {

        for (const shader of shaders){
            if(shader instanceof ShaderSmoothColorMapTex){
                throw Error("SMOOTH_COLOR_MAP_TEX shader is not supported for the heatmap layer");
            }

            if(shader instanceof ShaderPicking){
                throw Error("PICKING shader is not supported for the heatmap layer");
            }

            if(shader instanceof ShaderAbstractSurface){
                throw Error("ABSTRACT_SURFACES shader is not supported for the heatmap layer");
            }
        }

        // enables the depth test
        // glContext.enable(glContext.DEPTH_TEST);
        glContext.depthFunc(glContext.LEQUAL);

        // enable culling
        glContext.frontFace(glContext.CCW);
        glContext.enable(glContext.CULL_FACE);
        glContext.cullFace(glContext.BACK);

        // enables stencil
        glContext.enable(glContext.STENCIL_TEST);

        // the abs surfaces are loaded first to update the stencil
        for (const shader of shaders) {

            if(shader instanceof ShaderAbstractSurface){
                shader.renderPass(glContext, glContext.TRIANGLES, this._camera, this._mesh, this._zOrder);
            }
        }

        for (const shader of shaders) {
            if(shader instanceof ShaderAbstractSurface){
                continue;
            }else{
                shader.renderPass(glContext, glContext.TRIANGLES, this._camera, this._mesh, this._zOrder);
            }
        }

        // disables stencil
        glContext.disable(glContext.STENCIL_TEST);
        // disables the depth test
        // glContext.disable(glContext.DEPTH_TEST);
        // disables culling
        glContext.disable(glContext.CULL_FACE);
    }

    perFaceAvg(functionValues: number[][], indices: number[], ids: number[]): number[][]{

        let maxId = -1;

        for(const id of ids){
            if(id > maxId){
                maxId = id;
            }
        }

        let avg_accumulation_triangle_all_times: number[][] = [];

        for(let k = 0; k < functionValues.length; k++){ // iterating over timesteps
        
            avg_accumulation_triangle_all_times[k] = new Array(Math.trunc(indices.length/3)).fill(0);
            let avg_accumulation_cell = new Array(maxId+1).fill(0);
    
            let indicesByThree = Math.trunc(indices.length/3);
    
            // calculate acc by triangle
            for(let i = 0; i < indicesByThree; i++){ 
                let value = 0;
    
                value += functionValues[k][indices[i*3]];
                value += functionValues[k][indices[i*3+1]];
                value += functionValues[k][indices[i*3+2]];
    
                avg_accumulation_triangle_all_times[k][i] = value/3; // TODO: /3 or not? (distribute and accumulate?)
            }
    
            // calculate acc by cell based on the triangles that compose it
            let count_acc_cell = new Array(maxId+1).fill(0);
    
            indicesByThree = Math.trunc(indices.length/3);
    
            for(let i = 0; i < indicesByThree; i++){ 
                let cell = ids[i];
                
                avg_accumulation_cell[cell] += avg_accumulation_triangle_all_times[k][i];
    
                count_acc_cell[cell] += 1;
            }
    
            indicesByThree = Math.trunc(indices.length/3);
            
            for(let i = 0; i < indicesByThree; i++){ 
                let cell = ids[i];      
    
                avg_accumulation_triangle_all_times[k][i] = avg_accumulation_cell[cell]/count_acc_cell[cell]
            }
        
        }

        return avg_accumulation_triangle_all_times
    }

    /**
     * Distributes triangle avg to the coordinates that composes the triangle. 
     * The coordinates need to be duplicated, meaning that there are unique indices. 
     */
    perCoordinatesAvg(avg_accumulation_triangle: number[][], coordsLength: number, indices: number[]): number[][]{

        let avg_accumulation_per_coordinates: number[][] = [];

        for(let k = 0; k < avg_accumulation_triangle.length; k++){ // iterating over timesteps
            avg_accumulation_per_coordinates.push(new Array(coordsLength).fill(0));

            for(let i = 0; i < avg_accumulation_triangle[k].length; i++){
                let elem = avg_accumulation_triangle[k][i];

                avg_accumulation_per_coordinates[k][indices[i*3]] = elem
                avg_accumulation_per_coordinates[k][indices[i*3+1]] = elem
                avg_accumulation_per_coordinates[k][indices[i*3+2]] = elem            
            }
        }

        return avg_accumulation_per_coordinates
    }

    distributeFunctionValues(functionValues: number[][] | null): number[][] | null{
        if(functionValues == null){
            return null;
        }

        let ids = this._mesh.getIdsVBO();
        let indices = this._mesh.getIndicesVBO();
        let coordsLength = this._mesh.getTotalNumberOfCoords();

        let per_face_avg_accum = this.perFaceAvg(functionValues, indices, ids);

        let avg_accumulation_per_coordinates = this.perCoordinatesAvg(per_face_avg_accum, coordsLength, indices);
        
        return avg_accumulation_per_coordinates;
    }

    innerAggFunc(functionValues: number[] | null, startLevel: LevelType, endLevel: LevelType, operation: OperationType): number[] | null {
        throw Error("Inner operation is not supported for the heatmap layer");
    }

    getFunctionValueIndexOfId(id: number, level: LevelType): number | null {
        if(level == LevelType.COORDINATES3D){
            throw Error("The heatmap layer does not have function values attached to COORDINATES3D");
        }

        if(level == LevelType.COORDINATES){
            return id;
        }   

        if(level == LevelType.OBJECTS){
            let readCoords = 0;

            let coordsPerComp = this._mesh.getCoordsPerComp();

            for(let i = 0; i < coordsPerComp.length; i++){

                if(i == id){ // assumes that all coordinates of the same object have the same function value
                    return readCoords;
                }

                readCoords += coordsPerComp[i];
            }
        }

        return null;
    }

    /**
     * 
     * @returns each position of the array contains an element of that level
     */
    getCoordsByLevel(level: LevelType, centroid:number[] | Float32Array = [0,0,0], viewId: number): number[][] {
        let coordByLevel: number[][] = [];

        if(level == LevelType.COORDINATES || level == LevelType.OBJECTS){
            throw Error("The heatmap layer can only be operated in the COORDINATES3D level");
        }

        if(level == LevelType.COORDINATES3D){
            if(this._coordsByCOORDINATES3D.length == 0){
                let coords = this._mesh.getCoordinatesVBO(centroid, viewId);
    
                for(let i = 0; i < coords.length/3; i++){
                    coordByLevel.push([coords[i*3],coords[i*3+1],coords[i*3+2]]);
                }

                this._coordsByCOORDINATES3D = coordByLevel;
            }else{
                coordByLevel = this._coordsByCOORDINATES3D
            }

        }

        return coordByLevel;
    }

    getFunctionByLevel(level: LevelType, knotId: string): number[][][] {
        let functionByLevel: number[][][] = []; // each position represent all functions of a certain object in that level. Each coordinate has a list of timesteps

        if(level == LevelType.COORDINATES || level == LevelType.OBJECTS){
            throw Error("The heatmap layer can only be operated in the COORDINATES3D level");
        }

        if(level == LevelType.COORDINATES3D){

            let functions = this._mesh.getFunctionVBO(knotId)

            for(let i = 0; i < functions[0].length; i++){ // for each object 
                functionByLevel.push([[]]);

                for(let k = 0; k < functions.length; k++){ // for each timestep
                    functionByLevel[functionByLevel.length-1][0].push(functions[k][i]) // there is only one coordinate in each object
                }
            }
        }

        return functionByLevel;  
    }

    getHighlightsByLevel(level: LevelType): boolean[] {
        throw Error("The heatmap layer has no highlight attributes");
    }

}