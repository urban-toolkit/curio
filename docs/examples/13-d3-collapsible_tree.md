# Collapsible Tree
# Example: Visual analytics of hierarchical data

In this example, we will explore how Curio can facilitate visual analytics of hierarchical data by visualizing parent-child relationships between nodes in an interactive collapsible tree. Here is the overview of the entire dataflow pipeline:

Before you begin, please familiarize yourself with Curio's main concepts and functionalities by reading our [usage guide](https://github.com/urban-toolkit/curio/blob/main/docs/USAGE.md).

## Step 1: Load hierarchical data

The icons on the left-hand side can be used to instantiate different nodes, including data loading nodes. Let's start by instantiating a data loading node and changing its view to Code. Then, we load the hierarchical data as a flat edge list with `node`, `parent`, and `value` columns:

```python
import pandas as pd

df = pd.DataFrame([
    {"node": "City",          "parent": None,            "value": None},
    {"node": "North District","parent": "City",           "value": None},
    {"node": "South District","parent": "City",           "value": None},
    {"node": "Downtown",      "parent": "North District", "value": 42000},
    {"node": "Midtown",       "parent": "North District", "value": 31000},
    {"node": "Uptown",        "parent": "South District", "value": 18000},
    {"node": "Eastside",      "parent": "South District", "value": 27000},
    {"node": "Westside",      "parent": "South District", "value": 14000},
    {"node": "Southbank",     "parent": "South District", "value": 22000},
])

return df
```

The DataFrame has three columns: `node` is the name of each tree node, `parent` defines the parent-child relationship (the root node has `None` as its parent), and `value` holds an optional numeric value displayed alongside leaf nodes.

## Step 2: Create a collapsible tree visualization

We connect the loaded data to a D3 visualization node. The D3 code reconstructs a nested hierarchy from the flat edge list, then renders it as an interactive collapsible tree — clicking any node expands or collapses its children.

