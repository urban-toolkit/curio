# Example: Visual analytics of building energy efficiency

Authors: Himanshu Dongre, Aakash Kolli

In this example, we will learn how Curio can be used to perform a comparative analysis of building energy performance. The process involves loading and cleaning a dataset of Chicago buildings, then making a visualization to benchmark the energy efficiency across different property types.

Here is the overview of the entire dataflow pipeline:

![](../images/9-1.png)

Before you begin, please familiarize yourself with Curio’s main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

The data for this tutorial can be found [here](../data/energy_dataset.csv).

For completeness, we also include the template code in each dataflow step.

## Step 1: Load energy efficieency data

We begin by loading the energy efficiency dataset into Curio using a Data Loading node.
Make sure to include your full file path to the file as well. pd.read_csv(r'C:\Users\Username\Full Filepath Here\energy_dataset.csv')
```python
import pandas as pd

df = pd.read_csv("energy_dataset../data/../data/.csv")
return df
```

![](../images/9-2.png)

## Step 2: Data cleaning and processing

Next, we create a Data Cleaning node to preprocess the data to retain only the key attributes and remove incomplete rows. We also convert the ZIP code to an integer for consistency.

```python
edf  = arg[['Data Year', 'ID', 'Property Name', 'Address', 'ZIP Code', 'Chicago Energy Rating', 'Community Area', 'Primary Property Type', 'Gross Floor Area - Buildings (sq ft)', 'Year Built', '# of Buildings', 'ENERGY STAR Score', 'Site EUI (kBtu/sq ft)', 'Source EUI (kBtu/sq ft)', 'Weather Normalized Site EUI (kBtu/sq ft)', 'Weather Normalized Source EUI (kBtu/sq ft)', 'Total GHG Emissions (Metric Tons CO2e)', 'GHG Intensity (kg CO2e/sq ft)', 'Latitude', 'Longitude', 'Location']]

# Rename the data columns for consistency and easy use
edf.columns = ['Year', 'ID', 'Property Name', 'Address', 'ZIP Code', 'Chicago Energy Rating', 'Community Area', 'Primary Property Type', 'Gross Floor Area', 'Year Built', '# of Buildings', 'ENERGY STAR Score', 'Site EUI', 'Source EUI', 'Weather Normalized Site EUI', 'Weather Normalized Source EUI', 'Total GHG Emissions', 'GHG Intensity', 'Latitude', 'Longitude', 'Location']

# Filter out rows with missing data
edf = edf.dropna()
edf['ZIP Code'] = edf['ZIP Code'].astype(int)

return edf
```

![](../images/9-3.png)

## Step 3: Visualization – Mean and Median Chart

Then, we create a 2D Plot (Vega-Lite) node to create a bar and tick chart, which compares energy efficiency metrics across property types. This chart displays the mean and median of a selected metric (e.g., weather normalized site EUI) for each property type.

```json
{
  "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
  "description": "ENERGY STAR Score by Primary Property Type (mean bars with median ticks)",
  "title": "ENERGY STAR Score by Primary Property Type",
  "data": { "name": "edf" },
  "width": 600,
  "height": 400,
  "layer": [
    {
      "transform": [
        {
          "aggregate": [
            { "op": "mean", "field": "ENERGY STAR Score", "as": "mean_score" }
          ],
          "groupby": ["Primary Property Type"]
        }
      ],
      "mark": "bar",
      "encoding": {
        "y": {
          "field": "Primary Property Type",
          "type": "nominal",
          "title": "Primary Property Type"
        },
        "x": {
          "field": "mean_score",
          "type": "quantitative",
          "scale": { "domain": [0, 100] },
          "title": "Mean ENERGY STAR Score"
        },
        "tooltip": [
          {
            "field": "Primary Property Type",
            "type": "nominal",
            "title": "Primary Property Type"
          },
          {
            "field": "mean_score",
            "type": "quantitative",
            "title": "Mean ENERGY STAR Score",
            "format": ".2f"
          }
        ]
      }
    },
    {
      "transform": [
        {
          "aggregate": [
            { "op": "median", "field": "ENERGY STAR Score", "as": "median_score" }
          ],
          "groupby": ["Primary Property Type"]
        }
      ],
      "mark": {
        "type": "tick",
        "color": "red",
        "thickness": 2
      },
      "encoding": {
        "y": {
          "field": "Primary Property Type",
          "type": "nominal"
        },
        "x": {
          "field": "median_score",
          "type": "quantitative",
          "scale": { "domain": [0, 100] },
          "title": "Median ENERGY STAR Score"
        },
        "tooltip": [
          {
            "field": "Primary Property Type",
            "type": "nominal",
            "title": "Primary Property Type"
          },
          {
            "field": "median_score",
            "type": "quantitative",
            "title": "Median ENERGY STAR Score",
            "format": ".2f"
          }
        ]
      }
    }
  ]
}
```

![](../images/9-4.png)

## Final result

The final result of this workflow is a layered chart that presents both the mean and median energy use intensity for various building types. Displaying both metrics reveals important details about the data's distribution as a large gap between the mean and median values for a category shows that a few highly inefficient buildings are skewing the average. Recognizing this distinction helps in developing more effective energy efficiency policies and programs.
