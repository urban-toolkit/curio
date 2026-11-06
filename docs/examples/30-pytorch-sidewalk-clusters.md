# Example: PyTorch: sidewalk clusters

Project Sidewalk's volunteers have labeled 145,880 places on the sidewalks of Chicago and its suburbs: curb ramps, missing ramps, obstacles, surface problems and more. This example groups the labels by place with k-means, in PyTorch on the GPU when the machine has one, maps the clusters with Autark, and charts the types of label in each cluster.

PyTorch comes with Curio's Docker image, built for CUDA 12.9, and a node there reaches the GPU when the host hands one to the container ([The GPU](../DEPLOYMENT.md#the-gpu)). Elsewhere, install `torch` into Curio's Python first.

## Pipeline overview

```mermaid
flowchart LR
  L[`Data Loading`<br/>145,880 labels] --> K[`Python Computation`<br/>k-means on the GPU]
  K --> N[`Python Computation`<br/>labels by cluster and type]
  N --> C[`Vega-Lite`<br/>each cluster's label types]
  K --> Q[`Python Computation`<br/>squares of a kilometre]
  Q --> M[`Autark`<br/>the clusters on a map]
```

## Load the labels

```python
labels = curio_load_data("data.projectsidewalk.chicago-labels")

return labels[["label_type", "severity", "neighborhood", "geometry"]]
```

## Cluster on the GPU

k-means puts each label in the cluster whose centre is nearest, then moves each centre to the mean of its labels, until no label changes cluster. The node does it for all 145,880 labels at once on `device`:

- the labels' places are in metres (Illinois East), around their mean, in float64;
- the first centre is a random label, and each next one a label drawn with odds by its
  squared distance to the nearest centre so far (k-means++);
- each step's distances are one tensor of labels by centres, and the new centres the
  product of the labels' one-hot clusters with their places.

The random draws come from a seeded generator on the CPU, and the clusters are numbered from the largest, so a rerun gives the same clusters.

```python
import os

# Before CUDA starts, so cuBLAS repeats its sums in the same order on every run.
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

import numpy as np
import torch

# The same numbers on every run: seeded, deterministic kernels only, and full
# float32 precision (no TF32), so every GPU rounds them alike.
torch.manual_seed(30)
torch.use_deterministic_algorithms(True)
torch.backends.fp32_precision = "ieee"
torch.backends.cudnn.benchmark = False
device = "cuda" if torch.cuda.is_available() else "cpu"

K = 8

# Each label's place in metres (Illinois East), around the labels' mean, in
# float64, so every device puts each label in the same cluster.
metres = input_0.geometry.to_crs(26971)
xy = np.column_stack([metres.x, metres.y])
points = torch.from_numpy(xy - xy.mean(axis=0)).to(device)


def squared_distances(centres):
    """Every label's squared distance to every centre, labels by centres."""
    return (points[:, None, :] - centres[None, :, :]).square().sum(dim=2)


# k-means++ starts: each next centre a label drawn with odds by its squared
# distance to the nearest centre so far, by a generator on the CPU, so every
# device draws the same ones.
draws = torch.Generator().manual_seed(30)
centres = points[torch.randint(len(points), (1,), generator=draws).to(device)]
for _ in range(K - 1):
    nearest = squared_distances(centres).min(dim=1).values
    pick = torch.multinomial((nearest / nearest.sum()).cpu(), 1, generator=draws)
    centres = torch.cat([centres, points[pick.to(device)]])

# Lloyd's steps until no label changes cluster: each centre moves to the mean
# of its labels, a product with the labels' one-hot clusters.
assigned = None
for step in range(1, 101):
    closest = squared_distances(centres).argmin(dim=1)
    if assigned is not None and torch.equal(closest, assigned):
        break
    assigned = closest
    members = torch.nn.functional.one_hot(assigned, K).to(points.dtype)
    centres = (members.T @ points) / members.sum(dim=0).clamp(min=1)[:, None]
print(f"Ran on {device}: {K} clusters, settled after {step} steps.")

# Clusters numbered from the largest, 1 to K.
sizes = torch.nn.functional.one_hot(assigned, K).sum(dim=0).cpu()
rank = torch.empty(K, dtype=torch.long)
rank[torch.argsort(sizes, descending=True, stable=True)] = torch.arange(K)

clustered = input_0.copy()
clustered["cluster"] = (rank[assigned.cpu()] + 1).numpy()
clustered["device"] = device
return clustered
```

## Count and gather

One node counts each cluster's labels by type, for the chart:

```python
# How many labels of each type each cluster holds.
counts = input_0.groupby(["cluster", "label_type"]).size()

return counts.reset_index(name="labels")
```

The labels span about 80 by 100 kilometres, so on a map of them all a label's own point would be smaller than a pixel. Another node gathers them into squares of a kilometre, each in the cluster most of its labels are in, with how many labels it holds:

```python
# The labels gathered into squares of a kilometre, each in the cluster most of
# its labels are in: on a map of the whole region a square shows, where a
# label's own point would be too small to see.
import geopandas as gpd
import pandas as pd
from shapely.geometry import box

SIDE = 1000  # metres

metres = input_0.geometry.to_crs(26971)
labels = pd.DataFrame({
    "column": (metres.x // SIDE).astype(int),
    "row": (metres.y // SIDE).astype(int),
    "cluster": input_0["cluster"].to_numpy(),
})
counts = labels.groupby(["column", "row", "cluster"]).size().reset_index(name="labels")
totals = counts.groupby(["column", "row"])["labels"].sum().rename("labels_in_square")
# Each square's cluster with the most labels, the smaller number on a tie.
squares = counts.sort_values(["labels", "cluster"], ascending=[False, True], kind="stable")
squares = squares.drop_duplicates(["column", "row"]).join(totals, on=["column", "row"])
# By cluster: the map's legend lists the clusters in the order it meets them.
squares = squares.sort_values(["cluster", "row", "column"], kind="stable")

return gpd.GeoDataFrame(
    {"cluster": squares["cluster"].to_numpy(), "labels": squares["labels_in_square"].to_numpy()},
    geometry=[box(c * SIDE, r * SIDE, (c + 1) * SIDE, (r + 1) * SIDE)
              for c, r in zip(squares["column"], squares["row"])],
    crs=26971,
).to_crs(4326)
```

## The views

The Autark map draws the squares in their cluster's color, with no outlines:

```json
{
  "map": {
    "layerRefs": [
      {
        "dataRef": "[!! input_0 !!]",
        "getFnv": "cluster",
        "getFnvType": "categorical",
        "colorMapInterpolator": "schemeTableau10",
        "stroke": false,
        "title": "Cluster"
      }
    ]
  }
}
```

and the chart stacks each cluster's labels by type:

```json
{
  "mark": "bar",
  "encoding": {
    "x": {
      "field": "cluster",
      "type": "ordinal",
      "title": "Cluster",
      "axis": {
        "labelAngle": 0
      }
    },
    "y": {
      "field": "labels",
      "type": "quantitative",
      "aggregate": "sum",
      "title": "Labels"
    },
    "color": {
      "field": "label_type",
      "type": "nominal",
      "title": "Label type"
    },
    "tooltip": [
      {
        "field": "cluster"
      },
      {
        "field": "label_type"
      },
      {
        "field": "labels"
      }
    ]
  }
}
```
