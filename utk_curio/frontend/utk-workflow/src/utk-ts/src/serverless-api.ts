import { ILayerData, IMapGrammar, IPlotGrammar, IJoinedJson, IExternalJoinedJson, IMasterGrammar, IMapStyle, ICameraData, ILayerFeature } from './interfaces';

export class ServerlessApi {

    public mapData: IMasterGrammar | IMapGrammar | IPlotGrammar | null = null;
    public mapStyle: IMapStyle | null = null;
    public carameraParameters: ICameraData | null = null;
    public layers: ILayerData[] | null = null;
    public layersFeature: ILayerFeature[] | null = null;
    public joinedJsons: IJoinedJson[] | IExternalJoinedJson[] | null = null;
    public components: {id: string, json: IMapGrammar | IPlotGrammar}[] | null = null;

    public interactionCallbacks: any = {}; // {[knotId] -> callback} 

    public async setComponents(components: {id: string, json: IMapGrammar | IPlotGrammar}[]){
        this.components = components;
    }

    public async setLayers(layers: ILayerData[]){
        this.layers = layers;
    }

    public async setJoinedJsons(joinedJsons: IJoinedJson[] | IExternalJoinedJson[]){
        this.joinedJsons = joinedJsons;
    }

    public addInteractionCallback = (knotId: string, callback: any) => {
        if(this.interactionCallbacks[knotId] == undefined){
            this.interactionCallbacks[knotId] = {}
        }
    
        this.interactionCallbacks[knotId] = callback;
    }
}
