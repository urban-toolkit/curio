# Keyword types

The types a keyword in a dataflow's description can take, as Curio ships them: the default of the
Agent Catalog's Keyword types setting, which a run that reads the setting gets unless the user
changed it.

```json
[
  {"name": "Action", "description": "can usually be mapped to a specific node or part of the dataflow. Are commonly denoted by verbs.", "examples": ["Load", "Visualize", "Filter", "Clean"]},
  {"name": "Dataset", "description": "semantic references to datasets. Can be a single word or a set of words that describe the dataset.", "examples": ["311 requests", "Sidewalk", "Crime", "Temperature"]},
  {"name": "Where", "description": "a geographical location of interest.", "examples": ["New York City", "Brazil", "Illinois", "Chicago"]},
  {"name": "When", "description": "related to time.", "examples": ["over time", "on 1999", "12/06/2000", "between June and September"]},
  {"name": "About", "description": "related to the organization of the workflow.", "examples": ["two scenarios", "the second part of the dataflow", "the first half of the dataflow"]},
  {"name": "Interaction", "description": "denote interactions between nodes, with a node or with the data.", "examples": ["brushing", "click", "higlight", "widgets"]},
  {"name": "Source", "description": "source of the dataset.", "examples": ["API", "local file", "simulation"]},
  {"name": "Connection", "description": "describe how nodes or parts of the workflow are connected to each other. They can be explicit references to connection or implicit.", "examples": ["then", "after that", "second step", "connected"]},
  {"name": "Content", "description": "references to the content of a node or part of the workflow. They can make references to a column of a dataset, machine learning models, type of visualization and so on.", "examples": ["column", "model"]},
  {"name": "Metadata", "description": "information about the data like its format, number of columns, type.", "examples": ["2D", "3D", "JSON", "CSV"]},
  {"name": "None", "description": "all keywords that are not of any other type."}
]
```
