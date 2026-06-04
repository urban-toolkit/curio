# Data Catalog — UX/UI Exploration & System Design Spec

Using the current application screenshots as the visual and UX baseline, create a comprehensive exploration for a next-generation **Data Catalog** experience inside a node-based computational and visualization platform.

The deliverable must include:
- high-fidelity UI concepts
- interaction design explorations
- visual system extensions
- information architecture
- component documentation
- UX rationale annotations
- graph-aware workflows
- reusable data interaction patterns

The concepts should feel production-ready and aligned with:
- AI-native workflow systems
- graph-native analytics platforms
- computational knowledge environments
- modern data intelligence tooling

---

# CRITICAL DELIVERABLE FORMAT REQUIREMENTS

## Main UI Deliverables Must Be SVG-Based

All primary interface deliverables must be created as:

- editable SVG assets
- vector-native interface layouts
- modular SVG component systems
- scalable resolution-independent compositions

The SVG output should preserve:
- layers
- groups
- naming structure
- reusable components
- visual hierarchy
- editability

The generated visuals must be suitable for:
- direct import into Figma
- continued iteration in Figma
- design system extraction
- production prototyping
- motion design experimentation

---

# Figma Compatibility Requirements

All interface concepts must be structured specifically for seamless editing inside Figma.

Requirements:
- maintain editable vector layers
- separate logical UI regions into grouped structures
- preserve component modularity
- organize layouts with clear naming conventions
- use reusable component patterns
- support Auto Layout reconstruction where possible
- avoid flattened raster exports
- avoid destructive vector merges unless necessary

Deliverables should feel like:

> production-grade Figma-ready design explorations.

---

# IMPORTANT PRODUCT REFERENCE — TABLEAU DATA CONNECTIVITY

The Data Catalog should partially cross-reference and study the strengths of Tableau’s data connectivity and data source UX patterns.

This is NOT a request to copy Tableau visually.

Instead, analyze and reinterpret:
- data connection workflows
- source onboarding patterns
- schema inspection UX
- live vs extract paradigms
- relationship modeling
- metadata surfacing
- connection management
- federated data exploration
- data source discoverability
- transformation previews
- join relationship visualization
- field-level metadata systems
- semantic layer interactions

The final result should evolve beyond Tableau by integrating:
- graph-native workflows
- node-driven computation
- AI-native orchestration
- reusable computational pipelines
- computational transparency

---

# Tableau Connectivity Features To Reference

Study and reinterpret UX patterns such as:

## Connection Discovery
- database browsing
- cloud source onboarding
- API source connections
- local file ingestion
- reusable source credentials
- connection templates
- connector categorization

## Data Source Modeling
- joins
- relationships
- unions
- schema previews
- live connection indicators
- extract/materialization indicators
- query dependency awareness

## Metadata Exploration
- column typing
- field categorization
- semantic metadata
- calculated fields
- source health indicators
- freshness indicators
- usage metadata

## Data Preview Experiences
- inline previews
- adaptive table inspection
- sampled datasets
- schema-aware previews
- geospatial previews
- field statistics

## Data Governance Concepts
- certified datasets
- trusted sources
- ownership metadata
- source reliability indicators

---

# Core Product Vision

The Data Catalog is not just a repository of datasets.

It is the intelligence layer connecting:
- data
- computation
- transformations
- visualizations
- operational insights
- reusable workflows

The experience should communicate a transition:

> from simply viewing data → to understanding, orchestrating, and acting on data intelligently.

The UI should emphasize:
- trusted insights
- actionable intelligence
- interoperability
- reusable transformations
- contextual understanding
- visibility of relationships between data and nodes

The platform should feel:
- computational
- visual
- interconnected
- graph-aware
- modular
- insight-driven

---

# Core Design Goals

## 1. Data Must Be More Important Than Nodes

The current experience over-emphasizes nodes.

The new Data Catalog should:
- elevate datasets as first-class entities
- visually prioritize data assets
- expose relationships between datasets and nodes
- make data flow between nodes obvious

The user should immediately understand:
- what the data is
- which nodes generated it
- which nodes consume it
- which visualizations use it
- how it moves through pipelines

---

# Required UX Capabilities

## Global + Local Context

The Data Catalog must work in:
1. global workspace context
2. individual node context

Examples:
- browsing all workspace datasets
- inspecting datasets generated by a specific node
- understanding relationships between connected nodes
- viewing reusable outputs across pipelines

The experience should seamlessly transition between:
- graph-level understanding
- node-level understanding
- dataset-level understanding

---

# Key Features To Explore

## Data Relationships

Strong emphasis on:
- node/data relationships
- transformations
- relationship chains
- reusable outputs
- graph-aware interactions

Visual ideas:
- graph overlays
- relationship diagrams
- expandable dependency trees
- flow-based visualizations
- interactive relationship maps

Each dataset should clearly show:
- connected nodes
- related visualizations
- transformation stages
- reusable outputs
- downstream usage

---

# Innovative Data Visualization Ideas

Explore novel ways to visualize:
- data relationships
- schema structures
- transformations
- format compatibility
- reuse frequency
- pipeline dependencies
- data quality
- dataset activity

