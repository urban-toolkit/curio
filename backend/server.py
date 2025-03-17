from flask import Flask, request, send_from_directory, abort, jsonify, g
import requests
import json
from extensions import db, migrate
from models import User, UserSession
from services.google_oauth import GoogleOAuth
from middlewares import require_auth
import sqlite3

app = Flask(__name__)
address = 'localhost'
port = 5002

api_address = 'http://localhost'
api_port = 2000

# initialize database
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///urban_workflow.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)
migrate.init_app(app, db)

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

@app.after_request
def add_cors_headers(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
    return response

@app.route('/')
def root():
    abort(403)

@app.route('/upload', methods=['POST'])
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


@app.route('/processPythonCode', methods=['POST'])
def process_python_code():

    # response = requests.post(api_address+":"+str(api_port)+"/api/v2/execute", 
    #     data=json.dumps({
    #         "language": "python",
    #         "version": "3.12.0",
    #         "files": [
    #             {
    #                 "name": "test.py",
    #                 "content": request.json['code']
    #             }
    #         ]
    #     }),
    #     headers={"Content-Type": "application/json"},
    # )

    response = requests.post(api_address+":"+str(api_port)+"/exec", 
        data=json.dumps({
            "code": request.json['code']
        }),
        headers={"Content-Type": "application/json"},
    )

    return response.json()

@app.route('/toLayers', methods=['POST'])
def toLayers():

    if(request.json['geoJsons'] == None):
        abort(400, "geoJsons were not included in the post request")

    response = requests.post(api_address+":"+str(api_port)+"/toLayers", 
        data=json.dumps({
            "geoJsons": request.json['geoJsons']
        }),
        headers={"Content-Type": "application/json"},
    )

    return response.json()

@app.route('/signin', methods=['POST'])
def signin():
    # google_oauth = GoogleOAuth()
    # user_data = google_oauth.verify_token(request.json.get('token'))
    # if not user_data:
    #     return jsonify({'error': 'Invalid token'}), 400

    # user = User.query.filter_by(provider=user_data.get('provider'), provider_uid= user_data.get('uid')).first()
    # if user:
    #     user.name = user_data.get('name')
    #     user.profile_image = user_data.get('picture')
    # else:
    #     user = User(email=user_data.get('email'), name=user_data.get('name'), profile_image=user_data.get('picture'), provider=user_data.get('provider'), provider_uid=user_data.get('uid'))
    #     db.session.add(user)
    # db.session.commit()

    # create new session token
    # new_session = UserSession(user_id=user.id)
    new_session = UserSession(user_id=1)
    db.session.add(new_session)
    db.session.commit()

    # return jsonify({
    #     'user': {
    #         'name': user.name,
    #         'profile_image': user.profile_image,
    #         'type': user.type
    #     },
    #     'token': new_session.token
    # }), 200

    return jsonify({
        'user': {
            'name': 'Test',
            'profile_image': "",
            'type': 'programmer'
        },
        'token': new_session.token
    }), 200

@app.route('/getUser', methods=['GET'])
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

@app.route('/saveUserType', methods=['POST'])
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

@app.route('/saveUserProv', methods=['POST'])
def save_user_prov(): # only save if user with that name does not exist on the database
    
    conn = sqlite3.connect('provenance.db')
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

@app.route('/saveWorkflowProv', methods=['POST'])
def save_workflow_prov():
    
    conn = sqlite3.connect('provenance.db')
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

@app.route('/newBoxProv', methods=['POST'])
def new_box_prov():
    
    conn = sqlite3.connect('provenance.db')
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

    boxType = "_".join(data['activity_name'].split("_")[:-1])

    # adding a attributeRelation to each output type that this activity supports
    for outputType in outputTypesSupported[boxType]:
        cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
            VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

    # creating new activity 
    cursor.execute('''INSERT INTO activity (workflow_id, activity_name, output_relation_id, code)
                    VALUES (?, ?, ?, ?)''', (workflow_id, data['activity_name'], output_relation_id, data['code']))

    conn.commit()

    # getting all activities that point to the old workflow
    cursor.execute("SELECT activity_name, input_relation_id, output_relation_id, ve_id, code FROM activity WHERE workflow_id = ?", (old_workflow[0],))

    activities = cursor.fetchall()

    duplicated_output_relations = {} # dict of old to new ids.

    duplicated_activities_ids = [] 

    # duplicating all activities and making them point to the new workflow
    for activity in activities:

        print(activity)

        # getting the old output relation of duplicated activity 
        cursor.execute("SELECT relation_id, relation_name FROM relation WHERE relation_id = ?", (activity[2],))
        old_output_relation = cursor.fetchone()
        
        # # duplicate the old output relation
        # cursor.execute('''INSERT INTO relation (relation_name)
        #             VALUES (?)''', (old_output_relation[1],))

        # conn.commit()

        # # id of the new just added relation
        # output_relation_id = cursor.lastrowid
    
        boxType = "_".join(activity[0].split("_")[:-1])

        # # adding a attributeRelation to each output type that this activity supports
        # for outputType in outputTypesSupported[boxType]:
        #     cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
        #         VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

        # duplicated_output_relations[old_output_relation[0]] = output_relation_id # mapping old to new ids

        # cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
        #         VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], output_relation_id, activity[3],))

        cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id, code)
                VALUES (?, ?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], old_output_relation[0], activity[3], activity[4]))

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

