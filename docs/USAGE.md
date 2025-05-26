# Usage

## Table of contents
- [Usage](#usage)
  - [Table of contents](#table-of-contents)
  - [Installation](#installation)
    - [About Curio's multi-server management tool](#about-curios-multi-server-management-tool)
    - [Installing via Docker](#installing-via-docker)
    - [Installing manually (with `curio.py`)](#installing-manually-with-curiopy)
    - [Ray tracing](#ray-tracing)
    - [Quick start](#quick-start)

## Installation


Begin by cloning Curio's repository:

```bash
git clone git@github.com:urban-toolkit/curio.git
cd curio
```

Curio consists of three core components:

* **Backend**: provenance tracking and user management.
* **Sandbox**: Python execution environment for code modules.
* **Frontend**: user interface for composing workflows and interacting with modules.

Curio requires **Python >= 3.9 & < 3.12**. It has been tested on Windows 11, macOS Sonoma 14.5, and Ubuntu. It is recommended to install the environment using [Anaconda](https://anaconda.org):

```bash
conda create -n curio python=3.10
conda activate curio
```

You can install and run Curio using Docker for convenience or manually for customization. If running manually, **we recommend using `curio.py`**, a CLI tool that simplifies launching and managing Curio servers.

### About Curio's multi-server management tool

The `curio.py` launcher is a unified command-line tool for starting, stopping, and rebuilding the various Curio servers (backend, sandbox, and frontend).

You can inspect its help message by running:

```bash
python curio.py --help
```

Sample output:

```bash
Usage:
  python curio.py start                       # Start all servers (Backend, Sandbox, Frontend)
  python curio.py start backend               # Start only the backend (localhost:5002)
  python curio.py start sandbox               # Start only the sandbox (localhost:2000)
  python curio.py start --force-rebuild       # Force rebuild the frontend and start all
```

---

### Installing via Docker

Docker simplifies installation by orchestrating all components.

Prerequisites:
- [Docker](https://docs.docker.com/get-started/get-docker/)

After cloning the repository (see above), run the full Curio stack with:

```console
docker compose up
```

For older Docker versions, the following command may be required instead:
```console
docker-compose up
```

This will build and start all required servers. Curio's frontend will be available at http://localhost:8080.

⚠️ **Note:** Initial builds can take time. Use `--build` to rebuild if needed.

### Installing manually (with `curio.py`)

To install all requirements, inside the root folder:

```console
pip install -r requirements.txt
conda install -c conda-forge nodejs=22.13.0
```


Prepare the backend database:

```bash
cd backend
python create_provenance_db.py
FLASK_APP=server.py flask db upgrade
cd ..
```

You can now use `curio.py` to start everything:

```bash
python curio.py start             # Starts backend, sandbox, and frontend
```

This will build and start all required servers. Curio's frontend will be available at http://localhost:8080.

You can also start individual servers:

```bash
python curio.py start backend
python curio.py start sandbox
python curio.py start frontend
```

To force rebuild the frontend:

```bash
python curio.py start --force-rebuild
```

### Ray tracing

To use Ray Tracing, please see UTK's [requirements](https://github.com/urban-toolkit/utk).

### Quick start

For a simple introductory example check [this](QUICK-START.md) tutorial. See [here](README.md) for more examples.

![Tutorial](images/final_result.png?raw=true)


