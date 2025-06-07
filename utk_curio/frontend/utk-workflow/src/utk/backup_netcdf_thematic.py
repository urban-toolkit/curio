from pyproj import Transformer
import xarray as xr
import json
from netCDF4 import Dataset
import numpy as np
import os
import math

# from wrf import getvar, interplevel, to_np, ALL_TIMES

# def thematic_from_netcdf(file_path, variables, coords, layer_id, operations=[], time_indexes=[], bbox={}):
#     def cdiff(scalar, axis=0):
#         '''
#         Performs the same as GrADS function cdiff()
#         http://cola.gmu.edu/grads/gadoc/gradfunccdiff.html
#         The scalar quantity must by 2D.
#         The finite differences calculation ignores the borders, where np.nan is returned.
#         '''
#         # Check if 2D
#         dimScalar = np.size(np.shape(scalar))
#         if dimScalar != 2:
#             print(
#                 "Pystuff Error: scalar must have only 2 dimensions, but it has %d." % dimScalar)
#             return

#         # Length of each dimension
#         lendim0 = np.shape(scalar)[0]
#         lendim1 = np.shape(scalar)[1]

#         # Initialize output var
#         out = np.zeros(np.shape(scalar))
#         out.fill(np.nan)

#         # Centered finite differences
#         for x in np.arange(1, lendim0-1):
#             for y in np.arange(1, lendim1-1):
#                 if axis == 0:
#                     out[x, y] = scalar[x+1, y]-scalar[x-1, y]
#                 elif axis == 1:
#                     out[x, y] = scalar[x, y+1]-scalar[x, y-1]
#                 else:
#                     print(
#                         "Pystuff Error: Invalid axis option. Must be either 0 or 1.")
#                     return
#         return out
    
#     def hdivg(_u, _v, _lat, _lon, _r=6.371*(10**6)):
#         '''
#         Calculates the horizontal divergence (du/dx+dv/dy) exactly like GrADS. 
#         lat and lon are 1D arrays.
#         http://cola.gmu.edu/grads/gadoc/gradfunccdiff.html
#         '''
#         latv, lonv = np.meshgrid(_lat, _lon, indexing='ij')

#         # r = 
#         dtr = np.pi/180
#         dudx = cdiff(_u, axis=1)/cdiff(lonv*dtr, axis=1)
#         dvdy = cdiff(_v*np.cos(latv*dtr), axis=0)/cdiff(latv*dtr, axis=0)
#         out = (dudx + dvdy)/(_r*np.cos(latv*dtr))
#         return out
    
#     ncData = Dataset(file_path)
    
#     lat_arr = []
#     lon_arr = []

#     if len(ncData.variables[coords['lat']].shape) == 1:
#         lat_arr = ncData.variables[coords['lat']]
    
#     else:
#         lat_matrix = ncData.variables[coords['lat']][:][0]
#         lat_arr = np.array([row[0] for row in lat_matrix] )

#     if len(ncData.variables[coords['lon']].shape) == 1:
#         lon_arr = ncData.variables[coords['lon']]
    
#     else:
#         lon_arr = ncData.variables[coords['lon']][:][0][0]

#     min_lat_idx = 0
#     max_lat_idx = len(lat_arr)-1
        
#     min_lon_idx = 0
#     max_lon_idx = len(lon_arr)-1

#     if bbox:
#         min_lat_idx = None
#         max_lat_idx = None
            
#         min_lon_idx = None
#         max_lon_idx = None

#         for i in range(len(lat_arr)):
#             if min_lat_idx is None and lat_arr[i] >= bbox['min_lat'] >=bbox['min_lat']:
#                 min_lat_idx = i

#             elif max_lat_idx is None and lat_arr[i] >= bbox['max_lat'] >=bbox['max_lat']:
#                 max_lat_idx = i
#                 break

#         for i in range(len(lon_arr)):
#             if min_lon_idx is None and lon_arr[i] >= bbox['min_lon'] >=bbox['min_lon']:
#                 min_lon_idx = i

#             elif max_lon_idx is None and lon_arr[i] >= bbox['max_lon'] >=bbox['max_lon']:
#                 max_lon_idx = i
#                 break


