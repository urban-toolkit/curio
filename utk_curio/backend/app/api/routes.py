from flask import request, abort, jsonify, g
import requests
import json
import sqlite3
from utk_curio.backend.extensions import db
from utk_curio.backend.app.users.models import User, UserSession
from utk_curio.backend.app.services.google_oauth import GoogleOAuth
from utk_curio.backend.app.middlewares import require_auth
import uuid
import os
import zlib
import time
import mmap
from pathlib import Path
import re
import pandas as pd
import geopandas as gpd
from openai import OpenAI

# The Flask app
from utk_curio.backend.app.api import bp

# Sandbox address
api_address='http://'+os.getenv('FLASK_SANDBOX_HOST', 'localhost')
api_port=int(os.getenv('FLASK_SANDBOX_PORT', 2000))

conversation = {}

tokens_left = 200000 # Tokens allowed per minute
last_refresh = time.time() # Last time that 60 minutes elapsed

inputTypesSupported = {
    "DATA_LOADING": [],
    "DATA_EXPORT": ["DATAFRAME", "GEODATAFRAME"],
    "DATA_CLEANING": ["DATAFRAME", "GEODATAFRAME"],
    "DATA_TRANSFORMATION": ["DATAFRAME", "GEODATAFRAME"],
    "COMPUTATION_ANALYSIS": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
    "FLOW_SWITCH": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
    "VIS_UTK": ["GEODATAFRAME"],
    "VIS_VEGA": ["DATAFRAME"],
    "VIS_TABLE": ["DATAFRAME", "GEODATAFRAME"],
    "VIS_TEXT": ["VALUE"],
    "VIS_IMAGE": ["LIST"],
    "CONSTANTS": [],
    "DATA_POOL": ["DATAFRAME", "GEODATAFRAME"],
    "MERGE_FLOW": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
}

outputTypesSupported = {
    "DATA_LOADING": ["DATAFRAME", "GEODATAFRAME"],
    "DATA_EXPORT": [],
    "DATA_CLEANING": ["DATAFRAME", "GEODATAFRAME"],
    "DATA_TRANSFORMATION": ["DATAFRAME", "GEODATAFRAME"],
    "COMPUTATION_ANALYSIS": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
    "FLOW_SWITCH": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
    "VIS_UTK": ["GEODATAFRAME"],
    "VIS_VEGA": ["DATAFRAME"],
    "VIS_TABLE": ["DATAFRAME", "GEODATAFRAME"],
    "VIS_TEXT": ["VALUE"],
    "VIS_IMAGE": ["LIST"],
    "CONSTANTS": ["VALUE"],
    "DATA_POOL": ["DATAFRAME", "GEODATAFRAME"],
    "MERGE_FLOW": ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"],
}

attributeIds = {
    "DATAFRAME": "1",
    "GEODATAFRAME": "2",
    "VALUE": "3",
    "LIST": "4",
    "JSON": "5"
}

TYPE_MAP = {
    "computation_analysis": "COMPUTATION_ANALYSIS",
    "data_cleaning": "DATA_CLEANING",
    "data_export": "DATA_EXPORT",
    "data_loading": "DATA_LOADING",
    "data_transformation": "DATA_TRANSFORMATION",
    "utk": "VIS_UTK",
    "vega_lite": "VIS_VEGA"
}

FOLDER_MAP = {
    "COMPUTATION_ANALYSIS": "computation_analysis",
    "DATA_CLEANING": "data_cleaning",
    "DATA_EXPORT": "data_export",
    "DATA_LOADING": "data_loading",
    "DATA_TRANSFORMATION": "data_transformation",
    "VIS_UTK": "utk",
    "VIS_VEGA": "vega_lite"
}

TEMPLATE_DIR = "./templates"

def get_db_path():
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    db_path = os.path.join(launch_dir, ".curio", "provenance.db")
    return db_path

@bp.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

@bp.route('/')
def root():
    abort(403)

@bp.route('/live')
def live():
    return 'Backend is live.'

@bp.route('/cwd')
def cwd():
    return os.getcwd()

@bp.route('/launchCwd')
def launchCwd():
    return os.environ["CURIO_LAUNCH_CWD"]

@bp.route('/sharedDataPath')
def sharedDataPath():
    return os.environ["CURIO_SHARED_DATA"]

@bp.route('/upload', methods=['POST'])
def upload_file():

    if 'file' not in request.files:
        return 'No file part'

    file = request.files['file']

    if file.filename == '':
        return 'No selected file'
    
    response = requests.post(api_address+":"+str(api_port)+"/upload", files={'file': file}, data={'fileName': file.filename})

    if response.status_code == 200:
        return 'File uploaded successfully'
    else:
        return 'Error uploading file'


def transform_to_vega(data):
    """
    Transforms a pandas-style JSON (column-based) to Vega-Lite-ready JSON (row-based).
    
    Args:
        data (dict): The original pandas-style JSON data.

    Returns:
        dict: The transformed Vega-Lite-ready JSON data.
    """
    if "data" in data and isinstance(data["data"], dict):
        columns = list(data["data"].keys())
        values = []

        # Assuming all columns have the same number of rows
        num_rows = len(data["data"][columns[0]])

        for i in range(num_rows):
            row = {col: data["data"][col][i] for col in columns}
            values.append(row)

        return values

    return data

@bp.route('/get', methods=['GET'])
def get_file():
    file_name = request.args.get('fileName')
    vega = request.args.get('vega', 'false').lower() == 'true'

    if not file_name:
        return 'No file name specified', 400
    
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    base_path = Path(launch_dir) / shared_disk_path
    base_path = base_path.resolve()

    requested_path = Path(file_name)
    full_path = (base_path / requested_path).resolve()

    if not str(full_path).startswith(str(base_path)):
        return 'Invalid file path: %s'%full_path, 403

    if not full_path.exists():
        return 'File does not exist: %s'%full_path, 404

    try:
        # Using mmap for efficient memory-mapped loading
        with open(full_path, "rb") as file:
            with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mmapped_file:
                # Decompress and decode directly from the memory-mapped file
                decompressed_data = zlib.decompress(mmapped_file[:])
                data = json.loads(decompressed_data.decode('utf-8'))

                if isinstance(data, str):
                    data = json.loads(data)
                
                if vega:
                    data = transform_to_vega(data)

        return jsonify(data), 200

    except Exception as e:
        return f'Error loading file: {str(e)}', 500

@bp.route('/get-preview', methods=['GET'])
def get_file_preview():
    """
    Get first 100 rows + metadata for DataPool display optimization.
    Similar to /get but returns limited data to reduce transfer overhead.
    """
    file_name = request.args.get('fileName')
    
    if not file_name:
        return 'No file name specified', 400
    
    launch_dir = os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())
    shared_disk_path = os.environ.get("CURIO_SHARED_DATA", "./.curio/data/")
    base_path = Path(launch_dir) / shared_disk_path
    base_path = base_path.resolve()

    requested_path = Path(file_name)
    full_path = (base_path / requested_path).resolve()

    if not str(full_path).startswith(str(base_path)):
        return 'Invalid file path: %s'%full_path, 403

    if not full_path.exists():
        return 'File does not exist: %s'%full_path, 404

    try:
        # Using mmap for efficient memory-mapped loading
        with open(full_path, "rb") as file:
            with mmap.mmap(file.fileno(), 0, access=mmap.ACCESS_READ) as mmapped_file:
                # Decompress and decode directly from the memory-mapped file
                decompressed_data = zlib.decompress(mmapped_file[:])
                data = json.loads(decompressed_data.decode('utf-8'))

                if isinstance(data, str):
                    data = json.loads(data)
                
                # Create preview version with limited rows
                preview_data = create_preview_data(data)
                
                return jsonify(preview_data)

    except Exception as e:
        return f'Error loading preview: {str(e)}', 500

