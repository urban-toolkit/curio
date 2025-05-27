import sys
import numpy as np
import xarray as xr

from netCDF4 import Dataset
from termcolor import colored
# from wrf import getvar, interplevel, to_np, ALL_TIMES
from pyproj import Transformer

# class WRFOutputReader(object):
#     def __init__(self) -> None:
#         self.__className = "WRFOutputReader"
#         self.__variablesList = ('PM10', 'so2', 'co', 'o3', 'PM2_5_DRY', 'no', 'no2', 'no3', 'T2', 'rh', 'wind10m', 'accRain', '3hRain', '24hRain')
#         self.resetClass()
        
#     def __processRain(self, var_key, time_steps):
#         acc = self.__nTimes - 1
    
#         if var_key == '24hRain':
#             acc = 24

#         elif var_key == '3hRain':
#             acc = 3
        
#         data = []

#         rainc = self.__ncDs.variables['RAINC'][:]
#         rainnc = self.__ncDs.variables['RAINNC'][:]

#         rainAc = []

#         _t0 = 0 if self.__startTstepIdx == 0 else self.__startTstepIdx - acc

#         for t in range(_t0, self.__endTstepIdx + 1):
#             tRainc = rainc[t]
#             tRainnc = rainnc[t]

#             rainAc.append(np.flipud(tRainc + tRainnc))

#         self.__accPrec = rainAc
#         return data
    
#     def __process4DVariable(self, var_key, level, time_steps):
#         data = []

#         for t in time_steps:
#             var_time_matrix = getvar(self.__ncData, var_key, timeidx=t,
#                         squeeze=False, meta=False)
#             pressure_time_matrix = getvar(self.__ncData, 'pressure', timeidx=t,
#                         squeeze=False, meta=False)

#             var_time_matrix = to_np(interplevel(var_time_matrix, pressure_time_matrix, level))

#             if np.ma.isMaskedArray(var_time_matrix):
#                 var_time_matrix = list(var_time_matrix)
#                 var_time_matrix.reverse()
#                 data.append(var_time_matrix)

#         data = np.array(data)
#         return data
    
#     def getNTimes(self):
#         return self.__nTimes
    
#     def getVariableData(self, var_key, var_level=None, time_steps=[]):
#         active_var = None
#         data = None
        

#         if len(time_steps) == 0: time_steps = range(self.__nTimes)

#         # Set active_var
#         for i in range(len(self.__variablesList)):
#             if var_key.lower() == self.__variablesList[i].lower(): 
#                 active_var = self.__variablesList[i]
#                 break
        
#         # Set data according to the variable
#         if active_var:
#             if 'Rain' in active_var:
#                 self.__processRain(active_var, time_steps)

#             elif active_var == 'T2':
#                 data = self.__ncData.variables[active_var][:]
#                 data -= 273 # Kelvin to Celsius
            
#             elif active_var == 'wind10m':
#                 # to do
#                 data = []

#             elif self.__ncData.variables[active_var].shape == 4:
#                 self.__process4DVariable(active_var, var_level, time_steps)
                    
#         else:
#             sys.exit()
              
#         return data
       
#     def getLatLon(self):
#         # return self.__latMatrix, self.__lonMatrix
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
#         self.__gridId = None
#         self.__latList = None
#         self.__lonList = None
#         self.__nTimes = None
    
#     def setAttributes(self):
#         self.__latMatrix = sorted(self.__ncData.variables['XLAT'][:][0], key=lambda x: x[0], reverse=True)
#         self.__lonMatrix = self.__ncData.variables['XLONG'][:][0]
        
#         self.__latList = np.array([row[0] for row in self.__latMatrix] )
#         self.__lonList = np.array(self.__lonMatrix[0])

#         self.__nRows = self.__ncData.dimensions['south_north'].size
#         self.__nCols = self.__ncData.dimensions['west_east'].size

#         self.__nTimes = self.__ncData.dimensions['Time'].size

# def my_function(model, file_path, target_variables, time_steps=[], bbox=[]):

#     ncReader = None

#     if model.lower() == 'wrf':
#         ncReader = WRFOutputReader()
    
#     if ncReader:
#         ncReader.setNcData(file_path)
#         ncReader.setAttributes()

#         for var_obj in target_variables:
#             var_key   = var_obj.variable
#             var_level = var_obj.level

#             data = ncReader.getVariableData(var_key, var_level, time_steps)


    
# if __name__ == '__main__':
#     # path = f'../../examples/wrf_chicago'
#     # startDate = "2016-07-01"
#     # gId = "2"

#     # filepath = f"{path}/wrfout_d0{gId}_{startDate}.nc"

#     # thematic_from_wrf(filepath, ['T2'], 4326, range(1, 5), [33, -94, 42, -81])

#     path = f'../../examples/wrf_chicago'
#     startDate = "2023-06-09_20_00_00"
#     gId = "3"

#     filepath = f"{path}/wrfout_d0{gId}_{startDate}"

#     # thematic_from_wrf(filepath, ['T2'], 4326, range(1, 5), [33, -94, 42, -81])

#     obj1 = {'variable': 'T2', 'level': None}
#     obj2 = {'variable': 'rh', 'level': 850}
#     varList = [obj1, obj2]

#     my_function('wrf', filepath, varList)

#     # for v in ('PM10', 'so2', 'co', 'o3', 'PM2_5_DRY', 'no', 'no2', 'no3', 'T2'):
#     #     myvar = wrfout.getVariableData(v)
#     # print(myvar)

