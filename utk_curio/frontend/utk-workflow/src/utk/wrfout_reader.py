import os
import sys
import json
import numpy as np
from netCDF4 import Dataset
from termcolor import colored
# from wrf import getvar, interplevel, to_np, ALL_TIMES
from pyproj import Transformer
# import xarray as xr

# class WRFOutputReader(object):
#     def __init__(self) -> None:
#         self.__className = "WRFOutputReader"
#         self.__variablesList = ('PM10', 'so2', 'co', 'o3', 'PM2_5_DRY', 'no', 'no2', 'no3', 'T2', 'rh', 'wind10m', 'accRain', '3hRain', '24hRain')
#         self.resetClass()
        
#     def __processRain(self, time_idxs, interval):
#         rainc = self.__ncData.variables['RAINC'][:]
#         rainnc = self.__ncData.variables['RAINNC'][:]

#         accRain = rainc + rainnc

#         data = []

#         if not interval:
#             data = accRain if len(time_idxs) == 0 else np.array(accRain[t] for t in time_idxs)

#         else:
#             if len(time_idxs) == 0:
#                 data = [accRain[t] - accRain[t - interval] for t in range(0, self.__nTimes, interval)]

#             else:
#                 for t in time_idxs:
#                     if t - interval >= 0:
#                         data.append(accRain[t] - accRain[t - interval])
            
#             # elif all(t - interval >= 0 for t in time_idxs):
#             #     data = [accRain[t] - accRain[t - interval] for t in time_idxs]
                
#             # else:
#             #     msg = f"[{self.__className} - __processRain() - Negative time step.]"
#             #     raise ValueError(colored(msg, 'red'))
            
#             data = np.array(data)

#         return data

#     def __process4DVariable(self, var_key, level, time_idxs):
#         data = []

#         if len(time_idxs) == 0: time_idxs = range(self.__nTimes)

#         for t in time_idxs:
#             var_matrix = getvar(self.__ncData, var_key, timeidx=t,
#                         squeeze=False, meta=False)
#             pressure_matrix = getvar(self.__ncData, 'pressure', timeidx=t,
#                         squeeze=False, meta=False)

#             var_matrix = to_np(interplevel(var_matrix, pressure_matrix, level))

#             if np.ma.isMaskedArray(var_matrix):
#                 var_matrix = list(var_matrix)
#                 # var_matrix.reverse()
#             data.append(var_matrix)


#         data = np.array(data)
#         return data
    
#     def __processWind10m(self, level, time_idxs):
#         data = []
        
#         if len(time_idxs) == 0: time_idxs = range(self.__nTimes)

#         for t in time_idxs:
#             pressure_matrix = getvar(self.__ncData, 'pressure', timeidx=t,
#                 squeeze=False, meta=False)
#             u10_matrix = getvar(self.__ncData, 'u10', timeidx=t,
#                         squeeze=False, meta=False)
#             v10_matrix = getvar(self.__ncData, 'v10', timeidx=t,
#                         squeeze=False, meta=False)
#             wspd = ''
    
#     def getGridId(self):
#         return self.__gridId
    
#     def getStartDate(self):
#         return self.__startDate
    
#     def getGridDimensions(self):
#         return self.__nLat, self.__nLon

#     def getNTimes(self):
#         return self.__nTimes
    
#     def getVariableData(self, var_key, time_idxs, var_level=None):
#         active_var = None
#         data = []

#         # Set active_var
#         for i in range(len(self.__variablesList)):
#             if var_key.lower() == self.__variablesList[i].lower(): 
#                 active_var = self.__variablesList[i]
#                 break
        
#         # Set data according to the variable
#         if active_var:
#             if 'Rain' in active_var:
#                 interval = None
#                 if active_var == '3hRain':
#                     interval = 3
#                 elif active_var == '24hRain':
#                     interval = 24
#                 self.__processRain(time_idxs, interval)

#             elif active_var == 'T2':
#                 data = self.__ncData.variables[active_var][:] if len(time_idxs) == 0 else np.array([self.__ncData.variables[active_var][t] for t in time_idxs])
#                 data -= 273 # Kelvin to Celsius
            
#             elif active_var == 'wind10m':
#                 # to do
#                 # https://medium.com/the-barometer/plotting-wrf-data-using-python-wrf-python-and-cartopy-edition-b7bf45ff46bb
#                 data = []

#             else:
#                 data = self.__process4DVariable(active_var, var_level, time_idxs)
                    
#         else:
#             sys.exit()
              
#         return data
    
#     def getLatLon(self):
#         return self.__latList, self.__lonList
    
#     def setNcData(self, ncFilePath):
#         try:
#             self.__ncData = Dataset(ncFilePath)

#         except Exception as error:
#             msg = f"[{self.__className} - setNcData]\n{error}"
#             print(colored(f"{msg}", 'red'))
#             sys.exit()

#     def resetClass(self):
#         self.__ncData = None
      
#         self.__latList = None
#         self.__lonList = None

#         self.__nLat = None
#         self.__nLon = None

#         self.__nTimes = None
#         self.__gridId = None
#         self.__startDate = None
    
#     def setAttributes(self):
#         # latMatrix = sorted(self.__ncData.variables['XLAT'][:][0], key=lambda x: x[0], reverse=True)
#         latMatrix = self.__ncData.variables['XLAT'][:][0]
#         lonMatrix = self.__ncData.variables['XLONG'][:][0]
        
