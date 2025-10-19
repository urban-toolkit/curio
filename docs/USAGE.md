# Usage

- [Installation overview](#installation-overview)
- [Installation from pip](#installation-from-pip)
- [Installation from git](#installation-from-git)
  - [Installing via Docker](#installing-via-docker)
  - [Installing manually (with `curio.py`)](#installing-manually-with-curiopy)
- [Ray tracing](#ray-tracing)
- [Quick start](#quick-start)


## Installation overview

Curio includes a multi-server management tool that orchestrates three key components: the **Backend** for provenance tracking and user management, the **Sandbox** for executing code modules, and the **Frontend** for building visual workflows.

The `curio` launcher is a unified command-line tool for starting, stopping, and rebuilding the various Curio servers. If Curio is installed via pip (see instructions [here](#installation-from-pip)), the tool is accessed using the `curio` command, which can be run from any directory; this command internally maps to the installed `curio.py` script. If Curio is installed from the Git repository (see instructions [here](#installation-from-git)), the tool should be executed using `python curio.py` from within the cloned project folder.

You can inspect its help message by running:

```bash
curio --help
```

If installed from Git:

```bash
python curio.py --help
```

Sample output:

```bash
Usage:
  curio start                       # Start all servers (Backend, Sandbox, Frontend)
  curio start backend               # Start only the backend (localhost:5002)
  curio start sandbox               # Start only the sandbox (localhost:2000)
  curio start --verbose VERBOSE     # Verbosity level (e.g., 0=silent, 1=normal, 2=debug)
  curio start --force-rebuild       # Re-build the frontend and start all servers
  curio start --force-db-init       # Re-initialize the backend database and start all servers
```

> [!NOTE]
> When reading files from inside Curio's dataflow nodes, paths are resolved relative to the directory where you started Curio. If you see a "No such file or directory" error while loading a file, double-check the folder you're running Curio from, because the file path you provide is interpreted relative to that location.

## Installation from pip

Curio can be installed either via pip for a quick setup or from source for more customization:

```bash
pip install utk-curio
```

This will install Curio’s CLI and required components. After installation, simply run:

```bash
curio start
```

This will start the backend, sandbox, and frontend servers. The first time Curio runs, it will automatically install UTK. You can also start components individually:


```bash
curio start backend
curio start sandbox
curio start frontend
```

> [!NOTE]
> The pip installation includes a pre-built frontend and does not support rebuilding it. If you need to modify or rebuild the frontend, please use the manual installation method described below.

## Installation from git



Begin by cloning Curio's repository:

```bash
git clone https://github.com/urban-toolkit/curio.git
cd curio
```

Curio consists of three core components:

* **Backend**: provenance tracking and user management.
* **Sandbox**: Python execution environment for code modules.
* **Frontend**: user interface for composing workflows and interacting with modules.

Curio requires **Python >= 3.10 & < 3.12**. It has been tested on Windows 11, macOS Sonoma 14.5, and Ubuntu. It is recommended to install the environment using [Anaconda](https://anaconda.org):

```bash
conda create -n curio python=3.10
conda activate curio
```

There are two main ways to install Curio from the Git repository: [using Docker](#installing-via-docker) for a containerized setup, or [manually installing and running each component](#installing-manually-with-curiopy).


### Installing via Docker

Docker simplifies installation by orchestrating all components.

Prerequisites: [Docker](https://docs.docker.com/get-started/get-docker/)

After cloning the repository (see above), run the full Curio stack with:

```bash
docker compose up
```

For older Docker versions, the following command may be required instead:
```bash
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

You can now use `curio.py` to start everything:

```bash
python curio.py start             # Starts backend, sandbox, and frontend
```

This will build and start all required servers. The first time Curio runs, it will automatically install UTK. The installation of all required packages might take a few minutes. When finished, Curio's frontend will be available at http://localhost:8080.

You can also start individual servers:

```bash
python curio.py start backend
python curio.py start sandbox
python curio.py start frontend
```

To force the rebuild of the frontend:

```bash
python curio.py start --force-rebuild
```

This will delete and reinstall frontend dependencies and rerun the frontend build process.

To force the re-initialization of the backend database:

```bash
python curio.py start --force-db-init
```

This will recreate the provenance database and apply all migrations.

If you want to manually perform `npm install`, you should then:

```bash
cd utk_curio/frontend/utk-workflow/src/utk-ts
npm install
npm run build
```
And:
```bash
cd utk_curio/frontend/urban-workflows
npm install
npm run build
```


## Ray tracing

To use Ray Tracing, please see UTK's [requirements](https://github.com/urban-toolkit/utk).

## Quick start

For a simple introductory example check [this](QUICK-START.md) tutorial. See [here](README.md) for more examples.

![Tutorial](images/final_result.png?raw=true)

