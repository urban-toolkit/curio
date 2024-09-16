import { v4 as uuid } from "uuid";
import { AccessLevelType, BoxType} from "../constants";

export async function GetTemplates(){
    const response = await fetch('http://localhost:5002/getTemplates');
    const data = await response.json();
    
    return data
}

export const templates = [
//     {
//         id: uuid(),
//         type: BoxType.DATA_LOADING, 
//         name: "Parks (OSM)", 
//         description: "Load parks for Chicago using OSM", 
//         accessLevel: AccessLevelType.ANY, 
// code: "import utk \n\
// uc = utk.OSM.load([!! bbox$INPUT_LIST_VALUE$[41.88043474773062,-87.62760230820301,41.89666220782541,-87.59872148227429] !!], layers=[[!! layer$SELECTION$parks$parks;water !!]]) \n\
// gdf = uc.layers['gdf']['objects'][0] \n\
// gdf.metadata = {'name': [!! layer$SELECTION$parks$parks;water !!]} \n\
// return gdf",
//         custom: false
//     }

]

// [41.88043474773062, -87.62760230820301, 41.89666220782541, -87.59872148227429], layers=['parks']
// layers=[!! layers$INPUT_LIST_TEXT$[\"parks\"] !!]
// [!! layer$INPUT_TEXT$parks !!]