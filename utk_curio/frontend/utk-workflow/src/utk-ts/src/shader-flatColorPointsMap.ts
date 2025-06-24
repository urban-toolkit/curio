import { Shader } from "./shader";
import { Mesh } from "./mesh";
import { AuxiliaryShaderTriangles } from "./auxiliaryShaderTriangles";

import { ColorMap } from "./colormap";

// @ts-ignore
import vsFlatColorMap from './shaders/flatColorPointsMap.vs';
// @ts-ignore
import fsFlatColorMap from './shaders/flatColorPointsMap.fs';

import { IExKnot, IKnot } from "./interfaces";

import * as d3_scale from 'd3-scale';
import { Environment } from "./environment";

const d3 = require('d3');

export class ShaderFlatColorPointsMap extends AuxiliaryShaderTriangles {
    // Data to be rendered
    protected _coords:  number[] = [];
    protected _function: number[][] = [];
    protected _currentTimestepFunction: number = 0;
    protected _coordsPerComp: number[] = [];

    // TODO decide which function to use
    protected _functionToUse: number = 0;

    // Color map definition
    private _colorMap: string | null = null;
    private _range: number[];
    private _domain: number[];
    private _providedDomain: number[];
    private _scale: string;

    // Data location on GPU
    protected _glCoords:  WebGLBuffer | null = null;
    protected _glFunction: WebGLBuffer | null = null;
    protected _glIndices: WebGLBuffer | null = null;
    protected _glFiltered: WebGLBuffer | null = null;
    protected _glColorOrPicked: WebGLBuffer | null = null;

    // Data has changed
    protected _coordsDirty: boolean = false;
    protected _functionDirty: boolean = false;
    protected _colorMapDirty: boolean = false;
    protected _filteredDirty: boolean = false;
    protected _colorOrPickedDirty: boolean = false;

    // Id of each property in the VAO
    protected _coordsId = -1;
    protected _functionId = -1;
    protected _filteredId = -1;
    protected _colorOrPickedId = -1;

    // Uniforms location
    protected _uModelViewMatrix: WebGLUniformLocation | null = null;
    protected _uProjectionMatrix: WebGLUniformLocation | null = null;
    protected _uWorldOrigin: WebGLUniformLocation | null = null;
    protected _uColorMap: WebGLUniformLocation | null = null;

    protected _currentPickedElement: number[]; // stores the indices of the currently picked elements
    protected _colorOrPicked: number[] = [];

    protected _filtered: number[] = [];

    // Color map texture
    protected _texColorMap: WebGLTexture | null;

    constructor(glContext: WebGL2RenderingContext, grammarInterpreter: any, colorMap: string = "interpolateReds", range: number[] = [0, 1], domain: number[] = [], scale: string = "scaleLinear") {
        super(vsFlatColorMap, fsFlatColorMap, glContext, grammarInterpreter);

        // Saves the layer color
        this._colorMap = colorMap;
        this._range = range;
        this._domain = domain;
        this._providedDomain = domain;
        this._scale = scale;

        // Create the shader variables    
        this.createUniforms(glContext);
        this.createVertexArrayObject(glContext);
        this.createTextures(glContext);
    }

    get currentPickedElement(): number[]{
        return this._currentPickedElement;
    }

    set currentPickedElement(currentPickedElement: number[]){
        this._currentPickedElement = currentPickedElement;
    }

    public updateShaderGeometry(mesh: Mesh, centroid:number[] | Float32Array = [0,0,0], viewId: number) {
        this._coordsDirty = true;
        this._filteredDirty = true;
        this._coords = mesh.getCoordinatesVBO(centroid, viewId);

        this._coordsPerComp = mesh.getCoordsPerComp();

        let totalNumberOfCoords = mesh.getTotalNumberOfCoords();

        for(let i = 0; i < totalNumberOfCoords; i++){
            this._colorOrPicked.push(0.0);
            this._filtered.push(1.0); // 1 true to include
        }
    }

    public normalizeFunction(mesh: Mesh, knot: IKnot | IExKnot): void{
        this._function = mesh.getFunctionVBO(knot.id);
        this._currentKnot = knot;
        this._functionDirty = true;
        this._colorOrPickedDirty = true;
        
        let maxFuncValue = null;
        let minFuncValue = null;

        for(let i = 0; i < this._function[this._currentTimestepFunction].length; i++){

            let value = this._function[this._currentTimestepFunction][i];

            // get param for min max normalization only for filtered elements
            if(this._filtered.length == 0 || this._filtered[i] == 1){
                if(maxFuncValue == null){
                    maxFuncValue = value;
                }else if(value > maxFuncValue){
                    maxFuncValue = value;
                }
    
                if(minFuncValue == null){
                    minFuncValue = value;
                }else if(value < minFuncValue){
                    minFuncValue = value;
                }
            }

        }
        
        if (this._providedDomain.length === 0) {
            this._domain = d3.extent(this._function[this._currentTimestepFunction])
        }

        // @ts-ignore
        let scale = d3_scale[this._scale]().domain(this._domain).range(this._range);

        for(let i = 0; i < this._function[this._currentTimestepFunction].length; i++){
            this._function[this._currentTimestepFunction][i] = scale(this._function[this._currentTimestepFunction][i]);
        }

    }