#         # lat_idxs = [i for i in range(len(lat_arr)) if lat_arr[i] >= bbox['min_lat'] and lat_arr[i] <= bbox['max_lat']]
#         # lon_idxs = [j for j in range(len(lon_arr)) if lon_arr[j] >= bbox['min_lon'] and lon_arr[j] <= bbox['max_lon']]
    
#         # min_lat_idx = lat_idxs[0]
#         # max_lat_idx = lat_idxs[-1]
        
#         # min_lon_idx = lon_idxs[0]
#         # max_lon_idx = lon_idxs[-1]

# ############################################################################################
    
#     # data = ncData.variables[variables[0]['name']][:]
#     # new_data = np.array(data, copy=True)

#     # # addition = lambda a, b: a + b
#     # # multiplication = lambda a, b: a * b
#     # # division = lambda a, b: a / b

#     #############################################################################
#     final_data = []

#     for operation in operations:
#         if operation['type'] == 'vector':
#             if operation['dimension'] == 'space':
#                 if operation['function'] == 'sum':
#                     for v in variables:
#                         var_name = v['name']
#                         final_data = ncData.variables[v['name']][:] if len(final_data) == 0 else final_data + ncData.variables[v['name']][:]

#                 elif operation['function'] == 'interpolation':
#                     pressure   = [v for v in variables if v['key'] == 'pressure'][0]
#                     pressure_name = pressure['name']
                    
#                     var_name = [v['name'] for v in variables if v['key'] != 'pressure'][0]

#                     time_idxs = list(range(5))
#                     level = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_0'][0]

#                     for tidx in time_idxs:
#                         pressure_matrix = getvar(ncData, pressure_name, timeidx=tidx,
#                                     squeeze=False, meta=False)
                        
#                         var_matrix = getvar(ncData, var_name, timeidx=tidx,
#                         squeeze=False, meta=False)
                        
#                         var_matrix = to_np(interplevel(var_matrix, pressure_matrix, level))

#                         if np.ma.isMaskedArray(var_matrix):
#                             var_matrix = list(var_matrix)
#                         final_data.append(var_matrix)

#                     final_data = np.array(final_data)

#                 elif operation['function'] == 'calculate_wind':
#                     pressure   = [v for v in variables if v['key'] == 'pressure'][0]
#                     pressure_name = pressure['name']

#                     u_name = [v['name'] for v in variables if v['key'] == 'u'][0]
#                     v_name = [v['name'] for v in variables if v['key'] == 'v'][0]

#                     time_idxs = list(range(5))
#                     level = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_0'][0]

#                     for tidx in time_idxs:
#                         pressure = getvar(ncData, pressure_name, timeidx=tidx,
#                                     squeeze=False, meta=False)
                        
#                         u = getvar(ncData, u_name, timeidx=tidx,
#                                     squeeze=False, meta=False)
                        
#                         v = getvar(ncData, v_name, timeidx=tidx,
#                                     squeeze=False, meta=False)
                        
#                         # to do

#                 elif operation['function'] == 'calculate_hdiv':
#                     pressure   = [v for v in variables if v['key'] == 'pressure'][0]
#                     pressure_name = pressure['name']

#                     u_name = [v['name'] for v in variables if v['key'] == 'u'][0]
#                     v_name = [v['name'] for v in variables if v['key'] == 'v'][0]

#                     time_idxs = list(range(5))
#                     level = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_0'][0]

#                     for t in range(len(time_idxs)):
#                         u = getvar(ncData, u_name, timeidx=t, squeeze=False, meta=False)
#                         v = getvar(ncData, v_name, timeidx=t, squeeze=False, meta=False)
#                         pressure = getvar(ncData, pressure_name, timeidx=t,
#                                 squeeze=False, meta=False)
                        
#                         u_interp = to_np(interplevel(u, pressure, level))
#                         v_interp = to_np(interplevel(v, pressure, level))

#                         hdiv = hdivg(u_interp, v_interp, lat_arr, lon_arr)
#                         final_data.append(hdiv)
                             
#                 elif operation['function'] == 'calculate_kidx':
#                     pressure   = [v for v in variables if v['key'] == 'pressure'][0]
#                     pressure_name = pressure['name']

