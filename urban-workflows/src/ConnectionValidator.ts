import { BoxType, SupportedType } from "./constants";

export class ConnectionValidator {

    static _inputTypesSupported: any = {
        [BoxType.DATA_LOADING]: [],
        [BoxType.DATA_EXPORT]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.DATA_CLEANING]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.DATA_TRANSFORMATION]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.COMPUTATION_ANALYSIS]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
        [BoxType.FLOW_SWITCH]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
        [BoxType.VIS_UTK]: [SupportedType.GEODATAFRAME],
        [BoxType.VIS_VEGA]: [SupportedType.DATAFRAME],
        [BoxType.VIS_TABLE]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME],
        [BoxType.VIS_TEXT]: [SupportedType.VALUE],
        [BoxType.VIS_IMAGE]: [SupportedType.DATAFRAME],
        [BoxType.CONSTANTS]: [],
        [BoxType.DATA_POOL]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME],
        [BoxType.MERGE_FLOW]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
    };
    static _outputTypesSupported: any = {
        [BoxType.DATA_LOADING]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.DATA_EXPORT]: [],
        [BoxType.DATA_CLEANING]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.DATA_TRANSFORMATION]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.RASTER],
        [BoxType.COMPUTATION_ANALYSIS]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
        [BoxType.FLOW_SWITCH]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
        [BoxType.VIS_UTK]: [SupportedType.GEODATAFRAME],
        [BoxType.VIS_VEGA]: [SupportedType.DATAFRAME],
        [BoxType.VIS_TABLE]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME],
        [BoxType.VIS_TEXT]: [SupportedType.VALUE],
        [BoxType.VIS_IMAGE]: [SupportedType.DATAFRAME],
        [BoxType.CONSTANTS]: [SupportedType.VALUE],
        [BoxType.DATA_POOL]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME],
        [BoxType.MERGE_FLOW]: [SupportedType.DATAFRAME, SupportedType.GEODATAFRAME, SupportedType.VALUE, SupportedType.LIST, SupportedType.JSON, SupportedType.RASTER],
    };
    
    static checkBoxCompatibility(outBox: BoxType | undefined, inBox: BoxType | undefined){
        if(outBox == undefined || inBox == undefined)
            return false

        let intersection = ConnectionValidator._inputTypesSupported[inBox].filter((value: any) => {return ConnectionValidator._outputTypesSupported[outBox].includes(value)});

        return intersection.length > 0
    }

}