def create_preview_data(data, max_rows=100):
    """
    Create a preview version of the data with limited rows.
    Maintains the same structure but with fewer rows for display.
    """
    if not isinstance(data, dict):
        return data
    
    # Handle dataframe format
    if data.get('dataType') == 'dataframe' and 'data' in data:
        df_data = data['data']
        if isinstance(df_data, dict):
            # Check if columns contain arrays (list format)
            columns = list(df_data.keys())
            if columns:
                first_column_data = df_data[columns[0]]
                
                # Handle list format (most common)
                if isinstance(first_column_data, list):
                    total_rows = len(first_column_data)
                    limited_rows = min(max_rows, total_rows)
                    
                    # Create limited data for each column
                    limited_data = {}
                    for column in columns:
                        if isinstance(df_data[column], list):
                            limited_data[column] = df_data[column][:limited_rows]
                        else:
                            limited_data[column] = df_data[column]
                    
                    # Create preview response
                    preview = {
                        **data,  # Keep all original metadata
                        'data': limited_data,
                        'preview': True,
                        'previewRows': limited_rows,
                        'totalRows': total_rows
                    }
                    return preview
                
                # Handle dictionary-indexed format
                elif isinstance(first_column_data, dict):
                    # Get keys (indices) and limit to max_rows
                    all_indices = list(first_column_data.keys())
                    limited_indices = all_indices[:max_rows]
                    
                    # Create limited data for each column
                    limited_data = {}
                    for column in columns:
                        limited_data[column] = {
                            idx: df_data[column][idx] 
                            for idx in limited_indices 
                            if idx in df_data[column]
                        }
                    
                    # Create preview response
                    preview = {
                        **data,  # Keep all original metadata
                        'data': limited_data,
                        'preview': True,
                        'previewRows': len(limited_indices),
                        'totalRows': len(all_indices)
                    }
                    return preview
    
    # Handle geodataframe format  
    elif data.get('dataType') == 'geodataframe' and 'data' in data:
        gdf_data = data['data']
        if isinstance(gdf_data, dict) and 'features' in gdf_data:
            features = gdf_data['features']
            if isinstance(features, list):
                total_features = len(features)
                limited_features = features[:max_rows]
                
                preview = {
                    **data,  # Keep all original metadata
                    'data': {
                        **gdf_data,
                        'features': limited_features
                    },
                    'preview': True,
                    'previewRows': len(limited_features),
                    'totalRows': total_features
                }
                return preview
    
    # Return original data if format not recognized
    return data

@bp.route('/processPythonCode', methods=['POST'])
def process_python_code():

    code = request.json['code']
    boxType = request.json['boxType']
    input = {'path': "", 'dataType': ""}
    if(request.json['input']):
        if(request.json['input']['dataType'] == 'outputs'):
            input['path'] = request.json['input']['data']
            input['dataType'] = 'outputs'
        elif('filename' in request.json['input']):
            input['path'] = request.json['input']['filename']
            input['dataType'] = request.json['input']['dataType']
        else:
            input['path'] = request.json['input']['path']
            input['dataType'] = request.json['input']['dataType']
    try:
        response = requests.post(api_address+":"+str(api_port)+"/exec",
                                data=json.dumps({
                                    "code": code,
                                    "file_path": input['path'],
                                    "boxType": boxType,
                                    "dataType": input['dataType']
                                }),
                                headers={"Content-Type": "application/json"},
                                )
        
        try:
            response = response.json()
            stdout = response['stdout']
            stderr = response['stderr']
            output = response['output'] # contains path and dataType
            print(output, flush=True)
            
            return {'stdout': stdout, 'stderr': stderr, 'input': input, 'output': output}
        finally:
            pass
    finally:
        pass

@bp.route('/toLayers', methods=['POST'])
def toLayers():

    if(request.json['geojsons'] == None):
        abort(400, "geojsons were not included in the post request")
    try:
        import geopandas as gpd
        for geojson in request.json['geojsons']:
            gpd.GeoDataFrame.from_features(geojson['features'])
    except Exception as e:
        print("GeoPandas validation failed:", e)
    response = requests.post(api_address+":"+str(api_port)+"/toLayers",
                             data=json.dumps({
                                 "geojsons": request.json['geojsons']
                             }),
                             headers={"Content-Type": "application/json"},
                             )

    return response.json()

# @bp.route('/signin', methods=['POST'])
# def signin():
#     # google_oauth = GoogleOAuth()
#     # user_data = google_oauth.verify_token(request.json.get('token'))
#     # if not user_data:
#     #     return jsonify({'error': 'Invalid token'}), 400

#     # create new session token
#     # new_session = UserSession(user_id=user.id)
#     user_data = {
#         'id': 1,
#         'name': 'Test',
#         'email': 'Test@mail.com',
#         'provider': "",
#         'uid': "",
#         'picture': "",
#         'type': 'programmer'
#     }
#     new_session = UserSession(user_id=user_data.get('id'))
#     db.session.add(new_session)
#     db.session.commit()


#     # get user from database

#     user = User.query.filter_by(
#         id=user_data.get('id'),
#         # provider=user_data.get('provider'),
#         # provider_uid= user_data.get('uid')
#     ).first()

#     if user:
#         user.name = user_data.get('name')
#         user.profile_image = user_data.get('picture')
#     else:
#         user = User(
#             email=user_data.get('email'),
#             name=user_data.get('name'),
#             profile_image=user_data.get('picture'),
#             provider=user_data.get('provider'),
#             provider_uid=user_data.get('uid'))
#         db.session.add(user)
#     db.session.commit()


#     return jsonify({
#         'user': {
#             'name': user.name,
#             'profile_image': user.profile_image,
#             'type': user.type
#         },
#         'token': new_session.token
#     }), 200

