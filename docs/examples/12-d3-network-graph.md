# Network Graph
# Example: Visual analytics of connected data

In this example, we will explore how Curio can facilitate visual analytics of network/graph data by visualizing relationships and connection strengths between nodes. Here is the overview of the entire dataflow pipeline:

Before you begin, please familiarize yourself with Curio's main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

## Step 1: Load edge list data

The icons on the left-hand side can be used to instantiate different nodes, including data loading nodes. Let's start by instantiating a data loading node and changing its view to Code. Then, we load the network edge list data:

```python
import pandas as pd

df = pd.DataFrame([
    {"source": "Downtown",  "target": "Midtown",   "weight": 9},
    {"source": "Downtown",  "target": "Eastside",  "weight": 6},
    {"source": "Downtown",  "target": "Southbank", "weight": 8},
    {"source": "Midtown",   "target": "Uptown",    "weight": 5},
    {"source": "Midtown",   "target": "Westside",  "weight": 4},
    {"source": "Uptown",    "target": "Westside",  "weight": 7},
    {"source": "Uptown",    "target": "Eastside",  "weight": 3},
    {"source": "Eastside",  "target": "Southbank", "weight": 6},
    {"source": "Westside",  "target": "Southbank", "weight": 2},
    {"source": "Midtown",   "target": "Southbank", "weight": 5},
])

return df
```

The DataFrame has three columns: `source` and `target` define the directed edges between nodes, and `weight` represents the strength of each connection.

## Step 2: Create a network graph visualization

We connect the loaded data to a D3 visualization node. The D3 code derives nodes automatically from the edge list, sizes them by degree (number of connections), and uses a force-directed layout where stronger weights pull nodes closer together.

```javascript
({ d3, container, data }) => {
  const width  = 560;
  const height = 420;

  container.innerHTML = "";

  // ── Derive nodes from edge list ─────────────────────────────────────────
  const nodeSet = new Set();
  data.forEach(d => { nodeSet.add(d.source); nodeSet.add(d.target); });
  const nodes = Array.from(nodeSet).map(id => ({ id }));

  const links = data.map(d => ({
    source: d.source,
    target: d.target,
    weight: +d.weight,
  }));

  // ── Degree map — used to size nodes by connectivity ────────────────────
  const degree = {};
  nodes.forEach(n => { degree[n.id] = 0; });
  links.forEach(l => { degree[l.source]++; degree[l.target]++; });

  const rScale = d3.scaleSqrt()
    .domain([0, d3.max(Object.values(degree))])
    .range([8, 22]);

  const wScale = d3.scaleLinear()
    .domain([0, d3.max(links, l => l.weight)])
    .range([1, 6]);

  const colorScale = d3.scaleOrdinal(d3.schemeTableau10)
    .domain(nodes.map(n => n.id));

  // ── SVG ────────────────────────────────────────────────────────────────
  const svg = d3.select(container).append("svg")
    .attr("width", width).attr("height", height)
    .style("overflow", "visible");

  // Arrow marker
  svg.append("defs").append("marker")
    .attr("id", "arrow")
    .attr("viewBox", "0 -5 10 10")
    .attr("refX", 22).attr("refY", 0)
    .attr("markerWidth", 6).attr("markerHeight", 6)
    .attr("orient", "auto")
    .append("path")
    .attr("d", "M0,-5L10,0L0,5")
    .attr("fill", "#aaa");

  const gLink = svg.append("g");
  const gNode = svg.append("g");
  const gLabel = svg.append("g");

  // ── Force simulation ───────────────────────────────────────────────────
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links)
      .id(d => d.id)
      .distance(d => 120 - d.weight * 6)   // stronger links pull nodes closer
      .strength(0.8))
    .force("charge", d3.forceManyBody().strength(-280))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(d => rScale(degree[d.id]) + 6));

  // ── Links ──────────────────────────────────────────────────────────────
  const link = gLink.selectAll("line").data(links).enter().append("line")
    .attr("stroke", "#ccc")
    .attr("stroke-width", d => wScale(d.weight))
    .attr("stroke-opacity", 0.7)
    .attr("marker-end", "url(#arrow)");

  // Weight label on each edge
  const linkLabel = gLink.selectAll("text.wt").data(links).enter().append("text")
    .attr("class", "wt")
    .attr("text-anchor", "middle")
    .attr("font-size", 9)
    .attr("fill", "#999")
    .text(d => d.weight);

  // ── Nodes ──────────────────────────────────────────────────────────────
  const node = gNode.selectAll("circle").data(nodes).enter().append("circle")
    .attr("r", d => rScale(degree[d.id]))
    .attr("fill", d => colorScale(d.id))
    .attr("stroke", "#fff")
    .attr("stroke-width", 2)
    .attr("fill-opacity", 0.85)
    .call(
      d3.drag()
        .on("start", (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) sim.alphaTarget(0);
          d.fx = null; d.fy = null;
        })
    );

  // ── Node labels ────────────────────────────────────────────────────────
  const label = gLabel.selectAll("text.nl").data(nodes).enter().append("text")
    .attr("class", "nl")
    .attr("text-anchor", "middle")
    .attr("dy", "0.35em")
    .attr("font-size", 10)
    .attr("font-weight", "500")
    .attr("fill", "#333")
    .attr("pointer-events", "none")
    .text(d => d.id);

  // ── Tick ───────────────────────────────────────────────────────────────
  sim.on("tick", () => {
    link
      .attr("x1", d => d.source.x)
      .attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x)
      .attr("y2", d => d.target.y);

    linkLabel
      .attr("x", d => (d.source.x + d.target.x) / 2)
      .attr("y", d => (d.source.y + d.target.y) / 2);

    node
      .attr("cx", d => d.x = Math.max(24, Math.min(width  - 24, d.x)))
      .attr("cy", d => d.y = Math.max(24, Math.min(height - 24, d.y)));

    label
      .attr("x", d => d.x)
      .attr("y", d => d.y);
  });
}
```

Key design decisions in the visualization:

- **Node size** scales with degree — nodes with more connections appear larger
- **Edge thickness** scales with weight — stronger connections are drawn thicker
- **Edge distance** is inversely proportional to weight — stronger connections pull nodes closer
- **Arrows** indicate directionality of each edge
- **Drag interaction** allows nodes to be repositioned manually

## Final result

This example demonstrates how Curio can be used to visualize network data from a simple edge list. The force-directed layout automatically organizes nodes based on their connection strengths, making it easy to identify highly connected hubs and clusters within the network.
