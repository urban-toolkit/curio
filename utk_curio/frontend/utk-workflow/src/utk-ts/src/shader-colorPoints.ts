import { Shader } from "./shader";
import { Mesh } from "./mesh";

import { ColorMap } from "./colormap";

// @ts-ignore
import vsColorPoints from './shaders/colorPoints.vs';
// @ts-ignore
import fsColorPoints from './shaders/colorPoints.fs';

import { IExKnot, IKnot } from "./interfaces";

import * as d3_scale from 'd3-scale';

const d3 = require('d3');

export class ShaderColorPoints extends Shader {

    // Data to be rendered
    protected _coords:  number[] = [];
    protected _function: number[][] = [];
    protected _currentTimestepFunction: number = 0;

    // Color map definition
    private _colorMap: string | null = null;
    private _range: number[];
    private _domain: number[];
    private _providedDomain: number[];
    private _scale: string;

    // Global color used on the layer
    // protected _globalColor: number[] = [];

    // Data loaction on GPU
    protected _glCoords:  WebGLBuffer | null = null;
    protected _glFunction: WebGLBuffer | null = null;

    // Data has chaged
    protected _coordsDirty: boolean = false;
    protected _functionDirty: boolean = false;
    protected _colorMapDirty: boolean = false;

    // Id of each property in the VAO
    protected _coordsId = -1;
    protected _functionId = -1;

    // Uniforms location
    protected _uModelViewMatrix: WebGLUniformLocation | null = null;
    protected _uProjectionMatrix: WebGLUniformLocation | null = null;
    protected _uWorldOrigin: WebGLUniformLocation | null = null;
    // protected _uGlobalColor: WebGLUniformLocation | null = null;
    protected _uColorMap: WebGLUniformLocation | null = null;

    // Color map texture
    protected _texColorMap: WebGLTexture | null;

    constructor(glContext: WebGL2RenderingContext, grammarInterpreter: any, colorMap: string = "interpolateReds", range: number[] = [0, 1], domain: number[] = [], scale: string = "scaleLinear") {
        super(vsColorPoints, fsColorPoints, glContext, grammarInterpreter);
        // saves the layer color
        // this._globalColor = color;

        // saves the layer color
        this._colorMap = colorMap;
        this._range = range;
        this._domain = domain;
        this._providedDomain = domain;
        this._scale = scale;

        // creathe dhe shader variables
        this.createUniforms(glContext);
        this.createVertexArrayObject(glContext);
        this.createTextures(glContext);
    }

    public updateShaderGeometry(mesh: Mesh, centroid:number[] | Float32Array = [0,0,0], viewId: number) {
        this._coordsDirty = true;
        this._coords = mesh.getCoordinatesVBO(centroid, viewId);
    }

    public normalizeFunction(mesh: Mesh, knot: IKnot | IExKnot): void {
        this._function = mesh.getFunctionVBO(knot.id);
        this._functionDirty = true;

        if (this._providedDomain.length === 0) {
            this._domain = d3.extent(this._function[this._currentTimestepFunction]);
        }else{
            this._domain = this._providedDomain;
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
        // this._globalColor = <number[]> data;
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
        // this._uGlobalColor = glContext.getUniformLocation(this._shaderProgram, 'uGlobalColor');
    }

    public bindUniforms(glContext: WebGL2RenderingContext, camera: any): void {
        if (!this._shaderProgram) {
            return;
        }

        glContext.uniformMatrix4fv(this._uModelViewMatrix, false, camera.getModelViewMatrix());
        glContext.uniformMatrix4fv(this._uProjectionMatrix, false, camera.getProjectionMatrix());
        glContext.uniform2fv(this._uWorldOrigin, camera.getWorldOrigin());
        // glContext.uniform3fv(this._uGlobalColor, this._globalColor);
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

        // Creates the coords id.
        this._functionId = glContext.getAttribLocation(this._shaderProgram, 'funcValues');
        // Creates the function id
        this._glFunction = glContext.createBuffer();

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
    }

    public setFiltered(filtered: number[]){ 
    }

    public setHighlightElements(coordinates: number[], value: boolean): void {
        throw Error("Method not implemented yet");
    }

    public renderPass(glContext: WebGL2RenderingContext, glPrimitive: number, camera: any, mesh: Mesh, zOrder: number): void {
        if (!this._shaderProgram) {
            return;
        }

        glContext.useProgram(this._shaderProgram);

        this.bindUniforms(glContext, camera);
        this.bindVertexArrayObject(glContext, mesh);

        // glContext.drawElements(glPrimitive, this._coords.length/3, glContext.UNSIGNED_INT, 0);
        glContext.drawArrays(glPrimitive, 0, this._coords.length/3);

    }
}