```javascript
({ d3, container, data }) => {
  const WIDTH = 620;
  const MY = 14, ML = 54, MR = 130;
  const DX = 28;
  const innerW = WIDTH - ML - MR;

  // ── Reconstruct hierarchy from edge-list dataframe ──────────────────────
  const map = {};
  data.forEach(r => { map[r.node] = { name: r.node, value: r.value, children: [] }; });
  let rootData = null;
  data.forEach(r => {
    if (!r.parent || r.parent === "None" || r.parent === "") rootData = map[r.node];
    else if (map[r.parent]) map[r.parent].children.push(map[r.node]);
  });

  function prune(n) {
    if (!n.children.length) delete n.children;
    else n.children.forEach(prune);
  }
  prune(rootData);

  // ── D3 setup ─────────────────────────────────────────────────────────────
  const hier = d3.hierarchy(rootData);
  const treeLayout = d3.tree().nodeSize([DX, innerW / (1 + hier.height)]);
  const diagonal = d3.linkHorizontal().x(d => d.y).y(d => d.x);

  container.innerHTML = "";

  const svg = d3.select(container).append("svg")
    .attr("width", WIDTH)
    .style("font", "12px sans-serif")
    .style("overflow", "visible");

  const g = svg.append("g").attr("transform", `translate(${ML},0)`);
  const gLink = g.append("g")
    .attr("fill", "none").attr("stroke", "#aaa").attr("stroke-width", 1.5);
  const gNode = g.append("g")
    .attr("cursor", "pointer").attr("pointer-events", "all");

  const colorMap = {
    0: { fill: "#B5D4F4", stroke: "#185FA5", text: "#0C447C" },
    1: { fill: "#9FE1CB", stroke: "#0F6E56", text: "#085041" },
    2: { fill: "#D3D1C7", stroke: "#5F5E5A", text: "#444441" },
  };
  function col(depth) { return colorMap[Math.min(depth, 2)]; }

  let seq = 0;
  hier.descendants().forEach(d => {
    d.id = seq++;
    d._children = d.children ? d.children.slice() : null;
    if (d.depth > 0) d.children = null;
  });
  hier.x0 = 0;
  hier.y0 = 0;

  // ── Update ────────────────────────────────────────────────────────────────
  function update(source) {
    treeLayout(hier);

    const nodes = hier.descendants();
    const links = hier.links();

    let minX = Infinity, maxX = -Infinity;
    nodes.forEach(d => { if (d.x < minX) minX = d.x; if (d.x > maxX) maxX = d.x; });
    const treeH = maxX - minX + MY * 2 + DX;
    const oy = -minX + MY + DX / 2;

    svg.transition().duration(280).attr("height", treeH);

    // ── Nodes ────────────────────────────────────────────────────────────
    const node = gNode.selectAll("g.nd").data(nodes, d => d.id);

    const enter = node.enter().append("g").attr("class", "nd")
      .attr("transform", `translate(${source.y0 ?? source.y},${(source.x0 ?? source.x) + oy})`)
      .attr("opacity", 0)
      .on("click", (_, d) => {
        if (d._children) {
          d.children = d.children ? null : d._children.slice();
          update(d);
        }
      });

    enter.append("circle")
      .attr("r", d => d.depth === 0 ? 6 : 4)
      .attr("fill",   d => col(d.depth).fill)
      .attr("stroke", d => col(d.depth).stroke)
      .attr("stroke-width", 1.5);

    enter.append("text")
      .attr("dy", "0.32em")
      .attr("x", d => d.depth === 0 ? -10 : 8)
      .attr("text-anchor", d => d.depth === 0 ? "end" : "start")
      .attr("fill", d => col(d.depth).text)
      .each(function(d) {
        const el = d3.select(this);
        el.append("tspan").attr("font-weight", "500").text(d.data.name);
        if (d.data.value != null) {
          el.append("tspan")
            .attr("font-size", "10px")
            .attr("fill", "#888")
            .text("  " + Number(d.data.value).toLocaleString());
        }
      });

    node.merge(enter).transition().duration(280)
      .attr("transform", d => `translate(${d.y},${d.x + oy})`)
      .attr("opacity", 1);

    node.exit().transition().duration(280)
      .attr("transform", `translate(${source.y},${source.x + oy})`)
      .attr("opacity", 0)
      .remove();

    // ── Links ────────────────────────────────────────────────────────────
    const link = gLink.selectAll("path.lk").data(links, d => d.target.id);

    const linkEnter = link.enter().append("path").attr("class", "lk")
      .attr("d", () => {
        const o = { x: (source.x0 ?? source.x) + oy, y: source.y0 ?? source.y };
        return diagonal({ source: o, target: o });
      });

    link.merge(linkEnter).transition().duration(280)
      .attr("d", d => diagonal({
        source: { x: d.source.x + oy, y: d.source.y },
        target: { x: d.target.x + oy, y: d.target.y },
      }));

    link.exit().transition().duration(280)
      .attr("d", () => {
        const o = { x: source.x + oy, y: source.y };
        return diagonal({ source: o, target: o });
      })
      .remove();

    nodes.forEach(d => { d.x0 = d.x; d.y0 = d.y; });
  }

  update(hier);
}
```

Key design decisions in the visualization:

- **Hierarchy reconstruction** — the flat `node/parent` edge list is rebuilt into a nested tree at runtime, so any tabular source works without pre-nesting
- **Collapsible nodes** — clicking any internal node toggles its children open or closed with a smooth animated transition
- **Depth-based color coding** — root, intermediate, and leaf nodes each use a distinct color scheme
- **Dynamic height** — the SVG height adjusts automatically as branches are expanded or collapsed
- **Value display** — leaf nodes show their numeric value inline alongside the node name

## Final result

This example demonstrates how Curio can be used to visualize hierarchical data from a simple flat table. The collapsible tree layout makes it easy to explore nested structures interactively, expanding only the branches of interest while keeping the overall view uncluttered.
