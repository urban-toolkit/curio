from flask import request, abort, jsonify
import json
import subprocess
import geopandas as gpd
import pandas as pd
import utk
from utk_curio.sandbox.app import app, cache
from utk_curio.sandbox.app.utils.cache import make_key
import os
import mmap
from pathlib import Path

from shapely import wkt

DATA_DIR = "./data"

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

@app.route('/')
def root():
    abort(403)

@app.route('/live', methods=['GET'])
def live():
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

@app.route('/datasets', methods=['GET'])
def list_datasets():
    allowed_extensions = {'.json', '.geojson', '.csv'}

    files = []

    # Source 1: /data relative to the root of the installed pip package
    project_root_data = Path(__file__).parent.parent.parent / 'data'
    print("Loading datasets from pip package location:", project_root_data)

    if project_root_data.exists() and project_root_data.is_dir():
        files.extend([
            f.as_posix() for f in project_root_data.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_extensions
        ])

    # Source 2: /data relative to current working directory
    # cwd_data = os.getcwd() / 'data'
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    data_dir = os.path.join(launch_dir, "data")
    data_dir = Path(data_dir)
    print("Loading datasets from working directory:", data_dir)

    if data_dir.exists() and data_dir.is_dir():
        files.extend([
            f.as_posix() for f in data_dir.iterdir()
            if f.is_file() and f.suffix.lower() in allowed_extensions
        ])

    return jsonify(files)

@app.route('/exec', methods=['POST'])
# @cache.cached(make_cache_key=make_key)
def exec():
    import time
    start_time = time.time()
    app.logger.info(f'/exec: Request begin')

    # print(request.json['code'], flush=True)

    if(request.json['code'] == None):
        abort(400, "Code was not included in the post request")

    # Load default python wrapper code
    full_code = open('sandbox/python_wrapper.txt', 'r').read()

    # Set path to be relative to the place where curio is called
    original_dir = os.getcwd()
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    os.chdir(launch_dir)

    code = request.json['code']
    file_path = request.json['file_path']
    boxType = request.json['boxType']
    dataType = request.json['dataType']
    
    full_code = full_code.replace('{userCode}', str(code))
    full_code = full_code.replace('{filePath}', str(file_path))
    full_code = full_code.replace('{boxType}', str(boxType))
    full_code = full_code.replace('{dataType}', str(dataType))

    print("File input:", file_path)

    command = ['python', '-']
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    stdout, stderr = process.communicate(full_code)

    stdout = [item for item in stdout.split("\n") if item != '']

    print("File output", stdout)

    if(len(stdout) > 0):
        output = json.loads(stdout[-1])
    else:
        output = {}
        output['path'] = ""
        output['dataType'] = "str"

    jsonOutput = {
        "stdout": stdout[0:-1], # just get prints, remove output itself
        "stderr": stderr,
        "output": output
    }

    # print("----------", jsonOutput, flush=True)

    app.logger.info(f'/exec: Request end in time: {(time.time() - start_time) / 60} mins')

    os.chdir(original_dir)

    return jsonify(jsonOutput)

@app.route('/toLayers', methods=['POST'])
def toLayers():

    if(request.json['geojsons'] == None):
        abort(400, "geojsons were not included in the post request")

    geojsons = request.json['geojsons']

    layers = []
    joinedJsons = []

    for index, geojson in enumerate(geojsons):

        parsedGeoJson = geojson # json.loads(geojson)

        layerName = "layer"+str(index)

        if 'metadata' in parsedGeoJson and 'name' in parsedGeoJson['metadata']:
            layerName = parsedGeoJson['metadata']['name']

        # gdfs.append(gpd.GeoDataFrame.from_features(geoJson))
        gdf = gpd.GeoDataFrame.from_features(parsedGeoJson)
        # df = pd.DataFrame.from_dict(geojson)
        # df = pd.DataFrame({'geometry': geojson['geometry'], 'values': geojson['value']})
        # df = df[df['geometry'].apply(lambda x: isinstance(x, str))]
        # df['geometry'] = df['geometry'].apply(wkt.loads)
        # gdf = gpd.GeoDataFrame(df, geometry='geometry')

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
                    # print(layer['data'])
                    # print(layer['data'], flush=True)

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

