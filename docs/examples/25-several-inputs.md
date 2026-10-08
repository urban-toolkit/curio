# Example: Several inputs

One node fed by several others, in each kind of node that takes several inputs:
Python Computation, Data Transformation, JS Computation, Vega-Lite, Autark and
Data Pool. One of the inputs carries a tuple. The data are the air quality
readings and stations of [example 20](20-storage-folder-of-csv-files.md), and the
ZIP codes of Chicago's Loop.

## How several inputs reach a node

Each edge into a node takes the next input circle, numbered from 0, top to
bottom: `in`, `in_1`, `in_2`. The node runs once every wired circle holds a
value. Each input has a chip, `[!! input_1 !!]`, that writes how that kind of
node reads it:

| Node | One input | Several inputs |
|---|---|---|
| Python, Data Transformation, JavaScript | `input_0` is the input | `input_0`, `input_1`, ..., one variable per circle; `[!! input_k !!]` runs as `input_k` |
| Vega-Lite | the dataset `input_0` | the datasets `input_0`, `input_1`, ... |
| Autark | the table `input_0` | the tables `input_0`, `input_1`, ... |
| Data Pool | one tab | a tab per input |

A tuple a Python node returns leaves by its one output circle and arrives on one
input:

- In Python and JavaScript the tuple is that circle's variable, so on input 1
  `input_1[0]` is its first item, with one input or several.
- On a Vega-Lite or Autark node whose only input is a tuple, each item is a
  dataset or table of its own, `input_0`, `input_1`, ..., as in
  [example 17](17-autark-geodataframe-maps.md). A Vega-Lite node refuses a tuple
  next to other inputs, so this example takes the tuple apart in Python first.

So a circle's variable never changes when another edge is connected: code
written for one input, such as `input_0.crs`, keeps working beside a second
input, `input_1`. A circle with no edge is `None`.

## Pipeline overview

```mermaid
flowchart LR
  R[`Data Loading`<br/>the readings] --> M[`Python Computation`<br/>Summarize: a tuple]
  S[`Data Loading`<br/>the stations] -->|input 0| J[`Python Computation`<br/>Join three inputs]
  M -->|input 1| J
  Z[`Data Loading`<br/>the ZIP codes] -->|input 2| J
  R -->|input 0| T[`Data Transformation`<br/>Name the readings]
  J -->|input 1| T
  Z -->|input 0| X[`JS Computation`<br/>Stations per ZIP]
  J -->|input 1| X
  T -->|input 0| C[`Vega-Lite`<br/>Readings and means]
  J -->|input 1| C
  Z -->|input 0| A[`Autark`<br/>Stations map]
  J -->|input 1| A
  J -->|input 0| P[`Data Pool`<br/>a tab each]
  T -->|input 1| P
```

## Load the data

The readings, as in example 20:

```python
import pandas as pd
import geopandas as gpd

dataset_path = curio_data_path("data.curio.storage-air-quality")
try:
    df = gpd.read_parquet(dataset_path)
except Exception:
    df = pd.read_parquet(dataset_path)

return df
```

The stations, as points:

```python
import geopandas as gpd

df = curio_load_data("data.curio.storage-stations")

# A point at each station, in longitude and latitude.
return gpd.GeoDataFrame(df, geometry=gpd.points_from_xy(df["lon"], df["lat"]), crs=4326)
```

The ZIP codes of the Loop and around it:

```python
gdf = curio_load_data("data.utk.chicago-boundary")

# The Loop and the ZIP codes around it.
downtown = ["60601", "60602", "60603", "60604", "60605",
            "60606", "60607", "60611", "60654", "60661"]
return gdf[gdf["zip"].isin(downtown)][["zip", "geometry"]]
```

## One input, a tuple out

**Summarize** has one input, so `input_0` is the readings table itself. It returns
two tables as a tuple:

```python
# One input, on circle 0, so input_0 is that input itself: the readings table.
readings = input_0

# Two tables from one input, returned together as a tuple: each sensor's mean
# PM2.5 and its highest reading. The tuple leaves by the one output circle.
means = readings.groupby("sensor", as_index=False)["pm25"].mean().rename(columns={"pm25": "pm25_mean"})
peaks = readings.groupby("sensor", as_index=False)["pm25"].max().rename(columns={"pm25": "pm25_peak"})
return means, peaks
```

