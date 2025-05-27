import { Environment } from './environment';
import { DataLoader } from './data-loader';

import { ICameraData, ILayerFeature, ILayerData, IMapStyle, IMasterGrammar, IMapGrammar, IPlotGrammar, IJoinedJson, IExternalJoinedJson } from './interfaces';
import { ServerlessApi } from './serverless-api';

export abstract class DataApi {

    /**
     * Load all layers
     * @param {string} index The layers index file
     */
    static async getMapData(index: string, serverlessApi: ServerlessApi): Promise<IMasterGrammar | IMapGrammar | IPlotGrammar> {

        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${index}`;

            const datasets = await DataLoader.getJsonData(url);
            return <IMasterGrammar | IMapGrammar | IPlotGrammar>datasets;

        } else {
            if (serverlessApi.mapData == null) {
                throw new Error("map data needs to be set before calling getMapData");
            } else {
                return serverlessApi.mapData;
            }
        }
    }

    /**
     * @param {string} componentId The id of the component
     */
    static async getComponentData(componentId: string, serverlessApi: ServerlessApi): Promise<IMapGrammar | IPlotGrammar> {
        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${componentId}.json`;
            let component_grammar = <IMapGrammar | IPlotGrammar> await DataLoader.getJsonData(url);
            return component_grammar
        } else {
            if (serverlessApi.components == null) {
                throw new Error("components needs to be set before calling getComponentData");
            } else {
                for (const component of serverlessApi.components) {
                    if(component.id == componentId){
                        return component.json;
                    }
                }
                throw new Error("component "+componentId+" not found");
            }
        }
    }

    /**
     * Load a custom style
     * @param {string} style The style file
     */
    static async getCustomStyle(style: string, serverlessApi: ServerlessApi): Promise<IMapStyle> {
        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${style}.json`;

            const custom = <IMapStyle>await DataLoader.getJsonData(url);
            return <IMapStyle>custom;
        } else {
            if (serverlessApi.mapStyle == null) {
                throw new Error("map style needs to be set before calling getCustomStyle");
            } else {
                return serverlessApi.mapStyle;
            }
        }
    }

    /**
     * Load the camera
     * @param {string} camera The camera file
     */
    static async getCameraParameters(camera: string, serverlessApi: ServerlessApi): Promise<ICameraData> {
        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${camera}.json`;

            const params = <ICameraData>await DataLoader.getJsonData(url);
            return params;
        } else {
            if (serverlessApi.carameraParameters == null) {
                throw new Error("camera parameter needs to be set before calling getCameraParameters");
            } else {
                return serverlessApi.carameraParameters;
            }
        }
    }

    /**
     * Gets the layer data
     * @param {string} layerId the layer data
     */
    static async getLayer(layerId: string, serverlessApi: ServerlessApi): Promise<ILayerData> {

        if (!Environment.serverless) {
            const url_base = `${Environment.backend}/files/${layerId}.json`;
            const url_coordinates = `${Environment.backend}/files/${layerId}_coordinates.data`;
            const url_indices = `${Environment.backend}/files/${layerId}_indices.data`;
            const url_normals = `${Environment.backend}/files/${layerId}_normals.data`;
            const url_ids = `${Environment.backend}/files/${layerId}_ids.data`;

            const base_feature = <ILayerData>await DataLoader.getJsonData(url_base);

            let coordinates;
            let indices;
            let normals;
            let ids;

            if (base_feature.data != undefined) {

                if (base_feature.data[0].geometry.coordinates != undefined) {
                    console.log(url_coordinates);
                    coordinates = <Float64Array>await DataLoader.getBinaryData(url_coordinates, 'd');
                }

                if (base_feature.data[0].geometry.indices != undefined) {
                    console.log(url_indices);
                    indices = <Uint32Array>await DataLoader.getBinaryData(url_indices, 'I');
                }

                if (base_feature.data[0].geometry.normals != undefined) {
                    console.log(url_normals);
                    normals = <Float32Array>await DataLoader.getBinaryData(url_normals, 'f');
                }

                if (base_feature.data[0].geometry.ids != undefined) {
                    console.log(url_ids);
                    ids = <Uint32Array>await DataLoader.getBinaryData(url_ids, 'I');
                }

                for (let i = 0; i < base_feature.data.length; i++) {

                    if (coordinates != undefined) {
                        let startAndSize = base_feature.data[i].geometry.coordinates;
                        base_feature.data[i].geometry.coordinates = Array.from(coordinates.slice(startAndSize[0], startAndSize[0] + startAndSize[1]));
                    }

                    if (indices != undefined) {
                        let startAndSize = <number[]>base_feature.data[i].geometry.indices;
                        base_feature.data[i].geometry.indices = Array.from(indices.slice(startAndSize[0], startAndSize[0] + startAndSize[1]));
                    }

                    if (normals != undefined) {
                        let startAndSize = <number[]>base_feature.data[i].geometry.normals;
                        base_feature.data[i].geometry.normals = Array.from(normals.slice(startAndSize[0], startAndSize[0] + startAndSize[1]));
                    }

                    if (ids != undefined) {
                        let startAndSize = <number[]>base_feature.data[i].geometry.ids;
                        base_feature.data[i].geometry.ids = Array.from(ids.slice(startAndSize[0], startAndSize[0] + startAndSize[1]));
                    }

                }

            }

            return base_feature;
        } else {
            if (serverlessApi.layers == null) {
                throw new Error("layers needs to be set before calling getLayer");
            } else {
                for (const layer of serverlessApi.layers) {
                    if(layer.id == layerId){
                        return layer;
                    }
                }

                throw new Error("layer "+layerId+" not found");
            }
        }
    }


    /**
     * Gets the layer data
     * @param {string} layerId the layer data
     */
    static async getLayerFeature(layerId: string, serverlessApi: ServerlessApi): Promise<ILayerFeature[]> {
        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${layerId}.json`;

            const feature = <ILayerFeature[]>await DataLoader.getJsonData(url);
            return feature;
        }else{
            if (serverlessApi.layersFeature == null) {
                throw new Error("layersFeature needs to be set before calling getLayerFeature");
            } else {
                return serverlessApi.layersFeature;
            }
        }
    }

    // /**
    //  * Gets the layer function
    //  * @param {string} layerId the layer data
    //  */
    // static async getLayerFunction(layerId: string): Promise<ILayerFeature[]> {
    //     // TODO
    //     const url = `${Environment.backend}/files/${layerId}.json`;

    //     const feature = <ILayerFeature[]>await DataLoader.getJsonData(url);
    //     return feature;
    // }

    // /**
    //  * Gets the layer function
    //  * @param {string} layerId the layer data
    //  */
    // static async getLayerHighlight(layerId: string): Promise<ILayerFeature[]> {
    //     // TODO
    //     const url = `${Environment.backend}/files/${layerId}.json`;

    //     const feature = <ILayerFeature[]>await DataLoader.getJsonData(url);
    //     return feature;
    // }

    static async getJoinedJson(layerId: string, serverlessApi: ServerlessApi) {
        if (!Environment.serverless) {
            const url = `${Environment.backend}/files/${layerId + "_joined"}.json`;

            const joinedJson = <IJoinedJson>await DataLoader.getJsonData(url);
            return joinedJson;
        } else {
            if (serverlessApi.joinedJsons == null) {
                throw new Error("joinedJsons needs to be set before calling getJoinedJson");
            } else {
                for (const joinedJson of <IExternalJoinedJson[]>serverlessApi.joinedJsons) {
                    if(joinedJson.id == layerId){
                        return joinedJson;
                    }
                }
                throw new Error("joinedJson "+layerId+" not found");
            }
        }
    }

}
