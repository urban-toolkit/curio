# Usage

- [Installation overview](#installation-overview)
- [Installation from pip](#installation-from-pip)
- [Installation from git](#installation-from-git)
  - [Installing via Docker](#installing-via-docker)
  - [Installing manually (with `curio.py`)](#installing-manually-with-curiopy)
- [LLM configuration](#llm-configuration)
  - [Logged-in users](#logged-in-users)
  - [Guest users](#guest-users)
- [Node Catalog](#node-catalog)
- [Real-time collaboration (experimental)](#real-time-collaboration-experimental)
- [Quick start](#quick-start)

> [!NOTE]
> This guide covers running Curio locally for development or single-user use. To host a multi-user instance on a server with HTTPS, see the [deployment guide](DEPLOYMENT.md).

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
  curio start frontend              # Start only the frontend (localhost:8080)
  curio start --auth                # Require login before reaching the project page
  curio start --no-project          # Skip login and project page; open the canvas directly
  curio start --deploy              # Same as --auth; use for production deployments
  curio start --collab              # Enable real-time multi-user collaboration (experimental, LAN-only)
  curio start --verbose 2           # Verbosity level (0=silent, 1=normal, 2=debug)
  curio start --force-rebuild       # Re-build the frontend and start all servers
  curio start --force-db-init       # Re-initialize the backend database and start all servers
```

The three startup modes control which pages are shown when a user first opens Curio:

| Mode | Login page | Project page | Typical use |
|------|-----------|--------------|-------------|
| *(default)* | No — auto sign-in as shared guest | Yes | Local single-user development |
| `--auth` / `--deploy` | Yes | Yes | Multi-user or production deployment |
| `--no-project` | No — auto sign-in as shared guest | No — opens canvas directly | Demos or embedding Curio in a kiosk |
| `--collab` | Stackable with other modes (pairs naturally with `--auth`) | — | Real-time multi-user editing on a LAN. See [COLLABORATION.md](COLLABORATION.md). |

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

This will start the backend, sandbox, and frontend servers. You can also start components individually:


```bash
curio start backend
curio start sandbox
curio start frontend
```

Curio's frontend will be available at http://localhost:8080 by default.

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

Curio requires **Python 3.12**. It has been tested on Windows 11, macOS Sonoma 14.5, and Ubuntu. It is recommended to install the environment using [Anaconda](https://anaconda.org):

```bash
conda create -n curio python=3.12
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
conda install -c conda-forge nodejs=24
```

You can now use `curio.py` to start everything:

```bash
python curio.py start             # Starts backend, sandbox, and frontend
```

This will build and start all required servers. The installation of all required packages might take a few minutes. When finished, Curio's frontend will be available at http://localhost:8080.

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
cd utk_curio/frontend/urban-workflows
npm install
npm run build
```


## LLM configuration

Curio includes an LLM Assistant sidebar available on the canvas. This feature was originally developed as part of **Urbanite**, a project that has since been migrated into Curio. The assistant lets users ask questions and receive AI-generated guidance in the context of their active dataflow.

To use the LLM Assistant, Curio needs access to an LLM API. Each user can connect their own account, or you can configure a shared key for guest users.

### Logged-in users

Logged-in users configure their own LLM connection from the **Projects page**. Click the **LLM Settings** button in the top navigation bar to open the settings panel.

The following providers are supported:

| Provider | Notes |
|---|---|
| **OpenAI** | Uses the standard OpenAI API. Requires an OpenAI API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| **Anthropic** | Uses the Anthropic API. Requires an API key from [console.anthropic.com/keys](https://console.anthropic.com/keys). |
| **Google Gemini** | Uses the Gemini API. Requires an API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| **Custom** | Any OpenAI-compatible endpoint. Covers self-hosted models (Ollama, LM Studio, vLLM), Groq, Azure OpenAI, and others. Provide the base URL of the endpoint; the API key is optional for keyless local servers. |

Settings are stored per user in the database and apply across all of their projects.

### Guest users

Guest users cannot configure their own LLM key. Instead, a shared key is set by via environment variables in a `.env` file at the project root:

```bash
# Required
GUEST_LLM_API_KEY=sk-...

# Optional — defaults shown
GUEST_LLM_API_TYPE=openai_compatible   # openai_compatible | anthropic | gemini
GUEST_LLM_MODEL=gpt-4o-mini
GUEST_LLM_BASE_URL=                    # leave blank for the provider default
```

**Examples:**

OpenAI (default):
```bash
GUEST_LLM_API_KEY=sk-proj-abc123...
```

Local Ollama server (no key required):
```bash
GUEST_LLM_API_TYPE=openai_compatible
GUEST_LLM_BASE_URL=http://localhost:11434/v1
GUEST_LLM_API_KEY=ollama
GUEST_LLM_MODEL=llama3.2
```

Anthropic Claude:
```bash
GUEST_LLM_API_TYPE=anthropic
GUEST_LLM_API_KEY=sk-ant-...
GUEST_LLM_MODEL=claude-haiku-4-5-20251001
```

If `GUEST_LLM_API_KEY` is not set, the LLM Assistant will return an error for guest users rather than failing silently.

## Node Catalog

Curio's nodes ship as **packages** — small, self-contained folders with a `manifest.json` declaring the node kinds inside. The built-in nodes (Data Loading, Vega-Lite, AutkMap, etc.) live in a pre-installed package called `curio.builtin@1`; you can install more via the **Node Catalog** drawer.

To open the drawer: in the **Tools panel** on the left edge of the canvas, find the **Packages** dropdown (cube icon) and open it; the **Get more packages +** button sits in the dropdown's footer. From there you can:

- Browse the catalog and install new packages.
- See your installed packages grouped by fork family in the **Installed** tab.
- Import a `.curio.zip` archive from the footer.
- Author your own package directly from the canvas: build the node, click the cog on its header, then **Save as pack node…**. Edit per-package metadata later via the pencil button next to the export icon in the **Packages** dropdown.

The full walkthrough — concepts, the Save-As flow, the per-package metadata editor, exporting / importing, versioning, and fork lineage — is in [docs/CATALOG.md](CATALOG.md). The manifest format is specified in [docs/schemas/node-package.v3.json](schemas/node-package.v3.json), and the committed package catalog lives at `<repo_root>/packages/`.

## Real-time collaboration (experimental)

`curio start --collab` opens an opt-in Socket.IO channel that lets multiple signed-in users on the same LAN edit the same project simultaneously: presence indicators, per-node soft locks, code-change proposals with peer approval, and shared execution output. The feature is disabled by default — passing `--collab` flips an env flag that the frontend reads at runtime, so no rebuild is needed.

See [COLLABORATION.md](COLLABORATION.md) for the full architecture, security model, setup instructions, and current limitations.

## Quick start

For a simple introductory example check [this](QUICK-START.md) tutorial. See [here](README.md) for more examples.

![Tutorial](images/final_result.png?raw=true)

