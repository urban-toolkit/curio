import { OperationType, LevelType, RenderStyle } from "./constants";
import { ILayerData, ILayerFeature, IKnot, IExKnot } from "./interfaces";
import { Layer } from "./layer";
import { ShaderFlatColor } from "./shader-flatColor";
import { Shader } from "./shader";
import { AuxiliaryShader } from "./auxiliaryShader";
import { ShaderFlatColorMap } from "./shader-flatColorMap";
import { ShaderSmoothColor } from "./shader-smoothColor";
import { ShaderSmoothColorMap } from "./shader-smoothColorMap";
import { ShaderSmoothColorMapTex } from "./shader-smoothColorMapTex";
import { ShaderPicking } from "./shader-picking";
import { ShaderPickingTriangles } from "./shader-picking-triangles";
import { ShaderAbstractSurface } from "./shader-abstractSurface";
import { ShaderPickingPoints } from "./shader-picking-points";
import { AuxiliaryShaderTriangles } from "./auxiliaryShaderTriangles";
import { ShaderFlatColorPointsMap } from "./shader-flatColorPointsMap";

export class PointsLayer extends Layer {

    // protected _zOrder: number;
    protected _coordsByCOORDINATES3D: number[][] = [];
    protected _dimensions: number;
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

        this.updateMeshGeometry(geometryData);