#                     tc_name = [v for v in variables if v['key'] == 'tc'][0]
#                     rh_name = [v for v in variables if v['key'] == 'rh'][0]

#                     level_0 = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_0' ]
#                     level_1 = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_1' ]
#                     level_2 = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'level_2' ]

#                     a = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'a']
#                     b = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'b']
#                     mv = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'mv']
#                     le = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'le']
#                     r = [p['value'] for p in operation['parameters'] if operation['parameters']['name'] == 'r']

#                     for t in range(len(time_idxs)):
                    
#                         tc = getvar(ncData, tc_name, timeidx=t, squeeze=False, meta=False)
#                         rh = getvar(ncData, rh_name, timeidx=t, squeeze=False, meta=False)
#                         pressure = getvar(ncData, pressure_name, timeidx=t, squeeze=False, meta=False)

#                         tc_interp_0 = to_np(interplevel(tc, pressure, level_0))
#                         tc_interp_1 = to_np(interplevel(tc, pressure, level_1))
#                         tc_interp_2 = to_np(interplevel(tc, pressure, level_2))

#                         rh_interp_0 =  to_np(interplevel(tc, pressure, level_0))
#                         rh_interp_1 =  to_np(interplevel(tc, pressure, level_1))

#                         arr = []

#                         for i in range(len(lat_arr)):
#                             row_arr = []

#                             for j in range(len(lon_arr)):
#                                 t1 = tc_interp_0[i][j]
#                                 t2 = tc_interp_1[i][j]
#                                 t4 = tc_interp_2[i][j]

#                                 rh_0 = rh_interp_0[i][j]
#                                 rh_1 = rh_interp_1[i][j]

#                                 e3 = a * math.exp((mv*le/r) * ((1/b) - (1/(t1+b))))
#                                 e5 = a * math.exp((mv*le/r) * ((1/b) - (1/(t4+b))))
                                
#                                 es3 = rh_0[i][j]*e3/100
#                                 es5 = rh_1[i][j]*e5/100

#                                 td3 = 1/(1/b-(r/(mv*le)) * math.log10(es3/a)) - k
#                                 td5 = 1/(1/b-(r/(mv*le)) * math.log10(es5/a)) - k

#                                 t3 = td3
#                                 t5 = td5

#                                 k = t1-t2+t3-t4+t5

#                                 row_arr.append(k)
#                             arr.append(row_arr)
#                         final_data.append(arr)
#                     final_data = np.array(final_data)
            
#             elif operation['dimension'] == 'time':
#                 if operation['function'] == 'accumulate':
#                     interval = operation['parameters'][0]
#                     final_data = [final_data[t] + final_data[t + interval] for t in range(0, len(final_data), interval)]
                
#                 elif operation['function'] == 'unaccumulate':
#                     interval = operation['parameters'][0]
#                     final_data = [final_data[t] - final_data[t - interval] for t in range(len(final_data), 0-1, interval)]

#                 elif operation['function'] == 'avg':
#                     final_data = [final_data[t] - final_data[t - interval] for t in range(len(final_data), 0-1, interval)]

#         elif operation['type'] == 'vector_to_scalar':
#             if len(final_data) == 0:
#                 final_data = ncData.variables[variables[0]['name']][:]
            
#             if operation['function'] == 'avg':
#                 func = lambda x: np.mean(x)
#                 arr = [func(matrix) for matrix in final_data]

#                 final_data = np.array(arr)
        
#         elif operation['type'] == 'scalar':
#             if len(final_data) == 0:
#                 new_data = ncData.variables[variables[0]['name']][:]
            
#             for matrix in new_data:
#                 for row in matrix:
#                     for i in range(len(row)):
#                         apply_scalar = eval(operation['function'])
#                         row[i] = float(round(apply_scalar(row[i], operation['value']), 2))


#     # rainc = ncData.variables['RAINC'][:]
#     # rainnc = ncData.variables['RAINNC'][:]
    
#     # print(rainc[4][0][0], rainnc[4][0][0], new_data[4][0][0])

    

