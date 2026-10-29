---
name: street-trees
description: "Use this skill when: a dataflow counts or maps the city's street trees"
metadata:
  author: parks-team
---
## Street trees

A city's street tree census lists its street trees, one row a tree: where the tree stands, its species, the size of its trunk and how it is doing. This skill tells you how to count those trees and map them in a dataflow.

### Read the census before you write code

- Find the node that loads the census, and read the census's columns before you name one: each city names them its own way.
- Look for an id for each tree; its species, often as a common name and a Latin name; its trunk's diameter at breast height, in inches or in centimeters, as the census's notes say; its status, such as alive, dead or a stump, and its health; and where it stands, as a latitude and a longitude, an address, a block or a neighborhood.
- When no node loads a census, find the city's census in the Data Catalog. Never make up trees or a census.

### Count the trees

- Count the living trees only, unless the user asks for stumps or dead trees too: a census lists them all.
- Count by the area the user names. When the census has a column for that area, such as a block or a neighborhood, group by it. When it has only coordinates, join the trees to the areas' polygons with a Spatial Join node first.
- Group trees by their species' Latin names, since common names differ from one census to another. Before you group by species, read [species.md](references/species.md), which lists species common on city streets with the common names a census may give each. Show a census's own names in what you make.
- Give each count with what it counts, such as "1,204 living trees on 38 blocks", never as a bare number.

### Map the trees

- Draw each tree as a point at its latitude and longitude, colored by species: the ten most common species, and the rest as Other.
- Size each point by its trunk's diameter when the user asks how big the trees are.
- A city's census can hold hundreds of thousands of trees. Draw that many on an Autark map, or count them by area and color the areas instead.