@bp.route('/signin', methods=['POST'])
def signin():
    try:
        google_oauth = GoogleOAuth()
        user_data = google_oauth.verify_token(request.json.get('token'))

        if not user_data:
            return jsonify({'error': 'Invalid token'}), 400

        user = User.query.filter_by(provider_uid=user_data['uid']).first()

        if not user:
            user = User(
                email=user_data['email'],
                name=user_data['name'],
                profile_image=user_data['picture'],
                type='programmer',  
                provider='google',
                provider_uid=user_data['uid']
            )
            db.session.add(user)
            db.session.commit()

        new_session = UserSession(user_id=user.id)
        db.session.add(new_session)
        db.session.commit()

        return jsonify({
            'user': {
                'name': user.name,
                'email': user.email,
                'profile_image': user.profile_image,
                'type': user.type,
                'uid': user.provider_uid,
                'provider': user.provider
            },
            'token': new_session.token
        }), 200
    
    except:
        # create new session token
        user_data = {
            'id': 1,
            'name': 'Test',
            'email': 'Test@mail.com',
            'provider': "",
            'uid': "",
            'picture': "",
            'type': 'programmer'
        }
        new_session = UserSession(user_id=user_data.get('id'))
        db.session.add(new_session)
        db.session.commit()


        # get user from database

        user = User.query.filter_by(
            id=user_data.get('id'),
            # provider=user_data.get('provider'),
            # provider_uid= user_data.get('uid')
        ).first()

        if user:
            user.name = user_data.get('name')
            user.profile_image = user_data.get('picture')
        else:
            user = User(
                email=user_data.get('email'),
                name=user_data.get('name'),
                profile_image=user_data.get('picture'),
                provider=user_data.get('provider'),
                provider_uid=user_data.get('uid'))
            db.session.add(user)
        db.session.commit()


        return jsonify({
            'user': {
                'name': user.name,
                'profile_image': user.profile_image,
                'type': user.type
            },
            'token': new_session.token
        }), 200

@bp.route('/getUser', methods=['GET'])
@require_auth
def get_user():
    user = g.user
    return jsonify({
        'user': {
            'name': user.name,
            'profile_image': user.profile_image,
            'type': user.type
        }
    }), 200

@bp.route('/saveUserType', methods=['POST'])
@require_auth
def save_user_type():
    new_type = request.json.get('type')
    user = g.user
    user.type = new_type
    db.session.commit()

    return jsonify({
        'user': {
            'name': user.name,
            'profile_image': user.profile_image,
            'type': user.type
        }
    }), 200

@bp.route('/saveUserProv', methods=['POST'])
def save_user_prov(): # only save if user with that name does not exist on the database

    # conn = sqlite3.connect('backend/provenance.db')
    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    user = request.json.get('user')

    # Check if the user_name already exists in the table
    cursor.execute('''SELECT 1 FROM user WHERE user_name = ?''', (user['user_name'],))
    existing_record = cursor.fetchone()

    if not existing_record:
        data_to_insert = (user['user_name'], user['user_type'], user['user_IP'])
        cursor.execute('''INSERT INTO user (user_name, user_type, user_IP)
                        VALUES (?, ?, ?)''', data_to_insert)

    conn.commit()
    conn.close()

    return "",200

@bp.route('/saveWorkflowProv', methods=['POST'])
def save_workflow_prov():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    workflow_name = request.json.get('workflow')

    # starting a new version counter for the workflow
    cursor.execute('''INSERT INTO version (version_number)
                    VALUES (?)''', ('1.0',))

    conn.commit()

    # id of the new just added version element
    version_id = cursor.lastrowid

    # creating new versioned element for the new workflow
    cursor.execute('''INSERT INTO versionedElement (version_id)
                    VALUES (?)''', (version_id,))

    conn.commit()

    # id of the new just added versioned element
    ve_id = cursor.lastrowid

    # creating new workflow
    cursor.execute('''INSERT INTO workflow (workflow_name, ve_id)
                    VALUES (?, ?)''', (workflow_name, ve_id,))

    conn.commit()
    conn.close()

    return "",200

@bp.route('/newBoxProv', methods=['POST'])
def new_box_prov():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # // new version (increment version number based on previous old workflow that points to a ve that points to the version)
    # // new versioned element (pointing to the versioned element of the old workflow and pointing to the new version)
    # // new workflow
    # // point new workflow to the new versioned element
    # // create relation for new activity (output relation)
    # // new activity (pointing to the new workflow and to the new relation as output)
    # // duplicate all activities that point to the old workflow and point to the new one (duplicate relations tied to activities)

    data = request.json.get('data')

    # last workflow created with this name
    cursor.execute("SELECT * FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (data['workflow_name'],))
    old_workflow = cursor.fetchone()

    # getting versionedElement attached to the old workflow
    cursor.execute("SELECT * FROM versionedElement WHERE ve_id = ?", (old_workflow[2],))
    old_workflow_ve = cursor.fetchone()

    # getting the version atteched to the old workflow
    cursor.execute("SELECT * FROM version WHERE version_id = ?", (old_workflow_ve[1],))
    version = cursor.fetchone()

    new_version_number = str(float(version[1])+1.0)

    # creating new version
    cursor.execute('''INSERT INTO version (version_number)
                    VALUES (?)''', (new_version_number,))

    conn.commit()

    # id of the new just added version
    version_id = cursor.lastrowid

    # creating new versioned element for the new workflow
    cursor.execute('''INSERT INTO versionedElement (previous_ve_id, version_id)
                    VALUES (?, ?)''', (old_workflow_ve[0], version_id,))

    conn.commit()

    # id of the new just added versioned element
    ve_id = cursor.lastrowid

    # creating new workflow
    cursor.execute('''INSERT INTO workflow (workflow_name, ve_id)
                    VALUES (?, ?)''', (data['workflow_name'], ve_id,))

    conn.commit()

    # id of the new just added workflow
    workflow_id = cursor.lastrowid

    # creating relation for new activity
    cursor.execute('''INSERT INTO relation (relation_name)
                VALUES (?)''', (data['activity_name']+"_"+"out",))

    conn.commit()

    # id of the new just added relation
    output_relation_id = cursor.lastrowid
    input_relation_id = cursor.lastrowid

    boxType = data['activity_name'].split("-")[0]

    # adding a attributeRelation to each output type that this activity supports
    for outputType in outputTypesSupported[boxType]:
        cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
            VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

    # creating new activity
    cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id)
                    VALUES (?, ?, ?, ?)''', (workflow_id, data['activity_name'], input_relation_id, output_relation_id,))

    conn.commit()

    # getting all activities that point to the old workflow
    cursor.execute("SELECT activity_name, input_relation_id, output_relation_id, ve_id FROM activity WHERE workflow_id = ?", (old_workflow[0],))

    activities = cursor.fetchall()

    duplicated_output_relations = {} # dict of old to new ids.

    duplicated_activities_ids = []

    # duplicating all activities and making them point to the new workflow
    for activity in activities:

        # getting the old output relation of duplicated activity
        cursor.execute("SELECT relation_id, relation_name FROM relation WHERE relation_id = ?", (activity[2],))
        old_output_relation = cursor.fetchone()

        # # duplicate the old output relation
        # cursor.execute('''INSERT INTO relation (relation_name)
        #             VALUES (?)''', (old_output_relation[1],))

        # conn.commit()

        # # id of the new just added relation
        # output_relation_id = cursor.lastrowid

        boxType = activity[0].split("-")[0]

        # # adding a attributeRelation to each output type that this activity supports
        # for outputType in outputTypesSupported[boxType]:
        #     cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
        #         VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

        # duplicated_output_relations[old_output_relation[0]] = output_relation_id # mapping old to new ids

        # cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
        #         VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], output_relation_id, activity[3],))

        cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
                VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], old_output_relation[0], activity[3],))

        conn.commit()

        # id of the new just added activity
        activity_id = cursor.lastrowid

        duplicated_activities_ids.append(activity_id)

    # # updating duplicated activities to point to the duplicated relations
    # for old_output_id in duplicated_output_relations:
    #     cursor.execute("SELECT activity_id FROM activity WHERE input_relation_id = ?", (old_output_id,))
    #     activities = cursor.fetchall()

    #     for activity in activities:
    #         if activity[0] in duplicated_activities_ids: # this is a duplicated activity that needs to have input field updated to point to new duplicated relation
    #             cursor.execute("UPDATE activity SET input_relation_id = ? WHERE activity_id = ?", (duplicated_output_relations[old_output_id], activity[0],))
    #             conn.commit()

    conn.commit()
    conn.close()

    # // TODO: new and duplicated activities can also be versioned by creating a new versioned element
    return "",200

