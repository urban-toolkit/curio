# Simple Diagrams
# Example: Visual analytics of tabular urban data

In this example, we will explore how Curio can facilitate visual analytics of tabular data by connecting a single data source to multiple chart types — bar, horizontal bar, scatter, line, and pie — each configured through a simple JSON specification. Here is the overview of the entire dataflow pipeline:

Before you begin, please familiarize yourself with Curio's main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

## Step 1: Load tabular data

We start by instantiating a data loading node. The same DataFrame is shared across all five visualizations:

```python
import pandas as pd

df = pd.DataFrame({
    "neighborhood": ["Downtown", "Midtown", "Uptown", "Eastside", "Westside", "Southbank"],
    "avg_temp_c":   [28.4, 27.1, 25.8, 26.3, 24.9, 27.8],
    "green_cover":  [12, 23, 41, 18, 55, 9],
    "population":   [42000, 31000, 18000, 27000, 14000, 22000],
    "aqi":          [87, 72, 45, 68, 38, 91],
})

return df
```

The DataFrame contains five columns: `neighborhood` (categorical label), `avg_temp_c` (average temperature in °C), `green_cover` (green cover percentage), `population` (resident count), and `aqi` (air quality index).

## Step 2: Bar chart — Average Temperature by Neighborhood

Connect the data node to a VIS_D3 node configured as a vertical bar chart:

```json
{
  "chartType": "bar",
  "title": "Average Temperature by Neighborhood (°C)",
  "xField": "neighborhood",
  "yField": "avg_temp_c",
  "colorScheme": "tableau10",
  "width": 560,
  "height": 320
}
```

## Step 3: Horizontal bar chart — Green Cover by Neighborhood

Connect the same data node to a second VIS_D3 node for a horizontal bar chart:

```json
{
  "chartType": "barH",
  "title": "Green Cover % by Neighborhood",
  "xField": "green_cover",
  "yField": "neighborhood",
  "colorScheme": "set2",
  "width": 500,
  "height": 280
}
```

## Step 4: Scatter plot — Air Quality Index vs Green Cover

Connect the data node to a third VIS_D3 node to compare AQI against green cover, with neighborhood labels on each point:

```json
{
  "chartType": "scatter",
  "title": "Air Quality Index vs Green Cover %",
  "xField": "green_cover",
  "yField": "aqi",
  "labelField": "neighborhood",
  "colorScheme": "dark2",
  "radius": 7,
  "width": 540,
  "height": 320
}
```

## Step 5: Line chart — Temperature Profile Across Neighborhoods

Connect the data node to a fourth VIS_D3 node to render temperature as a continuous profile:

```json
{
  "chartType": "line",
  "title": "Temperature Profile Across Neighborhoods",
  "xField": "neighborhood",
  "yField": "avg_temp_c",
  "width": 560,
  "height": 300
}
```

## Step 6: Pie chart — Population Distribution

Connect the data node to a fifth VIS_D3 node to show each neighborhood's share of total population:

```json
{
  "chartType": "pie",
  "title": "Population Distribution",
  "nameField": "neighborhood",
  "valueField": "population",
  "colorScheme": "pastel1",
  "width": 420,
  "height": 420
}
```

## Final result

This example demonstrates how a single data loading node in Curio can fan out to multiple independent visualizations. Each VIS_D3 node receives the same DataFrame and renders a different chart type based on its JSON configuration, making it easy to explore different dimensions of the same dataset side by side.
