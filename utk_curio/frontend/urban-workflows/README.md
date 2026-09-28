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

- callback for interactions will receive interacted mapping per coordinate and coordinates per component.
- If datapools need to be linked to propagate interactions. There needs to be a column "linked" that contains arrays that point to the elements (indices) of the other pool
- Interaction edges are only used to send interactions. All interactions are received through input
- for a geojson be interpreter as storing buildings data one of its columns has to be named "building_id"
- Generic triangle layers have to be on the 3395 projection but buildings on the 4326 projection. Surface also need to be in 3395 projection.
- Images display from a dataframe or a geodataframe. Name the column image_url (a URL or data: URI) or image_content (raw base64 bytes); image, thumbnail and overlay_url are recognized too, and an unnamed column is used when its values are data: URIs or URLs ending in an image extension. A same-origin /api/... value is fetched with the signed-in user's token, so images Curio itself serves per user resolve correctly
- Some boxes have hot reload like Data Pool and Vis Image but other require running the code.
- Support to two of most important types: raster (rasterio) and vector (geopandas)
- What get passed by to each box in the case of raster data is the rasterio.io.DatasetReader. So if you want to send raster data from one box to the other you have to write to a file, read it and send the reader.
- Surface is just a polygon representing a bounding box. Surface needs to have a surface_id to be detected as surface.