    public updateShaderData(mesh: Mesh, knot: IKnot | IExKnot, currentTimestepFunction: number = 0): void {
        this._currentTimestepFunction = currentTimestepFunction;
        this.normalizeFunction(mesh, knot);
    }

    public updateShaderUniforms(data: any) {
        this._colorMapDirty = true;
        this._colorMap = <string> data;
    }

    public createUniforms(glContext: WebGL2RenderingContext): void {
        if (!this._shaderProgram) {
            return;
        }

        this._uModelViewMatrix = glContext.getUniformLocation(this._shaderProgram, 'uModelViewMatrix');
        this._uProjectionMatrix = glContext.getUniformLocation(this._shaderProgram, 'uProjectionMatrix');
        this._uWorldOrigin = glContext.getUniformLocation(this._shaderProgram, 'uWorldOrigin');
    }

    public bindUniforms(glContext: WebGL2RenderingContext, camera: any): void {
        if (!this._shaderProgram) {
            return;
        }

        glContext.uniformMatrix4fv(this._uModelViewMatrix, false, camera.getModelViewMatrix());
        glContext.uniformMatrix4fv(this._uProjectionMatrix, false, camera.getProjectionMatrix());
        glContext.uniform2fv(this._uWorldOrigin, camera.getWorldOrigin());
    }

    public setFiltered(filtered: number[]){ 
        if(filtered.length == 0){
            this._filtered = Array(this._filtered.length).fill(1.0);
        }else{
            this._filtered = filtered;
        }
        this._filteredDirty = true;
    }