@bp.route('/deleteBoxProv', methods=['POST'])
def delete_box_prov():

    # // new version (increment version number based on previous old workflow that points to a ve that points to the version)
    # // new versioned element (pointing to the versioned element of the old workflow and pointing to the new version)
    # // new workflow
    # // point new workflow to the new versioned element
    # // duplicate all activities (but the excluded box) that point to the old workflow and point to the new one

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    data = request.json.get('data')

    # last workflow created with this name
    cursor.execute("SELECT * FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (data['workflow_name'],))
    old_workflow = cursor.fetchone()

    # getting versionedElement attached to the old workflow
    cursor.execute("SELECT * FROM versionedElement WHERE ve_id = ?", (old_workflow[2],))
    old_workflow_ve = cursor.fetchone()

    # getting the version atteched to the old workflow
    cursor.execute("SELECT * FROM version WHERE version_id = ?", (old_workflow_ve[1],))
    version = cursor.fetchone()

    new_version_number = str(float(version[1])+1.0)

    # creating new version
    cursor.execute('''INSERT INTO version (version_number)
                    VALUES (?)''', (new_version_number,))

    conn.commit()

    # id of the new just added version
    version_id = cursor.lastrowid

    # creating new versioned element for the new workflow
    cursor.execute('''INSERT INTO versionedElement (previous_ve_id, version_id)
                    VALUES (?, ?)''', (old_workflow_ve[0], version_id,))

    conn.commit()

    # id of the new just added versioned element
    ve_id = cursor.lastrowid

    # creating new workflow
    cursor.execute('''INSERT INTO workflow (workflow_name, ve_id)
                    VALUES (?, ?)''', (data['workflow_name'], ve_id,))

    conn.commit()

    # id of the new just added workflow
    workflow_id = cursor.lastrowid

    # getting all activities that point to the old workflow
    cursor.execute("SELECT activity_name, input_relation_id, output_relation_id, ve_id FROM activity WHERE workflow_id = ?", (old_workflow[0],))

    activities = cursor.fetchall()

    duplicated_output_relations = {} # dict of old to new ids.

    duplicated_activities_ids = []

    # duplicating all activities (except deleted one) and making them point to the new workflow
    for activity in activities:
        if(activity[0] != data['activity_name']):

            # getting the old output relation of duplicated activity
            cursor.execute("SELECT relation_id, relation_name FROM relation WHERE relation_id = ?", (activity[2],))
            old_output_relation = cursor.fetchone()

            # # duplicate the old output relation
            # cursor.execute('''INSERT INTO relation (relation_name)
            #             VALUES (?)''', (old_output_relation[1],))

            # conn.commit()

            # # id of the new just added relation
            # output_relation_id = cursor.lastrowid

            boxType = activity[0].split("-")[0]

            # # adding a attributeRelation to each output type that this activity supports
            # for outputType in outputTypesSupported[boxType]:
            #     cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
            #         VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

            # duplicated_output_relations[old_output_relation[0]] = output_relation_id # mapping old to new ids

            # cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
            #         VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], output_relation_id, activity[3],))

            cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
                    VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], old_output_relation[0], activity[3],))

            conn.commit()

            # id of the new just added activity
            activity_id = cursor.lastrowid

            duplicated_activities_ids.append(activity_id)

    # # updating duplicated activities to point to the duplicated relations
    # for old_output_id in duplicated_output_relations:
    #     cursor.execute("SELECT activity_id FROM activity WHERE input_relation_id = ?", (old_output_id,))
    #     activities = cursor.fetchall()

    #     for activity in activities:
    #         if activity[0] in duplicated_activities_ids: # this is a duplicated activity that needs to have input field updated to point to new duplicated relation
    #             cursor.execute("UPDATE activity SET input_relation_id = ? WHERE activity_id = ?", (duplicated_output_relations[old_output_id], activity[0],))
    #             conn.commit()

    conn.commit()
    conn.close()

    # // TODO: new and duplicated activities can also be versioned by creating a new versioned element

    return "",200

@bp.route('/newConnectionProv', methods=['POST'])
def new_connection_prov():
    """
    Creates a new version of a workflow by adding a new connection and updating input/output relations_id.
    """
    data = request.json.get('data')
    if not data or not all(k in data for k in ['workflow_name', 'sourceNodeType', 'sourceNodeId', 'targetNodeType', 'targetNodeId']):
        return jsonify({"error": "Invalid payload. Missing required keys."}), 400

    conn = None
    try:
        db_path = get_db_path()
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # 1. Get the latest workflow with the given name
        cursor.execute("""
            SELECT * FROM workflow
            WHERE workflow_id = (
                SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?
            )
        """, (data['workflow_name'],))
        old_workflow = cursor.fetchone()

        if not old_workflow:
            return jsonify({"error": f"Workflow with name '{data['workflow_name']}' not found."}), 404

        # 2. Get versioning info
        cursor.execute("SELECT * FROM versionedElement WHERE ve_id = ?", (old_workflow['ve_id'],))
        old_workflow_ve = cursor.fetchone()
        cursor.execute("SELECT * FROM version WHERE version_id = ?", (old_workflow_ve['version_id'],))
        version = cursor.fetchone()

        # 3. Create new version, versioned element, and workflow entries
        new_version_number = str(int(float(version['version_number'])) + 1)
        cursor.execute("INSERT INTO version (version_number) VALUES (?)", (new_version_number,))
        new_version_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO versionedElement (previous_ve_id, version_id) VALUES (?, ?)",
            (old_workflow_ve['ve_id'], new_version_id)
        )
        new_ve_id = cursor.lastrowid

        cursor.execute(
            "INSERT INTO workflow (workflow_name, ve_id) VALUES (?, ?)",
            (data['workflow_name'], new_ve_id)
        )
        new_workflow_id = cursor.lastrowid

        # 4. Duplicate activities from the old workflow to the new one
        cursor.execute("SELECT * FROM activity WHERE workflow_id = ?", (old_workflow['workflow_id'],))
        old_activities = cursor.fetchall()

        for activity in old_activities:
            # Insert a copy of the activity pointing to the new workflow
            cursor.execute("""
                INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
                VALUES (?, ?, ?, ?, ?)
            """, (
                new_workflow_id,
                activity['activity_name'],
                activity['input_relation_id'],   
                activity['output_relation_id'],  
                activity['ve_id']
            ))

        # 5. Apply the new connection to the newly created activities
        
        # Get the output relation from the source activity (in the new workflow)
        source_activity_name = f"{data['sourceNodeType']}-{data['sourceNodeId']}"
        cursor.execute("""
            SELECT output_relation_id FROM activity
            WHERE workflow_id = ? AND activity_name = ?
        """, (new_workflow_id, source_activity_name))
        source_activity_output = cursor.fetchone()

        if not source_activity_output:
            raise ValueError(f"Source activity '{source_activity_name}' not found in the new workflow.")

        # Update the input relation of the target activity (in the new workflow)
        target_activity_name = f"{data['targetNodeType']}-{data['targetNodeId']}"
        cursor.execute("""
            UPDATE activity
            SET input_relation_id = ?
            WHERE workflow_id = ? AND activity_name = ?
        """, (source_activity_output['output_relation_id'], new_workflow_id, target_activity_name))
        
        # If we got here, everything went well. Commit the transaction.
        conn.commit()
        
        return jsonify({"message": "New workflow version created successfully.", "new_workflow_id": new_workflow_id}), 200

    except sqlite3.Error as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Database error occurred.", "details": str(e)}), 500
    except (ValueError, TypeError) as e:
        if conn:
            conn.rollback()
        return jsonify({"error": "Application data or logic error.", "details": str(e)}), 400
    finally:
        if conn:
            conn.close()