#         self.__latList = np.array([row[0] for row in latMatrix])
#         self.__lonList = np.array(lonMatrix[0])

#         self.__nLat = self.__ncData.dimensions['south_north'].size
#         self.__nLon = self.__ncData.dimensions['west_east'].size

#         self.__nTimes = self.__ncData.dimensions['Time'].size

#         self.__gridId = self.__ncData.GRID_ID
#         self.__startDate = self.__ncData.SIMULATION_START_DATE.replace(":", "")

#         # for k in self.__ncData.variables.keys(): print(k)
#         for k in self.__ncData.variables.keys(): print(k)
 
# def thematic_from_netcdf(model, file, file_path, target_variables, coordinates_projection, time_idxs=[], bbox=[]):
#     transformer = Transformer.from_crs(coordinates_projection, 3395)
#     ncReader = None

#     # Set ncReader
#     if model.lower() == 'wrf':
#         ncReader = WRFOutputReader()
    
#     ncReader.setNcData(file_path)
#     ncReader.setAttributes()

#     start_date = ncReader.getStartDate()
#     grid_id = ncReader.getGridId()

#     lat_array, lon_array = ncReader.getLatLon()

#     n_lat, n_lon = ncReader.getGridDimensions()
#     # n_times = ncReader.getNTimes()

#     lat_idxs = range(n_lat)
#     lon_idxs = range(n_lon)
    
#     latmin_idx = 0
#     latmax_idx = n_lat-1
        
#     lonmin_idx = 0
#     lonmax_idx = n_lon-1

#     time_idxs.sort()
    
#     if len(bbox) > 0:

#         latmin, lonmin = bbox[0], bbox[1]
#         latmax, lonmax = bbox[2], bbox[3]

#         lat_idxs = [i for i in range(n_lat) if lat_array[i] >= latmin and lat_array[i] <= latmax]
#         lon_idxs = [j for j in range(n_lon) if lon_array[j] >= lonmin and lon_array[j] <= lonmax]
    
#         latmin_idx = lat_idxs[0]
#         latmax_idx = lat_idxs[len(lat_idxs)-1]
        
#         lonmin_idx = lon_idxs[0]
#         lonmax_idx = lon_idxs[len(lon_idxs)-1]

#     try:
#         points = []

#         for latidx in range(latmin_idx, latmax_idx + 1):
#             for lonidx in range(lonmin_idx, lonmax_idx + 1):
#                 points.append((lat_array[latidx], lon_array[lonidx]))

#         coordinates = []

#         for point in transformer.itransform(points):
#             coordinates.append(float(point[0]))
#             coordinates.append(float(point[1]))
#             coordinates.append(0)

#     except Exception as error:
#             msg = f"[thematic_from_wrf]\n{error}"
#             print(colored(f"{msg}", "red"))
#             sys.exit()
    
    
#     for var_obj in target_variables:
#         var_key   = var_obj.get('variable')
#         var_level = var_obj.get('level')

#         values = []
#         layer_id = f"{file}_{var_key}"
        
#         data = ncReader.getVariableData(var_key, time_idxs, var_level)
        
#         try:
#             for latidx in range(latmin_idx, latmax_idx + 1):
#                 for lonidx in range(lonmin_idx, lonmax_idx + 1):
#                     pt_arr = [round(float(matrix[latidx][lonidx]), 2) for matrix in data]
#                     values.append(pt_arr)
        
#             abstract_json = {
#                 "id": layer_id,
#                 "coordinates": coordinates,
#                 "values": values
#             }

#             json_object = json.dumps(abstract_json)

#             directory = os.path.dirname(filepath)

#             with open(os.path.join(directory,layer_id+".json"), "w") as outfile:
#                 outfile.write(json_object)

#         except Exception as error:
#             msg = f"[thematic_from_wrf]\n{error}"
#             print(colored(f"{msg}", "red"))
#             sys.exit()


if __name__ == '__main__':
    # path = f'../../examples/wrf_chicago'
    # startDate = "2016-07-01"
    # gId = "2"

    # filepath = f"{path}/wrfout_d0{gId}_{startDate}.nc"

    path = f'../../examples/wrf_chicago'
    startDate = "2023-06-09_20_00_00"
    gId = "3"

    file = f"wrfout_d0{gId}_{startDate}"
    filepath = f"{path}/{file}"
    # filepath = f"{path}/wrfout_d03_2023-06-09_20_00_00.nc"

    # obj1 = {'variable': 'T2', 'level': None}
    # obj2 = {'variable': 'rh', 'level': 850}
    # obj3 = {'variable': '3hRain', 'level': None}
    # varList = [obj1, obj2, obj3]

    obj1 = {'variable': 'T2', 'level': None}
    obj2 = {'variable': 'rh', 'level': 850}
    obj3 = {'variable': '3hRain', 'level': None}
    varList = [obj3]

    # thematic_from_netcdf('wrf', file, filepath, varList, 4326)
    # thematic_from_netcdf('wrf', file, filepath, varList, 4326, [t for t in range(1, 5)], [33, -94, 42, -81])
    # thematic_from_netcdf('wrf', file, filepath, varList, 4326, list(range(0, 2)), [33, -94, 42, -81])
    # thematic_from_netcdf('wrf', file, filepath, varList, 4326)
    