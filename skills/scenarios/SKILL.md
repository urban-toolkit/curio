---
name: scenarios
description: >-
  Use this skill when a dataflow compares alternatives as scenarios, or when a task makes, reads
  or compares one. It says what a scenario's boundary, levers, fixed context and outcomes are, how
  a copy pairs with the scenario it comes from, how a chart stacks each scenario's outcome and
  colors it with the scenario chips, and how a scenario dragged in from another project names
  where it came from.
license: MIT
compatibility: Written for Curio's agents, their tools and node code.
metadata:
  author: curio
  version: "1.0.0"
---
## Scenarios

A scenario is a named selection of a dataflow's nodes, in "dataflow"."scenarios", used to compare alternatives: the same analysis with buildings twice as tall, say. Its boundary splits the dataflow into three parts. Its fixed context is the nodes outside it that it reads, through an edge into it. Its levers are its own nodes: what an alternative changes, such as a widget value, a line of code or a spec. Its outcomes are the outputs of its last nodes: what gets compared. A node belongs to one scenario at most, so a node two alternatives share sits outside both, as their common context. An alternative is usually a copy of another scenario's nodes that reads the same context, with a lever changed; each copy names the nodes it descends from in "metadata"."copiedFrom", which is how the levers of two scenarios pair.

To compare scenarios, connect each scenario's outcome to an input circle of its own, on a node outside the boxes. A {{template.label:curio.builtin/vis-vega}} node whose spec reads its inputs stacked charts them: "data": {"name": "{{inputs.stacked}}"} is every input's rows stacked, each row with "scenario" and "scenario_name" from the scenario box its input comes from, and a column of those rows is named by its chip, as "field": {{inputs.stacked_column:scenario_name}}. A chart or a map draws exactly its spec, and its scenario chips write the boxes' colors and order, from the boxes its inputs come from: "scale": {{scenarios.chip:colors}} on a color, fill or stroke on "scenario_name" (on a text mark, "scale": {{scenarios.chip:text_colors}}, the same colors in shades that read on white), and "sort": {{scenarios.chip:order}} on an axis, an offset or a facet on it, for example "color": {"field": "scenario_name", "type": "nominal", "scale": {{scenarios.chip:colors}}} and "x": {"field": "scenario_name", "type": "nominal", "sort": {{scenarios.chip:order}}}. Each input whose node is in no box comes last, in a grey of its own, and when no input comes from a box the colors chips write the names alone, so the grammar's own palette colors them. In a map's layer, or a chart's mark, "{{scenarios.chip:input.1}}" inside quotes is the color of the box input_1 comes from: "color": "{{scenarios.chip:input.1}}". A spec without the chips draws in Vega-Lite's or Autark's own colors, and the chips are for a spec, not for Python or JavaScript code. A {{template.label:curio.builtin/computation-analysis}} node takes the difference of two tables or layers, joining their rows on a column both have, such as osm_id or building_id.

A scenario the user dragged in from another project, through the Scenario Catalog, keeps where it came from: dataflow.read names its source, that project and that scenario by their names, or says that the project, or that scenario in it, is gone.