@bp.route('/deleteConnectionProv', methods=['POST'])
def delete_connection_prov():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    data = request.json.get('data')

    # // new version (increment version number based on previous old workflow that points to a ve that points to the version)
    # // new versioned element (pointing to the versioned element of the old workflow and pointing to the new version)
    # // new workflow
    # // point new workflow to the new versioned element
    # // duplicate all activities that point to the old workflow and point to the new one (duplicate relations tied to activities)
    # // update input relation of the activity to NULL

    # last workflow created with this name
    cursor.execute("SELECT * FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (data['workflow_name'],))
    old_workflow = cursor.fetchone()

    # getting versionedElement attached to the old workflow
    cursor.execute("SELECT * FROM versionedElement WHERE ve_id = ?", (old_workflow[2],))
    old_workflow_ve = cursor.fetchone()

    # getting the version atteched to the old workflow
    cursor.execute("SELECT * FROM version WHERE version_id = ?", (old_workflow_ve[1],))
    version = cursor.fetchone()

    new_version_number = str(float(version[1])+1.0)

    # creating new version
    cursor.execute('''INSERT INTO version (version_number)
                    VALUES (?)''', (new_version_number,))

    conn.commit()

    # id of the new just added version
    version_id = cursor.lastrowid

    # creating new versioned element for the new workflow
    cursor.execute('''INSERT INTO versionedElement (previous_ve_id, version_id)
                    VALUES (?, ?)''', (old_workflow_ve[0], version_id,))

    conn.commit()

    # id of the new just added versioned element
    ve_id = cursor.lastrowid

    # creating new workflow
    cursor.execute('''INSERT INTO workflow (workflow_name, ve_id)
                    VALUES (?, ?)''', (data['workflow_name'], ve_id,))

    conn.commit()

    # id of the new just added workflow
    workflow_id = cursor.lastrowid

    # getting all activities that point to the old workflow
    cursor.execute("SELECT activity_name, input_relation_id, output_relation_id, ve_id FROM activity WHERE workflow_id = ?", (old_workflow[0],))

    activities = cursor.fetchall()

    duplicated_output_relations = {} # dict of old to new ids.

    duplicated_activities_ids = []

    # duplicating all activities and making them point to the new workflow
    for activity in activities:

        # getting the old output relation of duplicated activity
        cursor.execute("SELECT relation_id, relation_name FROM relation WHERE relation_id = ?", (activity[2],))
        old_output_relation = cursor.fetchone()

        # # duplicate the old output relation
        # cursor.execute('''INSERT INTO relation (relation_name)
        #             VALUES (?)''', (old_output_relation[1],))

        # conn.commit()

        # # id of the new just added relation
        # output_relation_id = cursor.lastrowid

        boxType = activity[0].split("-")[0]

        # # adding a attributeRelation to each output type that this activity supports
        # for outputType in outputTypesSupported[boxType]:
        #     cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
        #         VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

        # duplicated_output_relations[old_output_relation[0]] = output_relation_id # mapping old to new ids

        # cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
        #         VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], output_relation_id, activity[3],))

        cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
                VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], old_output_relation[0], activity[3],))

        conn.commit()

        # id of the new just added activity
        activity_id = cursor.lastrowid

        duplicated_activities_ids.append(activity_id)

    # updating duplicated activities to point to the duplicated relations
    for old_output_id in duplicated_output_relations:
        cursor.execute("SELECT activity_id FROM activity WHERE input_relation_id = ?", (old_output_id,))
        activities = cursor.fetchall()

        for activity in activities:
            if activity[0] in duplicated_activities_ids: # this is a duplicated activity that needs to have input field updated to point to new duplicated relation
                cursor.execute("UPDATE activity SET input_relation_id = ? WHERE activity_id = ?", (duplicated_output_relations[old_output_id], activity[0],))
                conn.commit()

    # update input relation of the activity
    cursor.execute("UPDATE activity SET input_relation_id = NULL WHERE workflow_id = ? AND activity_name = ?", (workflow_id, data['targetNodeType']+"-"+data['targetNodeId'],))

    conn.commit()
    conn.close()

    return "",200

@bp.route('/checkDB', methods=['GET'])
def check_db():
    
    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    return "OK",200