    public createTextures(glContext: WebGL2RenderingContext): void {
        if (!this._colorMap) { return; }

        this._uColorMap = glContext.getUniformLocation(this._shaderProgram, 'uColorMap');

        this._texColorMap = glContext.createTexture();
        glContext.bindTexture(glContext.TEXTURE_2D, this._texColorMap);

        // Set the parameters so we can render any size image.
        glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_S, glContext.CLAMP_TO_EDGE);
        glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_WRAP_T, glContext.CLAMP_TO_EDGE);
        glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MIN_FILTER, glContext.NEAREST);
        glContext.texParameteri(glContext.TEXTURE_2D, glContext.TEXTURE_MAG_FILTER, glContext.NEAREST);
     
        // Upload the image into the texture.
        const texData = ColorMap.getColorMap(this._colorMap);

        const size = [256, 1];
        glContext.texImage2D(glContext.TEXTURE_2D, 0, glContext.RGB32F, size[0], size[1], 0, glContext.RGB, glContext.FLOAT, new Float32Array(texData));
    }

    public bindTextures(glContext: WebGL2RenderingContext): void {
        // set which texture units to render with.
        glContext.uniform1i(this._uColorMap, 0);

        glContext.activeTexture(glContext.TEXTURE0);
        glContext.bindTexture(glContext.TEXTURE_2D, this._texColorMap);
    }

    public createVertexArrayObject(glContext: WebGL2RenderingContext): void {
        if (!this._shaderProgram) {
            return;
        }

        // Creates the coords id.
        this._coordsId = glContext.getAttribLocation(this._shaderProgram, 'vertCoords');
        // Create a buffer for the positions.
        this._glCoords = glContext.createBuffer();

        this._filteredId = glContext.getAttribLocation(this._shaderProgram, 'inFiltered');
        this._glFiltered = glContext.createBuffer();

        this._colorOrPickedId = glContext.getAttribLocation(this._shaderProgram, 'inColorOrPicked');
        this._glColorOrPicked = glContext.createBuffer();

        // Creates the coords id.
        this._functionId = glContext.getAttribLocation(this._shaderProgram, 'funcValues');
        // Creates the function id
        this._glFunction = glContext.createBuffer();

    }

    public setPickedObject(ids: number[]): void {
        
        this._currentPickedElement = ids;
        
        for(const objectId of ids){
            let readCoords = 0;
            for(let i = 0; i < this._coordsPerComp.length; i++){
                if(objectId == i){
                    break;
                }
    
                readCoords += this._coordsPerComp[i];
            }
    
            for(let i = 0; i < this._coordsPerComp[objectId]; i++){
                if(this._colorOrPicked[readCoords+i] == 1){
                    this._colorOrPicked[readCoords+i] = 0;
                }else if(this._colorOrPicked[readCoords+i] == 0){
                    this._colorOrPicked[readCoords+i] = 1;
                }
            }
        }

        this._colorOrPickedDirty = true;
    }

    public bindVertexArrayObject(glContext: WebGL2RenderingContext, mesh: Mesh): void {
        if (!this._shaderProgram) {
            return;
        }

        // binds the position buffer
        glContext.bindBuffer(glContext.ARRAY_BUFFER, this._glCoords);
        // send data to gpu
        if (this._coordsDirty) {
            glContext.bufferData(
                glContext.ARRAY_BUFFER, new Float32Array(this._coords), glContext.STATIC_DRAW
            );
        }

        // binds the VAO
        glContext.vertexAttribPointer(this._coordsId, mesh.dimension, glContext.FLOAT, false, 0, 0);
        glContext.enableVertexAttribArray(this._coordsId);

        glContext.bindBuffer(glContext.ARRAY_BUFFER, this._glFiltered);
        if (this._filteredDirty) {
            glContext.bufferData(
                glContext.ARRAY_BUFFER, new Float32Array(this._filtered), glContext.STATIC_DRAW
            );
        }

        glContext.vertexAttribPointer(this._filteredId, 1, glContext.FLOAT, false, 0, 0);
        glContext.enableVertexAttribArray(this._filteredId); 

        glContext.bindBuffer(glContext.ARRAY_BUFFER, this._glColorOrPicked);
        if (this._colorOrPickedDirty) {

            if(Environment.serverless)
                this.exportInteractions(this._colorOrPicked, this._coordsPerComp, this._currentKnot.id);

            glContext.bufferData(
                glContext.ARRAY_BUFFER, new Float32Array(this._colorOrPicked), glContext.STATIC_DRAW
            );
        }

        glContext.vertexAttribPointer(this._colorOrPickedId, 1, glContext.FLOAT, false, 0, 0);
        glContext.enableVertexAttribArray(this._colorOrPickedId); 

        // binds the position buffer
        glContext.bindBuffer(glContext.ARRAY_BUFFER, this._glFunction);
        // send data to gpu
        if (this._functionDirty) {
            glContext.bufferData(
                glContext.ARRAY_BUFFER, new Float32Array(this._function[this._currentTimestepFunction]), glContext.STATIC_DRAW
            );
        }

        glContext.vertexAttribPointer(this._functionId, 1, glContext.FLOAT, false, 0, 0);
        glContext.enableVertexAttribArray(this._functionId);     

        this._coordsDirty = false;
        this._functionDirty = false;
        this._colorOrPickedDirty = false;
        this._filteredDirty = false;
    }

    public overwriteSelectedElements(externalSelected: number[]){
        let startIndex = 0;

        for(let i = 0; i < externalSelected.length; i++){
            let nCoords = this._coordsPerComp[i];

            for(let j = startIndex; j < startIndex+nCoords; j++){
                this._colorOrPicked[j] = externalSelected[i];
            }

            startIndex += nCoords;
        }

        this._colorOrPickedDirty = true;
    }

    public setHighlightElements(coordinates: number[], value: boolean): void {
        for(const coordIndex of coordinates){
            if(value)
                this._colorOrPicked[coordIndex] = 1;
            else
                this._colorOrPicked[coordIndex] = 0;
        }

        this._colorOrPickedDirty = true;
    }

    public clearPicking(){

        for(let i = 0; i < this._colorOrPicked.length; i++){
            this._colorOrPicked[i] = 0;
        }

        this._colorOrPickedDirty = true;
    }

    public renderPass(glContext: WebGL2RenderingContext, glPrimitive: number, camera: any, mesh: Mesh, zOrder: number): void {
        if (!this._shaderProgram) {
            return;
        }

        glContext.useProgram(this._shaderProgram);

        // binds data
        this.bindUniforms(glContext, camera);

        // glContext.stencilFunc(
        //     glContext.GEQUAL,     // the test
        //     zOrder,            // reference value
        //     0xFF,         // mask
        // );

        // glContext.stencilOp(
        //     glContext.KEEP,     // what to do if the stencil test fails
        //     glContext.KEEP,     // what to do if the depth test fails
        //     glContext.REPLACE,     // what to do if both tests pass
        // );

        this.bindVertexArrayObject(glContext, mesh);
        this.bindTextures(glContext);

        // draw arrays
        glContext.drawArrays(glPrimitive, 0, this._coords.length/3);
    }
}
