# Example: Temporal aggregation feeding linked Vega-Lite charts

This example demonstrates how a single time-aggregated table can feed two different Vega-Lite views, a per-camera stacked bar chart and a city-wide totals line chart, both reading from the same `Python Computation` output. The use case is Chicago's speed-camera violations dataset: we group violations per camera per year, keep the top five offenders, and visualise both the per-camera breakdown and the year-over-year total.

## Pipeline overview

```mermaid
flowchart LR
  L[`Data Loading`] --> C[`Python Computation`<br/>per-camera-per-year]
  C --> V1[`Vega-Lite`<br/>per-camera stacked bar]
  C --> V2[`Vega-Lite`<br/>citywide totals line]
```

## Data

This example reads its inputs from the [Data Catalog](../DATA-CATALOG.md). Each loader node
addresses a dataset by id via `curio_dataset_path("<id>")` rather than by a repo-relative path,
so the dataflow runs unchanged from a checkout, a Docker deployment or a `pip` install.

| Dataset | Id | Format | Size |
|---|---|---|---|
| Chicago Speed Camera Violations | `data.cityofchicago.speed-camera-violations` | parquet | 408,261 rows |

The catalog dataset is a Parquet conversion of the original zipped export, so it loads faster
and takes less space in the repo while keeping every row. It ships in the committed catalog under
`datasets/` and is already added to this dataflow. Source: [Chicago Data Portal](https://data.cityofchicago.org/).

## Step 1: Load the violations table (`Data Loading`)

Read the table from the catalog. Three trims at the source matter for runtime: `columns` keeps only the five columns downstream actually reads, and because parquet projects columns in the file format the other four are never decoded at all; `pd.to_datetime` parses `VIOLATION DATE` once instead of per-row, and stays above `dropna` so a row with an unparseable date is still dropped; converting `CAMERA ID` to a `category` cuts the in-memory size of the resulting DataFrame from ~130 MB (400k rows × 9 cols of mostly strings) to ~16 MB. Without these the inter-node serialization can time out the frontend.

```python
import pandas as pd

dataset_path = curio_dataset_path("data.cityofchicago.speed-camera-violations")
df = pd.read_parquet(
    dataset_path,
    columns=['CAMERA ID', 'VIOLATION DATE', 'VIOLATIONS', 'LATITUDE', 'LONGITUDE'],
)
df['VIOLATION DATE'] = pd.to_datetime(df['VIOLATION DATE'], format='%m/%d/%Y')
df.dropna(inplace=True)
df['CAMERA ID'] = df['CAMERA ID'].astype('category')
return df
```

## Step 2: Per-camera-per-year aggregation (`Python Computation`)

Parse the date, derive a `Year` column, sum violations per camera per year, then narrow to the five cameras with the highest cumulative violations. The mean lat/lon per camera is merged in so the same table could later be used to plot the cameras on a map.

```python
import pandas as pd

df = arg
df['Year'] = df['VIOLATION DATE'].dt.year

yr_sum = (df.groupby(['CAMERA ID', 'Year'], observed=True)['VIOLATIONS']
    .sum()
    .reset_index()
    .rename(columns={'VIOLATIONS': 'total_violations'}))

top_ids = (df.groupby('CAMERA ID', observed=True)['VIOLATIONS']
    .sum()
    .sort_values(ascending=False)
    .head(5)
    .index
    .tolist())

yr_sum = yr_sum[yr_sum['CAMERA ID'].isin(top_ids)]

camera_pos = (df.groupby('CAMERA ID', observed=True)[['LATITUDE', 'LONGITUDE']]
    .mean()
    .reset_index())

yr_sum = yr_sum.merge(camera_pos, on='CAMERA ID')

return yr_sum
```

## Step 3: Per-camera stacked bar chart (`Vega-Lite`)

The first view stacks violations by camera within each year so individual offenders stand out.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "data": {"name": "table"},
  "width": 320,
  "height": 260,
  "config": {"bar": {"continuousBandSize": 18}},
  "mark": {"type": "bar"},
  "encoding": {
    "x": {"field": "Year", "type": "quantitative", "title": "Year"},
    "y": {
      "aggregate": "sum",
      "field": "total_violations",
      "type": "quantitative",
      "title": "Total Violations"
    },
    "color": {
      "field": "CAMERA ID",
      "type": "nominal",
      "legend": {"title": "Camera ID"}
    }
  }
}
```

## Step 4: Citywide totals line chart (`Vega-Lite`)

The second view sums across the same five cameras to show the year-over-year trend.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
  "data": {"name": "table"},
  "width": 320,
  "height": 260,
  "transform": [
    {
      "aggregate": [{"op": "sum", "field": "total_violations", "as": "total"}],
      "groupby": ["Year"]
    },
    {"sort": {"field": "Year"}}
  ],
  "mark": {"type": "line", "point": true},
  "encoding": {
    "x": {"field": "Year", "type": "quantitative", "title": "Year"},
    "y": {"field": "total", "type": "quantitative", "title": "Total Violations"}
  }
}
```

## Final result

The two views share an upstream table without recomputing it: the bar chart answers "*which* cameras drive each year's totals?", while the line chart answers "is the total trending up or down?". Adding a third view (e.g. a map of the five cameras using their merged lat/lon columns) is just one more node off the same `Python Computation` output.