@app.route('/updateBoxCode', methods=['POST'])
def updateBoxCode():
    conn = sqlite3.connect('provenance.db')
    cursor = conn.cursor()

    batch_data = request.json.get('data')
    if not batch_data or not isinstance(batch_data, list):
        return "Dados inválidos", 400
    
    workflow_name = batch_data[0]['workflow_name']
    
    cursor.execute("SELECT * FROM workflow WHERE workflow_id = (SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?)", (workflow_name,))
    existing_workflow = cursor.fetchone()
    
    if not existing_workflow:
        return "Workflow não encontrado", 404
    
    old_workflow_id = existing_workflow[0]
    ve_id = existing_workflow[2]

    cursor.execute("SELECT * FROM versionedElement WHERE ve_id = ?", (ve_id,))
    old_versioned_element = cursor.fetchone()
    
    cursor.execute("SELECT * FROM version WHERE version_id = ?", (old_versioned_element[1],))
    old_version = cursor.fetchone()
    
    new_version_number = str(float(old_version[1]) + 1.0)
    
    cursor.execute('''INSERT INTO version (version_number) VALUES (?)''', (new_version_number,))
    conn.commit()
    version_id = cursor.lastrowid
    
    cursor.execute("INSERT INTO versionedElement (previous_ve_id, version_id) VALUES (?, ?)", (ve_id, version_id))
    conn.commit()
    new_ve_id = cursor.lastrowid
    
    cursor.execute("INSERT INTO workflow (workflow_name, ve_id) VALUES (?, ?)", (workflow_name, new_ve_id))
    conn.commit()
    new_workflow_id = cursor.lastrowid

    cursor.execute("SELECT activity_id, activity_name, input_relation_id, output_relation_id, ve_id, code FROM activity WHERE workflow_id = ?", (old_workflow_id,))
    activities = {a[1]: a for a in cursor.fetchall()}  # Dicionário para facilitar a busca por activity_name

    for activity_name, (activity_id, _, input_relation_id, output_relation_id, ve_id, old_code) in activities.items():
        new_code = next((item['code'] for item in batch_data if item['activity_name'] == activity_name), old_code)
        cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id, code)
                          VALUES (?, ?, ?, ?, ?, ?)''', (new_workflow_id, activity_name, input_relation_id, output_relation_id, ve_id, new_code))
    
    conn.commit()
    conn.close()
    return "", 200



@app.route('/deleteBoxProv', methods=['POST'])
def delete_box_prov():
    
    # // new version (increment version number based on previous old workflow that points to a ve that points to the version)
    # // new versioned element (pointing to the versioned element of the old workflow and pointing to the new version)
    # // new workflow
    # // point new workflow to the new versioned element
    # // duplicate all activities (but the excluded box) that point to the old workflow and point to the new one
    
    conn = sqlite3.connect('provenance.db')
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

            boxType = "_".join(activity[0].split("_")[:-1])
        
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

@app.route('/newConnectionProv', methods=['POST'])
def new_connection_prov():
    
    conn = sqlite3.connect('provenance.db')
    cursor = conn.cursor()

    data = request.json.get('data')

    # // new version (increment version number based on previous old workflow that points to a ve that points to the version)
    # // new versioned element (pointing to the versioned element of the old workflow and pointing to the new version)
    # // new workflow
    # // point new workflow to the new versioned element
    # // duplicate all activities that point to the old workflow and point to the new one (duplicate relations tied to activities)
    # // update input relation of the activity

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
    cursor.execute("SELECT activity_name, input_relation_id, output_relation_id, ve_id, code FROM activity WHERE workflow_id = ?", (old_workflow[0],))

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

        boxType = "_".join(activity[0].split("_")[:-1])
    
        # # adding a attributeRelation to each output type that this activity supports
        # for outputType in outputTypesSupported[boxType]:
        #     cursor.execute('''INSERT INTO attributeRelation (attribute_id, relation_id)
        #         VALUES (?, ?)''', (attributeIds[outputType], output_relation_id,))

        # duplicated_output_relations[old_output_relation[0]] = output_relation_id # mapping old to new ids

        # cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id)
        #         VALUES (?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], output_relation_id, activity[3],))

        cursor.execute('''INSERT INTO activity (workflow_id, activity_name, input_relation_id, output_relation_id, ve_id, code)
                VALUES (?, ?, ?, ?, ?, ?)''', (workflow_id, activity[0], activity[1], old_output_relation[0], activity[3], activity[4]))

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

    # get the source activity of the connection
    cursor.execute("SELECT output_relation_id FROM activity WHERE workflow_id = ? AND activity_name = ?", (workflow_id, data['sourceNodeType']+"_"+data['sourceNodeId'],))
    source_activity = cursor.fetchone()

    # update input relation of the activity
    cursor.execute("UPDATE activity SET input_relation_id = ? WHERE workflow_id = ? AND activity_name = ?", (source_activity[0], workflow_id, data['targetNodeType']+"_"+data['targetNodeId'],))

    conn.commit()
    conn.close()

    return "",200

