import random

fields = [
  {"key": "tmpsrf", "nick": "Ts"    , "name": "Temperature at Surface" , "unit": "°C"   , "colorRange" : ["#44a79a", "#44a79a"], "tsSelected": False},
  {"key": "tmp2m" , "nick": "T2"    , "name": "Temperature at 2 meters", "unit": "°C"   , "colorRange": ["#091CB9", "#091CB9"], "tsSelected": False},
  {"key": "rh"    , "nick": "RH"    , "name": "Relative Humidity"      , "unit": "--"   , "colorRange" : ["#44a79a", "#44a79a"], "tsSelected": False},
  {"key": "wind10", "nick": "W10"   , "name": "Wind at 10m"        , "unit": "m/s"   , "colorRange" : ["#44a79a", "#44a79a"], "tsSelected": False},
  {"key": "pm25"  , "nick": "PM2.5" , "name": "Particule Matter 2.5", "unit": "ug/m3", "colorRange": ["#a74472", "#a74472"], "tsSelected": False},
  {"key": "pm10"  , "nick": "PM210" , "name": "Particule Matter 10", "unit": "ug/m3", "colorRange": ["#a74472", "#a74472"], "tsSelected": False},
  {"key": "o3"    , "nick": "O3"    , "name": "Ozone"             , "unit": "--"   , "colorRange": ["#8a44a7", "#8a44a7"], "tsSelected": False},
  {"key": "co"    , "nick": "CO"    , "name": "CO"             , "unit": "--"   , "colorRange": ["#448ea7", "#448ea7"], "tsSelected": False},
  {"key": "so2"   , "nick": "SO2"   , "name": "SO2"             , "unit": "--"   , "colorRange": ["#f15555", "#f15555"], "tsSelected": False},
  {"key": "nox"   , "nick": "NOx"   , "name": "NOx"             , "unit": "--"   , "colorRange": ["#68a744", "#68a744"], "tsSelected": False},
]

fields_keys = [f["key"] for f in fields]

fakeScatterSys = [
  {
    "tmp2m":18,
    "tmpsrf": 23,
    "rh":80,
    "wind10":30,
    "pm25": 52,
    "pm10": 98  ,
    "o3"  : 4  ,
    "co"  : 21  ,
    "so2" : 76  ,
    "nox": 43   ,
    "crime1":130,
    "crime2":130,
    "crime3":130,
    # "time":1,
    # "point": [1, 3]
  },
  {
    "tmp2m":98,
    "tmpsrf": 54,
    "rh":76,
    "wind10":34,
    "pm25": 76,
    "pm10": 65  ,
    "o3"  : 4  ,
    "co"  : 12  ,
    "so2" : 32  ,
    "nox": 43   ,
    "crime1":54,
    "crime2":78,
    "crime3":43,
    # "time":1,
    # "point": [1, 3]
   },
  {
    "tmp2m":5,
    "tmpsrf": 1,
    "rh":31,
    "wind10":88,
    "pm25": 78,
    "pm10": 56  ,
    "o3"  : 54  ,
    "co"  : 43  ,
    "so2" : 21  ,
    "nox": 43   ,
    "crime1":32,
    "crime2":3,
    "crime3":8,
    # "time":1,
    # "point": [1, 3]
   },
  {
    "tmp2m":12,
    "tmpsrf": 65,
    "rh":12,
    "wind10":43,
    "pm25": 76,
    "pm10": 36  ,
    "o3"  : 4  ,
    "co"  : 75  ,
    "so2" : 25  ,
    "nox": 75   ,
    "crime1":75,
    "crime2":34,
    "crime3":65,
    # "time":1,
    # "point": [1, 3]
   },
]

socioFields = [
    {"key": "crm", "nick": "crime", "name": "Crimes"},
    {"key": "crm2", "nick": "crime2", "name": "Crimes2"},
    {"key": "crm3", "nick": "crime3", "name": "Crimes3"},
]

def buildFakeHmat():
  arr = []

  for f in fields:
      for sf in socioFields:
          obj = {
              "socioField": sf["nick"],
              "atmField": f["nick"],
              "corr": random.randint(1, 50)
          }

          arr.append(obj)
  return arr

fakeHmat = buildFakeHmat()
categories = [
    "Obs",
    "WRFout"
]