Potential visualization directions:
- graph-native interfaces
- relational constellations
- layered topology views
- dataset heatmaps
- transformation chains
- hybrid node/data overlays
- semantic clustering
- spatial data maps
- temporal activity views

The visual language should feel:
- intelligent
- dynamic
- computational
- exploratory
- scalable

---

# Dataset Interoperability

Show how users can:
- create datasets
- transform datasets
- reuse datasets
- pass datasets between nodes
- connect computation nodes with visualization nodes
- build reusable data pipelines

The UI should communicate:
- compatibility
- accepted formats
- transformability
- downstream usability
- execution readiness

The interoperability layer should also borrow concepts from modern BI tooling:
- reusable connections
- shared semantic models
- reusable transformations
- source abstraction
- portable schemas
- shared calculated fields
- federated querying concepts

---

# Data Type Categorization

Design a rich categorization system for datasets and formats.

Examples:
- GeoJSON
- CSV
- JSON
- Parquet
- SQL tables
- Vector embeddings
- Time-series
- Raster data
- Tabular datasets
- Graph datasets
- ML features
- Image collections

Explore:
- type badges
- semantic icons
- grouped browsing
- filter systems
- visual encoding by type
- schema previews
- adaptive previews

---

# Required Components

Include design concepts and documentation for:

## 1. Catalog Drawer

A contextual side panel for:
- browsing datasets
- quick previews
- schema inspection
- filtering
- search
- pinning datasets
- jumping to related nodes

Should support:
- compact mode
- expanded exploratory mode
- contextual actions

Include Tableau-inspired ideas such as:
- connection status
- live/extract indicators
- source grouping
- recent sources
- trusted source indicators
- quick schema preview

---

## 2. Palette Menu

A creation and insertion system for:
- datasets
- transformations
- reusable templates
- visualizers
- imports
- exports
- schema tools
- data connectors

Should feel:
- fast
- modular
- intelligent
- command-oriented

Include:
- searchable connector registry
- categorized data connectors
- recommended sources
- reusable connection presets
- transformation templates

---

## 3. Data Visualizer

A rich inspection interface for datasets.

Must support:
- schema visualization
- table preview
- geospatial preview
- graph preview
- statistics
- metadata
- quality indicators

Explore:
- split views
- multi-panel inspection
- contextual overlays
- adaptive visualization modes
- embedded microvisualizations

Reference Tableau-style workflows for:
- field inspection
- schema browsing
- preview generation
- data profiling
- calculated fields
- field-level metadata

---

## 4. Data Type Categorizer

A system for organizing and discovering datasets by:
- format
- structure
- semantic meaning
- compatibility
- usage frequency
- source
- pipeline context

Should support:
- connector-aware categorization
- source-type grouping
- semantic data domains
- governed datasets
- certified assets
- reusable semantic models

---

# Visual Identity Requirements

The Data Catalog must inherit the visual identity of the existing Node Catalog.

Replicate and extend:
- visual language
- spacing patterns
- interaction patterns
- motion behavior
- card styles
- hover behavior
- panel structure
- hierarchy system
- typography rhythm
- color semantics
- graph aesthetics

The result should feel like:

> a natural evolution of the current product ecosystem.

Not a disconnected module.

Do NOT visually mimic Tableau branding or styling directly.

Instead:
- reinterpret interaction paradigms
- modernize enterprise BI concepts
- merge BI workflows with graph-native UX
- evolve traditional analytics tooling into computational intelligence systems

---

# Interaction Design Expectations

Document:
- hover states
- transitions
- drag/drop interactions
- contextual menus
- expandable relationship flows
- cross-navigation behaviors
- filtering mechanics
- keyboard workflows
- multi-select interactions
- dataset pinning/saving
- node-to-data navigation

Include interaction concepts for:
- live connection management
- source switching
- schema refresh
- connector health monitoring
- field-level exploration

---

# Information Architecture Expectations

Include:
- navigation hierarchy
- dataset relationship structures
- graph/data interaction models
- contextual navigation flows
- reusable dataset lifecycle models

Provide:
- architecture diagrams
- relationship maps
- hierarchy explorations
- modular interaction systems

All diagrams should also be SVG-based and editable in Figma.

---

# Deliverables

Provide:

1. Multiple SVG-based interface explorations
2. Annotated SVG UI concepts
3. SVG component sheets
4. SVG interaction flow diagrams
5. SVG information architecture maps
6. Visual system extension documentation
7. Responsive/adaptive layout ideas
8. Scalability recommendations
9. Future extensibility concepts
10. Figma-ready editable vector structures
11. Reusable design system patterns
12. Tableau-inspired connectivity workflow reinterpretations
13. Data onboarding UX concepts
14. Connection and schema management explorations

---

# Quality Bar

The final result should feel comparable to:
- next-generation data intelligence platforms
- graph-native analytics systems
- AI-native workflow environments
- computational orchestration platforms
- modern observability tooling

The focus is:
- data visibility
- interoperability
- intelligence
- actionable insights
- computational transparency
- graph-aware UX
- editable vector-native design systems