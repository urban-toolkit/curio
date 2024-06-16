# urban-workflows

Every python code must have a final return with the data to be exported.  

"userCode" is a reserved keyword.  
"arg" is a reserved keyword.  

Supported return types:  
- int
- str
- float
- boolean
- list
- dict
- Dataframes
- GeoDataFrames

Tuples are reserved for multiple outputs  

- Every gdf for UTK must have a metadata attribute with a field name to name the physical layer
- gdf.metadata = {'name': 'water'}
- callback for interactions will receive interacted mapping per coordinate and coordinates per component.
- If datapools need to be linked to propagate interactions. There needs to be a column "linked" that contains arrays that point to the elements (indices) of the other pool
- The interaction resolution of the UTK box is used to determine what constitutes a selection. 
    - PICKING: all coordinates of the object need to be selected for the object to be considered selected
    - BRUSHING: at least one coordinate of the object need to be selected for the object to be considered selected
- Since UTK is the only visualization that can handle multiple "outputs" it is the only one that can have multiple in/out connections with data pools.
- The effects of interactions are automatic for UTK but not for Vega. Users have to program the effects on the plots.
- Interaction edges are only used to send interactions. All interactions are received through input
- for a geojson be interpreter as storing buildings data one of its columns has to be named "building_id"
- Generic triangle layers have to be on the 3395 projection but buildings on the 4326 projection. Surface also need to be in 3395 projection. 
- Images need to inside geodataframes with image_id and image_content columns. image_content needs to be byte code enconded in a byte64 string
- Some boxes have hot reload like Data Pool and Vis Image but other require running the code.
- Support to two of most important types: raster (rasterio) and vector (geopandas)
- What get passed by to each box in the case of raster data is the rasterio.io.DatasetReader. So if you want to send raster data from one box to the other you have to write to a file, read it and send the reader.
- Surface is just a polygon representing a bounding box. Surface needs to have a surface_id to be detected as surface.