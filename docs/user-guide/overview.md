# 🌇 Welcome to the `Curio` User Guide!

In this guide, we will walk you through (1) the overall architecture of `Curio`, (2) `Curio` components and (3) framework
modules and capabilities. Note that this guide does not cover all the features and capabilities of `Curio`, but it provides a good overview of what you can do with it.

This guide demonstrates hands-on how to use `Curio` for collaborative urban visual analytics using dataflow-based workflows.

## 🏙️ Architecture: Collaborative Visual Analytics

`Curio` uses a **dataflow model** with multiple abstraction levels 
to facilitate collaboration across the design and implementation of visual analytics components. Think of it as a collaborative 
workspace where urban experts, data scientists, and analysts can work together seamlessly.

### 🔄 Dataflow Model: The Core Approach

`Curio` organizes urban analysis into connected dataflow pipelines where:

- **Multiple abstraction levels** allow different users to contribute at their comfort level—from code to GUI interactions.
- **Visual dataflow graphs** make complex analysis pipelines transparent and collaborative.
- **Provenance tracking** keeps track of how data flows through transformations and visualizations.
- **Real-time collaboration** enables teams to work together on the same analysis workflows.

### 🛠️ Components: The Building Blocks

- **Data Loading Node**: Import and prepare your urban datasets from various sources.
- **Analysis & Modeling Nodes**: Transform, compute, and analyze your data using custom code or pre-built functions.
- **Data Cleaning Node**: Filter, clean, and prepare data for analysis.
- **Visualization Nodes**: Create interactive maps, charts, and plots using Vega-Lite, UTK, and other tools.
- **Data Pool Node**: Store and manage intermediate results for reuse across the workflow.
- **Merge Node**: Combine multiple data streams and coordinate complex workflows.

### 🎯 Core System Components: The Technical Foundation

- **Backend**: Manages database access, user authentication, and system coordination
- **Sandbox**: Provides secure execution environment for user Python code and data processing
- **Frontend**: The user interface system with two main components:
  - **Urban Workflows**: Main Curio interface for creating and editing dataflow pipelines
  - **UTK Workflow**: Embedded urban visualization toolkit for spatial analysis and mapping

### 🔗 Integration Capabilities

`Curio` connects with external tools and services to extend its analytical power:

- **Interactive Visualizations**: Rich, coordinated interactions between maps and charts
- **UTK Integration**: Advanced urban visualization and spatial analysis capabilities  
- **Vega-Lite Support**: Grammar-based statistical visualizations with interaction support
- **External Data Sources**: Connect to APIs, databases, and online urban data repositories
- **Collaborative Features**: Real-time shared workspaces and provenance tracking

!!! tip "Dataflow vs. Traditional Analysis: What's the Difference?"
      - **Traditional Analysis** typically follows a linear, script-based approach where each step builds on the previous one, making collaboration and iteration challenging.
      - **Curio's Dataflow Model** breaks analysis into connected, reusable nodes that can be developed independently, tested in isolation, and combined in flexible ways. This makes it easier for teams to collaborate, experiment with different approaches, and maintain complex analytical workflows.

!!! important "Learning Through Examples"
    This user guide focuses on `Curio`'s core concepts and modules. To see these capabilities in action
    with real urban data and collaborative workflows, explore our comprehensive examples section.

    [Quick Start Tutorial :material-rocket-launch:](../getting-started/quick_start.md){ .md-button } [View Examples :fontawesome-solid-compass:](../examples/examples.md){ .md-button }

## 🚀 Ready to Explore Each Component?

Dive into these sections to understand `Curio`'s technical architecture and capabilities:

- **[Backend](modules/backend.md)**: Database management, user authentication, and system coordination
- **[Sandbox](modules/sandbox.md)**: Secure Python code execution and data processing environment
- **[Urban Workflows](modules/urban-workflows.md)**: Main interface for dataflow creation and collaboration
- **[UTK Workflow](modules/utk-workflow.md)**: Embedded urban visualization and spatial analysis toolkit

!!! note "Coming Soon"
    This user guide is actively being developed. More detailed content for each module will be added soon.
    In the meantime, explore our examples section for hands-on tutorials and real-world use cases.

!!! info "Want to Contribute?"
    Help us improve Curio! Check out our [Contributing Guide](../CONTRIBUTING.md) to learn how to report issues, suggest features, or contribute code to the project.

    [Contributing Guide :material-hand-heart:](../CONTRIBUTING.md){ .md-button }