############################################################################################


    # points = []
    # values = []

    # for latidx in range(min_lat_idx, max_lat_idx + 1):
    #     for lonidx in range(min_lon_idx, max_lon_idx + 1):
    #         points.append((lat_arr[latidx], lon_arr[lonidx]))
    #         pt_arr = []
            
    #         for tidx in range(len(data)):
    #             pt_arr.append(float(data[tidx][latidx][lonidx]))

    #         values.append(pt_arr)

    # coordinates = []
    # transformer = Transformer.from_crs(coords['proj'], 3395)

    # for point in transformer.itransform(points):
    #     coordinates.append(float(point[0]))
    #     coordinates.append(float(point[1]))
    #     coordinates.append(0)

    # abstract_json = {
    #     "id": layer_id,
    #     "coordinates": coordinates,
    #     "values": values
    # }

    # json_object = json.dumps(abstract_json)

    # directory = os.path.dirname(file_path)

    # with open(os.path.join(directory,layer_id+".json"), "w") as outfile:
    #     outfile.write(json_object)
    

  
    
    
    # if len(variables'] == 1):
    #     var_name = variables'][0]['name']
    #     var_unit = variables'][0]['unit']
    #     var_level = variable'][0]['level']
    #     var_key   = variable'][0]['key']


if __name__ == '__main__':   
    # myobj = json.load(open("./netcdf_grammarv1.json") )


    file_path = "../../examples/wrf_chicago/wrfout_d03_2023-06-09_20_00_00"
    variables = [ #'RAINC', 'RAINNC'
        # {
        #     "name": "T2",
        #     "level": "",
        #     "unit": "C",
        #     "key": ""
        # }
            {
                "name": 'pressure',
                "key": 'pressure',
            },
            {
                "name": 'u',
                "key": 'u',
            },
            {
                "name": 'v',
                "key": 'v',
            }

    ]

    coords = {
        "lat": "XLAT",
        "lon": "XLONG",
        "proj": 4326,
    }

    bbox = {
            "min_lat": 33,
            "min_lon": -94,
            "max_lat": 42,
            "max_lon": -81
        }

    # operations = {
    #         "scalar": [ 
    #             # {
    #             #     "name": "addition",
    #             #     "value": -273,
    #             # },
    #             # {
    #             #     "name": "multiplication",
    #             #     "value": 2,
    #             # },
    #             # {
    #             #     "name": "division",
    #             #     "value": 3,
    #             # },
    #             {
    #                 "name": "lambda x, l: (x + l[0]) * l[1]",
    #                 "value": [ -273, 2],
    #             }

    #         ],

    #         "vector": [
    #             # {
    #             #     "name": "",
    #             #     "parameters" : {
    #             #         "name": "",
    #             #         "value": ""

    #             #     }
    #             # }
    #         ]
    #     }

    # operations = {
    #     "scalar": {
    #         "function": "lambda x, l: (x + l[0]) * l[1]",
    #         "parameters": [-273, 2]
    #     },

    #     "vector" : {
    #         "type": "between_variables",
    #         "function": "lambda x, y: x + y",
    #         "parameters": [],
    #     }
        
        
    # }

    operations = [
        {
            "type": "vector",
            "dimension": "space",
            "function": "calculate_wind",
            "parameters": [
                {
                    "name": "level",
                    "value": 850
                }

            ],
        },
        # {
        #     "type": "vector",
        #     "dimension": "space",
        #     "function": "sum",
        #     "parameters": [],
        # },
        # {
        #     "type": "scalar",
        #     "function": "lambda x, l: (x + l[0]) * l[1]",
        #     "parameters": [-273, 2]
        # },
    ]

    time_indexes = []
    layer_id = "wrfout_d03_2023-06-09_20_00_00_T2"

    # thematic_from_netcdf(file_path, variables, coords, operations, time_indexes, bbox)
    # thematic_from_netcdf(file_path, variables, coords, layer_id, operations)

    # def test():
        

    # test = lambda : print('hey')
    # a = eval('test')

    # a()
    
    # addMatrix = np.arange(3.0)
    # print(addMatrix)

# add_matrix = np.full((2, 3, 5), 7)
# print(add_matrix)