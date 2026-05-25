<div align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/logo.png?raw=true" alt="Curio Logo" height="180"/>

  <h1>Curio</h1>

  <p><strong>A dataflow-based framework for collaborative urban visual analytics.</strong></p>

  <p>
    <a href="https://arxiv.org/abs/2408.06139">Paper</a> ·
    <a href="https://urbantk.org/curio">Website</a>
  </p>

  <p>
    <a href="docs/README.md"><img alt="Documentation" src="https://img.shields.io/badge/Documentation-0366d6?style=for-the-badge&logo=readthedocs&logoColor=white"/></a>
    <a href="docs/USAGE.md"><img alt="Usage" src="https://img.shields.io/badge/Installation-f59e0b?style=for-the-badge&logo=lightning&logoColor=white"/></a>
    <a href="https://discord.gg/ajT6wF8TmN"><img alt="Discord" src="https://img.shields.io/badge/Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white"/></a>
  </p>

  <p>
    <a href="https://pypi.org/project/utk-curio/"><img alt="PyPI" src="https://img.shields.io/pypi/v/utk-curio?style=for-the-badge&label=PyPI&color=0073b7&prefix=v"/></a>
    <a href="https://github.com/urban-toolkit/curio"><img alt="GitHub" src="https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Furban-toolkit%2Fcurio%2Fmain%2Futk_curio%2F__init__.py&search=__version__%5Cs*%3D%5Cs*%22(.%2B%3F)%22&replace=v%241&style=for-the-badge&label=GitHub&color=24292e"/></a>
    <a href="https://curio.urbantk.org"><img alt="curio.urbantk.org" src="https://img.shields.io/badge/dynamic/json?style=for-the-badge&url=https%3A%2F%2Fcurio.urbantk.org%2Fapi%2Fversion&query=%24.version&label=curio.urbantk.org&color=2ea44f&cacheSeconds=300&prefix=v"/></a>
    <a href="https://curio-dev.urbantk.org"><img alt="curio-dev.urbantk.org" src="https://img.shields.io/badge/dynamic/json?style=for-the-badge&url=https%3A%2F%2Fcurio-dev.urbantk.org%2Fapi%2Fversion&query=%24.version&label=curio-dev.urbantk.org&color=8957e5&cacheSeconds=300&prefix=v"/></a>
  </p>

  <p>
    <a href="https://github.com/urban-toolkit/curio/actions/workflows/docker-compose.yml"><img alt="Full stack build" src="https://github.com/urban-toolkit/curio/actions/workflows/docker-compose.yml/badge.svg"/></a>
    <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white"/></a>
    <a href="https://nodejs.org/"><img alt="Node.js" src="https://img.shields.io/badge/Node.js-24-339933?logo=nodedotjs&logoColor=white"/></a>
    <a href="https://github.com/urban-toolkit/curio/graphs/contributors"><img alt="Contributors" src="https://img.shields.io/github/contributors/urban-toolkit/curio"/></a>
    <a href="https://github.com/urban-toolkit/curio/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg"/></a>
  </p>
</div>

