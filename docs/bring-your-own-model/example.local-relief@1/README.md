# Local Relief (example)

The node package of the worked example in [BRINGING-MODELS.md](../../BRINGING-MODELS.md).
Its one node, **Local Relief**, runs the Model Catalog's
`model.example.local-relief@1` on a raster of building heights and returns,
for each cell, how many metres it stands above the cells around it.

- `sources/local-relief.py`: the node's code. It loads the model and calls the module.
- `sources/local_relief/run.py`: prepares the model's input, runs it, writes the result.

Install it by copying this folder into `packages/` and the model folder,
`../model.example.local-relief@1/`, into `models/`, then restart Curio and add
the package from the Node Catalog. The guide has every step.
