import warnings
warnings.filterwarnings('ignore')
import rasterio
import geopandas as gpd
import pandas as pd
import json
def userCode(arg):
	import pandas as pd
	
	d = {'a': ["A", "B", "C", "D", "E", "F", "G", "H", "I"], 'b': [28, 55, 43, 91, 81, 53, 19, 87, 52]}
	df = pd.DataFrame(data=d)
	
	return df
boxType = 'DATA_LOADING'
def dumpsInput(input):
	if input['dataType'] == 'outputs':
		for key,elem in enumerate(input['data']):
			input['data'][key] = dumpsInput(elem)
		return json.dumps(input)
	else:
		return json.dumps(input)
input = ''
def parseInput(input):
    parsedInput = None
    parsedJson = json.loads(input)
    if(parsedJson['dataType'] == 'int'):
        parsedInput = int(parsedJson['data'])
    elif(parsedJson['dataType'] == 'str'):
        parsedInput = parsedJson['data']
    elif(parsedJson['dataType'] == 'float'):
        parsedInput = float(parsedJson['data'])
    elif(parsedJson['dataType'] == 'bool'):
        if(parsedJson['data'] == 'True'):
            parsedInput = True
        else:
            parsedInput = False
    elif(parsedJson['dataType'] == 'list'):
        parsedInput = json.loads(parsedJson['data'])
    elif(parsedJson['dataType'] == 'dict'):
        parsedInput = json.loads(parsedJson['data'])
    elif(parsedJson['dataType'] == 'dataframe'):
        parsedInput = pd.DataFrame.from_dict(json.loads(parsedJson['data']))
    elif(parsedJson['dataType'] == 'geodataframe'):
        loadedJson = json.loads(parsedJson['data'])
        parsedInput = gpd.GeoDataFrame.from_features(loadedJson)
        if('metadata' in loadedJson and 'name' in loadedJson['metadata']):
            parsedInput.metadata = {'name': loadedJson['metadata']['name']}
    elif(parsedJson['dataType'] == 'raster'):
        parsedInput = rasterio.open(parsedJson['data'])
    elif(parsedJson['dataType'] == 'outputs'):
        parsedInput = []
        for elem in parsedJson['data']:
            parsedInput.append(parseInput(elem))
        parsedInput = tuple(parsedInput)

    return parsedInput

# transforms the whole input into a dict (json) in depth
def toJsonInput(input):
    parsedJson = json.loads(input)
    if(parsedJson['dataType'] == 'outputs'):
        for key, elem in enumerate(parsedJson['data']):
            parsedJson['data'][key] = toJsonInput(elem)

    return parsedJson

def checkIOType(data, boxType, input=True):
    if(input):
        if(boxType == 'DATA_EXPORT' or boxType == 'DATA_CLEANING'):
            if(data['dataType'] == 'outputs'):
                if(len(data['data']) > 1):
                    raise Exception(boxType+' only supports one input')

                for elem in data['data']:
                    if(elem['dataType'] != 'dataframe' and elem['dataType'] != 'geodataframe'):
                        raise Exception(boxType+' only supports DataFrame and GeoDataFrame as input')
            else:
                if(data['dataType'] != 'dataframe' and data['dataType'] != 'geodataframe'):
                    raise Exception(boxType+' only supports DataFrame and GeoDataFrame as input')
        elif(boxType == 'DATA_TRANSFORMATION'):
            if(data['dataType'] == 'outputs'):
                if(len(data['data']) > 2):
                    raise Exception(boxType+' only supports one or two inputs')

                for elem in data['data']:
                    if(elem['dataType'] != 'dataframe' and elem['dataType'] != 'geodataframe' and elem['dataType'] != 'raster'):
                        raise Exception(boxType+' only supports DataFrame, GeoDataFrame and Raster as input')
            else:
                if(data['dataType'] != 'dataframe' and data['dataType'] != 'geodataframe' and data['dataType'] != 'raster'):
                    raise Exception(boxType+' only supports DataFrame, GeoDataFrame and Raster as input')
    else:
        if(boxType == 'DATA_LOADING' or boxType == 'DATA_CLEANING' or boxType == 'DATA_TRANSFORMATION'):
            if(data['dataType'] == 'outputs'):
                if(len(data['data']) > 1 and boxType != 'DATA_LOADING'):
                    raise Exception(boxType+' only supports one output')

                for elem in data['data']:
                    if(elem['dataType'] != 'dataframe' and elem['dataType'] != 'geodataframe' and elem['dataType'] != 'raster'):
                        raise Exception(boxType+' only supports DataFrame, GeoDataFrame and Raster as output')
            else:
                if(data['dataType'] != 'dataframe' and data['dataType'] != 'geodataframe' and data['dataType'] != 'raster'):
                    raise Exception(boxType+' only supports DataFrame, GeoDataFrame and Raster as output')
        elif(boxType == 'DATA_EXPORT'):
            raise Exception(boxType+' does not support output')

incomingInput = None

if(input != '' and input != None):
    checkIOType(toJsonInput(input), boxType)
    incomingInput = parseInput(input)
else:
    incomingInput = ''

output = userCode(incomingInput)

def parseOutput(output):
    jsonOutput = {'data': '', 'dataType': ''}
    outputType = type(output)
    if(outputType == int):
        jsonOutput['data'] = str(output)
        jsonOutput['dataType'] = 'int'
    elif(outputType == str):
        jsonOutput['data'] = output
        jsonOutput['dataType'] = 'str'
    elif(outputType == float):
        jsonOutput['data'] = str(output)
        jsonOutput['dataType'] = 'float'
    elif(outputType == bool):
        jsonOutput['data'] = str(output)
        jsonOutput['dataType'] = 'bool'
    elif(outputType == list):
        jsonOutput['data'] = json.dumps(output)
        jsonOutput['dataType'] = 'list'
    elif(outputType == dict):
        jsonOutput['data'] = json.dumps(output)
        jsonOutput['dataType'] = 'dict'
    elif(outputType == pd.core.frame.DataFrame):
        jsonOutput['data'] = json.dumps(output.to_dict())
        jsonOutput['dataType'] = 'dataframe'
    elif(outputType == gpd.geodataframe.GeoDataFrame):
        jsonOutput['data'] = output.to_json()
        if(hasattr(output, 'metadata') and 'name' in output.metadata):
            parsedGeojson = json.loads(jsonOutput['data'])
            parsedGeojson['metadata'] = {'name': output.metadata['name']}
            jsonOutput['data'] = json.dumps(parsedGeojson)
        jsonOutput['dataType'] = 'geodataframe'
    elif(outputType == rasterio.io.DatasetReader):
        jsonOutput['data'] = output.name
        jsonOutput['dataType'] = 'raster'
    elif(outputType == tuple):
        jsonOutput['data'] = []
        jsonOutput['dataType'] = 'outputs'
        for elem in list(output):
            jsonOutput['data'].append(parseOutput(elem))
    return jsonOutput

parsedOutput = parseOutput(output)

checkIOType(parsedOutput, boxType, False)

print(json.dumps(parsedOutput))