fakeHmatData = [
  {
    "date": "2012-01-01",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 5,
    "wind": 4.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-01-02",
    "precipitation": 10.9,
    "temp_max": 10.6,
    "temp_min": 2.8,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2012-01-03",
    "precipitation": 0.8,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2012-01-04",
    "precipitation": 20.3,
    "temp_max": 12.2,
    "temp_min": 5.6,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2012-01-05",
    "precipitation": 1.3,
    "temp_max": 8.9,
    "temp_min": 2.8,
    "wind": 6.1,
    "weather": "rain"
  },
  {
    "date": "2012-01-06",
    "precipitation": 2.5,
    "temp_max": 4.4,
    "temp_min": 2.2,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2012-01-07",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 2.8,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2012-01-08",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2012-01-09",
    "precipitation": 4.3,
    "temp_max": 9.4,
    "temp_min": 5,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-01-10",
    "precipitation": 1,
    "temp_max": 6.1,
    "temp_min": 0.6,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-01-11",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": -1.1,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2012-01-12",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": -1.7,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-01-13",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": -2.8,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2012-01-14",
    "precipitation": 4.1,
    "temp_max": 4.4,
    "temp_min": 0.6,
    "wind": 5.3,
    "weather": "snow"
  },
  {
    "date": "2012-01-15",
    "precipitation": 5.3,
    "temp_max": 1.1,
    "temp_min": -3.3,
    "wind": 3.2,
    "weather": "snow"
  },
  {
    "date": "2012-01-16",
    "precipitation": 2.5,
    "temp_max": 1.7,
    "temp_min": -2.8,
    "wind": 5,
    "weather": "snow"
  },
  {
    "date": "2012-01-17",
    "precipitation": 8.1,
    "temp_max": 3.3,
    "temp_min": 0,
    "wind": 5.6,
    "weather": "snow"
  },
  {
    "date": "2012-01-18",
    "precipitation": 19.8,
    "temp_max": 0,
    "temp_min": -2.8,
    "wind": 5,
    "weather": "snow"
  },
  {
    "date": "2012-01-19",
    "precipitation": 15.2,
    "temp_max": -1.1,
    "temp_min": -2.8,
    "wind": 1.6,
    "weather": "snow"
  },
  {
    "date": "2012-01-20",
    "precipitation": 13.5,
    "temp_max": 7.2,
    "temp_min": -1.1,
    "wind": 2.3,
    "weather": "snow"
  },
  {
    "date": "2012-01-21",
    "precipitation": 3,
    "temp_max": 8.3,
    "temp_min": 3.3,
    "wind": 8.2,
    "weather": "rain"
  },
  {
    "date": "2012-01-22",
    "precipitation": 6.1,
    "temp_max": 6.7,
    "temp_min": 2.2,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2012-01-23",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 1.1,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2012-01-24",
    "precipitation": 8.6,
    "temp_max": 10,
    "temp_min": 2.2,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-01-25",
    "precipitation": 8.1,
    "temp_max": 8.9,
    "temp_min": 4.4,
    "wind": 5.4,
    "weather": "rain"
  },
  {
    "date": "2012-01-26",
    "precipitation": 4.8,
    "temp_max": 8.9,
    "temp_min": 1.1,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2012-01-27",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": -2.2,
    "wind": 1.4,
    "weather": "drizzle"
  },
  {
    "date": "2012-01-28",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 0.6,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2012-01-29",
    "precipitation": 27.7,
    "temp_max": 9.4,
    "temp_min": 3.9,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2012-01-30",
    "precipitation": 3.6,
    "temp_max": 8.3,
    "temp_min": 6.1,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-01-31",
    "precipitation": 1.8,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-02-01",
    "precipitation": 13.5,
    "temp_max": 8.9,
    "temp_min": 3.3,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-02-02",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 1.7,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2012-02-03",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 2.2,
    "wind": 5.3,
    "weather": "sun"
  },
  {
    "date": "2012-02-04",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 5,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-02-05",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 1.7,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2012-02-06",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 1.7,
    "wind": 5,
    "weather": "sun"
  },
  {
    "date": "2012-02-07",
    "precipitation": 0.3,
    "temp_max": 15.6,
    "temp_min": 7.8,
    "wind": 5.3,
    "weather": "rain"
  },
  {
    "date": "2012-02-08",
    "precipitation": 2.8,
    "temp_max": 10,
    "temp_min": 5,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-02-09",
    "precipitation": 2.5,
    "temp_max": 11.1,
    "temp_min": 7.8,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2012-02-10",
    "precipitation": 2.5,
    "temp_max": 12.8,
    "temp_min": 6.7,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-02-11",
    "precipitation": 0.8,
    "temp_max": 8.9,
    "temp_min": 5.6,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-02-12",
    "precipitation": 1,
    "temp_max": 8.3,
    "temp_min": 5,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2012-02-13",
    "precipitation": 11.4,
    "temp_max": 7.2,
    "temp_min": 4.4,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2012-02-14",
    "precipitation": 2.5,
    "temp_max": 6.7,
    "temp_min": 1.1,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-02-15",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 0.6,
    "wind": 1.8,
    "weather": "drizzle"
  },
  {
    "date": "2012-02-16",
    "precipitation": 1.8,
    "temp_max": 7.2,
    "temp_min": 3.3,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2012-02-17",
    "precipitation": 17.3,
    "temp_max": 10,
    "temp_min": 4.4,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-02-18",
    "precipitation": 6.4,
    "temp_max": 6.7,
    "temp_min": 3.9,
    "wind": 8.1,
    "weather": "rain"
  },
  {
    "date": "2012-02-19",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 2.2,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2012-02-20",
    "precipitation": 3,
    "temp_max": 7.8,
    "temp_min": 1.7,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2012-02-21",
    "precipitation": 0.8,
    "temp_max": 10,
    "temp_min": 7.8,
    "wind": 7.5,
    "weather": "rain"
  },
  {
    "date": "2012-02-22",
    "precipitation": 8.6,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2012-02-23",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 2.8,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2012-02-24",
    "precipitation": 11.4,
    "temp_max": 6.7,
    "temp_min": 4.4,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2012-02-25",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 2.8,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2012-02-26",
    "precipitation": 1.3,
    "temp_max": 5,
    "temp_min": -1.1,
    "wind": 3.4,
    "weather": "snow"
  },
  {
    "date": "2012-02-27",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": -2.2,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-02-28",
    "precipitation": 3.6,
    "temp_max": 6.7,
    "temp_min": -0.6,
    "wind": 4.2,
    "weather": "snow"
  },
  {
    "date": "2012-02-29",
    "precipitation": 0.8,
    "temp_max": 5,
    "temp_min": 1.1,
    "wind": 7,
    "weather": "snow"
  },
  {
    "date": "2012-03-01",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": 1.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-03-02",
    "precipitation": 2,
    "temp_max": 6.7,
    "temp_min": 3.9,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-03-03",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 7,
    "weather": "sun"
  },
  {
    "date": "2012-03-04",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 6.7,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2012-03-05",
    "precipitation": 6.9,
    "temp_max": 7.8,
    "temp_min": 1.1,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2012-03-06",
    "precipitation": 0.5,
    "temp_max": 6.7,
    "temp_min": 0,
    "wind": 2.7,
    "weather": "snow"
  },
  {
    "date": "2012-03-07",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": -1.7,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2012-03-08",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 0.6,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2012-03-09",
    "precipitation": 3.6,
    "temp_max": 9.4,
    "temp_min": 5,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-03-10",
    "precipitation": 10.4,
    "temp_max": 7.2,
    "temp_min": 6.1,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-03-11",
    "precipitation": 13.7,
    "temp_max": 6.7,
    "temp_min": 2.8,
    "wind": 5.8,
    "weather": "rain"
  },
  {
    "date": "2012-03-12",
    "precipitation": 19.3,
    "temp_max": 8.3,
    "temp_min": 0.6,
    "wind": 6.2,
    "weather": "snow"
  },
  {
    "date": "2012-03-13",
    "precipitation": 9.4,
    "temp_max": 5.6,
    "temp_min": 0.6,
    "wind": 5.3,
    "weather": "snow"
  },
  {
    "date": "2012-03-14",
    "precipitation": 8.6,
    "temp_max": 7.8,
    "temp_min": 1.1,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2012-03-15",
    "precipitation": 23.9,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 5.8,
    "weather": "snow"
  },
  {
    "date": "2012-03-16",
    "precipitation": 8.4,
    "temp_max": 8.9,
    "temp_min": 3.9,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-03-17",
    "precipitation": 9.4,
    "temp_max": 10,
    "temp_min": 0.6,
    "wind": 3.8,
    "weather": "snow"
  },
  {
    "date": "2012-03-18",
    "precipitation": 3.6,
    "temp_max": 5,
    "temp_min": -0.6,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-03-19",
    "precipitation": 2,
    "temp_max": 7.2,
    "temp_min": -1.1,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-03-20",
    "precipitation": 3.6,
    "temp_max": 7.8,
    "temp_min": 2.2,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2012-03-21",
    "precipitation": 1.3,
    "temp_max": 8.9,
    "temp_min": 1.1,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-03-22",
    "precipitation": 4.1,
    "temp_max": 10,
    "temp_min": 1.7,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2012-03-23",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 0.6,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2012-03-24",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 3.3,
    "wind": 5.2,
    "weather": "sun"
  },
  {
    "date": "2012-03-25",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 2.2,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-03-26",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 4.3,
    "weather": "drizzle"
  },
  {
    "date": "2012-03-27",
    "precipitation": 4.8,
    "temp_max": 14.4,
    "temp_min": 6.7,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2012-03-28",
    "precipitation": 1.3,
    "temp_max": 10.6,
    "temp_min": 7.2,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2012-03-29",
    "precipitation": 27.4,
    "temp_max": 10,
    "temp_min": 6.1,
    "wind": 4.4,
    "weather": "rain"
  },
  {
    "date": "2012-03-30",
    "precipitation": 5.6,
    "temp_max": 9.4,
    "temp_min": 5,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2012-03-31",
    "precipitation": 13.2,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-04-01",
    "precipitation": 1.5,
    "temp_max": 8.9,
    "temp_min": 4.4,
    "wind": 6.8,
    "weather": "rain"
  },
  {
    "date": "2012-04-02",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 4.4,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-04-03",
    "precipitation": 1.5,
    "temp_max": 11.7,
    "temp_min": 3.3,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-04-04",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 2.8,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2012-04-05",
    "precipitation": 4.6,
    "temp_max": 9.4,
    "temp_min": 2.8,
    "wind": 1.8,
    "weather": "snow"
  },
  {
    "date": "2012-04-06",
    "precipitation": 0.3,
    "temp_max": 11.1,
    "temp_min": 3.3,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-07",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 1.7,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-04-08",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 7.2,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2012-04-09",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 6.1,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2012-04-10",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 8.9,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2012-04-11",
    "precipitation": 2.3,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-12",
    "precipitation": 0.5,
    "temp_max": 13.9,
    "temp_min": 5.6,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-13",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 3.9,
    "wind": 4,
    "weather": "drizzle"
  },
  {
    "date": "2012-04-14",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 3.3,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-04-15",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 7.2,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2012-04-16",
    "precipitation": 8.1,
    "temp_max": 13.3,
    "temp_min": 6.7,
    "wind": 5.8,
    "weather": "rain"
  },
  {
    "date": "2012-04-17",
    "precipitation": 1.8,
    "temp_max": 10,
    "temp_min": 4.4,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2012-04-18",
    "precipitation": 1.8,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-04-19",
    "precipitation": 10.9,
    "temp_max": 13.9,
    "temp_min": 5,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-20",
    "precipitation": 6.6,
    "temp_max": 13.3,
    "temp_min": 6.7,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-04-21",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 4.4,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-04-22",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 8.3,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-23",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 8.9,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2012-04-24",
    "precipitation": 4.3,
    "temp_max": 13.9,
    "temp_min": 10,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-04-25",
    "precipitation": 10.7,
    "temp_max": 16.7,
    "temp_min": 8.9,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-26",
    "precipitation": 3.8,
    "temp_max": 13.9,
    "temp_min": 6.7,
    "wind": 5.2,
    "weather": "rain"
  },
  {
    "date": "2012-04-27",
    "precipitation": 0.8,
    "temp_max": 13.3,
    "temp_min": 6.1,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2012-04-28",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 8.3,
    "wind": 2.5,
    "weather": "drizzle"
  },
  {
    "date": "2012-04-29",
    "precipitation": 4.3,
    "temp_max": 15.6,
    "temp_min": 8.9,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2012-04-30",
    "precipitation": 4.3,
    "temp_max": 12.8,
    "temp_min": 7.2,
    "wind": 8,
    "weather": "rain"
  },
  {
    "date": "2012-05-01",
    "precipitation": 0.5,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2012-05-02",
    "precipitation": 0.5,
    "temp_max": 13.3,
    "temp_min": 5.6,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-05-03",
    "precipitation": 18.5,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-05-04",
    "precipitation": 1.8,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2012-05-05",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 5,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-05-06",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 5,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2012-05-07",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 6.1,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2012-05-08",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 9.4,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-05-09",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 6.7,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-05-10",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 3.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-05-11",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 4.4,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-05-12",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 6.7,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2012-05-13",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 9.4,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2012-05-14",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2012-05-15",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 9.4,
    "wind": 4.1,
    "weather": "drizzle"
  },
  {
    "date": "2012-05-16",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 9.4,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2012-05-17",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 6.7,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2012-05-18",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 7.8,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-05-19",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 7.2,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2012-05-20",
    "precipitation": 6.4,
    "temp_max": 14.4,
    "temp_min": 11.7,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2012-05-21",
    "precipitation": 14,
    "temp_max": 16.7,
    "temp_min": 10,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2012-05-22",
    "precipitation": 6.1,
    "temp_max": 12.8,
    "temp_min": 8.9,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2012-05-23",
    "precipitation": 0.3,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2012-05-24",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 8.9,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2012-05-25",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 8.9,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-05-26",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 8.9,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2012-05-27",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 11.7,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2012-05-28",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 10,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-05-29",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 7.8,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2012-05-30",
    "precipitation": 0.3,
    "temp_max": 18.9,
    "temp_min": 11.1,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2012-05-31",
    "precipitation": 3.8,
    "temp_max": 17.8,
    "temp_min": 12.2,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-06-01",
    "precipitation": 6.6,
    "temp_max": 20,
    "temp_min": 12.8,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2012-06-02",
    "precipitation": 0.3,
    "temp_max": 18.9,
    "temp_min": 10.6,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2012-06-03",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 9.4,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2012-06-04",
    "precipitation": 1.3,
    "temp_max": 12.8,
    "temp_min": 8.9,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-06-05",
    "precipitation": 16,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2012-06-06",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 6.1,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2012-06-07",
    "precipitation": 16.5,
    "temp_max": 16.1,
    "temp_min": 8.9,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2012-06-08",
    "precipitation": 1.5,
    "temp_max": 15,
    "temp_min": 8.3,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-06-09",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 8.3,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2012-06-10",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 10,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2012-06-11",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 10,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2012-06-12",
    "precipitation": 0.8,
    "temp_max": 18.3,
    "temp_min": 12.8,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-06-13",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 11.1,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-06-14",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 10,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2012-06-15",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 9.4,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2012-06-16",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 15,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2012-06-17",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 11.7,
    "wind": 6.4,
    "weather": "sun"
  },
  {
    "date": "2012-06-18",
    "precipitation": 3,
    "temp_max": 17.2,
    "temp_min": 10,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2012-06-19",
    "precipitation": 1,
    "temp_max": 19.4,
    "temp_min": 10,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-06-20",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 10,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-06-21",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.7,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2012-06-22",
    "precipitation": 15.7,
    "temp_max": 13.9,
    "temp_min": 11.7,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2012-06-23",
    "precipitation": 8.6,
    "temp_max": 15.6,
    "temp_min": 9.4,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-06-24",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 9.4,
    "wind": 2,
    "weather": "drizzle"
  },
  {
    "date": "2012-06-25",
    "precipitation": 0.5,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2012-06-26",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-06-27",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 8.9,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2012-06-28",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 11.7,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-06-29",
    "precipitation": 0.3,
    "temp_max": 21.7,
    "temp_min": 15,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2012-06-30",
    "precipitation": 3,
    "temp_max": 20,
    "temp_min": 13.3,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2012-07-01",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 12.2,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2012-07-02",
    "precipitation": 2,
    "temp_max": 18.9,
    "temp_min": 11.7,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2012-07-03",
    "precipitation": 5.8,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2012-07-04",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 9.4,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2012-07-05",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 10.6,
    "wind": 3.1,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-06",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 11.1,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2012-07-07",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2012-07-08",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 14.4,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-07-09",
    "precipitation": 1.5,
    "temp_max": 25,
    "temp_min": 12.8,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2012-07-10",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.1,
    "wind": 2.3,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-11",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.3,
    "wind": 2.9,
    "weather": "fog"
  },
  {
    "date": "2012-07-12",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.3,
    "wind": 2.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-13",
    "precipitation": 0.5,
    "temp_max": 23.3,
    "temp_min": 13.9,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2012-07-14",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 15,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2012-07-15",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 13.3,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2012-07-16",
    "precipitation": 0.3,
    "temp_max": 26.1,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-07-17",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 15,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2012-07-18",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 14.4,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2012-07-19",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 14.4,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2012-07-20",
    "precipitation": 15.2,
    "temp_max": 19.4,
    "temp_min": 13.9,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2012-07-21",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.9,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-07-22",
    "precipitation": 1,
    "temp_max": 20.6,
    "temp_min": 12.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-07-23",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 11.1,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2012-07-24",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.2,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-07-25",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2012-07-26",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.8,
    "wind": 2.2,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-27",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 13.9,
    "wind": 2.8,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-28",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 13.3,
    "wind": 1.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-07-29",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 15,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2012-07-30",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 13.3,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-07-31",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 13.9,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-01",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.3,
    "wind": 2.2,
    "weather": "drizzle"
  },
  {
    "date": "2012-08-02",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.2,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2012-08-03",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 12.8,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2012-08-04",
    "precipitation": 0,
    "temp_max": 33.9,
    "temp_min": 16.7,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2012-08-05",
    "precipitation": 0,
    "temp_max": 33.9,
    "temp_min": 17.8,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-08-06",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15.6,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-08-07",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 15,
    "wind": 2.6,
    "weather": "drizzle"
  },
  {
    "date": "2012-08-08",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 15,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-08-09",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 14.4,
    "wind": 3.8,
    "weather": "drizzle"
  },
  {
    "date": "2012-08-10",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.2,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-08-11",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2012-08-12",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 15,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-08-13",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 15,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-14",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 13.9,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-15",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 16.7,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2012-08-16",
    "precipitation": 0,
    "temp_max": 34.4,
    "temp_min": 18.3,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-17",
    "precipitation": 0,
    "temp_max": 32.8,
    "temp_min": 16.1,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-18",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 14.4,
    "wind": 3,
    "weather": "drizzle"
  },
  {
    "date": "2012-08-19",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 15,
    "wind": 2.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-08-20",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 15,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-08-21",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 13.3,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-08-22",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 13.3,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-08-23",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 13.9,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-24",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2012-08-25",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 11.7,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2012-08-26",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 12.2,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2012-08-27",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.3,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2012-08-28",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.2,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2012-08-29",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 13.3,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2012-08-30",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.8,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-08-31",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10.6,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2012-09-01",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 10.6,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2012-09-02",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 10,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2012-09-03",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.8,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2012-09-04",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-09-05",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 11.7,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2012-09-06",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 14.4,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2012-09-07",
    "precipitation": 0,
    "temp_max": 32.2,
    "temp_min": 13.3,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-09-08",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-09-09",
    "precipitation": 0.3,
    "temp_max": 18.9,
    "temp_min": 13.9,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2012-09-10",
    "precipitation": 0.3,
    "temp_max": 20,
    "temp_min": 11.7,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-09-11",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 8.9,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2012-09-12",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10,
    "wind": 5.6,
    "weather": "sun"
  },
  {
    "date": "2012-09-13",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 11.7,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2012-09-14",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 11.1,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2012-09-15",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 11.1,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-09-16",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 9.4,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2012-09-17",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 11.7,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2012-09-18",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 11.7,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2012-09-19",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.7,
    "wind": 1.9,
    "weather": "drizzle"
  },
  {
    "date": "2012-09-20",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 10,
    "wind": 2.5,
    "weather": "drizzle"
  },
  {
    "date": "2012-09-21",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 12.8,
    "wind": 2.1,
    "weather": "drizzle"
  },
  {
    "date": "2012-09-22",
    "precipitation": 0.3,
    "temp_max": 19.4,
    "temp_min": 11.7,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2012-09-23",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 10,
    "wind": 1.4,
    "weather": "fog"
  },
  {
    "date": "2012-09-24",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 10,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2012-09-25",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2012-09-26",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 9.4,
    "wind": 1.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-09-27",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 10,
    "wind": 1.7,
    "weather": "drizzle"
  },
  {
    "date": "2012-09-28",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 12.2,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2012-09-29",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.2,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2012-09-30",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 7.8,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2012-10-01",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 8.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2012-10-02",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2012-10-03",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 7.8,
    "wind": 7.3,
    "weather": "sun"
  },
  {
    "date": "2012-10-04",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 8.3,
    "wind": 6.5,
    "weather": "sun"
  },
  {
    "date": "2012-10-05",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 8.9,
    "wind": 5.7,
    "weather": "sun"
  },
  {
    "date": "2012-10-06",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 7.8,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2012-10-07",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 7.8,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2012-10-08",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 7.8,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2012-10-09",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 8.9,
    "wind": 1.6,
    "weather": "drizzle"
  },
  {
    "date": "2012-10-10",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 8.3,
    "wind": 1.4,
    "weather": "drizzle"
  },
  {
    "date": "2012-10-11",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 7.2,
    "wind": 1.3,
    "weather": "drizzle"
  },
  {
    "date": "2012-10-12",
    "precipitation": 2,
    "temp_max": 13.9,
    "temp_min": 8.9,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2012-10-13",
    "precipitation": 4.8,
    "temp_max": 15.6,
    "temp_min": 12.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2012-10-14",
    "precipitation": 16.5,
    "temp_max": 17.8,
    "temp_min": 13.3,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-10-15",
    "precipitation": 7.9,
    "temp_max": 17.2,
    "temp_min": 11.1,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2012-10-16",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 8.3,
    "wind": 5.5,
    "weather": "sun"
  },
  {
    "date": "2012-10-17",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 6.1,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2012-10-18",
    "precipitation": 20.8,
    "temp_max": 17.8,
    "temp_min": 6.7,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2012-10-19",
    "precipitation": 4.8,
    "temp_max": 15,
    "temp_min": 9.4,
    "wind": 5.3,
    "weather": "rain"
  },
  {
    "date": "2012-10-20",
    "precipitation": 0.5,
    "temp_max": 11.1,
    "temp_min": 6.1,
    "wind": 5.7,
    "weather": "rain"
  },
  {
    "date": "2012-10-21",
    "precipitation": 6.4,
    "temp_max": 11.7,
    "temp_min": 4.4,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-10-22",
    "precipitation": 8.9,
    "temp_max": 7.8,
    "temp_min": 3.3,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-10-23",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-10-24",
    "precipitation": 7.1,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2012-10-25",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 6.7,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2012-10-26",
    "precipitation": 1.5,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-10-27",
    "precipitation": 23.1,
    "temp_max": 14.4,
    "temp_min": 9.4,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-10-28",
    "precipitation": 6.1,
    "temp_max": 14.4,
    "temp_min": 10,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2012-10-29",
    "precipitation": 10.9,
    "temp_max": 15.6,
    "temp_min": 10,
    "wind": 4.9,
    "weather": "rain"
  },
  {
    "date": "2012-10-30",
    "precipitation": 34.5,
    "temp_max": 15,
    "temp_min": 12.2,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-10-31",
    "precipitation": 14.5,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2012-11-01",
    "precipitation": 9.7,
    "temp_max": 15,
    "temp_min": 10.6,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-11-02",
    "precipitation": 5.6,
    "temp_max": 15,
    "temp_min": 10.6,
    "wind": 1,
    "weather": "rain"
  },
  {
    "date": "2012-11-03",
    "precipitation": 0.5,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2012-11-04",
    "precipitation": 8.1,
    "temp_max": 17.8,
    "temp_min": 12.8,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2012-11-05",
    "precipitation": 0.8,
    "temp_max": 15,
    "temp_min": 7.8,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2012-11-06",
    "precipitation": 0.3,
    "temp_max": 12.8,
    "temp_min": 6.7,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2012-11-07",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 3.9,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-11-08",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 1.1,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2012-11-09",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 1.1,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2012-11-10",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": -0.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2012-11-11",
    "precipitation": 15.2,
    "temp_max": 8.9,
    "temp_min": 1.1,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-11-12",
    "precipitation": 3.6,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2012-11-13",
    "precipitation": 5.3,
    "temp_max": 11.1,
    "temp_min": 7.8,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-11-14",
    "precipitation": 0.8,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2012-11-15",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 2.8,
    "wind": 2.4,
    "weather": "drizzle"
  },
  {
    "date": "2012-11-16",
    "precipitation": 5.6,
    "temp_max": 9.4,
    "temp_min": 2.2,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2012-11-17",
    "precipitation": 6.1,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 5.3,
    "weather": "rain"
  },
  {
    "date": "2012-11-18",
    "precipitation": 7.9,
    "temp_max": 10,
    "temp_min": 6.1,
    "wind": 4.9,
    "weather": "rain"
  },
  {
    "date": "2012-11-19",
    "precipitation": 54.1,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2012-11-20",
    "precipitation": 3.8,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2012-11-21",
    "precipitation": 11.2,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2012-11-22",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 2.8,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2012-11-23",
    "precipitation": 32,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2012-11-24",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 3.9,
    "wind": 1.2,
    "weather": "rain"
  },
  {
    "date": "2012-11-25",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 1.1,
    "wind": 3.6,
    "weather": "drizzle"
  },
  {
    "date": "2012-11-26",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 1.7,
    "wind": 3.8,
    "weather": "fog"
  },
  {
    "date": "2012-11-27",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 1.7,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2012-11-28",
    "precipitation": 2.8,
    "temp_max": 9.4,
    "temp_min": 2.2,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2012-11-29",
    "precipitation": 1.5,
    "temp_max": 12.8,
    "temp_min": 7.8,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2012-11-30",
    "precipitation": 35.6,
    "temp_max": 15,
    "temp_min": 7.8,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2012-12-01",
    "precipitation": 4.1,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2012-12-02",
    "precipitation": 19.6,
    "temp_max": 8.3,
    "temp_min": 7.2,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2012-12-03",
    "precipitation": 13,
    "temp_max": 9.4,
    "temp_min": 7.2,
    "wind": 4.4,
    "weather": "rain"
  },
  {
    "date": "2012-12-04",
    "precipitation": 14.2,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2012-12-05",
    "precipitation": 1.5,
    "temp_max": 8.9,
    "temp_min": 4.4,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2012-12-06",
    "precipitation": 1.5,
    "temp_max": 7.2,
    "temp_min": 6.1,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2012-12-07",
    "precipitation": 1,
    "temp_max": 7.8,
    "temp_min": 3.3,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2012-12-08",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 3.3,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2012-12-09",
    "precipitation": 1.5,
    "temp_max": 6.7,
    "temp_min": 2.8,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2012-12-10",
    "precipitation": 0.5,
    "temp_max": 7.2,
    "temp_min": 5.6,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2012-12-11",
    "precipitation": 3,
    "temp_max": 7.8,
    "temp_min": 5.6,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2012-12-12",
    "precipitation": 8.1,
    "temp_max": 6.7,
    "temp_min": 4.4,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2012-12-13",
    "precipitation": 2.3,
    "temp_max": 7.2,
    "temp_min": 3.3,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-12-14",
    "precipitation": 7.9,
    "temp_max": 6.1,
    "temp_min": 1.1,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2012-12-15",
    "precipitation": 5.3,
    "temp_max": 4.4,
    "temp_min": 0.6,
    "wind": 5.1,
    "weather": "snow"
  },
  {
    "date": "2012-12-16",
    "precipitation": 22.6,
    "temp_max": 6.7,
    "temp_min": 3.3,
    "wind": 5.5,
    "weather": "snow"
  },
  {
    "date": "2012-12-17",
    "precipitation": 2,
    "temp_max": 8.3,
    "temp_min": 1.7,
    "wind": 9.5,
    "weather": "rain"
  },
  {
    "date": "2012-12-18",
    "precipitation": 3.3,
    "temp_max": 3.9,
    "temp_min": 0.6,
    "wind": 5.3,
    "weather": "snow"
  },
  {
    "date": "2012-12-19",
    "precipitation": 13.7,
    "temp_max": 8.3,
    "temp_min": 1.7,
    "wind": 5.8,
    "weather": "snow"
  },
  {
    "date": "2012-12-20",
    "precipitation": 13.2,
    "temp_max": 7.2,
    "temp_min": 0.6,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2012-12-21",
    "precipitation": 1.8,
    "temp_max": 8.3,
    "temp_min": -1.7,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2012-12-22",
    "precipitation": 3.3,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2012-12-23",
    "precipitation": 6.6,
    "temp_max": 7.2,
    "temp_min": 3.3,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2012-12-24",
    "precipitation": 0.3,
    "temp_max": 5.6,
    "temp_min": 2.8,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2012-12-25",
    "precipitation": 13.5,
    "temp_max": 5.6,
    "temp_min": 2.8,
    "wind": 4.2,
    "weather": "snow"
  },
  {
    "date": "2012-12-26",
    "precipitation": 4.6,
    "temp_max": 6.7,
    "temp_min": 3.3,
    "wind": 4.9,
    "weather": "rain"
  },
  {
    "date": "2012-12-27",
    "precipitation": 4.1,
    "temp_max": 7.8,
    "temp_min": 3.3,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2012-12-28",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2012-12-29",
    "precipitation": 1.5,
    "temp_max": 5,
    "temp_min": 3.3,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2012-12-30",
    "precipitation": 0,
    "temp_max": 4.4,
    "temp_min": 0,
    "wind": 1.8,
    "weather": "drizzle"
  },
  {
    "date": "2012-12-31",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -1.1,
    "wind": 2,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-01",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": -2.8,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2013-01-02",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": -1.1,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2013-01-03",
    "precipitation": 4.1,
    "temp_max": 6.7,
    "temp_min": -1.7,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-01-04",
    "precipitation": 2.5,
    "temp_max": 10,
    "temp_min": 2.2,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2013-01-05",
    "precipitation": 3,
    "temp_max": 6.7,
    "temp_min": 4.4,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-01-06",
    "precipitation": 2,
    "temp_max": 7.2,
    "temp_min": 2.8,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-01-07",
    "precipitation": 2.3,
    "temp_max": 10,
    "temp_min": 4.4,
    "wind": 7.3,
    "weather": "rain"
  },
  {
    "date": "2013-01-08",
    "precipitation": 16.3,
    "temp_max": 11.7,
    "temp_min": 5.6,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2013-01-09",
    "precipitation": 38.4,
    "temp_max": 10,
    "temp_min": 1.7,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2013-01-10",
    "precipitation": 0.3,
    "temp_max": 3.3,
    "temp_min": -0.6,
    "wind": 2.1,
    "weather": "snow"
  },
  {
    "date": "2013-01-11",
    "precipitation": 0,
    "temp_max": 2.8,
    "temp_min": -2.8,
    "wind": 1.9,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-12",
    "precipitation": 0,
    "temp_max": 2.8,
    "temp_min": -3.9,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-01-13",
    "precipitation": 0,
    "temp_max": 2.2,
    "temp_min": -4.4,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2013-01-14",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -2.2,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-01-15",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": -0.6,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-01-16",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": -3.9,
    "wind": 1.8,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-17",
    "precipitation": 0,
    "temp_max": 3.9,
    "temp_min": -2.8,
    "wind": 1,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-18",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -1.1,
    "wind": 1.3,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-19",
    "precipitation": 0,
    "temp_max": 1.1,
    "temp_min": -0.6,
    "wind": 1.9,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-20",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -0.6,
    "wind": 2.1,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-21",
    "precipitation": 0,
    "temp_max": 2.2,
    "temp_min": -1.7,
    "wind": 1.1,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-22",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -1.7,
    "wind": 0.6,
    "weather": "drizzle"
  },
  {
    "date": "2013-01-23",
    "precipitation": 5.1,
    "temp_max": 7.2,
    "temp_min": 2.2,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-01-24",
    "precipitation": 5.8,
    "temp_max": 7.2,
    "temp_min": 1.1,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-01-25",
    "precipitation": 3,
    "temp_max": 10.6,
    "temp_min": 2.8,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2013-01-26",
    "precipitation": 2.3,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2013-01-27",
    "precipitation": 1.8,
    "temp_max": 5.6,
    "temp_min": 3.9,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2013-01-28",
    "precipitation": 7.9,
    "temp_max": 6.1,
    "temp_min": 3.3,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2013-01-29",
    "precipitation": 4.3,
    "temp_max": 8.3,
    "temp_min": 5,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-01-30",
    "precipitation": 3.6,
    "temp_max": 8.9,
    "temp_min": 6.7,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-01-31",
    "precipitation": 3,
    "temp_max": 9.4,
    "temp_min": 7.2,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2013-02-01",
    "precipitation": 0.3,
    "temp_max": 11.7,
    "temp_min": 5,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2013-02-02",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": 2.8,
    "wind": 2,
    "weather": "drizzle"
  },
  {
    "date": "2013-02-03",
    "precipitation": 2.3,
    "temp_max": 8.9,
    "temp_min": 2.8,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2013-02-04",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 6.7,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-02-05",
    "precipitation": 3.3,
    "temp_max": 10,
    "temp_min": 6.7,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-06",
    "precipitation": 1,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2013-02-07",
    "precipitation": 1.3,
    "temp_max": 9.4,
    "temp_min": 3.3,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-08",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 2.2,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-02-09",
    "precipitation": 0.3,
    "temp_max": 8.3,
    "temp_min": 4.4,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2013-02-10",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 1.7,
    "wind": 2,
    "weather": "drizzle"
  },
  {
    "date": "2013-02-11",
    "precipitation": 0.3,
    "temp_max": 8.3,
    "temp_min": 4.4,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2013-02-12",
    "precipitation": 1,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2013-02-13",
    "precipitation": 2.3,
    "temp_max": 9.4,
    "temp_min": 7.2,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-14",
    "precipitation": 1,
    "temp_max": 9.4,
    "temp_min": 5.6,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-02-15",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 5,
    "wind": 2.4,
    "weather": "drizzle"
  },
  {
    "date": "2013-02-16",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 3.9,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2013-02-17",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 4.4,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2013-02-18",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 3.9,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2013-02-19",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 1.7,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2013-02-20",
    "precipitation": 1.5,
    "temp_max": 7.8,
    "temp_min": 1.1,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-21",
    "precipitation": 0.5,
    "temp_max": 6.7,
    "temp_min": 3.9,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2013-02-22",
    "precipitation": 9.4,
    "temp_max": 7.8,
    "temp_min": 3.9,
    "wind": 8.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-23",
    "precipitation": 0.3,
    "temp_max": 10,
    "temp_min": 3.9,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2013-02-24",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 5,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2013-02-25",
    "precipitation": 2.3,
    "temp_max": 10.6,
    "temp_min": 3.3,
    "wind": 7.1,
    "weather": "rain"
  },
  {
    "date": "2013-02-26",
    "precipitation": 0.5,
    "temp_max": 8.9,
    "temp_min": 3.9,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2013-02-27",
    "precipitation": 4.6,
    "temp_max": 10,
    "temp_min": 4.4,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2013-02-28",
    "precipitation": 8.1,
    "temp_max": 11.7,
    "temp_min": 6.7,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2013-03-01",
    "precipitation": 4.1,
    "temp_max": 15,
    "temp_min": 11.1,
    "wind": 5.4,
    "weather": "rain"
  },
  {
    "date": "2013-03-02",
    "precipitation": 0.8,
    "temp_max": 13.9,
    "temp_min": 5,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2013-03-03",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 2.2,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2013-03-04",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 0,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2013-03-05",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2013-03-06",
    "precipitation": 11.9,
    "temp_max": 7.2,
    "temp_min": 5,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2013-03-07",
    "precipitation": 7.4,
    "temp_max": 12.2,
    "temp_min": 5,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2013-03-08",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 2.2,
    "wind": 2.6,
    "weather": "drizzle"
  },
  {
    "date": "2013-03-09",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 1.1,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2013-03-10",
    "precipitation": 0.8,
    "temp_max": 7.8,
    "temp_min": 3.9,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2013-03-11",
    "precipitation": 1.3,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2013-03-12",
    "precipitation": 2,
    "temp_max": 12.8,
    "temp_min": 10,
    "wind": 5.7,
    "weather": "rain"
  },
  {
    "date": "2013-03-13",
    "precipitation": 2.3,
    "temp_max": 11.7,
    "temp_min": 9.4,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2013-03-14",
    "precipitation": 2.8,
    "temp_max": 11.7,
    "temp_min": 9.4,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-03-15",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2013-03-16",
    "precipitation": 4.3,
    "temp_max": 10.6,
    "temp_min": 4.4,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2013-03-17",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 3.9,
    "wind": 6.1,
    "weather": "sun"
  },
  {
    "date": "2013-03-18",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 3.9,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2013-03-19",
    "precipitation": 11.7,
    "temp_max": 12.8,
    "temp_min": 1.7,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2013-03-20",
    "precipitation": 9.9,
    "temp_max": 11.1,
    "temp_min": 4.4,
    "wind": 7.6,
    "weather": "rain"
  },
  {
    "date": "2013-03-21",
    "precipitation": 8.1,
    "temp_max": 10,
    "temp_min": 2.2,
    "wind": 4.9,
    "weather": "snow"
  },
  {
    "date": "2013-03-22",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 0.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-03-23",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 1.1,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-03-24",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 0.6,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-03-25",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 4.4,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2013-03-26",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 6.1,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2013-03-27",
    "precipitation": 0.3,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2013-03-28",
    "precipitation": 2,
    "temp_max": 16.1,
    "temp_min": 8.3,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2013-03-29",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 7.8,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2013-03-30",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 5.6,
    "wind": 4.4,
    "weather": "drizzle"
  },
  {
    "date": "2013-03-31",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 6.7,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-04-01",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 8.3,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2013-04-02",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 8.9,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-04-03",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 7.8,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2013-04-04",
    "precipitation": 8.4,
    "temp_max": 14.4,
    "temp_min": 10,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-04-05",
    "precipitation": 18.5,
    "temp_max": 13.9,
    "temp_min": 10,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2013-04-06",
    "precipitation": 12.7,
    "temp_max": 12.2,
    "temp_min": 7.2,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2013-04-07",
    "precipitation": 39.1,
    "temp_max": 8.3,
    "temp_min": 5,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-04-08",
    "precipitation": 0.8,
    "temp_max": 13.3,
    "temp_min": 6.1,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-04-09",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2013-04-10",
    "precipitation": 9.4,
    "temp_max": 15,
    "temp_min": 8.9,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2013-04-11",
    "precipitation": 1.5,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2013-04-12",
    "precipitation": 9.7,
    "temp_max": 7.8,
    "temp_min": 4.4,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2013-04-13",
    "precipitation": 9.4,
    "temp_max": 10.6,
    "temp_min": 3.3,
    "wind": 5.7,
    "weather": "rain"
  },
  {
    "date": "2013-04-14",
    "precipitation": 5.8,
    "temp_max": 12.8,
    "temp_min": 4.4,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2013-04-15",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 4.4,
    "wind": 2.4,
    "weather": "fog"
  },
  {
    "date": "2013-04-16",
    "precipitation": 0.3,
    "temp_max": 13.9,
    "temp_min": 3.3,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-04-17",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 3.9,
    "wind": 3.3,
    "weather": "drizzle"
  },
  {
    "date": "2013-04-18",
    "precipitation": 5.3,
    "temp_max": 11.7,
    "temp_min": 6.7,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2013-04-19",
    "precipitation": 20.6,
    "temp_max": 13.3,
    "temp_min": 9.4,
    "wind": 4.9,
    "weather": "rain"
  },
  {
    "date": "2013-04-20",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 8.3,
    "wind": 5.8,
    "weather": "sun"
  },
  {
    "date": "2013-04-21",
    "precipitation": 3.3,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2013-04-22",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 5,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2013-04-23",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 3.9,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2013-04-24",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 6.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-04-25",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 6.7,
    "wind": 1.1,
    "weather": "sun"
  },
  {
    "date": "2013-04-26",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 8.3,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2013-04-27",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 10.6,
    "wind": 5.9,
    "weather": "sun"
  },
  {
    "date": "2013-04-28",
    "precipitation": 1,
    "temp_max": 15,
    "temp_min": 9.4,
    "wind": 5.2,
    "weather": "rain"
  },
  {
    "date": "2013-04-29",
    "precipitation": 3.8,
    "temp_max": 13.9,
    "temp_min": 6.7,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2013-04-30",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 4.4,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2013-05-01",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 3.3,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-05-02",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 6.7,
    "wind": 4,
    "weather": "sun"
  },
  {
    "date": "2013-05-03",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 9.4,
    "wind": 4.9,
    "weather": "sun"
  },
  {
    "date": "2013-05-04",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 11.1,
    "wind": 6.5,
    "weather": "sun"
  },
  {
    "date": "2013-05-05",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 11.7,
    "wind": 5.3,
    "weather": "sun"
  },
  {
    "date": "2013-05-06",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 12.2,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-05-07",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 11.1,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2013-05-08",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-05-09",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 10,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-05-10",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 9.4,
    "wind": 1,
    "weather": "sun"
  },
  {
    "date": "2013-05-11",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 12.2,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-05-12",
    "precipitation": 6.6,
    "temp_max": 21.7,
    "temp_min": 13.9,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-05-13",
    "precipitation": 3.3,
    "temp_max": 18.9,
    "temp_min": 9.4,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2013-05-14",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 7.8,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2013-05-15",
    "precipitation": 1,
    "temp_max": 17.2,
    "temp_min": 8.9,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2013-05-16",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 12.2,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2013-05-17",
    "precipitation": 0.5,
    "temp_max": 17.2,
    "temp_min": 11.7,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2013-05-18",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 11.1,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-05-19",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-05-20",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 9.4,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2013-05-21",
    "precipitation": 13.7,
    "temp_max": 15.6,
    "temp_min": 8.3,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2013-05-22",
    "precipitation": 13.7,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-05-23",
    "precipitation": 4.1,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2013-05-24",
    "precipitation": 0.3,
    "temp_max": 16.7,
    "temp_min": 8.9,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2013-05-25",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2013-05-26",
    "precipitation": 1.5,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-05-27",
    "precipitation": 9.7,
    "temp_max": 16.7,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-05-28",
    "precipitation": 0.5,
    "temp_max": 17.2,
    "temp_min": 11.7,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2013-05-29",
    "precipitation": 5.6,
    "temp_max": 16.1,
    "temp_min": 9.4,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2013-05-30",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 9.4,
    "wind": 5.3,
    "weather": "sun"
  },
  {
    "date": "2013-05-31",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-06-01",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.2,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-06-02",
    "precipitation": 1,
    "temp_max": 20.6,
    "temp_min": 12.2,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-06-03",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 11.1,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-06-04",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 12.2,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2013-06-05",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 14.4,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-06-06",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.2,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-06-07",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.3,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2013-06-08",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-06-09",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 11.1,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-10",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 11.7,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2013-06-11",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 10,
    "wind": 5.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-12",
    "precipitation": 0.3,
    "temp_max": 20.6,
    "temp_min": 11.7,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2013-06-13",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 11.7,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-06-14",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 12.2,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-15",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 10,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-06-16",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 12.8,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2013-06-17",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-06-18",
    "precipitation": 0.3,
    "temp_max": 23.3,
    "temp_min": 13.3,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2013-06-19",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 12.8,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-20",
    "precipitation": 3,
    "temp_max": 17.2,
    "temp_min": 12.8,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2013-06-21",
    "precipitation": 0.3,
    "temp_max": 20.6,
    "temp_min": 12.2,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2013-06-22",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 11.7,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-23",
    "precipitation": 7.9,
    "temp_max": 22.2,
    "temp_min": 15,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2013-06-24",
    "precipitation": 4.8,
    "temp_max": 21.1,
    "temp_min": 13.9,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2013-06-25",
    "precipitation": 9.9,
    "temp_max": 23.3,
    "temp_min": 14.4,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2013-06-26",
    "precipitation": 2,
    "temp_max": 22.2,
    "temp_min": 15,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2013-06-27",
    "precipitation": 3.6,
    "temp_max": 21.1,
    "temp_min": 16.7,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2013-06-28",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 16.1,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-06-29",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 18.3,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2013-06-30",
    "precipitation": 0,
    "temp_max": 33.9,
    "temp_min": 17.2,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-07-01",
    "precipitation": 0,
    "temp_max": 31.7,
    "temp_min": 18.3,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-07-02",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15.6,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-07-03",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 16.7,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2013-07-04",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.9,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2013-07-05",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 13.9,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-07-06",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.3,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-07-07",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.9,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-07-08",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 13.3,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2013-07-09",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 15,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-07-10",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 13.9,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-07-11",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.2,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-07-12",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 13.3,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-07-13",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-07-14",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 12.8,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-07-15",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 14.4,
    "wind": 4.6,
    "weather": "sun"
  },
  {
    "date": "2013-07-16",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 18.3,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2013-07-17",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 15,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-07-18",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.9,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-07-19",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.3,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-07-20",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-07-21",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 12.8,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-07-22",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.3,
    "wind": 2.4,
    "weather": "fog"
  },
  {
    "date": "2013-07-23",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 13.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-07-24",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 14.4,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-07-25",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 12.8,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-07-26",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 14.4,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-07-27",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-07-28",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 12.2,
    "wind": 3.4,
    "weather": "fog"
  },
  {
    "date": "2013-07-29",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2013-07-30",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2013-07-31",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.3,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2013-08-01",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 13.3,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-02",
    "precipitation": 2,
    "temp_max": 17.2,
    "temp_min": 15,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2013-08-03",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 15.6,
    "wind": 2.4,
    "weather": "fog"
  },
  {
    "date": "2013-08-04",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 15,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2013-08-05",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 15,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-08-06",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 13.9,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2013-08-07",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 13.9,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-08",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 14.4,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-08-09",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 14.4,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-08-10",
    "precipitation": 2.3,
    "temp_max": 25.6,
    "temp_min": 15,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2013-08-11",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 14.4,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-12",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 16.1,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-13",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 15,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2013-08-14",
    "precipitation": 0.8,
    "temp_max": 27.2,
    "temp_min": 15,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2013-08-15",
    "precipitation": 1.8,
    "temp_max": 21.1,
    "temp_min": 17.2,
    "wind": 1,
    "weather": "rain"
  },
  {
    "date": "2013-08-16",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 16.1,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2013-08-17",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 17.2,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-08-18",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 15.6,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-08-19",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 15.6,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2013-08-20",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 16.1,
    "wind": 4.6,
    "weather": "sun"
  },
  {
    "date": "2013-08-21",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 15,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2013-08-22",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 15,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-23",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 16.1,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2013-08-24",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 16.7,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2013-08-25",
    "precipitation": 0.3,
    "temp_max": 22.2,
    "temp_min": 16.1,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-08-26",
    "precipitation": 1,
    "temp_max": 24.4,
    "temp_min": 16.1,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2013-08-27",
    "precipitation": 1.3,
    "temp_max": 26.7,
    "temp_min": 17.2,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2013-08-28",
    "precipitation": 5.6,
    "temp_max": 26.7,
    "temp_min": 15.6,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2013-08-29",
    "precipitation": 19.3,
    "temp_max": 23.9,
    "temp_min": 18.3,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-08-30",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 16.1,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2013-08-31",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-09-01",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 15.6,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-09-02",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 17.2,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-09-03",
    "precipitation": 2.3,
    "temp_max": 25,
    "temp_min": 16.7,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2013-09-04",
    "precipitation": 0.3,
    "temp_max": 22.8,
    "temp_min": 16.1,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2013-09-05",
    "precipitation": 27.7,
    "temp_max": 20,
    "temp_min": 15.6,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2013-09-06",
    "precipitation": 21.3,
    "temp_max": 21.7,
    "temp_min": 16.1,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-09-07",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 17.2,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-09-08",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 14.4,
    "wind": 1.5,
    "weather": "fog"
  },
  {
    "date": "2013-09-09",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.9,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-09-10",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 15,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-09-11",
    "precipitation": 0,
    "temp_max": 33.9,
    "temp_min": 16.1,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2013-09-12",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 15,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2013-09-13",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 15.6,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2013-09-14",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 15.6,
    "wind": 1.4,
    "weather": "fog"
  },
  {
    "date": "2013-09-15",
    "precipitation": 3.3,
    "temp_max": 18.9,
    "temp_min": 14.4,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-09-16",
    "precipitation": 0.3,
    "temp_max": 21.7,
    "temp_min": 15,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2013-09-17",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 13.9,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2013-09-18",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-09-19",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 10,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2013-09-20",
    "precipitation": 3.6,
    "temp_max": 23.3,
    "temp_min": 13.3,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-09-21",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-09-22",
    "precipitation": 13.5,
    "temp_max": 17.2,
    "temp_min": 13.3,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2013-09-23",
    "precipitation": 2.8,
    "temp_max": 16.1,
    "temp_min": 11.1,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2013-09-24",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-09-25",
    "precipitation": 2,
    "temp_max": 16.1,
    "temp_min": 9.4,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-09-26",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 7.2,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-09-27",
    "precipitation": 1,
    "temp_max": 13.9,
    "temp_min": 10.6,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2013-09-28",
    "precipitation": 43.4,
    "temp_max": 16.7,
    "temp_min": 11.7,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2013-09-29",
    "precipitation": 16.8,
    "temp_max": 14.4,
    "temp_min": 11.1,
    "wind": 7.1,
    "weather": "rain"
  },
  {
    "date": "2013-09-30",
    "precipitation": 18.5,
    "temp_max": 13.9,
    "temp_min": 10,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2013-10-01",
    "precipitation": 7.9,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2013-10-02",
    "precipitation": 5.3,
    "temp_max": 12.8,
    "temp_min": 9.4,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2013-10-03",
    "precipitation": 0.8,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 0.9,
    "weather": "rain"
  },
  {
    "date": "2013-10-04",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 5.6,
    "wind": 1.1,
    "weather": "sun"
  },
  {
    "date": "2013-10-05",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 8.3,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2013-10-06",
    "precipitation": 4.1,
    "temp_max": 22.8,
    "temp_min": 7.8,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-10-07",
    "precipitation": 0.5,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2013-10-08",
    "precipitation": 6.9,
    "temp_max": 13.9,
    "temp_min": 7.8,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2013-10-09",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 5.6,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2013-10-10",
    "precipitation": 1,
    "temp_max": 14.4,
    "temp_min": 8.3,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2013-10-11",
    "precipitation": 9.1,
    "temp_max": 13.9,
    "temp_min": 10.6,
    "wind": 1,
    "weather": "rain"
  },
  {
    "date": "2013-10-12",
    "precipitation": 1,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-10-13",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 6.7,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2013-10-14",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 3.9,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2013-10-15",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 5,
    "wind": 0.9,
    "weather": "sun"
  },
  {
    "date": "2013-10-16",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 8.9,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2013-10-17",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 1.7,
    "weather": "fog"
  },
  {
    "date": "2013-10-18",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 7.2,
    "wind": 1.2,
    "weather": "sun"
  },
  {
    "date": "2013-10-19",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 7.8,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2013-10-20",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 7.8,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2013-10-21",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 8.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2013-10-22",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2013-10-23",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 0.4,
    "weather": "sun"
  },
  {
    "date": "2013-10-24",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 6.1,
    "wind": 0.6,
    "weather": "sun"
  },
  {
    "date": "2013-10-25",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 7.8,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2013-10-26",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 8.3,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2013-10-27",
    "precipitation": 1.8,
    "temp_max": 13.9,
    "temp_min": 8.3,
    "wind": 4.4,
    "weather": "rain"
  },
  {
    "date": "2013-10-28",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2013-10-29",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 3.3,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-10-30",
    "precipitation": 0.5,
    "temp_max": 15,
    "temp_min": 5.6,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-10-31",
    "precipitation": 0.3,
    "temp_max": 14.4,
    "temp_min": 10.6,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-11-01",
    "precipitation": 1.3,
    "temp_max": 17.8,
    "temp_min": 11.7,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2013-11-02",
    "precipitation": 12.7,
    "temp_max": 14.4,
    "temp_min": 8.3,
    "wind": 7.9,
    "weather": "rain"
  },
  {
    "date": "2013-11-03",
    "precipitation": 0.5,
    "temp_max": 12.2,
    "temp_min": 4.4,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2013-11-04",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 3.9,
    "wind": 1.6,
    "weather": "drizzle"
  },
  {
    "date": "2013-11-05",
    "precipitation": 2.5,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2013-11-06",
    "precipitation": 3.8,
    "temp_max": 12.8,
    "temp_min": 7.8,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2013-11-07",
    "precipitation": 30,
    "temp_max": 11.1,
    "temp_min": 10,
    "wind": 7.2,
    "weather": "rain"
  },
  {
    "date": "2013-11-08",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2013-11-09",
    "precipitation": 1.8,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2013-11-10",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 8.3,
    "wind": 4.4,
    "weather": "sun"
  },
  {
    "date": "2013-11-11",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 6.1,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2013-11-12",
    "precipitation": 4.1,
    "temp_max": 15.6,
    "temp_min": 8.9,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2013-11-13",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 10.6,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2013-11-14",
    "precipitation": 1.3,
    "temp_max": 11.1,
    "temp_min": 6.1,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2013-11-15",
    "precipitation": 3,
    "temp_max": 10.6,
    "temp_min": 7.2,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2013-11-16",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 5,
    "wind": 4.6,
    "weather": "sun"
  },
  {
    "date": "2013-11-17",
    "precipitation": 5.3,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 5.4,
    "weather": "rain"
  },
  {
    "date": "2013-11-18",
    "precipitation": 26.2,
    "temp_max": 12.8,
    "temp_min": 9.4,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-11-19",
    "precipitation": 1,
    "temp_max": 13.3,
    "temp_min": 4.4,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2013-11-20",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 1.7,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2013-11-21",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": -0.5,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2013-11-22",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 0,
    "wind": 4.6,
    "weather": "sun"
  },
  {
    "date": "2013-11-23",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 1.1,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-11-24",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 0.6,
    "wind": 0.9,
    "weather": "fog"
  },
  {
    "date": "2013-11-25",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 2.2,
    "wind": 0.5,
    "weather": "sun"
  },
  {
    "date": "2013-11-26",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 2.8,
    "wind": 1,
    "weather": "sun"
  },
  {
    "date": "2013-11-27",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 5.6,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-11-28",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 3.3,
    "wind": 0.7,
    "weather": "sun"
  },
  {
    "date": "2013-11-29",
    "precipitation": 0.5,
    "temp_max": 9.4,
    "temp_min": 5,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2013-11-30",
    "precipitation": 2.3,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-12-01",
    "precipitation": 3,
    "temp_max": 13.3,
    "temp_min": 7.8,
    "wind": 8.8,
    "weather": "rain"
  },
  {
    "date": "2013-12-02",
    "precipitation": 4.6,
    "temp_max": 7.8,
    "temp_min": 1.7,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2013-12-03",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": -0.5,
    "wind": 5.6,
    "weather": "sun"
  },
  {
    "date": "2013-12-04",
    "precipitation": 0,
    "temp_max": 4.4,
    "temp_min": -2.1,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2013-12-05",
    "precipitation": 0,
    "temp_max": 1.1,
    "temp_min": -4.9,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2013-12-06",
    "precipitation": 0,
    "temp_max": 1.1,
    "temp_min": -4.3,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2013-12-07",
    "precipitation": 0,
    "temp_max": 0,
    "temp_min": -7.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2013-12-08",
    "precipitation": 0,
    "temp_max": 2.2,
    "temp_min": -6.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2013-12-09",
    "precipitation": 0,
    "temp_max": 1.1,
    "temp_min": -4.9,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-12-10",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": 0.6,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2013-12-11",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": -1.6,
    "wind": 0.8,
    "weather": "sun"
  },
  {
    "date": "2013-12-12",
    "precipitation": 6.9,
    "temp_max": 5.6,
    "temp_min": -0.5,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2013-12-13",
    "precipitation": 0.5,
    "temp_max": 9.4,
    "temp_min": 5.6,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2013-12-14",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2013-12-15",
    "precipitation": 1.3,
    "temp_max": 11.7,
    "temp_min": 8.3,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2013-12-16",
    "precipitation": 0.3,
    "temp_max": 10,
    "temp_min": 4.4,
    "wind": 1,
    "weather": "rain"
  },
  {
    "date": "2013-12-17",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 4.4,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2013-12-18",
    "precipitation": 1.3,
    "temp_max": 7.8,
    "temp_min": 2.2,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2013-12-19",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": 0,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2013-12-20",
    "precipitation": 5.6,
    "temp_max": 8.3,
    "temp_min": 0.6,
    "wind": 3.7,
    "weather": "snow"
  },
  {
    "date": "2013-12-21",
    "precipitation": 5.6,
    "temp_max": 8.9,
    "temp_min": 5.6,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2013-12-22",
    "precipitation": 10.7,
    "temp_max": 10.6,
    "temp_min": 8.3,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2013-12-23",
    "precipitation": 1.5,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2013-12-24",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 2.8,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2013-12-25",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 1.7,
    "wind": 0.8,
    "weather": "sun"
  },
  {
    "date": "2013-12-26",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 0.6,
    "wind": 0.5,
    "weather": "sun"
  },
  {
    "date": "2013-12-27",
    "precipitation": 0.3,
    "temp_max": 8.9,
    "temp_min": 0,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2013-12-28",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 3.3,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2013-12-29",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 1.7,
    "wind": 1.1,
    "weather": "sun"
  },
  {
    "date": "2013-12-30",
    "precipitation": 0.3,
    "temp_max": 8.9,
    "temp_min": 4.4,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2013-12-31",
    "precipitation": 0.5,
    "temp_max": 8.3,
    "temp_min": 5,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2014-01-01",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 3.3,
    "wind": 1.2,
    "weather": "sun"
  },
  {
    "date": "2014-01-02",
    "precipitation": 4.1,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2014-01-03",
    "precipitation": 1.5,
    "temp_max": 8.9,
    "temp_min": 2.8,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-04",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 0.6,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2014-01-05",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": -0.5,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2014-01-06",
    "precipitation": 0.3,
    "temp_max": 7.8,
    "temp_min": -0.5,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-07",
    "precipitation": 12.2,
    "temp_max": 8.3,
    "temp_min": 5,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-08",
    "precipitation": 9.7,
    "temp_max": 10,
    "temp_min": 7.2,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-09",
    "precipitation": 5.8,
    "temp_max": 9.4,
    "temp_min": 5.6,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2014-01-10",
    "precipitation": 4.3,
    "temp_max": 12.8,
    "temp_min": 8.3,
    "wind": 7,
    "weather": "rain"
  },
  {
    "date": "2014-01-11",
    "precipitation": 21.3,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 8.8,
    "weather": "rain"
  },
  {
    "date": "2014-01-12",
    "precipitation": 1.5,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 8.1,
    "weather": "rain"
  },
  {
    "date": "2014-01-13",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 10,
    "wind": 7.1,
    "weather": "sun"
  },
  {
    "date": "2014-01-14",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2014-01-15",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-01-16",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 4.4,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-01-17",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": 2.8,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-01-18",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 0.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-01-19",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": 3.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-01-20",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-01-21",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 1.7,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2014-01-22",
    "precipitation": 0.5,
    "temp_max": 9.4,
    "temp_min": 5.6,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-23",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 5.2,
    "weather": "fog"
  },
  {
    "date": "2014-01-24",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 1.1,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2014-01-25",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 1.1,
    "wind": 0.8,
    "weather": "sun"
  },
  {
    "date": "2014-01-26",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 0.6,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2014-01-27",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 1.7,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2014-01-28",
    "precipitation": 8.9,
    "temp_max": 11.1,
    "temp_min": 6.1,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2014-01-29",
    "precipitation": 21.6,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2014-01-30",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 6.1,
    "wind": 6.4,
    "weather": "sun"
  },
  {
    "date": "2014-01-31",
    "precipitation": 2.3,
    "temp_max": 7.8,
    "temp_min": 5.6,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-02-01",
    "precipitation": 2,
    "temp_max": 7.8,
    "temp_min": 2.8,
    "wind": 0.8,
    "weather": "rain"
  },
  {
    "date": "2014-02-02",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 1.1,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-02-03",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": 0,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2014-02-04",
    "precipitation": 0,
    "temp_max": 2.8,
    "temp_min": -2.1,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2014-02-05",
    "precipitation": 0,
    "temp_max": -0.5,
    "temp_min": -5.5,
    "wind": 6.6,
    "weather": "sun"
  },
  {
    "date": "2014-02-06",
    "precipitation": 0,
    "temp_max": -1.6,
    "temp_min": -6,
    "wind": 4.5,
    "weather": "sun"
  },
  {
    "date": "2014-02-07",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -4.9,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-02-08",
    "precipitation": 5.1,
    "temp_max": 5.6,
    "temp_min": -0.5,
    "wind": 4.6,
    "weather": "snow"
  },
  {
    "date": "2014-02-09",
    "precipitation": 0.5,
    "temp_max": 3.9,
    "temp_min": 0,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2014-02-10",
    "precipitation": 18.3,
    "temp_max": 10,
    "temp_min": 2.2,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-02-11",
    "precipitation": 17,
    "temp_max": 12.2,
    "temp_min": 5.6,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-02-12",
    "precipitation": 4.6,
    "temp_max": 12.2,
    "temp_min": 7.2,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2014-02-13",
    "precipitation": 1.8,
    "temp_max": 12.8,
    "temp_min": 7.8,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2014-02-14",
    "precipitation": 9.4,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2014-02-15",
    "precipitation": 11.7,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-02-16",
    "precipitation": 26.4,
    "temp_max": 9.4,
    "temp_min": 3.9,
    "wind": 7.9,
    "weather": "rain"
  },
  {
    "date": "2014-02-17",
    "precipitation": 14.5,
    "temp_max": 8.3,
    "temp_min": 4.4,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2014-02-18",
    "precipitation": 15.2,
    "temp_max": 8.9,
    "temp_min": 5,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2014-02-19",
    "precipitation": 1,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2014-02-20",
    "precipitation": 3,
    "temp_max": 10,
    "temp_min": 5.6,
    "wind": 6.9,
    "weather": "rain"
  },
  {
    "date": "2014-02-21",
    "precipitation": 2.8,
    "temp_max": 6.7,
    "temp_min": 3.9,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2014-02-22",
    "precipitation": 2.5,
    "temp_max": 5.6,
    "temp_min": 2.8,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-02-23",
    "precipitation": 6.1,
    "temp_max": 7.2,
    "temp_min": 3.9,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-02-24",
    "precipitation": 13,
    "temp_max": 6.7,
    "temp_min": 3.3,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2014-02-25",
    "precipitation": 0.3,
    "temp_max": 12.2,
    "temp_min": 3.9,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2014-02-26",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 5.6,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-02-27",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 4.4,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-02-28",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 4.4,
    "wind": 5.9,
    "weather": "sun"
  },
  {
    "date": "2014-03-01",
    "precipitation": 0.5,
    "temp_max": 7.2,
    "temp_min": 4.4,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-03-02",
    "precipitation": 19.1,
    "temp_max": 11.1,
    "temp_min": 2.8,
    "wind": 5.7,
    "weather": "rain"
  },
  {
    "date": "2014-03-03",
    "precipitation": 10.7,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-03-04",
    "precipitation": 16.5,
    "temp_max": 13.9,
    "temp_min": 7.8,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-03-05",
    "precipitation": 46.7,
    "temp_max": 15.6,
    "temp_min": 10.6,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-03-06",
    "precipitation": 3,
    "temp_max": 13.3,
    "temp_min": 10,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2014-03-07",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 8.9,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-03-08",
    "precipitation": 32.3,
    "temp_max": 12.8,
    "temp_min": 6.7,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2014-03-09",
    "precipitation": 4.3,
    "temp_max": 15,
    "temp_min": 9.4,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2014-03-10",
    "precipitation": 18.8,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2014-03-11",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 4.4,
    "wind": 2.3,
    "weather": "fog"
  },
  {
    "date": "2014-03-12",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 3.3,
    "wind": 1.9,
    "weather": "fog"
  },
  {
    "date": "2014-03-13",
    "precipitation": 0.5,
    "temp_max": 13.9,
    "temp_min": 5,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2014-03-14",
    "precipitation": 6.9,
    "temp_max": 14.4,
    "temp_min": 8.3,
    "wind": 6.1,
    "weather": "rain"
  },
  {
    "date": "2014-03-15",
    "precipitation": 8.1,
    "temp_max": 16.7,
    "temp_min": 4.4,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2014-03-16",
    "precipitation": 27.7,
    "temp_max": 10.6,
    "temp_min": 4.4,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-03-17",
    "precipitation": 0.3,
    "temp_max": 10,
    "temp_min": 2.8,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2014-03-18",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 3.3,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2014-03-19",
    "precipitation": 0.5,
    "temp_max": 11.1,
    "temp_min": 3.3,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-03-20",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 1.7,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2014-03-21",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 2.8,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2014-03-22",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 1.1,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2014-03-23",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 4.4,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2014-03-24",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 2.8,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-03-25",
    "precipitation": 4.1,
    "temp_max": 13.9,
    "temp_min": 6.7,
    "wind": 4.4,
    "weather": "rain"
  },
  {
    "date": "2014-03-26",
    "precipitation": 3.6,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2014-03-27",
    "precipitation": 0.3,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2014-03-28",
    "precipitation": 22.1,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-03-29",
    "precipitation": 14,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-03-30",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2014-03-31",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 2.2,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2014-04-01",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 6.7,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-04-02",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 5.6,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-04-03",
    "precipitation": 2.5,
    "temp_max": 13.3,
    "temp_min": 6.1,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-04-04",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2014-04-05",
    "precipitation": 4.6,
    "temp_max": 11.7,
    "temp_min": 7.8,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2014-04-06",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 8.3,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-04-07",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 9.4,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-04-08",
    "precipitation": 4.6,
    "temp_max": 15.6,
    "temp_min": 8.3,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2014-04-09",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 6.7,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2014-04-10",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 6.7,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-04-11",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 5,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-04-12",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 7.8,
    "wind": 4.4,
    "weather": "sun"
  },
  {
    "date": "2014-04-13",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 5.6,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2014-04-14",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 5.6,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-04-15",
    "precipitation": 0.5,
    "temp_max": 14.4,
    "temp_min": 7.8,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2014-04-16",
    "precipitation": 10.9,
    "temp_max": 11.1,
    "temp_min": 8.9,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2014-04-17",
    "precipitation": 18.5,
    "temp_max": 11.7,
    "temp_min": 7.2,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-04-18",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 5.6,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2014-04-19",
    "precipitation": 13.7,
    "temp_max": 11.7,
    "temp_min": 5.6,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-04-20",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 5.6,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-04-21",
    "precipitation": 5.1,
    "temp_max": 17.2,
    "temp_min": 7.8,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2014-04-22",
    "precipitation": 14.2,
    "temp_max": 12.2,
    "temp_min": 5,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2014-04-23",
    "precipitation": 8.9,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2014-04-24",
    "precipitation": 12.4,
    "temp_max": 13.9,
    "temp_min": 6.1,
    "wind": 5.3,
    "weather": "rain"
  },
  {
    "date": "2014-04-25",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 5.6,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-04-26",
    "precipitation": 3.3,
    "temp_max": 15,
    "temp_min": 5.6,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-04-27",
    "precipitation": 6.9,
    "temp_max": 11.1,
    "temp_min": 6.1,
    "wind": 5.8,
    "weather": "rain"
  },
  {
    "date": "2014-04-28",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 4.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-04-29",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 9.4,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-04-30",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 9.4,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2014-05-01",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 11.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2014-05-02",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-03",
    "precipitation": 33.3,
    "temp_max": 15,
    "temp_min": 8.9,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2014-05-04",
    "precipitation": 16,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2014-05-05",
    "precipitation": 5.1,
    "temp_max": 15.6,
    "temp_min": 9.4,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-05-06",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 8.3,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-05-07",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 7.2,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-08",
    "precipitation": 13.7,
    "temp_max": 13.9,
    "temp_min": 9.4,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2014-05-09",
    "precipitation": 2,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2014-05-10",
    "precipitation": 0.5,
    "temp_max": 15.6,
    "temp_min": 7.2,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2014-05-11",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 8.3,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-12",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 9.4,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-13",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2014-05-14",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.3,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2014-05-15",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2014-05-16",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 11.7,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2014-05-17",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 11.7,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-05-18",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 10.6,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-05-19",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 10,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-05-20",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-21",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 10.6,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2014-05-22",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 11.7,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-05-23",
    "precipitation": 3.8,
    "temp_max": 20,
    "temp_min": 12.8,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2014-05-24",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 11.1,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-05-25",
    "precipitation": 5.6,
    "temp_max": 15,
    "temp_min": 10.6,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2014-05-26",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 11.1,
    "wind": 4.5,
    "weather": "sun"
  },
  {
    "date": "2014-05-27",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 10,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-05-28",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 10,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2014-05-29",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 11.1,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2014-05-30",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 8.9,
    "wind": 4.5,
    "weather": "sun"
  },
  {
    "date": "2014-05-31",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 10,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-06-01",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10.6,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-06-02",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 11.1,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-06-03",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 11.1,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-06-04",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 10,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-06-05",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-06-06",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 10.6,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-06-07",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 13.3,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2014-06-08",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.2,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2014-06-09",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-06-10",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 12.2,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2014-06-11",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-06-12",
    "precipitation": 1.8,
    "temp_max": 21.7,
    "temp_min": 12.2,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2014-06-13",
    "precipitation": 6.4,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2014-06-14",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 11.7,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-06-15",
    "precipitation": 0.5,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2014-06-16",
    "precipitation": 3.6,
    "temp_max": 17.8,
    "temp_min": 8.9,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2014-06-17",
    "precipitation": 1.3,
    "temp_max": 17.8,
    "temp_min": 10,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2014-06-18",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-06-19",
    "precipitation": 0.8,
    "temp_max": 25.6,
    "temp_min": 11.7,
    "wind": 3.7,
    "weather": "rain"
  },
  {
    "date": "2014-06-20",
    "precipitation": 0.3,
    "temp_max": 20,
    "temp_min": 10,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2014-06-21",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 10.6,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-06-22",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-06-23",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-06-24",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 14.4,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-06-25",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.9,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-06-26",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 14.4,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2014-06-27",
    "precipitation": 1.8,
    "temp_max": 21.1,
    "temp_min": 13.9,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2014-06-28",
    "precipitation": 2.3,
    "temp_max": 20,
    "temp_min": 13.3,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2014-06-29",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-06-30",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.8,
    "wind": 4.4,
    "weather": "sun"
  },
  {
    "date": "2014-07-01",
    "precipitation": 0,
    "temp_max": 34.4,
    "temp_min": 15.6,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2014-07-02",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 14.4,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-07-03",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.9,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2014-07-04",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.9,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-07-05",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 13.3,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2014-07-06",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 15,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2014-07-07",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 17.8,
    "wind": 4.1,
    "weather": "fog"
  },
  {
    "date": "2014-07-08",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 15.6,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2014-07-09",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 13.9,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-07-10",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 12.8,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2014-07-11",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 15,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-07-12",
    "precipitation": 0,
    "temp_max": 32.2,
    "temp_min": 16.7,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-07-13",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 15,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-07-14",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 15,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-07-15",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 13.9,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-07-16",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 14.4,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-07-17",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 13.9,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2014-07-18",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.7,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-07-19",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 15,
    "wind": 5.4,
    "weather": "fog"
  },
  {
    "date": "2014-07-20",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 14.4,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-07-21",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.3,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-07-22",
    "precipitation": 0.3,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2014-07-23",
    "precipitation": 19.3,
    "temp_max": 18.9,
    "temp_min": 13.3,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2014-07-24",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2014-07-25",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 12.2,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-07-26",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 13.3,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-07-27",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2014-07-28",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 15,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2014-07-29",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 15.6,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-07-30",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 14.4,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2014-07-31",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 17.8,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2014-08-01",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 15,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2014-08-02",
    "precipitation": 0.5,
    "temp_max": 29.4,
    "temp_min": 15.6,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2014-08-03",
    "precipitation": 0,
    "temp_max": 31.7,
    "temp_min": 14.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-08-04",
    "precipitation": 0,
    "temp_max": 32.8,
    "temp_min": 16.1,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-08-05",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.9,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-08-06",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 15,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2014-08-07",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.3,
    "wind": 2.4,
    "weather": "fog"
  },
  {
    "date": "2014-08-08",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.3,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2014-08-09",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 15.6,
    "wind": 4.1,
    "weather": "sun"
  },
  {
    "date": "2014-08-10",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 13.9,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2014-08-11",
    "precipitation": 0.5,
    "temp_max": 35.6,
    "temp_min": 17.8,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2014-08-12",
    "precipitation": 12.7,
    "temp_max": 27.2,
    "temp_min": 17.2,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-08-13",
    "precipitation": 21.6,
    "temp_max": 23.3,
    "temp_min": 15,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2014-08-14",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 17.2,
    "wind": 0.6,
    "weather": "sun"
  },
  {
    "date": "2014-08-15",
    "precipitation": 1,
    "temp_max": 24.4,
    "temp_min": 16.7,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2014-08-16",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 15.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-08-17",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 15,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-08-18",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 15.6,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2014-08-19",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 15.6,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2014-08-20",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.9,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-08-21",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 11.1,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2014-08-22",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.3,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2014-08-23",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2014-08-24",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 13.3,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-08-25",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 14.4,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2014-08-26",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 15.6,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2014-08-27",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 16.1,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2014-08-28",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 14.4,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-08-29",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 15,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2014-08-30",
    "precipitation": 8.4,
    "temp_max": 17.8,
    "temp_min": 15,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2014-08-31",
    "precipitation": 1.3,
    "temp_max": 21.1,
    "temp_min": 13.9,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2014-09-01",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.8,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2014-09-02",
    "precipitation": 3,
    "temp_max": 20,
    "temp_min": 13.9,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2014-09-03",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2014-09-04",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "fog"
  },
  {
    "date": "2014-09-05",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 6.5,
    "weather": "fog"
  },
  {
    "date": "2014-09-06",
    "precipitation": 0,
    "temp_max": 32.2,
    "temp_min": 15,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2014-09-07",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 13.3,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2014-09-08",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-09-09",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.3,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-09-10",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 12.2,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2014-09-11",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 12.8,
    "wind": 5.3,
    "weather": "sun"
  },
  {
    "date": "2014-09-12",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 12.8,
    "wind": 5.9,
    "weather": "sun"
  },
  {
    "date": "2014-09-13",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 10,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-09-14",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 11.7,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2014-09-15",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 12.2,
    "wind": 1.2,
    "weather": "sun"
  },
  {
    "date": "2014-09-16",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 13.9,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-09-17",
    "precipitation": 0.5,
    "temp_max": 22.8,
    "temp_min": 14.4,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2014-09-18",
    "precipitation": 0.3,
    "temp_max": 19.4,
    "temp_min": 15,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-09-19",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 16.1,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-09-20",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 14.4,
    "wind": 4.4,
    "weather": "fog"
  },
  {
    "date": "2014-09-21",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 12.8,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2014-09-22",
    "precipitation": 0.3,
    "temp_max": 22.2,
    "temp_min": 15,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2014-09-23",
    "precipitation": 18.3,
    "temp_max": 18.9,
    "temp_min": 14.4,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2014-09-24",
    "precipitation": 20.3,
    "temp_max": 18.9,
    "temp_min": 14.4,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2014-09-25",
    "precipitation": 4.3,
    "temp_max": 21.7,
    "temp_min": 14.4,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2014-09-26",
    "precipitation": 8.9,
    "temp_max": 20,
    "temp_min": 13.9,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2014-09-27",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 11.7,
    "wind": 3.2,
    "weather": "fog"
  },
  {
    "date": "2014-09-28",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 12.2,
    "wind": 2,
    "weather": "fog"
  },
  {
    "date": "2014-09-29",
    "precipitation": 0.8,
    "temp_max": 16.7,
    "temp_min": 11.1,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2014-09-30",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 12.2,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2014-10-01",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 11.1,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2014-10-02",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 10,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2014-10-03",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 8.9,
    "wind": 1,
    "weather": "sun"
  },
  {
    "date": "2014-10-04",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 12.2,
    "wind": 1.2,
    "weather": "sun"
  },
  {
    "date": "2014-10-05",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 11.7,
    "wind": 1.4,
    "weather": "fog"
  },
  {
    "date": "2014-10-06",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.3,
    "wind": 2.5,
    "weather": "fog"
  },
  {
    "date": "2014-10-07",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 13.9,
    "wind": 1,
    "weather": "fog"
  },
  {
    "date": "2014-10-08",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2014-10-09",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 11.1,
    "wind": 1,
    "weather": "fog"
  },
  {
    "date": "2014-10-10",
    "precipitation": 0.3,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-10-11",
    "precipitation": 7.4,
    "temp_max": 18.3,
    "temp_min": 11.7,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2014-10-12",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 11.7,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2014-10-13",
    "precipitation": 7.6,
    "temp_max": 21.1,
    "temp_min": 10,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-10-14",
    "precipitation": 7.1,
    "temp_max": 16.7,
    "temp_min": 11.7,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2014-10-15",
    "precipitation": 8.6,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-10-16",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 11.1,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2014-10-17",
    "precipitation": 3.3,
    "temp_max": 16.7,
    "temp_min": 11.7,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2014-10-18",
    "precipitation": 15,
    "temp_max": 19.4,
    "temp_min": 13.9,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2014-10-19",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 12.8,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2014-10-20",
    "precipitation": 11.7,
    "temp_max": 16.1,
    "temp_min": 12.2,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-10-21",
    "precipitation": 1,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-10-22",
    "precipitation": 32,
    "temp_max": 15.6,
    "temp_min": 11.7,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2014-10-23",
    "precipitation": 9.4,
    "temp_max": 14.4,
    "temp_min": 8.3,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2014-10-24",
    "precipitation": 4.1,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2014-10-25",
    "precipitation": 6.1,
    "temp_max": 16.7,
    "temp_min": 8.3,
    "wind": 5.4,
    "weather": "rain"
  },
  {
    "date": "2014-10-26",
    "precipitation": 1.5,
    "temp_max": 12.8,
    "temp_min": 7.8,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2014-10-27",
    "precipitation": 0.8,
    "temp_max": 15.6,
    "temp_min": 6.7,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2014-10-28",
    "precipitation": 12.7,
    "temp_max": 15,
    "temp_min": 9.4,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-10-29",
    "precipitation": 0.5,
    "temp_max": 16.7,
    "temp_min": 11.7,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-10-30",
    "precipitation": 25.4,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2014-10-31",
    "precipitation": 17,
    "temp_max": 12.8,
    "temp_min": 8.3,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2014-11-01",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 1.2,
    "weather": "fog"
  },
  {
    "date": "2014-11-02",
    "precipitation": 1.8,
    "temp_max": 13.3,
    "temp_min": 7.2,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2014-11-03",
    "precipitation": 10.9,
    "temp_max": 13.9,
    "temp_min": 11.1,
    "wind": 4.8,
    "weather": "rain"
  },
  {
    "date": "2014-11-04",
    "precipitation": 4.1,
    "temp_max": 14.4,
    "temp_min": 10.6,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2014-11-05",
    "precipitation": 4.8,
    "temp_max": 15,
    "temp_min": 10.6,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2014-11-06",
    "precipitation": 4.1,
    "temp_max": 16.7,
    "temp_min": 10.6,
    "wind": 6.7,
    "weather": "rain"
  },
  {
    "date": "2014-11-07",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2014-11-08",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 3.9,
    "wind": 0.8,
    "weather": "fog"
  },
  {
    "date": "2014-11-09",
    "precipitation": 5.1,
    "temp_max": 13.3,
    "temp_min": 7.8,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2014-11-10",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2014-11-11",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 1.1,
    "wind": 7.7,
    "weather": "sun"
  },
  {
    "date": "2014-11-12",
    "precipitation": 0,
    "temp_max": 6.7,
    "temp_min": 0,
    "wind": 7.6,
    "weather": "sun"
  },
  {
    "date": "2014-11-13",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 0.6,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2014-11-14",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": -2.1,
    "wind": 4.5,
    "weather": "sun"
  },
  {
    "date": "2014-11-15",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": -1.6,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-11-16",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": -2.1,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2014-11-17",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": -2.1,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2014-11-18",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": -0.5,
    "wind": 0.9,
    "weather": "sun"
  },
  {
    "date": "2014-11-19",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 2.2,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2014-11-20",
    "precipitation": 3.6,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2014-11-21",
    "precipitation": 15.2,
    "temp_max": 11.1,
    "temp_min": 8.3,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-11-22",
    "precipitation": 0.5,
    "temp_max": 9.4,
    "temp_min": 6.7,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2014-11-23",
    "precipitation": 11.9,
    "temp_max": 12.8,
    "temp_min": 5.6,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-11-24",
    "precipitation": 1.3,
    "temp_max": 11.7,
    "temp_min": 4.4,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-11-25",
    "precipitation": 18.3,
    "temp_max": 13.9,
    "temp_min": 9.4,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2014-11-26",
    "precipitation": 0.3,
    "temp_max": 15,
    "temp_min": 12.2,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2014-11-27",
    "precipitation": 3.3,
    "temp_max": 14.4,
    "temp_min": 11.7,
    "wind": 6.6,
    "weather": "rain"
  },
  {
    "date": "2014-11-28",
    "precipitation": 34.3,
    "temp_max": 12.8,
    "temp_min": 3.3,
    "wind": 5.8,
    "weather": "rain"
  },
  {
    "date": "2014-11-29",
    "precipitation": 3.6,
    "temp_max": 4.4,
    "temp_min": -4.3,
    "wind": 5.3,
    "weather": "snow"
  },
  {
    "date": "2014-11-30",
    "precipitation": 0,
    "temp_max": 2.8,
    "temp_min": -4.9,
    "wind": 4.4,
    "weather": "sun"
  },
  {
    "date": "2014-12-01",
    "precipitation": 0,
    "temp_max": 4.4,
    "temp_min": -3.2,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2014-12-02",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": -3.2,
    "wind": 5.7,
    "weather": "fog"
  },
  {
    "date": "2014-12-03",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 0,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-12-04",
    "precipitation": 0.8,
    "temp_max": 8.3,
    "temp_min": 3.9,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2014-12-05",
    "precipitation": 3,
    "temp_max": 12.8,
    "temp_min": 6.7,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-12-06",
    "precipitation": 7.4,
    "temp_max": 11.7,
    "temp_min": 7.8,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2014-12-07",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 6.1,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2014-12-08",
    "precipitation": 9.1,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2014-12-09",
    "precipitation": 9.9,
    "temp_max": 16.1,
    "temp_min": 10.6,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2014-12-10",
    "precipitation": 13,
    "temp_max": 18.9,
    "temp_min": 10,
    "wind": 6.7,
    "weather": "rain"
  },
  {
    "date": "2014-12-11",
    "precipitation": 6.9,
    "temp_max": 14.4,
    "temp_min": 8.3,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2014-12-12",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2014-12-13",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 3.9,
    "wind": 1.1,
    "weather": "fog"
  },
  {
    "date": "2014-12-14",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 1.7,
    "wind": 3.5,
    "weather": "fog"
  },
  {
    "date": "2014-12-15",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 5.9,
    "weather": "sun"
  },
  {
    "date": "2014-12-16",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 8.3,
    "wind": 4,
    "weather": "sun"
  },
  {
    "date": "2014-12-17",
    "precipitation": 2.8,
    "temp_max": 8.9,
    "temp_min": 6.1,
    "wind": 1.6,
    "weather": "rain"
  },
  {
    "date": "2014-12-18",
    "precipitation": 13,
    "temp_max": 9.4,
    "temp_min": 6.7,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2014-12-19",
    "precipitation": 3,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2014-12-20",
    "precipitation": 19.6,
    "temp_max": 12.8,
    "temp_min": 6.7,
    "wind": 5.5,
    "weather": "rain"
  },
  {
    "date": "2014-12-21",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 10,
    "wind": 5.2,
    "weather": "sun"
  },
  {
    "date": "2014-12-22",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2014-12-23",
    "precipitation": 20.6,
    "temp_max": 12.2,
    "temp_min": 5,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2014-12-24",
    "precipitation": 5.3,
    "temp_max": 7.2,
    "temp_min": 3.9,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2014-12-25",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 2.8,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2014-12-26",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": 1.7,
    "wind": 1.2,
    "weather": "fog"
  },
  {
    "date": "2014-12-27",
    "precipitation": 3.3,
    "temp_max": 9.4,
    "temp_min": 4.4,
    "wind": 4.9,
    "weather": "rain"
  },
  {
    "date": "2014-12-28",
    "precipitation": 4.1,
    "temp_max": 6.7,
    "temp_min": 2.8,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2014-12-29",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": 0.6,
    "wind": 4.3,
    "weather": "fog"
  },
  {
    "date": "2014-12-30",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -2.1,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2014-12-31",
    "precipitation": 0,
    "temp_max": 3.3,
    "temp_min": -2.7,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-01-01",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": -3.2,
    "wind": 1.2,
    "weather": "sun"
  },
  {
    "date": "2015-01-02",
    "precipitation": 1.5,
    "temp_max": 5.6,
    "temp_min": 0,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2015-01-03",
    "precipitation": 0,
    "temp_max": 5,
    "temp_min": 1.7,
    "wind": 1.7,
    "weather": "fog"
  },
  {
    "date": "2015-01-04",
    "precipitation": 10.2,
    "temp_max": 10.6,
    "temp_min": 3.3,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2015-01-05",
    "precipitation": 8.1,
    "temp_max": 12.2,
    "temp_min": 9.4,
    "wind": 6.4,
    "weather": "rain"
  },
  {
    "date": "2015-01-06",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2015-01-07",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 5.6,
    "wind": 1.6,
    "weather": "fog"
  },
  {
    "date": "2015-01-08",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 1.7,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2015-01-09",
    "precipitation": 0.3,
    "temp_max": 10,
    "temp_min": 3.3,
    "wind": 0.6,
    "weather": "rain"
  },
  {
    "date": "2015-01-10",
    "precipitation": 5.8,
    "temp_max": 7.8,
    "temp_min": 6.1,
    "wind": 0.5,
    "weather": "rain"
  },
  {
    "date": "2015-01-11",
    "precipitation": 1.5,
    "temp_max": 9.4,
    "temp_min": 7.2,
    "wind": 1.1,
    "weather": "rain"
  },
  {
    "date": "2015-01-12",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 4.4,
    "wind": 1.6,
    "weather": "fog"
  },
  {
    "date": "2015-01-13",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": 2.8,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-01-14",
    "precipitation": 0,
    "temp_max": 6.1,
    "temp_min": 0.6,
    "wind": 2.8,
    "weather": "fog"
  },
  {
    "date": "2015-01-15",
    "precipitation": 9.7,
    "temp_max": 7.8,
    "temp_min": 1.1,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2015-01-16",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 5.6,
    "wind": 4.5,
    "weather": "fog"
  },
  {
    "date": "2015-01-17",
    "precipitation": 26.2,
    "temp_max": 13.3,
    "temp_min": 3.3,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-01-18",
    "precipitation": 21.3,
    "temp_max": 13.9,
    "temp_min": 7.2,
    "wind": 6.6,
    "weather": "rain"
  },
  {
    "date": "2015-01-19",
    "precipitation": 0.5,
    "temp_max": 10,
    "temp_min": 6.1,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-01-20",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 3.3,
    "wind": 3,
    "weather": "fog"
  },
  {
    "date": "2015-01-21",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": -0.5,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2015-01-22",
    "precipitation": 0.8,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2015-01-23",
    "precipitation": 5.8,
    "temp_max": 12.2,
    "temp_min": 8.3,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-01-24",
    "precipitation": 0.5,
    "temp_max": 14.4,
    "temp_min": 11.1,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2015-01-25",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 7.2,
    "wind": 1.4,
    "weather": "fog"
  },
  {
    "date": "2015-01-26",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 6.1,
    "wind": 2.2,
    "weather": "fog"
  },
  {
    "date": "2015-01-27",
    "precipitation": 0.8,
    "temp_max": 11.1,
    "temp_min": 8.3,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2015-01-28",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 5,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2015-01-29",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 3.3,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2015-01-30",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 1.1,
    "wind": 0.8,
    "weather": "fog"
  },
  {
    "date": "2015-01-31",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 3.3,
    "wind": 1.9,
    "weather": "fog"
  },
  {
    "date": "2015-02-01",
    "precipitation": 1.5,
    "temp_max": 9.4,
    "temp_min": 4.4,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-02-02",
    "precipitation": 7.4,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-02-03",
    "precipitation": 1.3,
    "temp_max": 10,
    "temp_min": 5.6,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2015-02-04",
    "precipitation": 8.4,
    "temp_max": 10.6,
    "temp_min": 4.4,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2015-02-05",
    "precipitation": 26.2,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2015-02-06",
    "precipitation": 17.3,
    "temp_max": 14.4,
    "temp_min": 10,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2015-02-07",
    "precipitation": 23.6,
    "temp_max": 12.2,
    "temp_min": 9.4,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2015-02-08",
    "precipitation": 3.6,
    "temp_max": 15,
    "temp_min": 8.3,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2015-02-09",
    "precipitation": 6.1,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 2.5,
    "weather": "rain"
  },
  {
    "date": "2015-02-10",
    "precipitation": 0.3,
    "temp_max": 12.8,
    "temp_min": 8.3,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-02-11",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 5.6,
    "wind": 1,
    "weather": "fog"
  },
  {
    "date": "2015-02-12",
    "precipitation": 1,
    "temp_max": 16.7,
    "temp_min": 9.4,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2015-02-13",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 6.7,
    "wind": 1.7,
    "weather": "fog"
  },
  {
    "date": "2015-02-14",
    "precipitation": 0.3,
    "temp_max": 14.4,
    "temp_min": 6.7,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2015-02-15",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 3.9,
    "wind": 4.8,
    "weather": "sun"
  },
  {
    "date": "2015-02-16",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 5.6,
    "wind": 6.6,
    "weather": "fog"
  },
  {
    "date": "2015-02-17",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 4.4,
    "wind": 4,
    "weather": "sun"
  },
  {
    "date": "2015-02-18",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 4.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-02-19",
    "precipitation": 4.6,
    "temp_max": 10.6,
    "temp_min": 8.3,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2015-02-20",
    "precipitation": 0.8,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 0.9,
    "weather": "rain"
  },
  {
    "date": "2015-02-21",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 5.6,
    "wind": 4.5,
    "weather": "sun"
  },
  {
    "date": "2015-02-22",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 3.3,
    "wind": 4.2,
    "weather": "sun"
  },
  {
    "date": "2015-02-23",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 0.6,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2015-02-24",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 2.2,
    "wind": 1.5,
    "weather": "sun"
  },
  {
    "date": "2015-02-25",
    "precipitation": 4.1,
    "temp_max": 10,
    "temp_min": 6.7,
    "wind": 1,
    "weather": "rain"
  },
  {
    "date": "2015-02-26",
    "precipitation": 9.4,
    "temp_max": 11.7,
    "temp_min": 7.8,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2015-02-27",
    "precipitation": 18.3,
    "temp_max": 10,
    "temp_min": 6.7,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-02-28",
    "precipitation": 0,
    "temp_max": 12.2,
    "temp_min": 3.3,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2015-03-01",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 1.1,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-03-02",
    "precipitation": 0,
    "temp_max": 11.1,
    "temp_min": 4.4,
    "wind": 4.8,
    "weather": "sun"
  },
  {
    "date": "2015-03-03",
    "precipitation": 0,
    "temp_max": 10.6,
    "temp_min": 0,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-03-04",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": -0.5,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2015-03-05",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 2.8,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2015-03-06",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 3.3,
    "wind": 1.4,
    "weather": "sun"
  },
  {
    "date": "2015-03-07",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 3.9,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-03-08",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 3.9,
    "wind": 1.7,
    "weather": "fog"
  },
  {
    "date": "2015-03-09",
    "precipitation": 0,
    "temp_max": 14.4,
    "temp_min": 4.4,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2015-03-10",
    "precipitation": 0.8,
    "temp_max": 13.3,
    "temp_min": 5,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-03-11",
    "precipitation": 2.5,
    "temp_max": 14.4,
    "temp_min": 8.9,
    "wind": 3.1,
    "weather": "rain"
  },
  {
    "date": "2015-03-12",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 9.4,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2015-03-13",
    "precipitation": 2,
    "temp_max": 17.2,
    "temp_min": 7.8,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2015-03-14",
    "precipitation": 17,
    "temp_max": 13.9,
    "temp_min": 9.4,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2015-03-15",
    "precipitation": 55.9,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2015-03-16",
    "precipitation": 1,
    "temp_max": 13.9,
    "temp_min": 6.1,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2015-03-17",
    "precipitation": 0.8,
    "temp_max": 13.3,
    "temp_min": 4.4,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-03-18",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 7.2,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2015-03-19",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 8.3,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2015-03-20",
    "precipitation": 4.1,
    "temp_max": 13.9,
    "temp_min": 8.9,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2015-03-21",
    "precipitation": 3.8,
    "temp_max": 13.3,
    "temp_min": 8.3,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2015-03-22",
    "precipitation": 1,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2015-03-23",
    "precipitation": 8.1,
    "temp_max": 11.1,
    "temp_min": 5.6,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-03-24",
    "precipitation": 7.6,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2015-03-25",
    "precipitation": 5.1,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 4.4,
    "weather": "rain"
  },
  {
    "date": "2015-03-26",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 10,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-03-27",
    "precipitation": 1,
    "temp_max": 18.3,
    "temp_min": 8.9,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-03-28",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 9.4,
    "wind": 5.7,
    "weather": "sun"
  },
  {
    "date": "2015-03-29",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 8.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-03-30",
    "precipitation": 1.8,
    "temp_max": 17.8,
    "temp_min": 10.6,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2015-03-31",
    "precipitation": 1,
    "temp_max": 12.8,
    "temp_min": 6.1,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2015-04-01",
    "precipitation": 5.1,
    "temp_max": 12.8,
    "temp_min": 5.6,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2015-04-02",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 5.6,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-04-03",
    "precipitation": 1.5,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2015-04-04",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 3.9,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2015-04-05",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 2.8,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-04-06",
    "precipitation": 1,
    "temp_max": 13.9,
    "temp_min": 6.7,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2015-04-07",
    "precipitation": 0.5,
    "temp_max": 14.4,
    "temp_min": 6.7,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2015-04-08",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 6.1,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2015-04-09",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 6.1,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2015-04-10",
    "precipitation": 10.9,
    "temp_max": 13.9,
    "temp_min": 7.8,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2015-04-11",
    "precipitation": 0,
    "temp_max": 11.7,
    "temp_min": 5.6,
    "wind": 6.5,
    "weather": "sun"
  },
  {
    "date": "2015-04-12",
    "precipitation": 0,
    "temp_max": 13.3,
    "temp_min": 5.6,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2015-04-13",
    "precipitation": 14,
    "temp_max": 11.7,
    "temp_min": 3.9,
    "wind": 3.6,
    "weather": "rain"
  },
  {
    "date": "2015-04-14",
    "precipitation": 3.3,
    "temp_max": 11.7,
    "temp_min": 2.8,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2015-04-15",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 3.3,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-04-16",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 3.9,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2015-04-17",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 6.1,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2015-04-18",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 8.3,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2015-04-19",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 8.3,
    "wind": 3.6,
    "weather": "sun"
  },
  {
    "date": "2015-04-20",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 7.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-04-21",
    "precipitation": 5.6,
    "temp_max": 17.2,
    "temp_min": 6.7,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2015-04-22",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 5,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2015-04-23",
    "precipitation": 3,
    "temp_max": 12.2,
    "temp_min": 6.7,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2015-04-24",
    "precipitation": 3.3,
    "temp_max": 12.2,
    "temp_min": 6.1,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2015-04-25",
    "precipitation": 1.3,
    "temp_max": 13.3,
    "temp_min": 5.6,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2015-04-26",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 4.4,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-04-27",
    "precipitation": 0.3,
    "temp_max": 25,
    "temp_min": 10.6,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2015-04-28",
    "precipitation": 1.8,
    "temp_max": 15.6,
    "temp_min": 8.9,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2015-04-29",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 7.2,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2015-04-30",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 7.8,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-05-01",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 8.9,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-05-02",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 7.8,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-05-03",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 7.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-05-04",
    "precipitation": 0,
    "temp_max": 17.2,
    "temp_min": 7.2,
    "wind": 5.2,
    "weather": "sun"
  },
  {
    "date": "2015-05-05",
    "precipitation": 6.1,
    "temp_max": 14.4,
    "temp_min": 7.2,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2015-05-06",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 7.2,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2015-05-07",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 6.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-05-08",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 8.3,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-05-09",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 9.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-05-10",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2015-05-11",
    "precipitation": 0,
    "temp_max": 13.9,
    "temp_min": 10,
    "wind": 2.5,
    "weather": "fog"
  },
  {
    "date": "2015-05-12",
    "precipitation": 4.3,
    "temp_max": 15.6,
    "temp_min": 10.6,
    "wind": 3.3,
    "weather": "rain"
  },
  {
    "date": "2015-05-13",
    "precipitation": 4.1,
    "temp_max": 12.2,
    "temp_min": 10,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-05-14",
    "precipitation": 0.3,
    "temp_max": 17.8,
    "temp_min": 9.4,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2015-05-15",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 9.4,
    "wind": 2.8,
    "weather": "fog"
  },
  {
    "date": "2015-05-16",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-05-17",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 10.6,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-05-18",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.2,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-05-19",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 11.7,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-05-20",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 10.6,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2015-05-21",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 11.7,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-05-22",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 11.7,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-05-23",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-05-24",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2015-05-25",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 11.1,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2015-05-26",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 11.7,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-05-27",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 11.7,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2015-05-28",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 12.2,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-05-29",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 12.8,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2015-05-30",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 10,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2015-05-31",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 11.7,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-06-01",
    "precipitation": 4.6,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2015-06-02",
    "precipitation": 0.5,
    "temp_max": 17.8,
    "temp_min": 12.8,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2015-06-03",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 11.7,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-06-04",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 11.7,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2015-06-05",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.8,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2015-06-06",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 13.3,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-06-07",
    "precipitation": 0,
    "temp_max": 31.1,
    "temp_min": 15.6,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2015-06-08",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 14.4,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2015-06-09",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 14.4,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2015-06-10",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 11.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-06-11",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 11.1,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2015-06-12",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 11.7,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2015-06-13",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 9.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-06-14",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 11.7,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-06-15",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 16.1,
    "wind": 3.5,
    "weather": "drizzle"
  },
  {
    "date": "2015-06-16",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 11.1,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-06-17",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 11.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2015-06-18",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 13.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-06-19",
    "precipitation": 0.5,
    "temp_max": 23.9,
    "temp_min": 13.3,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2015-06-20",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 12.8,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2015-06-21",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 13.9,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-06-22",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 12.8,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-06-23",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 11.7,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-06-24",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 16.1,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-06-25",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 15.6,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-06-26",
    "precipitation": 0,
    "temp_max": 31.7,
    "temp_min": 17.8,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2015-06-27",
    "precipitation": 0,
    "temp_max": 33.3,
    "temp_min": 17.2,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2015-06-28",
    "precipitation": 0.3,
    "temp_max": 28.3,
    "temp_min": 18.3,
    "wind": 2.1,
    "weather": "rain"
  },
  {
    "date": "2015-06-29",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 17.2,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2015-06-30",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 15,
    "wind": 3.4,
    "weather": "fog"
  },
  {
    "date": "2015-07-01",
    "precipitation": 0,
    "temp_max": 32.2,
    "temp_min": 17.2,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2015-07-02",
    "precipitation": 0,
    "temp_max": 33.9,
    "temp_min": 17.8,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-03",
    "precipitation": 0,
    "temp_max": 33.3,
    "temp_min": 17.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-07-04",
    "precipitation": 0,
    "temp_max": 33.3,
    "temp_min": 15,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2015-07-05",
    "precipitation": 0,
    "temp_max": 32.8,
    "temp_min": 16.7,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-07-06",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 15.6,
    "wind": 3.2,
    "weather": "drizzle"
  },
  {
    "date": "2015-07-07",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 13.9,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-08",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 14.4,
    "wind": 1.9,
    "weather": "drizzle"
  },
  {
    "date": "2015-07-09",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 14.4,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-10",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 16.7,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-07-11",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 16.7,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-07-12",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 16.7,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-07-13",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 16.1,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2015-07-14",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 16.1,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2015-07-15",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 14.4,
    "wind": 3.2,
    "weather": "sun"
  },
  {
    "date": "2015-07-16",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 15,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2015-07-17",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2015-07-18",
    "precipitation": 0,
    "temp_max": 33.3,
    "temp_min": 17.8,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-19",
    "precipitation": 0,
    "temp_max": 35,
    "temp_min": 17.2,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2015-07-20",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 16.7,
    "wind": 3.9,
    "weather": "sun"
  },
  {
    "date": "2015-07-21",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 15,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-22",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 13.9,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2015-07-23",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 14.4,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2015-07-24",
    "precipitation": 0.3,
    "temp_max": 22.8,
    "temp_min": 13.3,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2015-07-25",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 14.4,
    "wind": 2.4,
    "weather": "fog"
  },
  {
    "date": "2015-07-26",
    "precipitation": 2,
    "temp_max": 22.2,
    "temp_min": 13.9,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-07-27",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.2,
    "wind": 1.9,
    "weather": "fog"
  },
  {
    "date": "2015-07-28",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-07-29",
    "precipitation": 0,
    "temp_max": 32.2,
    "temp_min": 14.4,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2015-07-30",
    "precipitation": 0,
    "temp_max": 34.4,
    "temp_min": 17.2,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2015-07-31",
    "precipitation": 0,
    "temp_max": 34.4,
    "temp_min": 17.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-08-01",
    "precipitation": 0,
    "temp_max": 33.3,
    "temp_min": 15.6,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2015-08-02",
    "precipitation": 0,
    "temp_max": 30.6,
    "temp_min": 16.1,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2015-08-03",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 17.2,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2015-08-04",
    "precipitation": 0,
    "temp_max": 26.1,
    "temp_min": 14.4,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2015-08-05",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 12.2,
    "wind": 3.5,
    "weather": "sun"
  },
  {
    "date": "2015-08-06",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 15,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2015-08-07",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15.6,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-08-08",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 15.6,
    "wind": 3.6,
    "weather": "fog"
  },
  {
    "date": "2015-08-09",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-08-10",
    "precipitation": 0,
    "temp_max": 28.9,
    "temp_min": 16.1,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-08-11",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 16.7,
    "wind": 4.4,
    "weather": "sun"
  },
  {
    "date": "2015-08-12",
    "precipitation": 7.6,
    "temp_max": 28.3,
    "temp_min": 16.7,
    "wind": 2.7,
    "weather": "rain"
  },
  {
    "date": "2015-08-13",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 15.6,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-08-14",
    "precipitation": 30.5,
    "temp_max": 18.3,
    "temp_min": 15,
    "wind": 5.2,
    "weather": "rain"
  },
  {
    "date": "2015-08-15",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 13.9,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-08-16",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 14.4,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-08-17",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 13.9,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-08-18",
    "precipitation": 0,
    "temp_max": 30,
    "temp_min": 15,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-08-19",
    "precipitation": 0,
    "temp_max": 31.7,
    "temp_min": 16.1,
    "wind": 2.1,
    "weather": "drizzle"
  },
  {
    "date": "2015-08-20",
    "precipitation": 2,
    "temp_max": 22.8,
    "temp_min": 14.4,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2015-08-21",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 14.4,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-08-22",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 12.2,
    "wind": 2.5,
    "weather": "drizzle"
  },
  {
    "date": "2015-08-23",
    "precipitation": 0,
    "temp_max": 27.8,
    "temp_min": 13.9,
    "wind": 1.8,
    "weather": "drizzle"
  },
  {
    "date": "2015-08-24",
    "precipitation": 0,
    "temp_max": 23.9,
    "temp_min": 12.2,
    "wind": 2.3,
    "weather": "sun"
  },
  {
    "date": "2015-08-25",
    "precipitation": 0,
    "temp_max": 25.6,
    "temp_min": 12.2,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-08-26",
    "precipitation": 0,
    "temp_max": 28.3,
    "temp_min": 13.9,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2015-08-27",
    "precipitation": 0,
    "temp_max": 29.4,
    "temp_min": 14.4,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-08-28",
    "precipitation": 0.5,
    "temp_max": 23.3,
    "temp_min": 15.6,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-08-29",
    "precipitation": 32.5,
    "temp_max": 22.2,
    "temp_min": 13.3,
    "wind": 5.8,
    "weather": "rain"
  },
  {
    "date": "2015-08-30",
    "precipitation": 10.2,
    "temp_max": 20,
    "temp_min": 12.8,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2015-08-31",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 16.1,
    "wind": 5.8,
    "weather": "sun"
  },
  {
    "date": "2015-09-01",
    "precipitation": 5.8,
    "temp_max": 19.4,
    "temp_min": 13.9,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2015-09-02",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2015-09-03",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2015-09-04",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 2.9,
    "weather": "sun"
  },
  {
    "date": "2015-09-05",
    "precipitation": 0.3,
    "temp_max": 20.6,
    "temp_min": 8.9,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2015-09-06",
    "precipitation": 5.3,
    "temp_max": 16.1,
    "temp_min": 11.7,
    "wind": 2.4,
    "weather": "rain"
  },
  {
    "date": "2015-09-07",
    "precipitation": 0.3,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2015-09-08",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 13.3,
    "wind": 2.4,
    "weather": "sun"
  },
  {
    "date": "2015-09-09",
    "precipitation": 0,
    "temp_max": 24.4,
    "temp_min": 13.9,
    "wind": 3.3,
    "weather": "sun"
  },
  {
    "date": "2015-09-10",
    "precipitation": 0,
    "temp_max": 25,
    "temp_min": 14.4,
    "wind": 3.6,
    "weather": "fog"
  },
  {
    "date": "2015-09-11",
    "precipitation": 0,
    "temp_max": 27.2,
    "temp_min": 15,
    "wind": 3.1,
    "weather": "sun"
  },
  {
    "date": "2015-09-12",
    "precipitation": 0,
    "temp_max": 26.7,
    "temp_min": 14.4,
    "wind": 2.1,
    "weather": "sun"
  },
  {
    "date": "2015-09-13",
    "precipitation": 0.5,
    "temp_max": 20.6,
    "temp_min": 12.8,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2015-09-14",
    "precipitation": 0,
    "temp_max": 16.7,
    "temp_min": 10.6,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-09-15",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10,
    "wind": 2.8,
    "weather": "sun"
  },
  {
    "date": "2015-09-16",
    "precipitation": 1,
    "temp_max": 20,
    "temp_min": 10,
    "wind": 1.9,
    "weather": "rain"
  },
  {
    "date": "2015-09-17",
    "precipitation": 1.8,
    "temp_max": 18.3,
    "temp_min": 12.8,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2015-09-18",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 12.8,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-09-19",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 14.4,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2015-09-20",
    "precipitation": 4.1,
    "temp_max": 22.8,
    "temp_min": 12.2,
    "wind": 6.8,
    "weather": "rain"
  },
  {
    "date": "2015-09-21",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 9.4,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-09-22",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 7.8,
    "wind": 2,
    "weather": "sun"
  },
  {
    "date": "2015-09-23",
    "precipitation": 0,
    "temp_max": 20.6,
    "temp_min": 8.3,
    "wind": 1.8,
    "weather": "sun"
  },
  {
    "date": "2015-09-24",
    "precipitation": 0,
    "temp_max": 22.2,
    "temp_min": 11.1,
    "wind": 2.5,
    "weather": "fog"
  },
  {
    "date": "2015-09-25",
    "precipitation": 2,
    "temp_max": 15.6,
    "temp_min": 12.8,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-09-26",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 2.7,
    "weather": "sun"
  },
  {
    "date": "2015-09-27",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 7.2,
    "wind": 3.8,
    "weather": "sun"
  },
  {
    "date": "2015-09-28",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 9.4,
    "wind": 5.1,
    "weather": "sun"
  },
  {
    "date": "2015-09-29",
    "precipitation": 0,
    "temp_max": 21.7,
    "temp_min": 8.9,
    "wind": 1.9,
    "weather": "sun"
  },
  {
    "date": "2015-09-30",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2015-10-01",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 9.4,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2015-10-02",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 10,
    "wind": 2.9,
    "weather": "fog"
  },
  {
    "date": "2015-10-03",
    "precipitation": 0,
    "temp_max": 19.4,
    "temp_min": 11.1,
    "wind": 4.8,
    "weather": "sun"
  },
  {
    "date": "2015-10-04",
    "precipitation": 0,
    "temp_max": 22.8,
    "temp_min": 10,
    "wind": 3.7,
    "weather": "sun"
  },
  {
    "date": "2015-10-05",
    "precipitation": 0,
    "temp_max": 23.3,
    "temp_min": 9.4,
    "wind": 1.6,
    "weather": "sun"
  },
  {
    "date": "2015-10-06",
    "precipitation": 0,
    "temp_max": 18.3,
    "temp_min": 10,
    "wind": 2.6,
    "weather": "drizzle"
  },
  {
    "date": "2015-10-07",
    "precipitation": 9.9,
    "temp_max": 16.1,
    "temp_min": 13.9,
    "wind": 2.2,
    "weather": "rain"
  },
  {
    "date": "2015-10-08",
    "precipitation": 0,
    "temp_max": 18.9,
    "temp_min": 13.3,
    "wind": 1.1,
    "weather": "fog"
  },
  {
    "date": "2015-10-09",
    "precipitation": 0.3,
    "temp_max": 19.4,
    "temp_min": 12.2,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-10-10",
    "precipitation": 28.7,
    "temp_max": 21.1,
    "temp_min": 13.3,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2015-10-11",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10.6,
    "wind": 2.6,
    "weather": "sun"
  },
  {
    "date": "2015-10-12",
    "precipitation": 4.6,
    "temp_max": 18.3,
    "temp_min": 10.6,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-10-13",
    "precipitation": 1.3,
    "temp_max": 16.7,
    "temp_min": 9.4,
    "wind": 3.2,
    "weather": "rain"
  },
  {
    "date": "2015-10-14",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 10,
    "wind": 5,
    "weather": "fog"
  },
  {
    "date": "2015-10-15",
    "precipitation": 0,
    "temp_max": 21.1,
    "temp_min": 9.4,
    "wind": 3.4,
    "weather": "fog"
  },
  {
    "date": "2015-10-16",
    "precipitation": 0,
    "temp_max": 20,
    "temp_min": 8.9,
    "wind": 1.3,
    "weather": "sun"
  },
  {
    "date": "2015-10-17",
    "precipitation": 0.3,
    "temp_max": 19.4,
    "temp_min": 11.7,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2015-10-18",
    "precipitation": 3.8,
    "temp_max": 15,
    "temp_min": 12.8,
    "wind": 2,
    "weather": "rain"
  },
  {
    "date": "2015-10-19",
    "precipitation": 0.3,
    "temp_max": 17.2,
    "temp_min": 12.2,
    "wind": 2.6,
    "weather": "rain"
  },
  {
    "date": "2015-10-20",
    "precipitation": 0,
    "temp_max": 17.8,
    "temp_min": 10.6,
    "wind": 1.8,
    "weather": "fog"
  },
  {
    "date": "2015-10-21",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 8.3,
    "wind": 1.3,
    "weather": "fog"
  },
  {
    "date": "2015-10-22",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 8.9,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-10-23",
    "precipitation": 0,
    "temp_max": 12.8,
    "temp_min": 7.2,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2015-10-24",
    "precipitation": 0,
    "temp_max": 15,
    "temp_min": 8.9,
    "wind": 2.9,
    "weather": "fog"
  },
  {
    "date": "2015-10-25",
    "precipitation": 8.9,
    "temp_max": 19.4,
    "temp_min": 8.9,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2015-10-26",
    "precipitation": 6.9,
    "temp_max": 12.2,
    "temp_min": 10,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2015-10-27",
    "precipitation": 0,
    "temp_max": 16.1,
    "temp_min": 7.8,
    "wind": 1.7,
    "weather": "fog"
  },
  {
    "date": "2015-10-28",
    "precipitation": 3.3,
    "temp_max": 13.9,
    "temp_min": 11.1,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-10-29",
    "precipitation": 1.8,
    "temp_max": 15,
    "temp_min": 12.2,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2015-10-30",
    "precipitation": 19.3,
    "temp_max": 17.2,
    "temp_min": 11.7,
    "wind": 6.7,
    "weather": "rain"
  },
  {
    "date": "2015-10-31",
    "precipitation": 33,
    "temp_max": 15.6,
    "temp_min": 11.7,
    "wind": 7.2,
    "weather": "rain"
  },
  {
    "date": "2015-11-01",
    "precipitation": 26.2,
    "temp_max": 12.2,
    "temp_min": 8.9,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2015-11-02",
    "precipitation": 0.3,
    "temp_max": 11.1,
    "temp_min": 7.2,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-11-03",
    "precipitation": 0.8,
    "temp_max": 10.6,
    "temp_min": 5,
    "wind": 1.4,
    "weather": "rain"
  },
  {
    "date": "2015-11-04",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 3.3,
    "wind": 2.2,
    "weather": "sun"
  },
  {
    "date": "2015-11-05",
    "precipitation": 1.3,
    "temp_max": 11.7,
    "temp_min": 7.8,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2015-11-06",
    "precipitation": 0,
    "temp_max": 15.6,
    "temp_min": 8.3,
    "wind": 2.7,
    "weather": "fog"
  },
  {
    "date": "2015-11-07",
    "precipitation": 12.7,
    "temp_max": 12.2,
    "temp_min": 9.4,
    "wind": 3,
    "weather": "rain"
  },
  {
    "date": "2015-11-08",
    "precipitation": 6.6,
    "temp_max": 11.1,
    "temp_min": 7.8,
    "wind": 1.8,
    "weather": "rain"
  },
  {
    "date": "2015-11-09",
    "precipitation": 3.3,
    "temp_max": 10,
    "temp_min": 5,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2015-11-10",
    "precipitation": 1.3,
    "temp_max": 11.1,
    "temp_min": 3.9,
    "wind": 3.9,
    "weather": "rain"
  },
  {
    "date": "2015-11-11",
    "precipitation": 1.5,
    "temp_max": 11.1,
    "temp_min": 6.1,
    "wind": 4.6,
    "weather": "rain"
  },
  {
    "date": "2015-11-12",
    "precipitation": 9.9,
    "temp_max": 11.1,
    "temp_min": 5,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2015-11-13",
    "precipitation": 33.5,
    "temp_max": 13.3,
    "temp_min": 9.4,
    "wind": 6.5,
    "weather": "rain"
  },
  {
    "date": "2015-11-14",
    "precipitation": 47.2,
    "temp_max": 9.4,
    "temp_min": 6.1,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2015-11-15",
    "precipitation": 22.4,
    "temp_max": 8.9,
    "temp_min": 2.2,
    "wind": 4.1,
    "weather": "rain"
  },
  {
    "date": "2015-11-16",
    "precipitation": 2,
    "temp_max": 8.9,
    "temp_min": 1.7,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-11-17",
    "precipitation": 29.5,
    "temp_max": 13.3,
    "temp_min": 6.7,
    "wind": 8,
    "weather": "rain"
  },
  {
    "date": "2015-11-18",
    "precipitation": 1.5,
    "temp_max": 8.9,
    "temp_min": 3.3,
    "wind": 3.8,
    "weather": "rain"
  },
  {
    "date": "2015-11-19",
    "precipitation": 2,
    "temp_max": 8.9,
    "temp_min": 2.8,
    "wind": 4.2,
    "weather": "rain"
  },
  {
    "date": "2015-11-20",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 0.6,
    "wind": 4,
    "weather": "fog"
  },
  {
    "date": "2015-11-21",
    "precipitation": 0,
    "temp_max": 8.9,
    "temp_min": 0.6,
    "wind": 4.7,
    "weather": "sun"
  },
  {
    "date": "2015-11-22",
    "precipitation": 0,
    "temp_max": 10,
    "temp_min": 1.7,
    "wind": 3.1,
    "weather": "fog"
  },
  {
    "date": "2015-11-23",
    "precipitation": 3,
    "temp_max": 6.7,
    "temp_min": 0,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2015-11-24",
    "precipitation": 7.1,
    "temp_max": 6.7,
    "temp_min": 2.8,
    "wind": 4.5,
    "weather": "rain"
  },
  {
    "date": "2015-11-25",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 0,
    "wind": 5.7,
    "weather": "sun"
  },
  {
    "date": "2015-11-26",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": -1,
    "wind": 4.3,
    "weather": "sun"
  },
  {
    "date": "2015-11-27",
    "precipitation": 0,
    "temp_max": 9.4,
    "temp_min": -1.6,
    "wind": 3,
    "weather": "sun"
  },
  {
    "date": "2015-11-28",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": -2.7,
    "wind": 1,
    "weather": "sun"
  },
  {
    "date": "2015-11-29",
    "precipitation": 0,
    "temp_max": 1.7,
    "temp_min": -2.1,
    "wind": 0.9,
    "weather": "fog"
  },
  {
    "date": "2015-11-30",
    "precipitation": 0.5,
    "temp_max": 5.6,
    "temp_min": -3.8,
    "wind": 1.7,
    "weather": "rain"
  },
  {
    "date": "2015-12-01",
    "precipitation": 12.2,
    "temp_max": 10,
    "temp_min": 3.9,
    "wind": 3.5,
    "weather": "rain"
  },
  {
    "date": "2015-12-02",
    "precipitation": 2.5,
    "temp_max": 10.6,
    "temp_min": 4.4,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2015-12-03",
    "precipitation": 12.7,
    "temp_max": 15.6,
    "temp_min": 7.8,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2015-12-04",
    "precipitation": 2,
    "temp_max": 10.6,
    "temp_min": 6.1,
    "wind": 4.7,
    "weather": "rain"
  },
  {
    "date": "2015-12-05",
    "precipitation": 15.7,
    "temp_max": 10,
    "temp_min": 6.1,
    "wind": 4,
    "weather": "rain"
  },
  {
    "date": "2015-12-06",
    "precipitation": 11.2,
    "temp_max": 12.8,
    "temp_min": 7.2,
    "wind": 5.9,
    "weather": "rain"
  },
  {
    "date": "2015-12-07",
    "precipitation": 27.4,
    "temp_max": 11.1,
    "temp_min": 8.3,
    "wind": 3.4,
    "weather": "rain"
  },
  {
    "date": "2015-12-08",
    "precipitation": 54.1,
    "temp_max": 15.6,
    "temp_min": 10,
    "wind": 6.2,
    "weather": "rain"
  },
  {
    "date": "2015-12-09",
    "precipitation": 13.5,
    "temp_max": 12.2,
    "temp_min": 7.8,
    "wind": 6.3,
    "weather": "rain"
  },
  {
    "date": "2015-12-10",
    "precipitation": 9.4,
    "temp_max": 11.7,
    "temp_min": 6.1,
    "wind": 7.5,
    "weather": "rain"
  },
  {
    "date": "2015-12-11",
    "precipitation": 0.3,
    "temp_max": 9.4,
    "temp_min": 4.4,
    "wind": 2.8,
    "weather": "rain"
  },
  {
    "date": "2015-12-12",
    "precipitation": 16,
    "temp_max": 8.9,
    "temp_min": 5.6,
    "wind": 5.6,
    "weather": "rain"
  },
  {
    "date": "2015-12-13",
    "precipitation": 1.3,
    "temp_max": 7.8,
    "temp_min": 6.1,
    "wind": 6.1,
    "weather": "rain"
  },
  {
    "date": "2015-12-14",
    "precipitation": 0,
    "temp_max": 7.8,
    "temp_min": 1.7,
    "wind": 1.7,
    "weather": "sun"
  },
  {
    "date": "2015-12-15",
    "precipitation": 1.5,
    "temp_max": 6.7,
    "temp_min": 1.1,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2015-12-16",
    "precipitation": 3.6,
    "temp_max": 6.1,
    "temp_min": 2.8,
    "wind": 2.3,
    "weather": "rain"
  },
  {
    "date": "2015-12-17",
    "precipitation": 21.8,
    "temp_max": 6.7,
    "temp_min": 3.9,
    "wind": 6,
    "weather": "rain"
  },
  {
    "date": "2015-12-18",
    "precipitation": 18.5,
    "temp_max": 8.9,
    "temp_min": 4.4,
    "wind": 5.1,
    "weather": "rain"
  },
  {
    "date": "2015-12-19",
    "precipitation": 0,
    "temp_max": 8.3,
    "temp_min": 2.8,
    "wind": 4.1,
    "weather": "fog"
  },
  {
    "date": "2015-12-20",
    "precipitation": 4.3,
    "temp_max": 7.8,
    "temp_min": 4.4,
    "wind": 6.7,
    "weather": "rain"
  },
  {
    "date": "2015-12-21",
    "precipitation": 27.4,
    "temp_max": 5.6,
    "temp_min": 2.8,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2015-12-22",
    "precipitation": 4.6,
    "temp_max": 7.8,
    "temp_min": 2.8,
    "wind": 5,
    "weather": "rain"
  },
  {
    "date": "2015-12-23",
    "precipitation": 6.1,
    "temp_max": 5,
    "temp_min": 2.8,
    "wind": 7.6,
    "weather": "rain"
  },
  {
    "date": "2015-12-24",
    "precipitation": 2.5,
    "temp_max": 5.6,
    "temp_min": 2.2,
    "wind": 4.3,
    "weather": "rain"
  },
  {
    "date": "2015-12-25",
    "precipitation": 5.8,
    "temp_max": 5,
    "temp_min": 2.2,
    "wind": 1.5,
    "weather": "rain"
  },
  {
    "date": "2015-12-26",
    "precipitation": 0,
    "temp_max": 4.4,
    "temp_min": 0,
    "wind": 2.5,
    "weather": "sun"
  },
  {
    "date": "2015-12-27",
    "precipitation": 8.6,
    "temp_max": 4.4,
    "temp_min": 1.7,
    "wind": 2.9,
    "weather": "rain"
  },
  {
    "date": "2015-12-28",
    "precipitation": 1.5,
    "temp_max": 5,
    "temp_min": 1.7,
    "wind": 1.3,
    "weather": "rain"
  },
  {
    "date": "2015-12-29",
    "precipitation": 0,
    "temp_max": 7.2,
    "temp_min": 0.6,
    "wind": 2.6,
    "weather": "fog"
  },
  {
    "date": "2015-12-30",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": -1,
    "wind": 3.4,
    "weather": "sun"
  },
  {
    "date": "2015-12-31",
    "precipitation": 0,
    "temp_max": 5.6,
    "temp_min": -2.1,
    "wind": 3.5,
    "weather": "sun"
  }
]