        this._dimensions = 3;
        // this._zOrder = zOrder;

    }

    supportInteraction(eventName: string): boolean {
        return true;
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
    
    getSelectedFiltering(): number[] | null {
        throw Error("Filtering not supported for point layer");
    }

    directAddMeshFunction(functionValues: number[][], knotId: string): void{
        let distributedValues = this.distributeFunctionValues(functionValues);

        this._mesh.loadFunctionData(distributedValues, knotId);
    }

    updateFunction(knot: IKnot | IExKnot, shaders: (Shader|AuxiliaryShader)[]): void {
        // updates the shader references
        for (const shader of shaders) {
            shader.updateShaderData(this._mesh, knot);
        }
    }

    render(glContext: WebGL2RenderingContext, shaders: (Shader|AuxiliaryShader)[]): void {

        for (const shader of shaders){
            if(shader instanceof ShaderFlatColor){
                throw Error("FLAT_COLOR not supported for point cloud layer");
            }

            if(shader instanceof ShaderFlatColorMap){
                throw Error("FLAT_COLOR_MAP not supported for point cloud layer");
            }

            if(shader instanceof ShaderSmoothColor){
                throw Error("SMOOTH_COLOR not supported for point cloud layer");
            }

            if(shader instanceof ShaderSmoothColorMap){
                throw Error("SMOOTH_COLOR_MAP not supported for point cloud layer");
            }

            if(shader instanceof ShaderSmoothColorMapTex){
                throw Error("SMOOTH_COLOR_MAP_TEX not supported for point cloud layer");
            }

            if(shader instanceof ShaderAbstractSurface){
                throw Error("ABSTRACT_SURFACES not supported for point cloud layer");
            }
        }

        // enables the depth test
        glContext.enable(glContext.DEPTH_TEST);
        glContext.depthFunc(glContext.LEQUAL);

        // enable culling
        glContext.frontFace(glContext.CCW);
        glContext.enable(glContext.CULL_FACE);
        glContext.cullFace(glContext.BACK);

        // enables stencil
        // glContext.enable(glContext.STENCIL_TEST);

        // the abs surfaces are loaded first to update the stencil
        for (const shader of shaders) {
            if(shader instanceof ShaderPickingPoints){
                shader.renderPass(glContext, glContext.POINTS, this._camera, this._mesh, -1);
            }
        }

        for (const shader of shaders) {
            if(!(shader instanceof ShaderPickingPoints)){
                shader.renderPass(glContext, glContext.POINTS, this._camera, this._mesh, -1);
            }
        }


        // disables stencil
        // glContext.disable(glContext.STENCIL_TEST);

        // disables the depth test
        glContext.disable(glContext.DEPTH_TEST);
        // disables culling
        glContext.disable(glContext.CULL_FACE);
    }

    setHighlightElements(elements: number[], level: LevelType, value: boolean, shaders: (Shader|AuxiliaryShader)[], centroid:number[] | Float32Array = [0,0,0], viewId: number): void {
        if(elements[0] == undefined)
            return;

        let coords = this.getCoordsByLevel(level, centroid, viewId);
        
        for(let i = 0; i < elements.length; i++){
            let offsetCoords = 0;
            let coordsIndex = [];
            let elementIndex = elements[i];

            for(let j = 0; j < elementIndex; j++){
                offsetCoords += (coords[j].length)/this._dimensions;
            }

            for(let k = 0; k < (coords[elementIndex].length)/this._dimensions; k++){
                coordsIndex.push(offsetCoords+k);
            }

            for(const shader of shaders){
                if(shader instanceof ShaderPickingPoints){
                    shader.setHighlightElements(coordsIndex, value);
                }
            }

        }
    }

    highlightElement(glContext: WebGL2RenderingContext, x: number, y: number, shaders: (Shader|AuxiliaryShader)[]){
        if(!glContext.canvas || !(glContext.canvas instanceof HTMLCanvasElement)){
            return;
        }

        let pixelX = x * glContext.canvas.width / glContext.canvas.clientWidth;
        let pixelY = glContext.canvas.height - y * glContext.canvas.height / glContext.canvas.clientHeight - 1;

        for(const shader of shaders){
            if(shader instanceof ShaderPickingPoints){
                shader.updatePickObjectPosition(pixelX, pixelY);
            }
        }
    }

    getIdLastHighlightedElement(shaders: (Shader|AuxiliaryShaderTriangles)[]){
        for(const shader of shaders){
            if(shader instanceof ShaderFlatColorPointsMap){
                let picked = shader.currentPickedElement;
                shader.currentPickedElement = [];
                return picked;
            }
        }
    }

    highlightElementsInArea(glContext: WebGL2RenderingContext, x: number, y: number, shaders: (Shader|AuxiliaryShader)[], radius: number){
        if(!glContext.canvas || !(glContext.canvas instanceof HTMLCanvasElement)){
            return;
        }

        let pixelX = x * glContext.canvas.width / glContext.canvas.clientWidth;
        let pixelY = glContext.canvas.height - y * glContext.canvas.height / glContext.canvas.clientHeight - 1;

        for(const shader of shaders){
            if(shader instanceof ShaderPickingPoints){
                shader.updatePickObjectArea(pixelX, pixelY, radius);
            }
        }
    }

    distributeFunctionValues(functionValues: number[][] | null): number[][] | null{
        return functionValues;
    }
    innerAggFunc(functionValues: number[] | null, startLevel: LevelType, endLevel: LevelType, operation: OperationType): number[] | null {
        throw new Error("Method not implemented.");
    }
    getFunctionValueIndexOfId(id: number, level: LevelType): number | null {
        throw new Error("Method not implemented.");
    }
    getCoordsByLevel(level: LevelType, centroid:number[] | Float32Array = [0,0,0], viewId: number): number[][] {
        let coordByLevel: number[][] = [];

        if(level == LevelType.COORDINATES){
            throw Error("Cannot get COORDINATES attached to the layer because it does not have a 2D representation");            
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

        if(level == LevelType.OBJECTS){
            throw Error("Cannot get OBJECTS attached to the layer because it does not have a 2D representation");            
        }

        return coordByLevel;
    }
    getFunctionByLevel(level: LevelType, knotId: string): number[][][] {
        let functionByLevel: number[][][] = [];

        if(level == LevelType.COORDINATES){
            throw Error("Cannot get abstract information attached to COORDINATES because the layer does not have a 2D representation");            
        }

        if(level == LevelType.COORDINATES3D || level == LevelType.OBJECTS){

            let functions = this._mesh.getFunctionVBO(knotId)

            for(let i = 0; i < functions[0].length; i++){ // for each object 
                functionByLevel.push([[]]);

                for(let k = 0; k < functions.length; k++){ // for each timestep
                    functionByLevel[functionByLevel.length-1][0].push(functions[k][i]) // there is only one coordinate in each object
                }
            }
        }

        // if(level == LevelType.OBJECTS){
        //     // throw Error("Cannot get abstract information attached to OBJECTS because the layer does not have a 2D representation");            
        // }

        return functionByLevel;  
    }

    getHighlightsByLevel(level: LevelType): boolean[] {
        let booleanHighlights: boolean[] = [];
        let highlightsByLevel: boolean[][] = [];

        let totalNumberOfCoords = this._mesh.getTotalNumberOfCoords();

        for(let i = 0; i < totalNumberOfCoords; i++){
            booleanHighlights.push(false);
        }

        if(level == LevelType.COORDINATES){
            if(this._dimensions != 2){
                throw Error("Cannot get highlight information related to COORDINATES because the layer does not have a 2D representation");            
            }

            if(this._highlightByCOORDINATES.length == 0){
                highlightsByLevel = booleanHighlights.map(x => [x])

                this._highlightByCOORDINATES = highlightsByLevel;
            }else{
                highlightsByLevel = this._highlightByCOORDINATES;
            }

        }

        if(level == LevelType.COORDINATES3D){
            if(this._dimensions != 3){
                throw Error("Cannot get highlight information related to COORDINATES3D because the layer does not have a 3D representation");            
            }

            if(this._highlightByCOORDINATES3D.length == 0){
                highlightsByLevel = booleanHighlights.map(x => [x])

                this._highlightByCOORDINATES3D = highlightsByLevel;
            }else{
                highlightsByLevel = this._highlightByCOORDINATES3D;
            }

        }

        if(level == LevelType.OBJECTS){
            if(this._highlightByOBJECTS.length == 0){
                let readHighlights = 0;
                
                let coordsPerComp = this._mesh.getCoordsPerComp();

                for(const numCoords of coordsPerComp){
                    let groupedHighlights = [];
    
                    for(let i = 0; i < numCoords; i++){
                        groupedHighlights.push(booleanHighlights[i+readHighlights]);
                    }
    
                    readHighlights += numCoords;
                    highlightsByLevel.push(groupedHighlights);
                }

                this._highlightByOBJECTS = highlightsByLevel;
            }else{
                highlightsByLevel = this._highlightByOBJECTS;
            }

        }

        let flattenedHighlights: boolean[] = [];

        // flattening the highlight data
        for(const elemHighlights of highlightsByLevel){
            let allHighlighted = true;

            for(const value of elemHighlights){
                if(!value){
                    allHighlighted = false;
                }
            }

            if(allHighlighted) // all the coordinates of the element must be highlighted for it to be considered highlighted
                flattenedHighlights.push(true)
            else
                flattenedHighlights.push(false)

        }

        return flattenedHighlights;
    }

    // getHighlightsByLevel(level: LevelType): boolean[] {

    //     let booleanHighlights: boolean[] = [];
    //     let highlightsByLevel: boolean[][] = [];

    //     let totalNumberOfCoords = this._mesh.getTotalNumberOfCoords();

    //     for(let i = 0; i < totalNumberOfCoords; i++){
    //         booleanHighlights.push(false);
    //     }

    //     if(level == LevelType.OBJECTS){
    //         throw new Error("There is not highlight for OBJECTS in a points layer");
    //     }

    //     if(level == LevelType.COORDINATES){
    //         if(this._highlightByCOORDINATES.length == 0){
    //             highlightsByLevel = booleanHighlights.map(x => [x])

    //             this._highlightByCOORDINATES = highlightsByLevel;
    //         }else{
    //             highlightsByLevel = this._highlightByCOORDINATES;
    //         }

    //     }

    //     if(level == LevelType.COORDINATES3D){

    //         if(this._highlightByCOORDINATES3D.length == 0){
    //             highlightsByLevel = booleanHighlights.map(x => [x])

    //             this._highlightByCOORDINATES3D = highlightsByLevel;
    //         }else{
    //             highlightsByLevel = this._highlightByCOORDINATES3D;
    //         }

    //     }

    //     let flattenedHighlights: boolean[] = [];

    //     // flattening the highlight data
    //     for(const elemHighlights of highlightsByLevel){
    //         let allHighlighted = true;

    //         for(const value of elemHighlights){
    //             if(!value){
    //                 allHighlighted = false;
    //             }
    //         }

    //         if(allHighlighted) // all the coordinates of the element must be highlighted for it to be considered highlighted
    //             flattenedHighlights.push(true)
    //         else
    //             flattenedHighlights.push(false)

    //     }

    //     return flattenedHighlights;
    // }
}