@bp.route('/boxExecProv', methods=['POST'])
def box_exec_prov():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    data = request.json.get('data')

    # new workflow execution
    # replicate all activity execution from old workflow execution (except the one related to the activity I'm currently running) and make them point to the new workflow execution
    # create relation instances from the input and output relation id of the activity
    # create the attribute values based on the attributes connected to the relations of the activity. The values are 1 if there is data of that type or 0 if there is not.
    # new activity execution

    # getting the id of the most recent execution of this workflow
    cursor.execute('''
        SELECT MAX(workflowexec_id)
        FROM workflowExecution
        JOIN workflow ON workflowExecution.workflow_id = workflow.workflow_id
        WHERE workflow_name = ?
    ''', (data['workflow_name'],))

    workflowexec_id = cursor.fetchone()

    # getting the most recent execution of this workflow
    cursor.execute("SELECT workflowexec_id, workflow_id, workflowexec_start_time, workflowexec_end_time FROM workflowExecution WHERE workflowexec_id = ?", (workflowexec_id[0],))
    old_workflow_execution = cursor.fetchone()

    # getting last workflow create with this name
    cursor.execute("SELECT * FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (data['workflow_name'],))
    workflow = cursor.fetchone()

    # getting activity attached to this workflow
    cursor.execute("SELECT activity_id, input_relation_id, output_relation_id FROM activity WHERE workflow_id = ? AND activity_name = ?", (workflow[0], data['activity_name'],))
    activity = cursor.fetchone()

    # creating new workflow execution

    if(data['interaction'] == True):
        time.sleep(1) #Ensure that interaction is in the table before box_exec_prov executes. Consider finding a better approach for this logic.


        cursor.execute("SELECT int_id FROM interaction ORDER BY int_id DESC LIMIT 1")
        int_id = cursor.fetchone()[0]


        cursor.execute('''INSERT INTO workflowExecution (workflowexec_start_time, workflowexec_end_time, workflow_id, int_id)
                        VALUES (?, ?, ?, ?)''', (data["activityexec_start_time"], data["activityexec_end_time"], workflow[0], int_id))

        conn.commit()
    else:
        cursor.execute('''INSERT INTO workflowExecution (workflowexec_start_time, workflowexec_end_time, workflow_id)
                VALUES (?, ?, ?)''', (data["activityexec_start_time"], data["activityexec_end_time"], workflow[0],))

        conn.commit()


    # id of the new just added workflowExecution
    workflowExecution_id = cursor.lastrowid

    old_activity_executions = []

    if(old_workflow_execution != None):
        # getting all activity execution from the old workflow execution except the one related to the activity
        cursor.execute("SELECT activity_id, activityexec_start_time, activityexec_end_time, input_ri_id, output_ri_id, activity_source_code FROM activityExecution WHERE workflowexec_id = ? AND activity_id <> ?", (old_workflow_execution[0], activity[0],))
        old_activity_executions = cursor.fetchall()

    input_relation_id = activity[1]
    output_relation_id = activity[2]

    # get the most recent relationInstance of the input relation
    cursor.execute("SELECT re_id FROM relationInstance WHERE re_id = (SELECT MAX(re_id) FROM relationInstance WHERE relation_id = ?)", (input_relation_id,))
    relation_instance_input = cursor.fetchone()

    if(relation_instance_input != None):
        # creating relation instances
        cursor.execute('''INSERT INTO relationInstance (relation_id, original_ri)
                        VALUES (?, ?)''', (input_relation_id, relation_instance_input[0],))
    else:
        # creating relation instances
        cursor.execute('''INSERT INTO relationInstance (relation_id)
                        VALUES (?)''', (input_relation_id,))

    conn.commit()

    input_ri_id = cursor.lastrowid

    # # get the most recent relationInstance of the output relation
    # cursor.execute("SELECT re_id FROM relationInstance WHERE re_id = (SELECT MAX(re_id) FROM relationInstance WHERE relation_id = ?)", (output_relation_id,))
    # relation_instance_output = cursor.fetchone()

    # if(relation_instance_output != None):
    #     cursor.execute('''INSERT INTO relationInstance (relation_id, original_ri)
    #                     VALUES (?)''', (output_relation_id, relation_instance_output[0]))
    # else:
    #     # creating relation instances
    #     cursor.execute('''INSERT INTO relationInstance (relation_id)
    #                     VALUES (?)''', (output_relation_id,))

    # creating relation instances
    cursor.execute('''INSERT INTO relationInstance (relation_id)
                    VALUES (?)''', (output_relation_id,))

    conn.commit()

    output_ri_id = cursor.lastrowid

    # getting types names and ids of attributes of input relation
    cursor.execute('''SELECT attribute.attribute_id, attribute.attribute_name
                        FROM relation
                        JOIN attributeRelation ON relation.relation_id = attributeRelation.relation_id
                        JOIN attribute ON attributeRelation.attribute_id = attribute.attribute_id
                        WHERE attribute.attribute_type = ? AND relation.relation_id = ?''', ('Data', input_relation_id))

    input_attributes = cursor.fetchall()

    # getting types names and ids of attributes of output relation
    cursor.execute('''SELECT attribute.attribute_id, attribute.attribute_name
                        FROM relation
                        JOIN attributeRelation ON relation.relation_id = attributeRelation.relation_id
                        JOIN attribute ON attributeRelation.attribute_id = attribute.attribute_id
                        WHERE attribute.attribute_type = ? AND relation.relation_id = ?''', ('Data', output_relation_id))

    output_attributes = cursor.fetchall()

    for input_attribute in input_attributes: #
        # creating attributeValues
        # cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
        #                 VALUES (?, ?, ?)''', (input_attribute[0], input_ri_id, data['types_input'][input_attribute[1]],))
        cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
                VALUES (?, ?, ?)''', (input_attribute[0], input_ri_id+1, data['inputData'],))

        conn.commit()

    for output_attribute in output_attributes: #
        # creating attributeValues
        # cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
        #                 VALUES (?, ?, ?)''', (output_attribute[0], output_ri_id, data['types_output'][output_attribute[1]],))
        cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
                VALUES (?, ?, ?)''', (output_attribute[0], output_ri_id+1, data['outputData'],))

        conn.commit()

    # duplicating all old activity executions of this workflow
    for old_activity_execution in old_activity_executions:
        cursor.execute('''INSERT INTO activityExecution (activity_id, workflowexec_id, activityexec_start_time, activityexec_end_time, input_ri_id, output_ri_id, activity_source_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)''', (old_activity_execution[0], workflowExecution_id, old_activity_execution[1], old_activity_execution[2], old_activity_execution[3], old_activity_execution[4], old_activity_execution[5]))

        conn.commit()

    # adding new activityExecution
    cursor.execute('''INSERT INTO activityExecution (activity_id, workflowexec_id, activityexec_start_time, activityexec_end_time, input_ri_id, output_ri_id, activity_source_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)''', (activity[0], workflowExecution_id, data['activityexec_start_time'], data['activityexec_end_time'], input_ri_id, output_ri_id, data["activity_source_code"]))

    conn.commit()
    conn.close()

    return "",200

@bp.route('/getBoxGraph', methods=['POST'])
def get_box_graph():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    data = request.json.get('data')

    # last workflow created with this name
    cursor.execute("SELECT workflow_id FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (data['workflow_name'],))
    workflow = cursor.fetchone()

    # activity
    cursor.execute("SELECT activity_id FROM activity WHERE workflow_id = ? AND activity_name = ?", (workflow[0], data['activity_name'],))
    activity = cursor.fetchone()

    # all the executions of this activity in the order they were executed
    cursor.execute("SELECT activityexec_id, input_ri_id, output_ri_id, activity_source_code FROM activityExecution WHERE activity_id = ? ORDER BY activityexec_id ASC", (activity[0],))
    activity_executions = cursor.fetchall()

    # getting the list of all attribute values for input of all executions of this activity
    cursor.execute('''SELECT activityExecution.activityexec_id, attribute.attribute_name
                        FROM activityExecution
                        JOIN attributeValue ON activityExecution.input_ri_id = attributeValue.ri_id
                        JOIN attribute ON attribute.attribute_id = attributeValue.attribute_id
                        WHERE activityExecution.activity_id = ? AND value = ? AND attribute.attribute_type = ?''', (activity[0], '1', 'Data'))
    input_types = cursor.fetchall()

    # getting the list of all attribute values for input of all executions of this activity
    cursor.execute('''SELECT activityExecution.activityexec_id, attribute.attribute_name
                        FROM activityExecution
                        JOIN attributeValue ON activityExecution.output_ri_id = attributeValue.ri_id
                        JOIN attribute ON attribute.attribute_id = attributeValue.attribute_id
                        WHERE activityExecution.activity_id = ? AND value = ? AND attribute.attribute_type = ?''', (activity[0], '1', 'Data'))
    output_types = cursor.fetchall()

    mapIdToTypes_input = {} # activity execution id to array of input types
    mapIdToTypes_output = {} # activity execution id to array of output types

    for input_type in input_types:

        if input_type[0] not in mapIdToTypes_input:
            mapIdToTypes_input[input_type[0]] = [input_type[1]]
        else:
            mapIdToTypes_input[input_type[0]].append(input_type[1])

    for output_type in output_types:

        if output_type[0] not in mapIdToTypes_output:
            mapIdToTypes_output[output_type[0]] = [output_type[1]]
        else:
            mapIdToTypes_output[output_type[0]].append(output_type[1])

    graph = []

    for activity_execution in activity_executions:

        if activity_execution[0] not in mapIdToTypes_input:
            mapIdToTypes_input[activity_execution[0]] = []

        if activity_execution[0] not in mapIdToTypes_output:
            mapIdToTypes_output[activity_execution[0]] = []

        node = {
            "id": activity_execution[0],
            "code": activity_execution[3],
            "inputs": mapIdToTypes_input[activity_execution[0]],
            "outputs": mapIdToTypes_output[activity_execution[0]]
        }

        graph.append(node)

    conn.commit()
    conn.close()

    return jsonify({
        "graph": graph
    }),200

@bp.route('/truncateDBProv', methods=['GET'])
def truncate_db_prov():

    # db_path = os.path.join(os.getcwd(), ".curio", "provenance.db")
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Fetch the list of tables in the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = cursor.fetchall()
    for table in tables:
        # Get the table name from the tuple
        table_name = table[0]
        # Execute a DELETE statement to truncate the table
        cursor.execute(f"DELETE FROM {table_name};")

    cursor.execute("INSERT INTO ATTRIBUTE(attribute_id, attribute_name, attribute_type) VALUES (1, 'DATAFRAME', 'Data');")
    cursor.execute("INSERT INTO ATTRIBUTE(attribute_id, attribute_name, attribute_type) VALUES (2, 'GEODATAFRAME', 'Data');")
    cursor.execute("INSERT INTO ATTRIBUTE(attribute_id, attribute_name, attribute_type) VALUES (3, 'VALUE', 'Data');")
    cursor.execute("INSERT INTO ATTRIBUTE(attribute_id, attribute_name, attribute_type) VALUES (4, 'LIST', 'Data');")
    cursor.execute("INSERT INTO ATTRIBUTE(attribute_id, attribute_name, attribute_type) VALUES (5, 'JSON', 'Data');")

    conn.commit()
    conn.close()

    return "",200

@bp.route('/insert_attribute_value_change', methods=['POST'])
def insert_attribute_value_change():
    data = request.json.get('data')
    activity_name = data.get('activity_name')

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 1. Search act ID
        cursor.execute("SELECT activity_id, input_relation_id FROM activity WHERE activity_name = ?", (activity_name,))
        activity = cursor.fetchone()
        if not activity:
            return {'message': f'Activity "{activity_name}" not found'}, 404
        activity_id, input_relation_id = activity

        cursor.execute("SELECT int_id FROM interaction ORDER BY int_id DESC LIMIT 1")
        interaction = cursor.fetchone()

        if interaction is None:
            return {'message': 'Interaction not found'}, 404

        int_id = interaction[0]

        # 2. Fetch the last attributeValue linked to the relationship


        cursor.execute("""
            SELECT re_id
            FROM relationInstance
            WHERE relation_id = ?
            ORDER BY re_id DESC
        """, (input_relation_id,))

        relation_id = [row[0] for row in cursor.fetchall()]     

        placeholders = ', '.join(['?'] * len(relation_id))

        cursor.execute(f"""
        SELECT av_id, value
        FROM attributeValue
        WHERE ri_id IN ({placeholders})
        ORDER BY av_id DESC
        """, relation_id)

        attr = cursor.fetchall()

        attr = [row for row in attr if row[1] not in (None, '')][0]

        

        if not attr:
            return {'message': 'No attribute value found for the relationship of this activity'}, 404
        av_id, old_value = attr

        # 3. Insert value change
        cursor.execute("""
            INSERT INTO attributeValueChange (av_id, int_id, old_value)
            VALUES (?, ?, ?)
        """, (av_id, int_id, old_value))
        conn.commit()

        return {'message': 'Value change successfully recorded'}, 201

    except Exception as e:
        conn.rollback()
        return {'error': str(e)}, 500

    finally:
        cursor.close()
        conn.close()


@bp.route('/insert_visualization', methods=['POST'])
def insert_visualization():
    data = request.json.get('data')
    activity_name = data.get('activity_name')

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()


    try: 
        # mapping id executions
        cursor.execute("SELECT vis_path, vis_content, activityexec_id from visualization")
        old_activityexec_id = cursor.fetchall()

        for vis in old_activityexec_id:
            # Restoring the activity IDs
            cursor.execute("SELECT activity_id FROM activityExecution WHERE activityexec_id = ? ORDER BY activityexec_id DESC LIMIT 1",
            (vis[2],))
            activity_id = cursor.fetchone()[0]
            # Fetching new execution ID
            cursor.execute("SELECT activityexec_id FROM activityExecution WHERE activity_id = ? ORDER BY activityexec_id DESC LIMIT 1",
            (activity_id,))
            activityexec_id = cursor.fetchone()[0]

            cursor.execute("""
            INSERT INTO visualization (vis_path, vis_content, activityexec_id)
            VALUES (?, ?, ?)
            """, (vis[0], vis[1], activityexec_id))
            
            
            conn.commit()            
    except: 
        pass


    try:
        # 1. Search act id
        cursor.execute("SELECT activity_id FROM activity WHERE activity_name = ? ORDER BY activity_id DESC LIMIT 1",
            (activity_name,))
        activity = cursor.fetchone()
        if not activity:
            return {'message': f'Atividade "{activity_name}" não encontrada.'}, 404
        activity_id = activity[0]

        # 2. Fetch the execution ID of the most recent activity

        cursor.execute("SELECT activityexec_id FROM activityExecution WHERE activity_id = ? ORDER BY activityexec_id DESC LIMIT 1",
            (activity_id,))
        activityExecution = cursor.fetchone()
        activityExecution_id = activityExecution[0]

        # 3. Getting the name of the visualization box

        match = re.match(r"([A-Z]+_[A-Z]+)-", activity_name)
        vis_name = match.group(1)

        # 4. Adding to the Visualization table

        cursor.execute("""
            INSERT INTO visualization (vis_path, vis_content, activityexec_id)
            VALUES (?, ?, ?)
        """, ("", vis_name, activityExecution_id))
        conn.commit()

        # 5. Deleting duplicates
        cursor.execute("""
        DELETE FROM visualization
        WHERE vis_id NOT IN (
            SELECT MIN(vis_id)
            FROM visualization
            GROUP BY activityexec_id
            )
        """)
        conn.commit()

        return {'message': 'Visualization registered successfully'}, 201

    except Exception as e:
        conn.rollback()
        return {'error': str(e)}, 500

    finally:
        cursor.close()
        conn.close()


@bp.route('/insert_interaction', methods=['POST'])
def insert_interaction():
    data = request.json.get('data')
    activity_name = data.get('activity_name')

    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:

        # 1. Search act id
        cursor.execute("SELECT activity_id FROM activity WHERE activity_name = ? ORDER BY activity_id DESC LIMIT 1",
            (activity_name,))
        activity = cursor.fetchone()
        if not activity:
            return {'message': f'Atividade "{activity_name}" não encontrada.'}, 404
        activity_id = activity[0]

        # 2. Fetch the execution ID of the most recent activity

        cursor.execute("SELECT activityexec_id FROM activityExecution WHERE activity_id = ? ORDER BY activityexec_id DESC LIMIT 1",
            (activity_id,))
        activityExecution = cursor.fetchone()
        activityExecution_id = activityExecution[0]

        # 3. Searching the visualization table

        cursor.execute("SELECT vis_id FROM visualization WHERE activityexec_id = ? ORDER BY activityexec_id DESC LIMIT 1",
            (activityExecution_id,))
        vis_id = cursor.fetchone()
        vis_id = vis_id[0]

        # 3. Inserting into the interaction table

        cursor.execute("""
            INSERT INTO interaction (int_time, user_id, vis_id)
            VALUES (?, ?, ?)
        """, (data['int_time'], "", vis_id))
        conn.commit()

        return {'message': 'Visualization successfully recorded'}, 201

    except Exception as e:
        conn.rollback()
        return {'error': str(e)}, 500

    finally:
        cursor.close()
        conn.close()


def create_template_object(folder, filename, code):
    return {
        "id": str(uuid.uuid4()),
        "type": TYPE_MAP.get(folder, "UNKNOWN"),
        "name": filename.replace(".py", "").replace("_", " "),
        "description": "",
        "accessLevel": "ANY",
        "code": code,
        "custom": True
    }

def generate_templates():
    templates = []

    for folder in TYPE_MAP.keys():
        folder_path = os.path.join(TEMPLATE_DIR, folder)

        if not os.path.isdir(folder_path):
            continue

        for file in os.listdir(folder_path):
            if file.endswith(".py"):

                with open(os.path.join(folder_path, file), "r", encoding="utf-8") as f:
                    code = f.read()

                template_obj = create_template_object(folder, file, code)
                templates.append(template_obj)

    return templates

@bp.route('/datasets', methods=['GET'])
def list_datasets():
    response = requests.get(api_address+":"+str(api_port)+"/datasets")
    response.raise_for_status() 
    files = response.json()
    return jsonify(files)
    

@bp.route("/templates", methods=["GET"])
def get_templates():
    return jsonify(generate_templates())

@bp.route('/addTemplate', methods=['POST'])
def add_template():
    data = request.get_json()

    required_fields = ['id', 'type', 'name', 'description', 'accessLevel', 'code', 'custom']
    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Missing one or more required fields'}), 400

    template_type = data['type']
    if template_type not in FOLDER_MAP:
        return jsonify({'error': f"Unknown template type: {template_type}"}), 400

    subfolder = FOLDER_MAP[template_type]
    folder_path = os.path.join(TEMPLATE_DIR, subfolder)
    os.makedirs(folder_path, exist_ok=True)

    replace_name = data['name'].replace(" ", "_")

    filename = f"{replace_name}.py"
    filepath = os.path.join(folder_path, filename)

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data['code'])
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'message': f"Template saved to {filepath}"}), 200

def get_loaded_files_metadata(folder_path):
    metadata = ""

    for file in os.listdir(folder_path):
        file_path = os.path.join(folder_path, file)
        if file.endswith(".csv"):
            df = pd.read_csv(file_path)
            columns = [f"{col} ({df[col].dtype})" for col in df.columns]
            geometry_type = "None"
        elif file.endswith(".json") or file.endswith(".geojson"):
            try:
                gdf = gpd.read_file(file_path, parse_dates=False)
                columns = [f"{col} ({gdf[col].dtype})" for col in gdf.columns]
                if "geometry" in gdf.columns:
                    geometry_type = gdf.geom_type.unique().tolist()
                else:
                    geometry_type = "None"
            except Exception:
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        columns = list(data[0].keys()) if isinstance(data, list) and data else []
                        geometry_type = "None"
                except Exception:
                    columns = []
                    geometry_type = "Unreadable JSON"
        else:
            continue
        
        metadata += f"File name: {file}\nColumns: {', '.join(columns)}\nGeometry type: {geometry_type}\n\n"

    return metadata

@bp.route('/openAI', methods=['POST'])
def llm_openaAI():
    global conversation

    data = request.get_json()

    preamble_file = data.get("preamble", None)
    prompt_file = data.get("prompt", None)
    text = data.get("text", None)
    chatId = data.get("chatId", None)

    past_conversation = []

    if chatId != None and chatId in conversation:
        past_conversation = conversation[chatId]

    prompt_preamble_file = open("./llm-prompts/"+preamble_file+".txt")
    prompt_preamble = prompt_preamble_file.read()

    prompt_preamble += "In case you need. This is the list of files and metadata currently loaded into the system"

    metadata = get_loaded_files_metadata("./")

    prompt_preamble += "\n" + metadata

    prompt_file_obj = open("./llm-prompts/"+prompt_file+".txt")
    prompt_text = prompt_file_obj.read()

    if len(past_conversation) == 0: # Adding the prompt to the conversation
        past_conversation.append({"role": "system", "content": prompt_preamble + "\n" + prompt_text})

    api_file = open("api.env")
    api_key = api_file.read()

    client = OpenAI(
        api_key=api_key
    )
    
    past_conversation.append({"role": "user", "content": text})

    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        store=True,
        messages=past_conversation
    )

    # completion = client.chat.completions.create(
    #     model="o3-mini",
    #     store=True,
    #     messages=past_conversation
    # )

    assistant_reply = completion.choices[0].message.content

    past_conversation.append({"role": "assistant", "content": assistant_reply})

    if chatId != None: # User want to save chat
        conversation[chatId] = past_conversation

    return jsonify({"result": completion.choices[0].message.content})

@bp.route('/checkUsageOpenAI', methods=['POST'])
def check_usage_OpenAI():
    global conversation
    global tokens_left
    global last_refresh

    data = request.get_json()

    preamble_file = data.get("preamble", None)
    prompt_file = data.get("prompt", None)
    text = data.get("text", None)
    chatId = data.get("chatId", None)

    past_conversation = []

    if chatId != None and chatId in conversation:
        past_conversation = conversation[chatId]

    print("Current dir", os.getcwd())

    prompt_preamble_file = open("./llm-prompts/"+preamble_file+".txt")
    prompt_preamble = prompt_preamble_file.read()

    prompt_file_obj = open("./llm-prompts/"+prompt_file+".txt")
    prompt_text = prompt_file_obj.read()

    if len(past_conversation) == 0: # Adding the prompt to the conversation
        past_conversation.append({"role": "system", "content": prompt_preamble + "\n" + prompt_text})

    past_conversation.append({"role": "user", "content": text})

    total_tokens = 0

    for message in past_conversation:
        total_tokens += len(message["content"].split()) * 1.5 # estimating the number of tokens

    print("total_tokens", total_tokens)
    print("tokens_left", tokens_left)

    now_time = time.time()

    if((now_time - last_refresh) >= 60): # One minute passed
        tokens_left = 200000

    if(tokens_left > total_tokens):
        tokens_left -= total_tokens
        return jsonify({"result": "yes"})
    
    return jsonify({"result": (60 - (now_time - last_refresh))})

@bp.route('/cleanOpenAIChat', methods=['GET'])
def clean_openai_chat():
    global conversation

    chatId = request.args.get('chatId', None)

    if chatId == None:
        return jsonify({"message": "You need to specify which chatId is being cleaned"}), 400

    conversation[chatId] = []

    return jsonify({"message": "Success"}), 200