> 🌐 **Hosted instances** — Try Curio in your browser without installing anything. Stable at [**curio.urbantk.org**](https://curio.urbantk.org), and the latest `main` build at [**curio-dev.urbantk.org**](https://curio-dev.urbantk.org). Sign in with Google to save dataflows; guests can browse shared examples read-only. To run your own server, see the [deployment guide](docs/DEPLOYMENT.md). For local deployment, see [installation and usage guide](docs/USAGE.md). Local installs require **Python 3.12**.

Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels (code, grammar, GUI elements) to facilitate collaboration across the design and implementation of visual analytics components. The framework allows experts to intertwine preprocessing, managing, and visualization stages while tracking provenance of code and visualizations.

## Key features

<table align="center">
  <tr>
    <td align="center" width="33%">
      <strong>Provenance-aware dataflow</strong><br/>
      <sub>Track transformation and visualization steps</sub>
    </td>
    <td align="center" width="33%">
      <strong>Linked interactions</strong><br/>
      <sub>Data-driven cross-view filtering and brushing</sub>
    </td>
    <td align="center" width="33%">
      <strong>Autark + Vega-Lite</strong><br/>
      <sub>First-class 2D and 3D maps via Autark, plus Vega-Lite charts</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="33%">
      <strong>LLM integration via Urbanite</strong><br/>
      <sub>Natural-language assistance for dataflow authoring</sub>
    </td>
    <td align="center" width="33%">
      <strong>Jupyter Notebook import</strong><br/>
      <sub>Bring existing notebooks into Curio dataflows</sub>
    </td>
    <td align="center" width="33%">
      <strong>Scenario-oriented analyses</strong><br/>
      <sub>Multi-user what-if exploration with branching dataflows</sub>
    </td>
  </tr>
  <tr>
    <td align="center" width="33%">
      <strong>One-click Node Catalog</strong><br/>
      <sub>Install packaged nodes from a catalog, or author your own from the canvas</sub>
    </td>
    <td align="center" width="33%">
      <strong>Composable node packages</strong><br/>
      <sub>Mix built-ins, community packages, and your own in a single dataflow</sub>
    </td>
    <td align="center" width="33%">
      <strong>Reproducible & shareable</strong><br/>
      <sub>Versioned, forkable <code>.curio.zip</code> archives pin a workflow's exact node set</sub>
    </td>
  </tr>
</table>

<p align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/docs/images/banner.jpg?raw=true" alt="Curio Use Cases" width="1000"/>
</p>

## 🆕 What's new

A lot has landed since v0.5. Highlights:

- 🌐 **Hosted instances** — Public deployments at [curio.urbantk.org](https://curio.urbantk.org) (stable) and [curio-dev.urbantk.org](https://curio-dev.urbantk.org) (dev), plus a [deployment guide](docs/DEPLOYMENT.md) for self-hosting behind HTTPS.
- 📦 **Node Catalog** — Every node now lives in a manifest-driven package, and you can freely mix built-ins, community packages, and your own in a single dataflow. Install ready-made packages from the catalog with one click, save a canvas node directly into a (new or existing) package via **Save as pack node**, import `.curio.zip` archives shared by collaborators, or fork an existing package to extend it. Per-package metadata (description, license, README, permissions) is editable from the catalog drawer; Python / JS dependencies are detected automatically from each template's source. Packages are **versioned and pinnable**, so a workflow can declare the exact node set it depends on — reproducibility for shared research artefacts. See the [Node Catalog guide](docs/CATALOG.md).
- 🤖 **Per-user LLM configuration** — Connect Curio to OpenAI, Anthropic, Gemini, or a custom endpoint, configurable per user.
- 🗺️ **Autark integration** — New `AutkMap` and `AutkPlot` node types, with JS Computation I/O routed through Python DuckDB.
- ⚡ **JavaScript Computation node** — Run Node.js code in a sandbox subprocess alongside Python nodes.
- 🧬 **Provenance refactor** — Provenance is now tracked in the dataflow JSON itself, with the visualization rebuilt on React Flow (no separate provenance DB).
- 📓 **Jupyter ↔ dataflow conversion** — Initial bidirectional notebook conversion support.
- 💾 **Auto-save** — With unsaved-changes guard and a save status icon.
- ▶️ **Play All & auto-play ancestors** — Execute nodes in topological order, or automatically run upstream nodes when a downstream play button is clicked.
- 👥 **Session-level multi-user isolation** — Across backend, sandbox, and frontend.
- 📊 **Dashboard mode toggle** — Switches mode while preserving node state, edges, and positions.
- 🦆 **DuckDB-native artifact I/O** — Faster, type-safe data exchange between sandbox and backend.
- 🖼️ **Project thumbnails** in the project list, plus the `--with-examples` flag to seed example projects on startup, and toast notifications replacing browser alerts.

See the full [release notes](https://github.com/urban-toolkit/curio/releases) for more. To get started, follow the [usage guide](docs/USAGE.md) or jump into the [quick start tutorial](docs/QUICK-START.md). If you'd like to contribute, read the [contribution guide](docs/CONTRIBUTING.md).

---

## Overview

**Curio: A Dataflow-Based Framework for Collaborative Urban Visual Analytics**  
*Gustavo Moreira, Maryam Hosseini, Carolina Veiga, Lucas Alexandre, Nico Colaninno, Daniel de Oliveira, Nivan Ferreira, Marcos Lage, Fabio Miranda*  
IEEE Transactions on Visualization and Computer Graphics (Volume: 31, Issue: 1, January 2025)  
Paper: [[DOI](https://doi.org/10.1109/TVCG.2024.3456353)], [[Arxiv](https://arxiv.org/abs/2408.06139)]

This project is part of the [Urban Toolkit ecosystem](https://urbantk.org), which includes [Autark](https://github.com/urban-toolkit/autark/). Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels to facilitate collaboration across the design and implementation of visual analytics components. Autark is a flexible and extensible visualization framework that enables the easy authoring of web-based urban visualizations.

## Usage and contributions

For detailed instructions on how to use the project, please see the [usage](docs/USAGE.md) document. To install, fork, or publish node packages, see the [node catalog guide](docs/CATALOG.md). A set of examples can be found [here](https://github.com/urban-toolkit/curio/tree/main/docs).

🐳 Curio supports a Docker-based setup for easier installation and orchestration of all components. See the [usage guide](docs/USAGE.md) for instructions on running Curio with Docker.

🌐 To host a multi-user instance on your own server with HTTPS, see the [deployment guide](docs/DEPLOYMENT.md).

If you'd like to contribute, see the [contributions](docs/CONTRIBUTING.md) and [architecture](docs/ARCHITECTURE.md) documents for guidelines.

---

## Citation

```
@ARTICLE{moreira2025curio,
  author={Moreira, Gustavo and Hosseini, Maryam and Veiga, Carolina and Alexandre, Lucas and Colaninno, Nicola and de Oliveira, Daniel and Ferreira, Nivan and Lage, Marcos and Miranda, Fabio},
  journal={IEEE Transactions on Visualization and Computer Graphics},
  title={Curio: A Dataflow-Based Framework for Collaborative Urban Visual Analytics},
  year={2025},
  volume={31},
  number={1},
  pages={1224-1234},
  doi={10.1109/TVCG.2024.3456353}
}
```

## License

Curio is MIT Licensed. Free for both commercial and research use.

## Acknowledgements

Curio and the Urban Toolkit have been supported by the National Science Foundation (NSF) (Awards [#2320261](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2320261), [#2330565](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2330565), and [#2411223](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2411223)), Discovery Partners Institute (DPI), and IDOT.