## Three inputs in Python

**Join three inputs** takes the stations on input 0, Summarize's tuple on
input 1 and the ZIP codes on input 2: `input_0`, `input_1` and `input_2`, and
the tuple is `input_1`:

```python
import geopandas as gpd

# Three inputs, one per circle, and each chip below runs as that circle's
# variable, input_0, input_1, input_2.
stations = [!! input_0 !!]      # runs as input_0: the stations
means, peaks = [!! input_1 !!]  # runs as input_1: Summarize's tuple, unpacked
zips = [!! input_2 !!]          # runs as input_2: the ZIP code polygons

# input_1[0] would be the means alone: input 1, then item 0 of its tuple.
stations = stations.merge(means, on="sensor").merge(peaks, on="sensor")
return gpd.sjoin(stations, zips, predicate="within").drop(columns="index_right")
```

Each station comes out with its mean, its peak and its ZIP code: Clark and
Madison in 60603 (mean 8.0), State and Lake in 60601 (10.0), and Michigan and
Adams in 60604 (12.0).

## Two inputs in Data Transformation

```python
readings, stations = [!! input_0 !!], [!! input_1 !!]

# Each reading, with the name of the station that took it.
return readings.merge(stations[["sensor", "name"]], on="sensor")
```

## Two inputs in JavaScript

A JS Computation node reads them by the same names. A GeoDataFrame arrives as a
GeoJSON FeatureCollection, and a DataFrame as a list of rows. The node returns
one row per ZIP code, with the number of stations in it and their mean:

```js
// Two inputs, input_0 and input_1. A GeoDataFrame reaches JavaScript as
// a GeoJSON FeatureCollection (and a DataFrame as a list of rows).
const zips = [!! input_0 !!];
const stations = [!! input_1 !!];

// How many stations stand in each ZIP code, and their mean PM2.5.
return zips.features.map((zip) => {
  const inside = stations.features.filter((station) => station.properties.zip === zip.properties.zip);
  const total = inside.reduce((sum, station) => sum + station.properties.pm25_mean, 0);
  return {
    zip: zip.properties.zip,
    stations: inside.length,
    pm25_mean: inside.length > 0 ? Math.round((total / inside.length) * 100) / 100 : null,
  };
});
```

## Two inputs in Vega-Lite

The chart draws `input_0`, the named readings, unless a view names another
input. Its second layer names `input_1`, the joined stations, with the input's
chip, and a column chip, `[!! input_1.pm25_mean !!]`, names a column of it. A
chip inside a quoted string runs as the plain name, which keeps the spec JSON:

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "description": "PM2.5 at each station over time, and a dashed rule at its mean.",
  "layer": [
    {
      "mark": {"type": "line", "point": true},
      "encoding": {
        "x": {"field": "timestamp", "type": "temporal", "title": "Time", "scale": {"type": "utc"}},
        "y": {"field": "pm25", "type": "quantitative", "title": "PM2.5"},
        "color": {"field": "name", "type": "nominal", "title": "Station"}
      }
    },
    {
      "data": {"name": "[!! input_1 !!]"},
      "mark": {"type": "rule", "strokeDash": [4, 4]},
      "encoding": {
        "y": {"field": "[!! input_1.pm25_mean !!]", "type": "quantitative"},
        "color": {"field": "name", "type": "nominal"}
      }
    }
  ]
}
```

The chips run as `"input_1"` and `"pm25_mean"`.

## Two inputs in Autark

Each input is a table, `input_0` the ZIP codes and `input_1` the stations,
coloured by their mean:

```json
{
  "map": {
    "layerRefs": [
      {"dataRef": "[!! input_0 !!]"},
      {
        "dataRef": "[!! input_1 !!]",
        "getFnv": "pm25_mean",
        "getFnvType": "quantitative",
        "colorMapInterpolator": "interpolateReds",
        "isPick": true
      }
    ]
  }
}
```

## Two inputs in a Data Pool

The pool shows each input as a tab: the joined stations on input 0, the named
readings on input 1.
