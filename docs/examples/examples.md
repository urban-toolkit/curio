# 🌇 `Curio Examples` guide!

!!! warning "Have you walked through the Getting Started guide?"
    Make sure to have walked through the [Installation](../getting-started/installation.md) and [Quick Start](../getting-started/quick_start.md) guide 
    before diving into these examples.

The simplest approach to get to know more about how to work with `Curio` is to explore the 
hands-on examples in this documentation. These **step-by-step tutorials** walk you through the framework's 
features, from `visual analytics` and `data integration` to `what-if scenario planning` and `interactive visualizations`. 

Whether you are new to urban data science or an experienced researcher, these examples will help you unlock 
`Curio`'s full potential for collaborative urban visual analytics.


!!! tip "We use real open-source data throughout all of our examples, want to know where to get them?"
    The public datasets used in these examples are available directly through the documentation. Each example 
    includes download links to the required datasets.
    
    - **Access datasets from examples:**
        - Each tutorial includes direct download links to the required data files
        - Data files are provided for immediate use with the examples
        - Simply click the data links in each tutorial to download what you need
     - **Alternative data sources:**
         - Follow the original data source links provided in each tutorial
         - Download datasets directly from their official channels (census data, city open data portals, etc.)
         - Many examples use publicly available urban datasets from sources like OpenStreetMap and government APIs
    
       Ready to start exploring urban data! 🎉

## `Curio` Examples Explained

The examples are organized into four main categories: `Visual Analytics`, `Urban Planning`, 
`Advanced Analytics` and `Interactive Visualizations`. Here's an overview of what each tutorial covers:

Icons indicate the complexity level of each example: 🟢 Easy, 🟡 Intermediate, 🔴 Advanced.


=== "📊 Visual Analytics & Data Integration"

    `Curio` excels at integrating heterogeneous urban datasets and creating compelling visual analytics workflows.
    The `Visual Analytics` section showcases how to combine different data types and create insightful visualizations.

    - 🟢 **[01 - Visual analytics of heterogeneous data](detailed_examples/01-visual-analytics.md)**: Learn how to integrate multiple urban datasets for thermal analysis.
        - *What it does*: Integrates raster thermal data, meteorological readings, and sociodemographic data to compute the Universal Thermal Climate Index (UTCI) and analyze heat vulnerability across Milan neighborhoods.

    - 🟢 **[09 - Building energy efficiency](detailed_examples/09-energy-efficiency.md)**: Discover patterns in urban energy consumption.
        - *What it does*: Compares mean and median energy use intensity across building types to identify outliers and efficiency gaps using interactive visualizations.

    - 🟢 **[10 - Green roofs spatial analysis](detailed_examples/10-green-roofs.md)**: Explore environmental infrastructure distribution.
        - *What it does*: Visualizes the distribution and density of green roofs across Chicago using dot density maps and zip code aggregation techniques.

=== "🏗️ Urban Planning & Scenarios"

    `Curio` provides powerful tools for urban planning and scenario analysis, allowing planners to explore
    what-if scenarios and analyze accessibility patterns across urban environments.

    - 🟡 **[02 - What-if scenario planning](detailed_examples/02-what-if.md)**: Explore the impact of urban development on shadow patterns.
        - *What it does*: Creates interactive dataflows to simulate shadow impact from proposed buildings in Boston, allowing users to modify building heights and compare shadow patterns before and after changes.

    - 🟢 **[04 - Accessibility analysis](detailed_examples/04-accessibility-analysis.md)**: Understand urban accessibility patterns.
        - *What it does*: Analyzes sidewalk accessibility features using severity and agreement metrics to visualize neighborhood patterns and identify improvement areas.

    - 🟢 **[05 - Flooding analysis](detailed_examples/05-flooding-complaints.md)**: Map urban infrastructure complaints.
        - *What it does*: Analyzes 311 flooding complaints to identify patterns in urban infrastructure issues, demonstrating data aggregation and spatial visualization techniques.

=== "🤖 Advanced Analytics & Machine Learning"

    `Curio` supports sophisticated machine learning workflows with human-in-the-loop capabilities,
    enabling experts to train, evaluate, and refine models collaboratively.

    - 🔴 **[03 - Expert-in-the-loop urban accessibility analysis](detailed_examples/03-expert-in-the-loop.md)**: Combine AI with human expertise.
        - *What it does*: Demonstrates machine learning workflows for urban accessibility analysis, including model training, evaluation, and human-in-the-loop validation using computer vision for sidewalk assessment.

=== "🔗 Interactive Visualizations"

    `Curio` creates rich interactive experiences that allow users to explore urban data through
    multiple linked views and coordinated interactions between different visualization components.

    - 🟡 **[06 - Interactions between Vega-Lite and UTK](detailed_examples/06-interaction.md)**: Connect maps and charts seamlessly.
        - *What it does*: Demonstrates how to link user interactions between UTK map components and Vega-Lite plots for coordinated multi-view exploration.

    - 🟡 **[07 - Speed camera violations](detailed_examples/07-speed-camera.md)**: Analyze traffic patterns over time.
        - *What it does*: Performs temporal aggregation and creates linked bar and line charts to analyze top camera violations over years with interactive filtering.

    - 🟡 **[08 - Red-light traffic violation analysis](detailed_examples/08-red-light-violation.md)**: Build comprehensive traffic dashboards.
        - *What it does*: Analyzes Chicago red-light violation data through multiple dataflows, creating seasonal trend analysis, camera effectiveness comparisons, and spatial distribution maps with coordinated interactions.

    - 🟡 **[11 - Building energy consumption](detailed_examples/11-building-energy.md)**: Explore multi-dimensional energy data.
        - *What it does*: Analyzes temporal, spatial, and structural patterns in building energy use with interactive visualizations supporting drill-down and comparison workflows. 


!!! question "Ready to dive deeper?"
    Each example includes step-by-step instructions, code snippets, and downloadable datasets.
    For advanced features and detailed component documentation, explore the User Guide.

    [User Guide :material-book-open:](../user-guide/overview.md){ .md-button }