fakeScatterData = [
   {
      "Name":"chevrolet chevelle malibu",
      "Miles_per_Gallon":18,
      "Cylinders":8,
      "Displacement":307,
      "Horsepower":130,
      "Weight_in_lbs":3504,
      "Acceleration":12,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick skylark 320",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":165,
      "Weight_in_lbs":3693,
      "Acceleration":11.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth satellite",
      "Miles_per_Gallon":18,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":3436,
      "Acceleration":11,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc rebel sst",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":150,
      "Weight_in_lbs":3433,
      "Acceleration":12,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford torino",
      "Miles_per_Gallon":17,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":140,
      "Weight_in_lbs":3449,
      "Acceleration":10.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford galaxie 500",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":429,
      "Horsepower":198,
      "Weight_in_lbs":4341,
      "Acceleration":10,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet impala",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":454,
      "Horsepower":220,
      "Weight_in_lbs":4354,
      "Acceleration":9,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth fury iii",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":440,
      "Horsepower":215,
      "Weight_in_lbs":4312,
      "Acceleration":8.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac catalina",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":455,
      "Horsepower":225,
      "Weight_in_lbs":4425,
      "Acceleration":10,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc ambassador dpl",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":390,
      "Horsepower":190,
      "Weight_in_lbs":3850,
      "Acceleration":8.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"citroen ds-21 pallas",
      "Miles_per_Gallon":None,
      "Cylinders":4,
      "Displacement":133,
      "Horsepower":115,
      "Weight_in_lbs":3090,
      "Acceleration":17.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"chevrolet chevelle concours (sw)",
      "Miles_per_Gallon":None,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":165,
      "Weight_in_lbs":4142,
      "Acceleration":11.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford torino (sw)",
      "Miles_per_Gallon":None,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":153,
      "Weight_in_lbs":4034,
      "Acceleration":11,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth satellite (sw)",
      "Miles_per_Gallon":None,
      "Cylinders":8,
      "Displacement":383,
      "Horsepower":175,
      "Weight_in_lbs":4166,
      "Acceleration":10.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc rebel sst (sw)",
      "Miles_per_Gallon":None,
      "Cylinders":8,
      "Displacement":360,
      "Horsepower":175,
      "Weight_in_lbs":3850,
      "Acceleration":11,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge challenger se",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":383,
      "Horsepower":170,
      "Weight_in_lbs":3563,
      "Acceleration":10,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth 'cuda 340",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":340,
      "Horsepower":160,
      "Weight_in_lbs":3609,
      "Acceleration":8,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford mustang boss 302",
      "Miles_per_Gallon":None,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":140,
      "Weight_in_lbs":3353,
      "Acceleration":8,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet monte carlo",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":150,
      "Weight_in_lbs":3761,
      "Acceleration":9.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick estate wagon (sw)",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":455,
      "Horsepower":225,
      "Weight_in_lbs":3086,
      "Acceleration":10,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corona mark ii",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":113,
      "Horsepower":95,
      "Weight_in_lbs":2372,
      "Acceleration":15,
      "Year":"1970-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth duster",
      "Miles_per_Gallon":22,
      "Cylinders":6,
      "Displacement":198,
      "Horsepower":95,
      "Weight_in_lbs":2833,
      "Acceleration":15.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc hornet",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":199,
      "Horsepower":97,
      "Weight_in_lbs":2774,
      "Acceleration":15.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford maverick",
      "Miles_per_Gallon":21,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":85,
      "Weight_in_lbs":2587,
      "Acceleration":16,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun pl510",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":88,
      "Weight_in_lbs":2130,
      "Acceleration":14.5,
      "Year":"1970-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"volkswagen 1131 deluxe sedan",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":46,
      "Weight_in_lbs":1835,
      "Acceleration":20.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"peugeot 504",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":110,
      "Horsepower":87,
      "Weight_in_lbs":2672,
      "Acceleration":17.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"audi 100 ls",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":107,
      "Horsepower":90,
      "Weight_in_lbs":2430,
      "Acceleration":14.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"saab 99e",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":104,
      "Horsepower":95,
      "Weight_in_lbs":2375,
      "Acceleration":17.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"bmw 2002",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":113,
      "Weight_in_lbs":2234,
      "Acceleration":12.5,
      "Year":"1970-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"amc gremlin",
      "Miles_per_Gallon":21,
      "Cylinders":6,
      "Displacement":199,
      "Horsepower":90,
      "Weight_in_lbs":2648,
      "Acceleration":15,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford f250",
      "Miles_per_Gallon":10,
      "Cylinders":8,
      "Displacement":360,
      "Horsepower":215,
      "Weight_in_lbs":4615,
      "Acceleration":14,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevy c20",
      "Miles_per_Gallon":10,
      "Cylinders":8,
      "Displacement":307,
      "Horsepower":200,
      "Weight_in_lbs":4376,
      "Acceleration":15,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge d200",
      "Miles_per_Gallon":11,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":210,
      "Weight_in_lbs":4382,
      "Acceleration":13.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"hi 1200d",
      "Miles_per_Gallon":9,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":193,
      "Weight_in_lbs":4732,
      "Acceleration":18.5,
      "Year":"1970-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun pl510",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":88,
      "Weight_in_lbs":2130,
      "Acceleration":14.5,
      "Year":"1971-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet vega 2300",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":90,
      "Weight_in_lbs":2264,
      "Acceleration":15.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corona",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":113,
      "Horsepower":95,
      "Weight_in_lbs":2228,
      "Acceleration":14,
      "Year":"1971-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":None,
      "Weight_in_lbs":2046,
      "Acceleration":19,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen super beetle 117",
      "Miles_per_Gallon":None,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":48,
      "Weight_in_lbs":1978,
      "Acceleration":20,
      "Year":"1971-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"amc gremlin",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":2634,
      "Acceleration":13,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth satellite custom",
      "Miles_per_Gallon":16,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":105,
      "Weight_in_lbs":3439,
      "Acceleration":15.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevelle malibu",
      "Miles_per_Gallon":17,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":100,
      "Weight_in_lbs":3329,
      "Acceleration":15.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford torino 500",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":88,
      "Weight_in_lbs":3302,
      "Acceleration":15.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":3288,
      "Acceleration":15.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet impala",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":165,
      "Weight_in_lbs":4209,
      "Acceleration":12,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac catalina brougham",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":175,
      "Weight_in_lbs":4464,
      "Acceleration":11.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford galaxie 500",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":153,
      "Weight_in_lbs":4154,
      "Acceleration":13.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth fury iii",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4096,
      "Acceleration":13,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge monaco (sw)",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":383,
      "Horsepower":180,
      "Weight_in_lbs":4955,
      "Acceleration":11.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford country squire (sw)",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":170,
      "Weight_in_lbs":4746,
      "Acceleration":12,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac safari (sw)",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":175,
      "Weight_in_lbs":5140,
      "Acceleration":12,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc hornet sportabout (sw)",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":258,
      "Horsepower":110,
      "Weight_in_lbs":2962,
      "Acceleration":13.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet vega (sw)",
      "Miles_per_Gallon":22,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":72,
      "Weight_in_lbs":2408,
      "Acceleration":19,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac firebird",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":100,
      "Weight_in_lbs":3282,
      "Acceleration":15,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford mustang",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":88,
      "Weight_in_lbs":3139,
      "Acceleration":14.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury capri 2000",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":86,
      "Weight_in_lbs":2220,
      "Acceleration":14,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"opel 1900",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":116,
      "Horsepower":90,
      "Weight_in_lbs":2123,
      "Acceleration":14,
      "Year":"1971-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"peugeot 304",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":70,
      "Weight_in_lbs":2074,
      "Acceleration":19.5,
      "Year":"1971-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"fiat 124b",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":88,
      "Horsepower":76,
      "Weight_in_lbs":2065,
      "Acceleration":14.5,
      "Year":"1971-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota corolla 1200",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":71,
      "Horsepower":65,
      "Weight_in_lbs":1773,
      "Acceleration":19,
      "Year":"1971-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 1200",
      "Miles_per_Gallon":35,
      "Cylinders":4,
      "Displacement":72,
      "Horsepower":69,
      "Weight_in_lbs":1613,
      "Acceleration":18,
      "Year":"1971-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"volkswagen model 111",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":60,
      "Weight_in_lbs":1834,
      "Acceleration":19,
      "Year":"1971-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"plymouth cricket",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":70,
      "Weight_in_lbs":1955,
      "Acceleration":20.5,
      "Year":"1971-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corona hardtop",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":113,
      "Horsepower":95,
      "Weight_in_lbs":2278,
      "Acceleration":15.5,
      "Year":"1972-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge colt hardtop",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":97.5,
      "Horsepower":80,
      "Weight_in_lbs":2126,
      "Acceleration":17,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen type 3",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":54,
      "Weight_in_lbs":2254,
      "Acceleration":23.5,
      "Year":"1972-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"chevrolet vega",
      "Miles_per_Gallon":20,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":90,
      "Weight_in_lbs":2408,
      "Acceleration":19.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford pinto runabout",
      "Miles_per_Gallon":21,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":86,
      "Weight_in_lbs":2226,
      "Acceleration":16.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet impala",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":165,
      "Weight_in_lbs":4274,
      "Acceleration":12,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac catalina",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":175,
      "Weight_in_lbs":4385,
      "Acceleration":12,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth fury iii",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4135,
      "Acceleration":13.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford galaxie 500",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":153,
      "Weight_in_lbs":4129,
      "Acceleration":13,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc ambassador sst",
      "Miles_per_Gallon":17,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":150,
      "Weight_in_lbs":3672,
      "Acceleration":11.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury marquis",
      "Miles_per_Gallon":11,
      "Cylinders":8,
      "Displacement":429,
      "Horsepower":208,
      "Weight_in_lbs":4633,
      "Acceleration":11,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick lesabre custom",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":155,
      "Weight_in_lbs":4502,
      "Acceleration":13.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile delta 88 royale",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":160,
      "Weight_in_lbs":4456,
      "Acceleration":13.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler newport royal",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":190,
      "Weight_in_lbs":4422,
      "Acceleration":12.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mazda rx2 coupe",
      "Miles_per_Gallon":19,
      "Cylinders":3,
      "Displacement":70,
      "Horsepower":97,
      "Weight_in_lbs":2330,
      "Acceleration":13.5,
      "Year":"1972-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"amc matador (sw)",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":150,
      "Weight_in_lbs":3892,
      "Acceleration":12.5,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevelle concours (sw)",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":307,
      "Horsepower":130,
      "Weight_in_lbs":4098,
      "Acceleration":14,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford gran torino (sw)",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":140,
      "Weight_in_lbs":4294,
      "Acceleration":16,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth satellite custom (sw)",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4077,
      "Acceleration":14,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volvo 145e (sw)",
      "Miles_per_Gallon":18,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":112,
      "Weight_in_lbs":2933,
      "Acceleration":14.5,
      "Year":"1972-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volkswagen 411 (sw)",
      "Miles_per_Gallon":22,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":76,
      "Weight_in_lbs":2511,
      "Acceleration":18,
      "Year":"1972-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"peugeot 504 (sw)",
      "Miles_per_Gallon":21,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":87,
      "Weight_in_lbs":2979,
      "Acceleration":19.5,
      "Year":"1972-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"renault 12 (sw)",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":96,
      "Horsepower":69,
      "Weight_in_lbs":2189,
      "Acceleration":18,
      "Year":"1972-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"ford pinto (sw)",
      "Miles_per_Gallon":22,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":86,
      "Weight_in_lbs":2395,
      "Acceleration":16,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 510 (sw)",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":92,
      "Weight_in_lbs":2288,
      "Acceleration":17,
      "Year":"1972-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyouta corona mark ii (sw)",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":97,
      "Weight_in_lbs":2506,
      "Acceleration":14.5,
      "Year":"1972-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge colt (sw)",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":80,
      "Weight_in_lbs":2164,
      "Acceleration":15,
      "Year":"1972-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corolla 1600 (sw)",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":88,
      "Weight_in_lbs":2100,
      "Acceleration":16.5,
      "Year":"1972-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"buick century 350",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":175,
      "Weight_in_lbs":4100,
      "Acceleration":13,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":150,
      "Weight_in_lbs":3672,
      "Acceleration":11.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet malibu",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":145,
      "Weight_in_lbs":3988,
      "Acceleration":13,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford gran torino",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":137,
      "Weight_in_lbs":4042,
      "Acceleration":14.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge coronet custom",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":3777,
      "Acceleration":12.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury marquis brougham",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":429,
      "Horsepower":198,
      "Weight_in_lbs":4952,
      "Acceleration":11.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet caprice classic",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":150,
      "Weight_in_lbs":4464,
      "Acceleration":12,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford ltd",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":158,
      "Weight_in_lbs":4363,
      "Acceleration":13,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth fury gran sedan",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4237,
      "Acceleration":14.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler new yorker brougham",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":440,
      "Horsepower":215,
      "Weight_in_lbs":4735,
      "Acceleration":11,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick electra 225 custom",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":455,
      "Horsepower":225,
      "Weight_in_lbs":4951,
      "Acceleration":11,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc ambassador brougham",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":360,
      "Horsepower":175,
      "Weight_in_lbs":3821,
      "Acceleration":11,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth valiant",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":105,
      "Weight_in_lbs":3121,
      "Acceleration":16.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet nova custom",
      "Miles_per_Gallon":16,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":100,
      "Weight_in_lbs":3278,
      "Acceleration":18,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc hornet",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":2945,
      "Acceleration":16,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford maverick",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":88,
      "Weight_in_lbs":3021,
      "Acceleration":16.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth duster",
      "Miles_per_Gallon":23,
      "Cylinders":6,
      "Displacement":198,
      "Horsepower":95,
      "Weight_in_lbs":2904,
      "Acceleration":16,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen super beetle",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":46,
      "Weight_in_lbs":1950,
      "Acceleration":21,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"chevrolet impala",
      "Miles_per_Gallon":11,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":150,
      "Weight_in_lbs":4997,
      "Acceleration":14,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford country",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":167,
      "Weight_in_lbs":4906,
      "Acceleration":12.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth custom suburb",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":360,
      "Horsepower":170,
      "Weight_in_lbs":4654,
      "Acceleration":13,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile vista cruiser",
      "Miles_per_Gallon":12,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":180,
      "Weight_in_lbs":4499,
      "Acceleration":12.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc gremlin",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":2789,
      "Acceleration":15,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota carina",
      "Miles_per_Gallon":20,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":88,
      "Weight_in_lbs":2279,
      "Acceleration":19,
      "Year":"1973-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet vega",
      "Miles_per_Gallon":21,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":72,
      "Weight_in_lbs":2401,
      "Acceleration":19.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 610",
      "Miles_per_Gallon":22,
      "Cylinders":4,
      "Displacement":108,
      "Horsepower":94,
      "Weight_in_lbs":2379,
      "Acceleration":16.5,
      "Year":"1973-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"maxda rx3",
      "Miles_per_Gallon":18,
      "Cylinders":3,
      "Displacement":70,
      "Horsepower":90,
      "Weight_in_lbs":2124,
      "Acceleration":13.5,
      "Year":"1973-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":19,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":85,
      "Weight_in_lbs":2310,
      "Acceleration":18.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury capri v6",
      "Miles_per_Gallon":21,
      "Cylinders":6,
      "Displacement":155,
      "Horsepower":107,
      "Weight_in_lbs":2472,
      "Acceleration":14,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"fiat 124 sport coupe",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":90,
      "Weight_in_lbs":2265,
      "Acceleration":15.5,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"chevrolet monte carlo s",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":145,
      "Weight_in_lbs":4082,
      "Acceleration":13,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac grand prix",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":230,
      "Weight_in_lbs":4278,
      "Acceleration":9.5,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"fiat 128",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":68,
      "Horsepower":49,
      "Weight_in_lbs":1867,
      "Acceleration":19.5,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"opel manta",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":116,
      "Horsepower":75,
      "Weight_in_lbs":2158,
      "Acceleration":15.5,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"audi 100ls",
      "Miles_per_Gallon":20,
      "Cylinders":4,
      "Displacement":114,
      "Horsepower":91,
      "Weight_in_lbs":2582,
      "Acceleration":14,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volvo 144ea",
      "Miles_per_Gallon":19,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":112,
      "Weight_in_lbs":2868,
      "Acceleration":15.5,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"dodge dart custom",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":3399,
      "Acceleration":11,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"saab 99le",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":110,
      "Weight_in_lbs":2660,
      "Acceleration":14,
      "Year":"1973-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota mark ii",
      "Miles_per_Gallon":20,
      "Cylinders":6,
      "Displacement":156,
      "Horsepower":122,
      "Weight_in_lbs":2807,
      "Acceleration":13.5,
      "Year":"1973-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"oldsmobile omega",
      "Miles_per_Gallon":11,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":180,
      "Weight_in_lbs":3664,
      "Acceleration":11,
      "Year":"1973-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth duster",
      "Miles_per_Gallon":20,
      "Cylinders":6,
      "Displacement":198,
      "Horsepower":95,
      "Weight_in_lbs":3102,
      "Acceleration":16.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford maverick",
      "Miles_per_Gallon":21,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":None,
      "Weight_in_lbs":2875,
      "Acceleration":17,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc hornet",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":2901,
      "Acceleration":16,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet nova",
      "Miles_per_Gallon":15,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":100,
      "Weight_in_lbs":3336,
      "Acceleration":17,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun b210",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":67,
      "Weight_in_lbs":1950,
      "Acceleration":19,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":80,
      "Weight_in_lbs":2451,
      "Acceleration":16.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corolla 1200",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":71,
      "Horsepower":65,
      "Weight_in_lbs":1836,
      "Acceleration":21,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet vega",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":75,
      "Weight_in_lbs":2542,
      "Acceleration":17,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevelle malibu classic",
      "Miles_per_Gallon":16,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":100,
      "Weight_in_lbs":3781,
      "Acceleration":17,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador",
      "Miles_per_Gallon":16,
      "Cylinders":6,
      "Displacement":258,
      "Horsepower":110,
      "Weight_in_lbs":3632,
      "Acceleration":18,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth satellite sebring",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":105,
      "Weight_in_lbs":3613,
      "Acceleration":16.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford gran torino",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":140,
      "Weight_in_lbs":4141,
      "Acceleration":14,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick century luxus (sw)",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":150,
      "Weight_in_lbs":4699,
      "Acceleration":14.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge coronet custom (sw)",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4457,
      "Acceleration":13.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford gran torino (sw)",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":140,
      "Weight_in_lbs":4638,
      "Acceleration":16,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador (sw)",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":150,
      "Weight_in_lbs":4257,
      "Acceleration":15.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"audi fox",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":83,
      "Weight_in_lbs":2219,
      "Acceleration":16.5,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volkswagen dasher",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":67,
      "Weight_in_lbs":1963,
      "Acceleration":15.5,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"opel manta",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":78,
      "Weight_in_lbs":2300,
      "Acceleration":14.5,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota corona",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":76,
      "Horsepower":52,
      "Weight_in_lbs":1649,
      "Acceleration":16.5,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 710",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":83,
      "Horsepower":61,
      "Weight_in_lbs":2003,
      "Acceleration":19,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge colt",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":75,
      "Weight_in_lbs":2125,
      "Acceleration":14.5,
      "Year":"1974-01-01",
      "Origin":"USA"
   },
   {
      "Name":"fiat 128",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":75,
      "Weight_in_lbs":2108,
      "Acceleration":15.5,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"fiat 124 tc",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":116,
      "Horsepower":75,
      "Weight_in_lbs":2246,
      "Acceleration":14,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda civic",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":97,
      "Weight_in_lbs":2489,
      "Acceleration":15,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"subaru",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":108,
      "Horsepower":93,
      "Weight_in_lbs":2391,
      "Acceleration":15.5,
      "Year":"1974-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"fiat x1.9",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":67,
      "Weight_in_lbs":2000,
      "Acceleration":16,
      "Year":"1974-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"plymouth valiant custom",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":95,
      "Weight_in_lbs":3264,
      "Acceleration":16,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet nova",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":105,
      "Weight_in_lbs":3459,
      "Acceleration":16,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury monarch",
      "Miles_per_Gallon":15,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":72,
      "Weight_in_lbs":3432,
      "Acceleration":21,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford maverick",
      "Miles_per_Gallon":15,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":72,
      "Weight_in_lbs":3158,
      "Acceleration":19.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac catalina",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":170,
      "Weight_in_lbs":4668,
      "Acceleration":11.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet bel air",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":145,
      "Weight_in_lbs":4440,
      "Acceleration":14,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth grand fury",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4498,
      "Acceleration":14.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford ltd",
      "Miles_per_Gallon":14,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":148,
      "Weight_in_lbs":4657,
      "Acceleration":13.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick century",
      "Miles_per_Gallon":17,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":110,
      "Weight_in_lbs":3907,
      "Acceleration":21,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevroelt chevelle malibu",
      "Miles_per_Gallon":16,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":105,
      "Weight_in_lbs":3897,
      "Acceleration":18.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador",
      "Miles_per_Gallon":15,
      "Cylinders":6,
      "Displacement":258,
      "Horsepower":110,
      "Weight_in_lbs":3730,
      "Acceleration":19,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth fury",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":95,
      "Weight_in_lbs":3785,
      "Acceleration":19,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick skyhawk",
      "Miles_per_Gallon":21,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":110,
      "Weight_in_lbs":3039,
      "Acceleration":15,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet monza 2+2",
      "Miles_per_Gallon":20,
      "Cylinders":8,
      "Displacement":262,
      "Horsepower":110,
      "Weight_in_lbs":3221,
      "Acceleration":13.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford mustang ii",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":129,
      "Weight_in_lbs":3169,
      "Acceleration":12,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corolla",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":75,
      "Weight_in_lbs":2171,
      "Acceleration":16,
      "Year":"1975-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":83,
      "Weight_in_lbs":2639,
      "Acceleration":17,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc gremlin",
      "Miles_per_Gallon":20,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":100,
      "Weight_in_lbs":2914,
      "Acceleration":16,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac astro",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":78,
      "Weight_in_lbs":2592,
      "Acceleration":18.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corona",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":134,
      "Horsepower":96,
      "Weight_in_lbs":2702,
      "Acceleration":13.5,
      "Year":"1975-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"volkswagen dasher",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":71,
      "Weight_in_lbs":2223,
      "Acceleration":16.5,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"datsun 710",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":97,
      "Weight_in_lbs":2545,
      "Acceleration":17,
      "Year":"1975-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":171,
      "Horsepower":97,
      "Weight_in_lbs":2984,
      "Acceleration":14.5,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen rabbit",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":70,
      "Weight_in_lbs":1937,
      "Acceleration":14,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"amc pacer",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":90,
      "Weight_in_lbs":3211,
      "Acceleration":17,
      "Year":"1975-01-01",
      "Origin":"USA"
   },
   {
      "Name":"audi 100ls",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":115,
      "Horsepower":95,
      "Weight_in_lbs":2694,
      "Acceleration":15,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"peugeot 504",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":88,
      "Weight_in_lbs":2957,
      "Acceleration":17,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volvo 244dl",
      "Miles_per_Gallon":22,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":98,
      "Weight_in_lbs":2945,
      "Acceleration":14.5,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"saab 99le",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":115,
      "Weight_in_lbs":2671,
      "Acceleration":13.5,
      "Year":"1975-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda civic cvcc",
      "Miles_per_Gallon":33,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":53,
      "Weight_in_lbs":1795,
      "Acceleration":17.5,
      "Year":"1975-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"fiat 131",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":107,
      "Horsepower":86,
      "Weight_in_lbs":2464,
      "Acceleration":15.5,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"opel 1900",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":116,
      "Horsepower":81,
      "Weight_in_lbs":2220,
      "Acceleration":16.9,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"capri ii",
      "Miles_per_Gallon":25,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":92,
      "Weight_in_lbs":2572,
      "Acceleration":14.9,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge colt",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":79,
      "Weight_in_lbs":2255,
      "Acceleration":17.7,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"renault 12tl",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":101,
      "Horsepower":83,
      "Weight_in_lbs":2202,
      "Acceleration":15.3,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"chevrolet chevelle malibu classic",
      "Miles_per_Gallon":17.5,
      "Cylinders":8,
      "Displacement":305,
      "Horsepower":140,
      "Weight_in_lbs":4215,
      "Acceleration":13,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge coronet brougham",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":4190,
      "Acceleration":13,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc matador",
      "Miles_per_Gallon":15.5,
      "Cylinders":8,
      "Displacement":304,
      "Horsepower":120,
      "Weight_in_lbs":3962,
      "Acceleration":13.9,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford gran torino",
      "Miles_per_Gallon":14.5,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":152,
      "Weight_in_lbs":4215,
      "Acceleration":12.8,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth valiant",
      "Miles_per_Gallon":22,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":100,
      "Weight_in_lbs":3233,
      "Acceleration":15.4,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet nova",
      "Miles_per_Gallon":22,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":105,
      "Weight_in_lbs":3353,
      "Acceleration":14.5,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford maverick",
      "Miles_per_Gallon":24,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":81,
      "Weight_in_lbs":3012,
      "Acceleration":17.6,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc hornet",
      "Miles_per_Gallon":22.5,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":90,
      "Weight_in_lbs":3085,
      "Acceleration":17.6,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevette",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":52,
      "Weight_in_lbs":2035,
      "Acceleration":22.2,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet woody",
      "Miles_per_Gallon":24.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":60,
      "Weight_in_lbs":2164,
      "Acceleration":22.1,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"vw rabbit",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":70,
      "Weight_in_lbs":1937,
      "Acceleration":14.2,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda civic",
      "Miles_per_Gallon":33,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":53,
      "Weight_in_lbs":1795,
      "Acceleration":17.4,
      "Year":"1976-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge aspen se",
      "Miles_per_Gallon":20,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":100,
      "Weight_in_lbs":3651,
      "Acceleration":17.7,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford granada ghia",
      "Miles_per_Gallon":18,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":78,
      "Weight_in_lbs":3574,
      "Acceleration":21,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac ventura sj",
      "Miles_per_Gallon":18.5,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":110,
      "Weight_in_lbs":3645,
      "Acceleration":16.2,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc pacer d/l",
      "Miles_per_Gallon":17.5,
      "Cylinders":6,
      "Displacement":258,
      "Horsepower":95,
      "Weight_in_lbs":3193,
      "Acceleration":17.8,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen rabbit",
      "Miles_per_Gallon":29.5,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":71,
      "Weight_in_lbs":1825,
      "Acceleration":12.2,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"datsun b-210",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":70,
      "Weight_in_lbs":1990,
      "Acceleration":17,
      "Year":"1976-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyota corolla",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":75,
      "Weight_in_lbs":2155,
      "Acceleration":16.4,
      "Year":"1976-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford pinto",
      "Miles_per_Gallon":26.5,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":72,
      "Weight_in_lbs":2565,
      "Acceleration":13.6,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volvo 245",
      "Miles_per_Gallon":20,
      "Cylinders":4,
      "Displacement":130,
      "Horsepower":102,
      "Weight_in_lbs":3150,
      "Acceleration":15.7,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"plymouth volare premier v8",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":3940,
      "Acceleration":13.2,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"peugeot 504",
      "Miles_per_Gallon":19,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":88,
      "Weight_in_lbs":3270,
      "Acceleration":21.9,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota mark ii",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":156,
      "Horsepower":108,
      "Weight_in_lbs":2930,
      "Acceleration":15.5,
      "Year":"1976-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mercedes-benz 280s",
      "Miles_per_Gallon":16.5,
      "Cylinders":6,
      "Displacement":168,
      "Horsepower":120,
      "Weight_in_lbs":3820,
      "Acceleration":16.7,
      "Year":"1976-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"cadillac seville",
      "Miles_per_Gallon":16.5,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":180,
      "Weight_in_lbs":4380,
      "Acceleration":12.1,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevy c10",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":145,
      "Weight_in_lbs":4055,
      "Acceleration":12,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford f108",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":130,
      "Weight_in_lbs":3870,
      "Acceleration":15,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge d100",
      "Miles_per_Gallon":13,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":150,
      "Weight_in_lbs":3755,
      "Acceleration":14,
      "Year":"1976-01-01",
      "Origin":"USA"
   },
   {
      "Name":"honda Accelerationord cvcc",
      "Miles_per_Gallon":31.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":68,
      "Weight_in_lbs":2045,
      "Acceleration":18.5,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"buick opel isuzu deluxe",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":111,
      "Horsepower":80,
      "Weight_in_lbs":2155,
      "Acceleration":14.8,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"renault 5 gtl",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":58,
      "Weight_in_lbs":1825,
      "Acceleration":18.6,
      "Year":"1977-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"plymouth arrow gs",
      "Miles_per_Gallon":25.5,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":96,
      "Weight_in_lbs":2300,
      "Acceleration":15.5,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun f-10 hatchback",
      "Miles_per_Gallon":33.5,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":70,
      "Weight_in_lbs":1945,
      "Acceleration":16.8,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet caprice classic",
      "Miles_per_Gallon":17.5,
      "Cylinders":8,
      "Displacement":305,
      "Horsepower":145,
      "Weight_in_lbs":3880,
      "Acceleration":12.5,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile cutlass supreme",
      "Miles_per_Gallon":17,
      "Cylinders":8,
      "Displacement":260,
      "Horsepower":110,
      "Weight_in_lbs":4060,
      "Acceleration":19,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge monaco brougham",
      "Miles_per_Gallon":15.5,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":145,
      "Weight_in_lbs":4140,
      "Acceleration":13.7,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury cougar brougham",
      "Miles_per_Gallon":15,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":130,
      "Weight_in_lbs":4295,
      "Acceleration":14.9,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet concours",
      "Miles_per_Gallon":17.5,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":110,
      "Weight_in_lbs":3520,
      "Acceleration":16.4,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick skylark",
      "Miles_per_Gallon":20.5,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":105,
      "Weight_in_lbs":3425,
      "Acceleration":16.9,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth volare custom",
      "Miles_per_Gallon":19,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":100,
      "Weight_in_lbs":3630,
      "Acceleration":17.7,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford granada",
      "Miles_per_Gallon":18.5,
      "Cylinders":6,
      "Displacement":250,
      "Horsepower":98,
      "Weight_in_lbs":3525,
      "Acceleration":19,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac grand prix lj",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":180,
      "Weight_in_lbs":4220,
      "Acceleration":11.1,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet monte carlo landau",
      "Miles_per_Gallon":15.5,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":170,
      "Weight_in_lbs":4165,
      "Acceleration":11.4,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler cordoba",
      "Miles_per_Gallon":15.5,
      "Cylinders":8,
      "Displacement":400,
      "Horsepower":190,
      "Weight_in_lbs":4325,
      "Acceleration":12.2,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford thunderbird",
      "Miles_per_Gallon":16,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":149,
      "Weight_in_lbs":4335,
      "Acceleration":14.5,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen rabbit custom",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":78,
      "Weight_in_lbs":1940,
      "Acceleration":14.5,
      "Year":"1977-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"pontiac sunbird coupe",
      "Miles_per_Gallon":24.5,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":88,
      "Weight_in_lbs":2740,
      "Acceleration":16,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corolla liftback",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":75,
      "Weight_in_lbs":2265,
      "Acceleration":18.2,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"ford mustang ii 2+2",
      "Miles_per_Gallon":25.5,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":89,
      "Weight_in_lbs":2755,
      "Acceleration":15.8,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevette",
      "Miles_per_Gallon":30.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":63,
      "Weight_in_lbs":2051,
      "Acceleration":17,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge colt m/m",
      "Miles_per_Gallon":33.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":83,
      "Weight_in_lbs":2075,
      "Acceleration":15.9,
      "Year":"1977-01-01",
      "Origin":"USA"
   },
   {
      "Name":"subaru dl",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":67,
      "Weight_in_lbs":1985,
      "Acceleration":16.4,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"volkswagen dasher",
      "Miles_per_Gallon":30.5,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":78,
      "Weight_in_lbs":2190,
      "Acceleration":14.1,
      "Year":"1977-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"datsun 810",
      "Miles_per_Gallon":22,
      "Cylinders":6,
      "Displacement":146,
      "Horsepower":97,
      "Weight_in_lbs":2815,
      "Acceleration":14.5,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"bmw 320i",
      "Miles_per_Gallon":21.5,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":110,
      "Weight_in_lbs":2600,
      "Acceleration":12.8,
      "Year":"1977-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"mazda rx-4",
      "Miles_per_Gallon":21.5,
      "Cylinders":3,
      "Displacement":80,
      "Horsepower":110,
      "Weight_in_lbs":2720,
      "Acceleration":13.5,
      "Year":"1977-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"volkswagen rabbit custom diesel",
      "Miles_per_Gallon":43.1,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":48,
      "Weight_in_lbs":1985,
      "Acceleration":21.5,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"ford fiesta",
      "Miles_per_Gallon":36.1,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":66,
      "Weight_in_lbs":1800,
      "Acceleration":14.4,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mazda glc deluxe",
      "Miles_per_Gallon":32.8,
      "Cylinders":4,
      "Displacement":78,
      "Horsepower":52,
      "Weight_in_lbs":1985,
      "Acceleration":19.4,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun b210 gx",
      "Miles_per_Gallon":39.4,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":70,
      "Weight_in_lbs":2070,
      "Acceleration":18.6,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"honda civic cvcc",
      "Miles_per_Gallon":36.1,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":60,
      "Weight_in_lbs":1800,
      "Acceleration":16.4,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"oldsmobile cutlass salon brougham",
      "Miles_per_Gallon":19.9,
      "Cylinders":8,
      "Displacement":260,
      "Horsepower":110,
      "Weight_in_lbs":3365,
      "Acceleration":15.5,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge diplomat",
      "Miles_per_Gallon":19.4,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":140,
      "Weight_in_lbs":3735,
      "Acceleration":13.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury monarch ghia",
      "Miles_per_Gallon":20.2,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":139,
      "Weight_in_lbs":3570,
      "Acceleration":12.8,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac phoenix lj",
      "Miles_per_Gallon":19.2,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":105,
      "Weight_in_lbs":3535,
      "Acceleration":19.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet malibu",
      "Miles_per_Gallon":20.5,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":95,
      "Weight_in_lbs":3155,
      "Acceleration":18.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford fairmont (auto)",
      "Miles_per_Gallon":20.2,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":85,
      "Weight_in_lbs":2965,
      "Acceleration":15.8,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford fairmont (man)",
      "Miles_per_Gallon":25.1,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":88,
      "Weight_in_lbs":2720,
      "Acceleration":15.4,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth volare",
      "Miles_per_Gallon":20.5,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":100,
      "Weight_in_lbs":3430,
      "Acceleration":17.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc concord",
      "Miles_per_Gallon":19.4,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":90,
      "Weight_in_lbs":3210,
      "Acceleration":17.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick century special",
      "Miles_per_Gallon":20.6,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":105,
      "Weight_in_lbs":3380,
      "Acceleration":15.8,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury zephyr",
      "Miles_per_Gallon":20.8,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":85,
      "Weight_in_lbs":3070,
      "Acceleration":16.7,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge aspen",
      "Miles_per_Gallon":18.6,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":110,
      "Weight_in_lbs":3620,
      "Acceleration":18.7,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc concord d/l",
      "Miles_per_Gallon":18.1,
      "Cylinders":6,
      "Displacement":258,
      "Horsepower":120,
      "Weight_in_lbs":3410,
      "Acceleration":15.1,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet monte carlo landau",
      "Miles_per_Gallon":19.2,
      "Cylinders":8,
      "Displacement":305,
      "Horsepower":145,
      "Weight_in_lbs":3425,
      "Acceleration":13.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick regal sport coupe (turbo)",
      "Miles_per_Gallon":17.7,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":165,
      "Weight_in_lbs":3445,
      "Acceleration":13.4,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford futura",
      "Miles_per_Gallon":18.1,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":139,
      "Weight_in_lbs":3205,
      "Acceleration":11.2,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge magnum xe",
      "Miles_per_Gallon":17.5,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":140,
      "Weight_in_lbs":4080,
      "Acceleration":13.7,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet chevette",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":68,
      "Weight_in_lbs":2155,
      "Acceleration":16.5,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota corona",
      "Miles_per_Gallon":27.5,
      "Cylinders":4,
      "Displacement":134,
      "Horsepower":95,
      "Weight_in_lbs":2560,
      "Acceleration":14.2,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 510",
      "Miles_per_Gallon":27.2,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":97,
      "Weight_in_lbs":2300,
      "Acceleration":14.7,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge omni",
      "Miles_per_Gallon":30.9,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":75,
      "Weight_in_lbs":2230,
      "Acceleration":14.5,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota celica gt liftback",
      "Miles_per_Gallon":21.1,
      "Cylinders":4,
      "Displacement":134,
      "Horsepower":95,
      "Weight_in_lbs":2515,
      "Acceleration":14.8,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth sapporo",
      "Miles_per_Gallon":23.2,
      "Cylinders":4,
      "Displacement":156,
      "Horsepower":105,
      "Weight_in_lbs":2745,
      "Acceleration":16.7,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile starfire sx",
      "Miles_per_Gallon":23.8,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":85,
      "Weight_in_lbs":2855,
      "Acceleration":17.6,
      "Year":"1978-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 200-sx",
      "Miles_per_Gallon":23.9,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":97,
      "Weight_in_lbs":2405,
      "Acceleration":14.9,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"audi 5000",
      "Miles_per_Gallon":20.3,
      "Cylinders":5,
      "Displacement":131,
      "Horsepower":103,
      "Weight_in_lbs":2830,
      "Acceleration":15.9,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volvo 264gl",
      "Miles_per_Gallon":17,
      "Cylinders":6,
      "Displacement":163,
      "Horsepower":125,
      "Weight_in_lbs":3140,
      "Acceleration":13.6,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"saab 99gle",
      "Miles_per_Gallon":21.6,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":115,
      "Weight_in_lbs":2795,
      "Acceleration":15.7,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"peugeot 604sl",
      "Miles_per_Gallon":16.2,
      "Cylinders":6,
      "Displacement":163,
      "Horsepower":133,
      "Weight_in_lbs":3410,
      "Acceleration":15.8,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volkswagen scirocco",
      "Miles_per_Gallon":31.5,
      "Cylinders":4,
      "Displacement":89,
      "Horsepower":71,
      "Weight_in_lbs":1990,
      "Acceleration":14.9,
      "Year":"1978-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda Accelerationord lx",
      "Miles_per_Gallon":29.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":68,
      "Weight_in_lbs":2135,
      "Acceleration":16.6,
      "Year":"1978-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"pontiac lemans v6",
      "Miles_per_Gallon":21.5,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":115,
      "Weight_in_lbs":3245,
      "Acceleration":15.4,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury zephyr 6",
      "Miles_per_Gallon":19.8,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":85,
      "Weight_in_lbs":2990,
      "Acceleration":18.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford fairmont 4",
      "Miles_per_Gallon":22.3,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":88,
      "Weight_in_lbs":2890,
      "Acceleration":17.3,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc concord dl 6",
      "Miles_per_Gallon":20.2,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":90,
      "Weight_in_lbs":3265,
      "Acceleration":18.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge aspen 6",
      "Miles_per_Gallon":20.6,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":110,
      "Weight_in_lbs":3360,
      "Acceleration":16.6,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet caprice classic",
      "Miles_per_Gallon":17,
      "Cylinders":8,
      "Displacement":305,
      "Horsepower":130,
      "Weight_in_lbs":3840,
      "Acceleration":15.4,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford ltd landau",
      "Miles_per_Gallon":17.6,
      "Cylinders":8,
      "Displacement":302,
      "Horsepower":129,
      "Weight_in_lbs":3725,
      "Acceleration":13.4,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury grand marquis",
      "Miles_per_Gallon":16.5,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":138,
      "Weight_in_lbs":3955,
      "Acceleration":13.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge st. regis",
      "Miles_per_Gallon":18.2,
      "Cylinders":8,
      "Displacement":318,
      "Horsepower":135,
      "Weight_in_lbs":3830,
      "Acceleration":15.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick estate wagon (sw)",
      "Miles_per_Gallon":16.9,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":155,
      "Weight_in_lbs":4360,
      "Acceleration":14.9,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford country squire (sw)",
      "Miles_per_Gallon":15.5,
      "Cylinders":8,
      "Displacement":351,
      "Horsepower":142,
      "Weight_in_lbs":4054,
      "Acceleration":14.3,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet malibu classic (sw)",
      "Miles_per_Gallon":19.2,
      "Cylinders":8,
      "Displacement":267,
      "Horsepower":125,
      "Weight_in_lbs":3605,
      "Acceleration":15,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler lebaron town @ country (sw)",
      "Miles_per_Gallon":18.5,
      "Cylinders":8,
      "Displacement":360,
      "Horsepower":150,
      "Weight_in_lbs":3940,
      "Acceleration":13,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"vw rabbit custom",
      "Miles_per_Gallon":31.9,
      "Cylinders":4,
      "Displacement":89,
      "Horsepower":71,
      "Weight_in_lbs":1925,
      "Acceleration":14,
      "Year":"1979-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"maxda glc deluxe",
      "Miles_per_Gallon":34.1,
      "Cylinders":4,
      "Displacement":86,
      "Horsepower":65,
      "Weight_in_lbs":1975,
      "Acceleration":15.2,
      "Year":"1979-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge colt hatchback custom",
      "Miles_per_Gallon":35.7,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":80,
      "Weight_in_lbs":1915,
      "Acceleration":14.4,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc spirit dl",
      "Miles_per_Gallon":27.4,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":80,
      "Weight_in_lbs":2670,
      "Acceleration":15,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercedes benz 300d",
      "Miles_per_Gallon":25.4,
      "Cylinders":5,
      "Displacement":183,
      "Horsepower":77,
      "Weight_in_lbs":3530,
      "Acceleration":20.1,
      "Year":"1979-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"cadillac eldorado",
      "Miles_per_Gallon":23,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":125,
      "Weight_in_lbs":3900,
      "Acceleration":17.4,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"peugeot 504",
      "Miles_per_Gallon":27.2,
      "Cylinders":4,
      "Displacement":141,
      "Horsepower":71,
      "Weight_in_lbs":3190,
      "Acceleration":24.8,
      "Year":"1979-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"oldsmobile cutlass salon brougham",
      "Miles_per_Gallon":23.9,
      "Cylinders":8,
      "Displacement":260,
      "Horsepower":90,
      "Weight_in_lbs":3420,
      "Acceleration":22.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth horizon",
      "Miles_per_Gallon":34.2,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":70,
      "Weight_in_lbs":2200,
      "Acceleration":13.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth horizon tc3",
      "Miles_per_Gallon":34.5,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":70,
      "Weight_in_lbs":2150,
      "Acceleration":14.9,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 210",
      "Miles_per_Gallon":31.8,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":65,
      "Weight_in_lbs":2020,
      "Acceleration":19.2,
      "Year":"1979-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"fiat strada custom",
      "Miles_per_Gallon":37.3,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":69,
      "Weight_in_lbs":2130,
      "Acceleration":14.7,
      "Year":"1979-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"buick skylark limited",
      "Miles_per_Gallon":28.4,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":2670,
      "Acceleration":16,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet citation",
      "Miles_per_Gallon":28.8,
      "Cylinders":6,
      "Displacement":173,
      "Horsepower":115,
      "Weight_in_lbs":2595,
      "Acceleration":11.3,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile omega brougham",
      "Miles_per_Gallon":26.8,
      "Cylinders":6,
      "Displacement":173,
      "Horsepower":115,
      "Weight_in_lbs":2700,
      "Acceleration":12.9,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac phoenix",
      "Miles_per_Gallon":33.5,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":2556,
      "Acceleration":13.2,
      "Year":"1979-01-01",
      "Origin":"USA"
   },
   {
      "Name":"vw rabbit",
      "Miles_per_Gallon":41.5,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":76,
      "Weight_in_lbs":2144,
      "Acceleration":14.7,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota corolla tercel",
      "Miles_per_Gallon":38.1,
      "Cylinders":4,
      "Displacement":89,
      "Horsepower":60,
      "Weight_in_lbs":1968,
      "Acceleration":18.8,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet chevette",
      "Miles_per_Gallon":32.1,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":70,
      "Weight_in_lbs":2120,
      "Acceleration":15.5,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 310",
      "Miles_per_Gallon":37.2,
      "Cylinders":4,
      "Displacement":86,
      "Horsepower":65,
      "Weight_in_lbs":2019,
      "Acceleration":16.4,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"chevrolet citation",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":2678,
      "Acceleration":16.5,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford fairmont",
      "Miles_per_Gallon":26.4,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":88,
      "Weight_in_lbs":2870,
      "Acceleration":18.1,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc concord",
      "Miles_per_Gallon":24.3,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":3003,
      "Acceleration":20.1,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge aspen",
      "Miles_per_Gallon":19.1,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":90,
      "Weight_in_lbs":3381,
      "Acceleration":18.7,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"audi 4000",
      "Miles_per_Gallon":34.3,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":78,
      "Weight_in_lbs":2188,
      "Acceleration":15.8,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota corona liftback",
      "Miles_per_Gallon":29.8,
      "Cylinders":4,
      "Displacement":134,
      "Horsepower":90,
      "Weight_in_lbs":2711,
      "Acceleration":15.5,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda 626",
      "Miles_per_Gallon":31.3,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":75,
      "Weight_in_lbs":2542,
      "Acceleration":17.5,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 510 hatchback",
      "Miles_per_Gallon":37,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":92,
      "Weight_in_lbs":2434,
      "Acceleration":15,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyota corolla",
      "Miles_per_Gallon":32.2,
      "Cylinders":4,
      "Displacement":108,
      "Horsepower":75,
      "Weight_in_lbs":2265,
      "Acceleration":15.2,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda glc",
      "Miles_per_Gallon":46.6,
      "Cylinders":4,
      "Displacement":86,
      "Horsepower":65,
      "Weight_in_lbs":2110,
      "Acceleration":17.9,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge colt",
      "Miles_per_Gallon":27.9,
      "Cylinders":4,
      "Displacement":156,
      "Horsepower":105,
      "Weight_in_lbs":2800,
      "Acceleration":14.4,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"datsun 210",
      "Miles_per_Gallon":40.8,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":65,
      "Weight_in_lbs":2110,
      "Acceleration":19.2,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"vw rabbit c (diesel)",
      "Miles_per_Gallon":44.3,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":48,
      "Weight_in_lbs":2085,
      "Acceleration":21.7,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"vw dasher (diesel)",
      "Miles_per_Gallon":43.4,
      "Cylinders":4,
      "Displacement":90,
      "Horsepower":48,
      "Weight_in_lbs":2335,
      "Acceleration":23.7,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"audi 5000s (diesel)",
      "Miles_per_Gallon":36.4,
      "Cylinders":5,
      "Displacement":121,
      "Horsepower":67,
      "Weight_in_lbs":2950,
      "Acceleration":19.9,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"mercedes-benz 240d",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":146,
      "Horsepower":67,
      "Weight_in_lbs":3250,
      "Acceleration":21.8,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda civic 1500 gl",
      "Miles_per_Gallon":44.6,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":67,
      "Weight_in_lbs":1850,
      "Acceleration":13.8,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"renault lecar deluxe",
      "Miles_per_Gallon":40.9,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":None,
      "Weight_in_lbs":1835,
      "Acceleration":17.3,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"subaru dl",
      "Miles_per_Gallon":33.8,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":67,
      "Weight_in_lbs":2145,
      "Acceleration":18,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"vokswagen rabbit",
      "Miles_per_Gallon":29.8,
      "Cylinders":4,
      "Displacement":89,
      "Horsepower":62,
      "Weight_in_lbs":1845,
      "Acceleration":15.3,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"datsun 280-zx",
      "Miles_per_Gallon":32.7,
      "Cylinders":6,
      "Displacement":168,
      "Horsepower":132,
      "Weight_in_lbs":2910,
      "Acceleration":11.4,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda rx-7 gs",
      "Miles_per_Gallon":23.7,
      "Cylinders":3,
      "Displacement":70,
      "Horsepower":100,
      "Weight_in_lbs":2420,
      "Acceleration":12.5,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"triumph tr7 coupe",
      "Miles_per_Gallon":35,
      "Cylinders":4,
      "Displacement":122,
      "Horsepower":88,
      "Weight_in_lbs":2500,
      "Acceleration":15.1,
      "Year":"1980-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"ford mustang cobra",
      "Miles_per_Gallon":23.6,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":None,
      "Weight_in_lbs":2905,
      "Acceleration":14.3,
      "Year":"1980-01-01",
      "Origin":"USA"
   },
   {
      "Name":"honda Accelerationord",
      "Miles_per_Gallon":32.4,
      "Cylinders":4,
      "Displacement":107,
      "Horsepower":72,
      "Weight_in_lbs":2290,
      "Acceleration":17,
      "Year":"1980-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth reliant",
      "Miles_per_Gallon":27.2,
      "Cylinders":4,
      "Displacement":135,
      "Horsepower":84,
      "Weight_in_lbs":2490,
      "Acceleration":15.7,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"buick skylark",
      "Miles_per_Gallon":26.6,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":84,
      "Weight_in_lbs":2635,
      "Acceleration":16.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge aries wagon (sw)",
      "Miles_per_Gallon":25.8,
      "Cylinders":4,
      "Displacement":156,
      "Horsepower":92,
      "Weight_in_lbs":2620,
      "Acceleration":14.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet citation",
      "Miles_per_Gallon":23.5,
      "Cylinders":6,
      "Displacement":173,
      "Horsepower":110,
      "Weight_in_lbs":2725,
      "Acceleration":12.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"plymouth reliant",
      "Miles_per_Gallon":30,
      "Cylinders":4,
      "Displacement":135,
      "Horsepower":84,
      "Weight_in_lbs":2385,
      "Acceleration":12.9,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota starlet",
      "Miles_per_Gallon":39.1,
      "Cylinders":4,
      "Displacement":79,
      "Horsepower":58,
      "Weight_in_lbs":1755,
      "Acceleration":16.9,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth champ",
      "Miles_per_Gallon":39,
      "Cylinders":4,
      "Displacement":86,
      "Horsepower":64,
      "Weight_in_lbs":1875,
      "Acceleration":16.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"honda civic 1300",
      "Miles_per_Gallon":35.1,
      "Cylinders":4,
      "Displacement":81,
      "Horsepower":60,
      "Weight_in_lbs":1760,
      "Acceleration":16.1,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"subaru",
      "Miles_per_Gallon":32.3,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":67,
      "Weight_in_lbs":2065,
      "Acceleration":17.8,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 210",
      "Miles_per_Gallon":37,
      "Cylinders":4,
      "Displacement":85,
      "Horsepower":65,
      "Weight_in_lbs":1975,
      "Acceleration":19.4,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyota tercel",
      "Miles_per_Gallon":37.7,
      "Cylinders":4,
      "Displacement":89,
      "Horsepower":62,
      "Weight_in_lbs":2050,
      "Acceleration":17.3,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda glc 4",
      "Miles_per_Gallon":34.1,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":68,
      "Weight_in_lbs":1985,
      "Acceleration":16,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth horizon 4",
      "Miles_per_Gallon":34.7,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":63,
      "Weight_in_lbs":2215,
      "Acceleration":14.9,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford escort 4w",
      "Miles_per_Gallon":34.4,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":65,
      "Weight_in_lbs":2045,
      "Acceleration":16.2,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford escort 2h",
      "Miles_per_Gallon":29.9,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":65,
      "Weight_in_lbs":2380,
      "Acceleration":20.7,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen jetta",
      "Miles_per_Gallon":33,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":74,
      "Weight_in_lbs":2190,
      "Acceleration":14.2,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"renault 18i",
      "Miles_per_Gallon":34.5,
      "Cylinders":4,
      "Displacement":100,
      "Horsepower":None,
      "Weight_in_lbs":2320,
      "Acceleration":15.8,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"honda prelude",
      "Miles_per_Gallon":33.7,
      "Cylinders":4,
      "Displacement":107,
      "Horsepower":75,
      "Weight_in_lbs":2210,
      "Acceleration":14.4,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyota corolla",
      "Miles_per_Gallon":32.4,
      "Cylinders":4,
      "Displacement":108,
      "Horsepower":75,
      "Weight_in_lbs":2350,
      "Acceleration":16.8,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 200sx",
      "Miles_per_Gallon":32.9,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":100,
      "Weight_in_lbs":2615,
      "Acceleration":14.8,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda 626",
      "Miles_per_Gallon":31.6,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":74,
      "Weight_in_lbs":2635,
      "Acceleration":18.3,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"peugeot 505s turbo diesel",
      "Miles_per_Gallon":28.1,
      "Cylinders":4,
      "Displacement":141,
      "Horsepower":80,
      "Weight_in_lbs":3230,
      "Acceleration":20.4,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"saab 900s",
      "Miles_per_Gallon":None,
      "Cylinders":4,
      "Displacement":121,
      "Horsepower":110,
      "Weight_in_lbs":2800,
      "Acceleration":15.4,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"volvo diesel",
      "Miles_per_Gallon":30.7,
      "Cylinders":6,
      "Displacement":145,
      "Horsepower":76,
      "Weight_in_lbs":3160,
      "Acceleration":19.6,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"toyota cressida",
      "Miles_per_Gallon":25.4,
      "Cylinders":6,
      "Displacement":168,
      "Horsepower":116,
      "Weight_in_lbs":2900,
      "Acceleration":12.6,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 810 maxima",
      "Miles_per_Gallon":24.2,
      "Cylinders":6,
      "Displacement":146,
      "Horsepower":120,
      "Weight_in_lbs":2930,
      "Acceleration":13.8,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"buick century",
      "Miles_per_Gallon":22.4,
      "Cylinders":6,
      "Displacement":231,
      "Horsepower":110,
      "Weight_in_lbs":3415,
      "Acceleration":15.8,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile cutlass ls",
      "Miles_per_Gallon":26.6,
      "Cylinders":8,
      "Displacement":350,
      "Horsepower":105,
      "Weight_in_lbs":3725,
      "Acceleration":19,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford granada gl",
      "Miles_per_Gallon":20.2,
      "Cylinders":6,
      "Displacement":200,
      "Horsepower":88,
      "Weight_in_lbs":3060,
      "Acceleration":17.1,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler lebaron salon",
      "Miles_per_Gallon":17.6,
      "Cylinders":6,
      "Displacement":225,
      "Horsepower":85,
      "Weight_in_lbs":3465,
      "Acceleration":16.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet cavalier",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":112,
      "Horsepower":88,
      "Weight_in_lbs":2605,
      "Acceleration":19.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet cavalier wagon",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":112,
      "Horsepower":88,
      "Weight_in_lbs":2640,
      "Acceleration":18.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet cavalier 2-door",
      "Miles_per_Gallon":34,
      "Cylinders":4,
      "Displacement":112,
      "Horsepower":88,
      "Weight_in_lbs":2395,
      "Acceleration":18,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac j2000 se hatchback",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":112,
      "Horsepower":85,
      "Weight_in_lbs":2575,
      "Acceleration":16.2,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"dodge aries se",
      "Miles_per_Gallon":29,
      "Cylinders":4,
      "Displacement":135,
      "Horsepower":84,
      "Weight_in_lbs":2525,
      "Acceleration":16,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"pontiac phoenix",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":2735,
      "Acceleration":18,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford fairmont futura",
      "Miles_per_Gallon":24,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":92,
      "Weight_in_lbs":2865,
      "Acceleration":16.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"amc concord dl",
      "Miles_per_Gallon":23,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":None,
      "Weight_in_lbs":3035,
      "Acceleration":20.5,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"volkswagen rabbit l",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":74,
      "Weight_in_lbs":1980,
      "Acceleration":15.3,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"mazda glc custom l",
      "Miles_per_Gallon":37,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":68,
      "Weight_in_lbs":2025,
      "Acceleration":18.2,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"mazda glc custom",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":68,
      "Weight_in_lbs":1970,
      "Acceleration":17.6,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"plymouth horizon miser",
      "Miles_per_Gallon":38,
      "Cylinders":4,
      "Displacement":105,
      "Horsepower":63,
      "Weight_in_lbs":2125,
      "Acceleration":14.7,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"mercury lynx l",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":98,
      "Horsepower":70,
      "Weight_in_lbs":2125,
      "Acceleration":17.3,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"nissan stanza xe",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":88,
      "Weight_in_lbs":2160,
      "Acceleration":14.5,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"honda Accelerationord",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":107,
      "Horsepower":75,
      "Weight_in_lbs":2205,
      "Acceleration":14.5,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"toyota corolla",
      "Miles_per_Gallon":34,
      "Cylinders":4,
      "Displacement":108,
      "Horsepower":70,
      "Weight_in_lbs":2245,
      "Acceleration":16.9,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"honda civic",
      "Miles_per_Gallon":38,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":67,
      "Weight_in_lbs":1965,
      "Acceleration":15,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"honda civic (auto)",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":67,
      "Weight_in_lbs":1965,
      "Acceleration":15.7,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"datsun 310 gx",
      "Miles_per_Gallon":38,
      "Cylinders":4,
      "Displacement":91,
      "Horsepower":67,
      "Weight_in_lbs":1995,
      "Acceleration":16.2,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"buick century limited",
      "Miles_per_Gallon":25,
      "Cylinders":6,
      "Displacement":181,
      "Horsepower":110,
      "Weight_in_lbs":2945,
      "Acceleration":16.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"oldsmobile cutlass ciera (diesel)",
      "Miles_per_Gallon":38,
      "Cylinders":6,
      "Displacement":262,
      "Horsepower":85,
      "Weight_in_lbs":3015,
      "Acceleration":17,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chrysler lebaron medallion",
      "Miles_per_Gallon":26,
      "Cylinders":4,
      "Displacement":156,
      "Horsepower":92,
      "Weight_in_lbs":2585,
      "Acceleration":14.5,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford granada l",
      "Miles_per_Gallon":22,
      "Cylinders":6,
      "Displacement":232,
      "Horsepower":112,
      "Weight_in_lbs":2835,
      "Acceleration":14.7,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"toyota celica gt",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":144,
      "Horsepower":96,
      "Weight_in_lbs":2665,
      "Acceleration":13.9,
      "Year":"1982-01-01",
      "Origin":"Japan"
   },
   {
      "Name":"dodge charger 2.2",
      "Miles_per_Gallon":36,
      "Cylinders":4,
      "Displacement":135,
      "Horsepower":84,
      "Weight_in_lbs":2370,
      "Acceleration":13,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevrolet camaro",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":151,
      "Horsepower":90,
      "Weight_in_lbs":2950,
      "Acceleration":17.3,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford mustang gl",
      "Miles_per_Gallon":27,
      "Cylinders":4,
      "Displacement":140,
      "Horsepower":86,
      "Weight_in_lbs":2790,
      "Acceleration":15.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"vw pickup",
      "Miles_per_Gallon":44,
      "Cylinders":4,
      "Displacement":97,
      "Horsepower":52,
      "Weight_in_lbs":2130,
      "Acceleration":24.6,
      "Year":"1982-01-01",
      "Origin":"Europe"
   },
   {
      "Name":"dodge rampage",
      "Miles_per_Gallon":32,
      "Cylinders":4,
      "Displacement":135,
      "Horsepower":84,
      "Weight_in_lbs":2295,
      "Acceleration":11.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"ford ranger",
      "Miles_per_Gallon":28,
      "Cylinders":4,
      "Displacement":120,
      "Horsepower":79,
      "Weight_in_lbs":2625,
      "Acceleration":18.6,
      "Year":"1982-01-01",
      "Origin":"USA"
   },
   {
      "Name":"chevy s-10",
      "Miles_per_Gallon":31,
      "Cylinders":4,
      "Displacement":119,
      "Horsepower":82,
      "Weight_in_lbs":2720,
      "Acceleration":19.4,
      "Year":"1982-01-01",
      "Origin":"USA"
   }
]