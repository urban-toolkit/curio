# Curio [![Discord](https://img.shields.io/badge/Discord-738ADB)](https://discord.gg/vjpSMSJR8r) [![Full stack build](https://github.com/urban-toolkit/curio/actions/workflows/docker-compose.yml/badge.svg)](https://github.com/urban-toolkit/curio/actions/workflows/docker-compose.yml) [![PyPI version](https://img.shields.io/pypi/v/utk-curio)](https://pypi.org/project/utk-curio/)


<div align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/logo.png?raw=true" alt="Curio Logo" height="200"/></br>
  [<a href="https://arxiv.org/abs/2408.06139">Paper</a>] | [<a href="https://urbantk.org/curio">Website</a>]
</div>

Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels (code, grammar, GUI elements) to facilitate collaboration across the design and implementation of visual analytics components. The framework allows experts to intertwine preprocessing, managing, and visualization stages while tracking provenance of code and visualizations.

- [What's New](#whats-new)
- [Roadmap](#roadmap)
- [Overview](#overview)
  - [Key features](#key-features)
- [Usage and contributions](#usage-and-contributions)
- [Citation](#citation)
- [License](#license)
- [Acknowledgements](#acknowledgements)

## What's New

Curio v0.5.3 introduces a number of improvements and fixes thanks to the efforts of new contributors. Highlights include:

- 📦 **Pip Installation Support:** Curio can now be installed via `pip install utk-curio`, making it easier to get started. Check the [usage](docs/USAGE.md) document for details.
- 🚀 **Performance Improvements:** Enhanced computation execution speed in the backend.
- 🧪 **Initial End-to-End Testing:** Integrated test for backend/sandbox testing.
- 🧭 **New Examples Added:** Included new dataflows like "Complaints by Zip Code" and "Accessibility Analysis".
- 🐳 **Docker Enhancements:** Fixed Docker build issues by enforcing platform and fixing dependency installation errors.
- 🧹 **General Bug Fixes:** Resolved issues with icons, route definitions, upload status tracking, and environment variable references.

See the full [Changelog](https://github.com/urban-toolkit/curio/commits/v0.5.3) for more.


## Roadmap

We're actively working on several enhancements to make Curio more powerful, extensible, and user-friendly:

- 🔌 **UTK-Serverless Integration:** Integration with UTK’s upcoming serverless version is underway (Summer 2025).
- 🧪 **Expanded Testing Suite:** A more comprehensive testing framework is being extended to also cover frontend scenarios (Fall 2025).
- 🧠 **Enhanced Learning Resources:** More example dataflows and revised documentation are being created (Summer / Fall 2025).
- 🧩 **Modular Node Architecture:** A refactor is in progress to support a plug-in architecture, allowing programmers to define and register custom dataflow nodes more easily (Fall 2025).
- 📓 **Notebook Interoperability:** We are building support for importing/exporting dataflows to and from Jupyter notebooks (Fall 2025).
- 🧾 **Advanced Provenance Tracking:** We are improving how Curio tracks and visualizes the history of user actions (Fall 2025).

---

## Overview

**Curio: A Dataflow-Based Framework for Collaborative Urban Visual Analytics**  
*Gustavo Moreira, Maryam Hosseini, Carolina Veiga, Lucas Alexandre, Nico Colaninno, Daniel de Oliveira, Nivan Ferreira, Marcos Lage, Fabio Miranda*  
IEEE Transactions on Visualization and Computer Graphics ( Volume: 31, Issue: 1, January 2025)  
Paper: [[DOI](https://doi.org/10.1109/TVCG.2024.3456353)], [[Arxiv](https://arxiv.org/abs/2408.06139)]

<div align="center">
  <video src="https://github.com/urban-toolkit/curio/assets/2387594/6d29bda8-5e94-4496-a4ae-fd55adff024f" />
</div>

<p align="center">
  <img src="https://github.com/urban-toolkit/curio/blob/main/banner.jpg?raw=true" alt="Curio Use Cases" width="1000"/>
</p>

This project is part of the [Urban Toolkit ecosystem](https://urbantk.org), which includes [Curio](https://github.com/urban-toolkit/curio/) and [UTK](https://github.com/urban-toolkit/utk). Curio is a framework for collaborative urban visual analytics that uses a dataflow model with multiple abstraction levels to facilitate collaboration across the design and implementation of visual analytics components. UTK is a flexible and extensible visualization framework that enables the easy authoring of web-based visualizations through a new high-level grammar specifically built with common urban use cases in mind. 


### Key features
- Provenance-aware dataflow
- Modularized and collaborative visual analytics
- Support for 2D and 3D maps
- Linked data-driven interactions  
- Integration with [UTK](https://urbantk.org) and [Vega-Lite](https://vega.github.io/vega-lite/)

---

## Usage and contributions
For detailed instructions on how to use the project, please see the [usage](docs/USAGE.md) document. A set of examples can be found [here](https://github.com/urban-toolkit/curio/tree/main/docs). 

🚀 Curio now supports a Docker-based setup for easier installation and orchestration of all components. See the [usage guide](docs/USAGE.md) for instructions on running Curio with Docker.

If you'd like to contribute, see the [contributions](docs/CONTRIBUTIONS.md) document for guidelines. For questions, join [UTK's Discord](https://discord.gg/vjpSMSJR8r) server.

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

## License
Curio is MIT Licensed. Free for both commercial and research use.


## Acknowledgements
Curio and the Urban Toolkit have been supported by the National Science Foundation (NSF) (Awards [#2320261](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2320261), [#2330565](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2330565), and [#2411223](https://www.nsf.gov/awardsearch/showAward?AWD_ID=2411223)), Discovery Partners Institute (DPI), and IDOT.