@app.route('/deleteConnectionProv', methods=['POST'])
def delete_connection_prov():
    
    conn = sqlite3.connect('provenance.db')
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

        boxType = "_".join(activity[0].split("_")[:-1])

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
    cursor.execute("UPDATE activity SET input_relation_id = NULL WHERE workflow_id = ? AND activity_name = ?", (workflow_id, data['targetNodeType']+"_"+data['targetNodeId'],))

    conn.commit()
    conn.close()

    return "",200

@app.route('/boxExecProv', methods=['POST'])
def box_exec_prov():
    
    conn = sqlite3.connect('provenance.db')
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

    for input_attribute in input_attributes:
        # creating attributeValues
        cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
                        VALUES (?, ?, ?)''', (input_attribute[0], input_ri_id, data['types_input'][input_attribute[1]],))

        conn.commit()

    for output_attribute in output_attributes:
        # creating attributeValues
        cursor.execute('''INSERT INTO attributeValue (attribute_id, ri_id, value)
                        VALUES (?, ?, ?)''', (output_attribute[0], output_ri_id, data['types_output'][output_attribute[1]],))

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

@app.route('/getBoxGraph', methods=['POST'])
def get_box_graph():
    
    conn = sqlite3.connect('provenance.db')
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

@app.route('/truncateDBProv', methods=['GET'])
def truncate_db_prov():
    
    conn = sqlite3.connect('provenance.db')
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

@app.route('/getTemplates', methods=['GET'])
def get_templates():
    conn = sqlite3.connect('template.db')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM template")
    templates = cursor.fetchall()

    conn.close()

    templates_list = []
    for template in templates:
        templates_list.append({
            "id": template[0],
            "name": template[1],
            "type": template[2],
            "description": template[3],
            "accessLevel": template[4],
            "code": template[5],
            "custom": bool(template[6])
        })

    return jsonify(templates_list), 200

@app.route('/registerTemplate', methods=['POST'])
def register_template():
    data = request.json

    required_fields = ['name', 'type', 'description', 'accessLevel', 'code', 'custom']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"'{field}' é obrigatório."}), 400

    conn = sqlite3.connect('template.db')
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO template (id, name, type, description, accessLevel, code, custom)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            data['id'],  
            data['name'],
            data['type'],
            data['description'],
            data['accessLevel'],
            data['code'],
            int(data['custom'])  
        ))

        conn.commit()

        return jsonify({"message": "Template registrado com sucesso."}), 201

    except sqlite3.Error as e:
        print(e)
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

@app.route('/updateTemplate/<string:id>', methods=['PUT'])
def update_template(id):
    data = request.json

    required_fields = ['name', 'type', 'description', 'accessLevel', 'code', 'custom']
    for field in required_fields:
        if field not in data:
            return jsonify({"error": f"'{field}' is mandatory."}), 400

    conn = sqlite3.connect('template.db')
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE template
            SET name = ?, type = ?, description = ?, accessLevel = ?, code = ?, custom = ?
            WHERE id = ?
        """, (
            data['name'],
            data['type'],
            data['description'],
            data['accessLevel'],
            data['code'],
            int(data['custom']),  
            id
        ))

        if cursor.rowcount == 0:
            return jsonify({"error": "Template not found."}), 404

        conn.commit()

        return jsonify({"message": "Template updated successfully."}), 200

    except sqlite3.Error as e:
        print(e)
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()


@app.route('/deleteTemplate/<string:id>', methods=['DELETE'])
def delete_template(id):
    conn = sqlite3.connect('template.db')
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM template WHERE id = ?", (id,))

        if cursor.rowcount == 0:
            return jsonify({"error": "Template not found."}), 404

        conn.commit()

        return jsonify({"message": "Template deleted successfully."}), 200

    except sqlite3.Error as e:
        print(e)
        conn.rollback()
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

@app.route('/getWorkflowNames', methods=['GET'])
def get_workflow_names():
    conn = sqlite3.connect('provenance.db')
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT workflow_id, workflow_name
            FROM workflow
            WHERE workflow_id IN (
                SELECT MAX(workflow_id)
                FROM workflow
                GROUP BY workflow_name
            )
            ORDER BY workflow_id DESC
        """)
        workflows = cursor.fetchall()

        if not workflows:
            return jsonify({"message": "No workflows found."}), 404

        return jsonify({"workflows": [{"id": workflow[0], "name": workflow[1]} for workflow in workflows]}), 200

    except sqlite3.Error as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()
        
@app.route('/updateActivityCode', methods=['POST'])
def update_activity_code():
    data = request.get_json()
    activity_name = data.get("activity_name")
    new_code = data.get("code")

    print(new_code)
    print(activity_name)

    if not activity_name or new_code is None:
        return jsonify({"error": "Missing activity_name or code"}), 400

    conn = sqlite3.connect('provenance.db')
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT activity_id FROM activity
            WHERE activity_name = ?
            ORDER BY activity_id DESC
            LIMIT 1
        """, (activity_name,))
        row = cursor.fetchone()

        if not row:
            return jsonify({"error": "Activity not found"}), 404

        activity_id = row[0]

        cursor.execute("""
            UPDATE activity
            SET code = ?
            WHERE activity_id = ?
        """, (new_code, activity_id))
        conn.commit()

        return jsonify({"message": "Code updated successfully"}), 200

    except sqlite3.Error as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()

@app.route('/getActivitiesByWorkflowIds', methods=['GET'])
def get_activities_by_workflow_ids():
    workflow_ids = request.args.getlist("workflow_id")

    if not workflow_ids:
        return jsonify({"error": "Missing workflow_ids"}), 400

    conn = sqlite3.connect('provenance.db')
    cursor = conn.cursor()

    try:
        placeholders = ','.join(['?'] * len(workflow_ids))
        cursor.execute(f"""
            SELECT * FROM activity
            WHERE workflow_id IN ({placeholders})
        """, workflow_ids)
        rows = cursor.fetchall()

        if not rows:
            return jsonify({"error": "Activities not found"}), 404

        result = [dict(zip([column[0] for column in cursor.description], row)) for row in rows]
        return jsonify(result), 200

    except sqlite3.Error as e:
        print(e)
        return jsonify({"error": str(e)}), 500

    finally:
        conn.close()



if __name__ == '__main__':
    app.run(host=address, port=port, threaded=False)