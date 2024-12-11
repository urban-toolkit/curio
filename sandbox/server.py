from flask import Flask, request, send_from_directory, abort, jsonify
import requests
import json
import subprocess
import geopandas as gpd
import utk

app = Flask(__name__)
address = '0.0.0.0'
port = 2000

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

@app.route('/')
def root():
    abort(403)

@app.route('/liveness', methods=['GET'])
def liveness():
    return 'Sandbox is live.'

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']
    if file.filename == '':
        return 'No selected file'

    file.save(request.form['fileName'])

    return file.filename

@app.route('/exec', methods=['POST'])
def exec():

    if(request.json['code'] == None):
        abort(400, "Code was not included in the post request")

    file = open("running.py", "w")
    file.write(request.json['code'])
    file.close()
    command = ['python', 'running.py']
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()

    stdout = [item for item in stdout.decode('ascii').split("\n") if item != '']

    if(len(stdout) == 0):
        stdout = ""
    else:
        stdout = stdout[-1]

    jsonOutput = {
        "stdout": stdout,
        "stderr": stderr.decode('ascii'),
        "output": stdout
    }

    return jsonify(jsonOutput)

@app.route('/toLayers', methods=['POST'])
def toLayers():

    if(request.json['geoJsons'] == None):
        abort(400, "geoJsons were not included in the post request")

    geoJsons = request.json['geoJsons']

    layers = []
    joinedJsons = []

    for index, geoJson in enumerate(geoJsons):

        parsedGeoJson = json.loads(geoJson)

        layerName = "layer"+str(index)

        if 'metadata' in parsedGeoJson and 'name' in parsedGeoJson['metadata']:
            layerName = parsedGeoJson['metadata']['name']

        # gdfs.append(gpd.GeoDataFrame.from_features(geoJson))
        gdf = gpd.GeoDataFrame.from_features(parsedGeoJson)

        if 'building_id' in gdf.columns:

            gdf = gdf.set_crs('4326')
            mesh = utk.OSM.mesh_from_buildings_gdf(gdf, 5)['data']

            non_geometry_columns = [col for col in gdf.columns if col != gdf.geometry.name and col != "id" and col != "interacted" and col != "linked" and col != 'building_id' and col != 'tags' and col != 'height' and col != 'min_height']

            joinedJson = {
                "id": layerName,
                "incomingId": [],
                "inValues": []
            }

            renderStyle = []

            if(len(non_geometry_columns) > 0):
                renderStyle = ["SMOOTH_COLOR_MAP_TEX", "PICKING"]
            else:
                renderStyle = ["SMOOTH_COLOR_MAP_TEX"]

            layer = {
                "id": layerName,
                "type": "BUILDINGS_LAYER",
                "renderStyle": renderStyle,
                "styleKey": "surface",
                "data": mesh
            }

            layers.append(layer)

            for column in non_geometry_columns:
                
                inValues = []

                currentBuildingId = -1

                uniqueObjectIndex = 0

                print("column", column)

                for index, row in gdf.iterrows():
                    
                    if(row['building_id'] != currentBuildingId): # only replicate values for the first reference to that building
                        currentBuildingId = row['building_id']

                        objectUnit = layer['data'][uniqueObjectIndex]['geometry'] # object (each row of the gdf was transformed in a set of coordinates)

                        for i in range(int(len(objectUnit['coordinates'])/3)): 
                            if(isinstance(row[column],list)): # different values for each coordinate # TODO: consider multiple timesteps
                                inValues.append(row[column][i])
                            else: # for each coordinate replicate the value of the row
                                inValues.append(row[column])

                        uniqueObjectIndex += 1

                joinedJson["incomingId"].append(column)
                joinedJson["inValues"].append([inValues]) # TODO: support for multiple timesteps

            joinedJsons.append(joinedJson)

        elif 'surface_id' in gdf.columns:

            gdf = gdf.set_crs('3395')
            gdf = gdf.to_crs('4326')

            polygon_geometry = gdf.geometry.iloc[0]

            coordinates = list(polygon_geometry.exterior.coords)

            minLat = None
            maxLat = None
            minLon = None
            maxLon = None

            for coord in coordinates:
                if(minLat == None or minLat > coord[1]):
                    minLat = coord[1]

                if(maxLat == None or maxLat < coord[1]):
                    maxLat = coord[1]

                if(minLon == None or minLon > coord[0]):
                    minLon = coord[0]

                if(maxLon == None or maxLon < coord[0]):
                    maxLon = coord[0]

            mesh = utk.OSM.create_surface_mesh([minLat, minLon, maxLat, maxLon], True, -1, 5)

            non_geometry_columns = [col for col in gdf.columns if col != gdf.geometry.name and col != "id" and col != "interacted" and col != "linked" and col != 'surface_id']

            joinedJson = {
                "id": layerName,
                "incomingId": [],
                "inValues": []
            }

            renderStyle = []

            if(len(non_geometry_columns) > 0):
                renderStyle = ["SMOOTH_COLOR_MAP", "PICKING"]
            else:
                renderStyle = ["SMOOTH_COLOR"]

            layer = {
                "id": layerName,
                "type": "TRIANGLES_3D_LAYER",
                "renderStyle": renderStyle,
                "styleKey": "surface",
                "data": mesh['data']
            }

            layers.append(layer)

            for column in non_geometry_columns:
                
                inValues = []

                for index, row in gdf.iterrows():
                    
                    objectUnit = layer['data'][index]['geometry'] # object (each row of the gdf was transformed in a set of coordinates)

                    for i in range(int(len(objectUnit['coordinates'])/3)): 
                        if(isinstance(row[column],list)): # different values for each coordinate # TODO: consider multiple timesteps
                            inValues.append(row[column][i])
                        else: # for each coordinate replicate the value of the row
                            inValues.append(row[column])

                joinedJson["incomingId"].append(column)
                joinedJson["inValues"].append([inValues]) # TODO: support for multiple timesteps

            joinedJsons.append(joinedJson)

        else: 
                
            gdf = gdf.set_crs('3395')
            mesh = utk.mesh_from_gdf(gdf)

            # layer = {
            #     "id": layerName,
            #     "type": "TRIANGLES_3D_LAYER",
            #     "renderStyle": ["SMOOTH_COLOR_MAP"],
            #     "styleKey": "surface",
            #     "data": mesh
            # }

            non_geometry_columns = [col for col in gdf.columns if col != gdf.geometry.name and col != "id" and col != "interacted" and col != "linked"]

            joinedJson = {
                "id": layerName,
                "incomingId": [],
                "inValues": []
            }

            renderStyle = []

            if(len(non_geometry_columns) > 0):
                renderStyle = ["SMOOTH_COLOR_MAP", "PICKING"]
            else:
                renderStyle = ["SMOOTH_COLOR"]

            layer = {
                "id": layerName,
                "type": "TRIANGLES_3D_LAYER",
                "renderStyle": renderStyle,
                "styleKey": "surface",
                "data": mesh
            }

            layers.append(layer)

            for column in non_geometry_columns:
                
                inValues = []

                for index, row in gdf.iterrows():
                    
                    objectUnit = layer['data'][index]['geometry'] # object (each row of the gdf was transformed in a set of coordinates)

                    for i in range(int(len(objectUnit['coordinates'])/3)): 
                        if(isinstance(row[column],list)): # different values for each coordinate # TODO: consider multiple timesteps
                            inValues.append(row[column][i])
                        else: # for each coordinate replicate the value of the row
                            inValues.append(row[column])

                joinedJson["incomingId"].append(column)
                joinedJson["inValues"].append([inValues]) # TODO: support for multiple timesteps

            joinedJsons.append(joinedJson)

    jsonOutput = {
        "layers": layers,
        "joinedJsons": joinedJsons
    }

    return jsonify(jsonOutput)


if __name__ == '__main__':
    app.run(host=address, port=port)
