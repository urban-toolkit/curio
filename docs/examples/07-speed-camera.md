# Example: Visual analytics of speed camera violations

Author: Ameer Mustafa, Filip Petrev, Sania Sohail, Aakash Kolli

In this example, we will explore how Curio can facilitate the temporal analysis of urban mobility data by processing and aggregating tabular records to analyze and visualize trends in speed camera violations across Chicago.

Here is the overview of the entire dataflow pipeline:

![Dataflow](images/7-1.png)

Before you begin, please familiarize yourself with Curio’s main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

The data for this tutorial can be found [here](data/07-speed_camera_violations.zip).

For completeness, we also include the template code in each dataflow step.

## Step 1: Load speed camera violatiions data

We begin creating a Data Loading node to load the speed camera violations dataset into Curio.

```python
import pandas as pd

df = pd.read_csv("docs/examples/data/07-speed_camera_violations.zip")
df.dropna(inplace=True)
return df
```

![](images/7-2.png)

## Step 2: Data Pool

Next, we create a Data Pool node, which passes the cleaned DataFrame to downstream nodes for further transformation and visualization.

## Step 3: Data Transformation – Top 5 Cameras by Violations per Year

Now, we will create a Data transformation node connected to the output of Step 2:

```python
import pandas as pd

df = arg

df['VIOLATION DATE'] = pd.to_datetime(df['VIOLATION DATE'], format='%m/%d/%Y')

df['Year'] = df['VIOLATION DATE'].dt.year

yr_sum = (df.groupby(['CAMERA ID', 'Year'])['VIOLATIONS']
          .sum()
          .reset_index()
          .rename(columns={'VIOLATIONS': 'avg_violations'}))

top_ids = (df.groupby('CAMERA ID')['VIOLATIONS']
             .sum()
             .sort_values(ascending=False)
             .head(5)
             .index
             .tolist())

yr_sum = yr_sum[yr_sum['CAMERA ID'].isin(top_ids)]

camera_pos = (df.groupby('CAMERA ID')[['LATITUDE', 'LONGITUDE']]
                .mean()
                .reset_index())

yr_sum = yr_sum.merge(camera_pos, on='CAMERA ID')

return yr_sum
```

![](images/7-3.png)

This analysis aggregates the violations by camera and year, identifying the top 5 cameras with the highest total violations.

## Step 4: Per-Camera Bar Chart

We create a 2D Plot (Vega-Lite) node and connect it to the Computation Analysis node. This first plot stacks per-camera violations by year.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "data": { "name": "table" },
  "width": 320,
  "height": 260,
  "config": { "bar": { "continuousBandSize": 18 } },
  "mark": { "type": "bar" },
  "encoding": {
    "x": { "field": "Year", "type": "quantitative", "title": "Year" },
    "y": {
      "aggregate": "sum",
      "field": "avg_violations",
      "type": "quantitative",
      "title": "Total Violations"
    },
    "color": {
      "field": "CAMERA ID",
      "type": "nominal",
      "legend": { "title": "Camera ID" }
    }
  }
}
```

## Step 5: Total Violations Line Chart

We add a second 2D Plot (Vega-Lite) node, also connected to the Computation Analysis node, that aggregates totals across cameras and renders a line chart.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "data": { "name": "table" },
  "width": 320,
  "height": 260,
  "transform": [
    {
      "aggregate": [
        { "op": "sum", "field": "avg_violations", "as": "total" }
      ],
      "groupby": ["Year"]
    },
    { "sort": { "field": "Year" } }
  ],
  "mark": { "type": "line", "point": true },
  "encoding": {
    "x": {
      "field": "Year",
      "type": "quantitative",
      "title": "Year"
    },
    "y": {
      "field": "total",
      "type": "quantitative",
      "title": "Total Violations"
    }
  }
}
```

![](images/7-4.png)

## Final result

This example demonstrates how Curio can be used for a detailed temporal analysis of urban safety data. By transforming and aggregating violation records, we can generate interactive visualizations like stacked bar charts and linked views to effectively identify and compare trends over time. This workflow allows for a deeper understanding of violation patterns and the performance of specific camera locations.
