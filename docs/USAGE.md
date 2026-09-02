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
- [Data Catalog](#data-catalog)
- [Agent Catalog](#agent-catalog)
- [Real-time collaboration](#real-time-collaboration)
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

There are two commands. `start` launches the servers (running `setup` first automatically); `setup` installs the framework and every installed package's Python dependencies for the current interpreter, then exits without starting anything, which is useful for warming a container image or a CI job.

```bash
curio start                  # all three servers
curio start backend          # one server: all | frontend | backend | sandbox
curio setup                  # install deps and exit
```

**Startup mode**

| Flag | Effect |
|---|---|
| *(none)* | Auto sign-in as shared guest, projects page shown |
| `--auth` | Require login (`CURIO_NO_AUTH=0`) |
| `--no-project` | Skip both login and projects; open the canvas directly |
| `--deploy` | Auth **and** projects on. Use for anything reachable by others |
| `--collab` | Real-time collaborative editing. Experimental, LAN-only |

**Catalogs**

| Flag | Default | Effect |
|---|---|---|
| `--catalog-root PATH` | `<repo_root>/datasets/` | Where the shared Data Catalog is read from and published to |
| `--save-node-outputs` / `--no-save-node-outputs` | off | Default state of every node's save-output toggle |
| `--allow-publish` / `--no-allow-publish` | on | Whether the node-catalog Publish/Unpublish actions are offered |
| `--with-examples` | off | Seed the example projects from `docs/examples/` |
| `--reseed` | off | Force re-seeding catalog packages into the guest package store |
| `--isolation auto\|fork\|off` | `auto` (resolves to off) | Run each node's Python in an isolated child process. Linux only. See [ARCHITECTURE.md](ARCHITECTURE.md#isolated-node-execution-opt-in-linux-only) |
| `--exec-memory-mb` / `--exec-timeout` / `--exec-parallelism` / `--exec-user` | 4096 / 300 / 2 / none | Limits for isolated execution. The real host memory ceiling is `exec-memory-mb x exec-parallelism` |
| `--allow-runtime-install` / `--no-allow-runtime-install` | on locally, off with `--auth` / `--deploy` | Whether the sandbox's `POST /install` endpoint accepts `pip install` requests |

**Hosts, ports, and diagnostics**

`--backend-host` / `--backend-port` (127.0.0.1:5002), `--sandbox-host` / `--sandbox-port` (127.0.0.1:2000), `--frontend-host` / `--frontend-port` (localhost:8080), and `--verbose N` (0=silent, 1=normal, 2=debug).

> [!WARNING]
> Leave `--sandbox-host` at `127.0.0.1` unless you are genuinely running the backend on another machine. The sandbox executes arbitrary node code and, while it now requires a shared secret, there is no reason to offer that surface to the network.

> [!NOTE]
> `--force-rebuild` and `--force-db-init` exist only in dev mode, which `curio.py` sets and the pip entry point does not. From a pip install or inside Docker they are rejected as unknown arguments; rebuild by other means there.

Because these flags are set as environment variables on every start, putting the corresponding `CURIO_*` var in a `.env` has no effect when you launch through `curio.py`. Use the flag.

The three startup modes control which pages are shown when a user first opens Curio:

| Mode | Login page | Project page | Typical use |
|------|-----------|--------------|-------------|
| *(default)* | No (auto sign-in as shared guest) | Yes | Local single-user development |
| `--auth` / `--deploy` | Yes | Yes | Multi-user or production deployment |
| `--no-project` | No (auto sign-in as shared guest) | No, opens the canvas directly | Demos or embedding Curio in a kiosk |
| `--collab` | Stackable with other modes (pairs naturally with `--auth`) | n/a | Real-time multi-user editing. See [COLLABORATION.md](COLLABORATION.md). |

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

Curio's AI surfaces (the Agent Catalog's agents, the node-authoring assistants, and chat) all answer through one provider, configured in **AI Settings**.

Curio ships no endpoint of its own, so an instance whose operator configures nothing resolves no provider and says so rather than sending prompts somewhere nobody chose. Each user can connect their own account, or you can configure a shared key for guest users.

### Logged-in users

Logged-in users configure their own connection in **AI Settings**, reachable from the **Projects page** and the catalog pages via the top navigation bar, and on the canvas from the Agent Catalog drawer's header.

The panel sets the provider, base URL, API key, model, and a HuggingFace token (used only for gated models in the Street Vision node). Each field falls back to the deployment default when you leave it blank, so filling in only one box keeps the rest of the operator's configuration. Key and base URL are not inherited across providers: switching to Anthropic does not lend you the deployment's OpenAI-compatible endpoint.

**An account holds one API key, against one provider.** The provider tabs pick which provider that is; they are not four separate slots. So the saved-key markers show only on the tab the key was saved under, and saving from a different tab replaces it. Before this was made explicit, every tab claimed a saved key, and saving from one of them kept the previous provider's key under the new provider's name.

The following providers are supported:

| Provider | Notes |
|---|---|
| **OpenAI** | Uses the standard OpenAI API. Requires an OpenAI API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| **Anthropic** | Uses the Anthropic API. Requires an API key from [console.anthropic.com/keys](https://console.anthropic.com/keys). |
| **Google Gemini** | Uses the Gemini API. Requires an API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| **Custom** | Any OpenAI-compatible endpoint. Covers self-hosted models (Ollama, LM Studio, vLLM), Groq, Azure OpenAI, and others. Provide the base URL of the endpoint; the API key is optional for keyless local servers. |

Settings are stored per user in the database and apply across all of their projects.

### Guest users

Guest users cannot configure their own LLM key. Instead, a shared key is set through environment variables in **`utk_curio/backend/.env`**. The backend loads its `.env` relative to its own package directory ([`config.py`](../utk_curio/backend/config.py)), so a `.env` at the repo root is not read by the app. (Docker Compose does read a root `.env`, but only for interpolating values like `BACKEND_URL` into `docker-compose.yml`.)

```bash
# Required
GUEST_LLM_API_KEY=sk-...

# Optional (defaults shown)
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
GUEST_LLM_MODEL=claude-haiku-4-5
```

If `GUEST_LLM_API_KEY` is not set, the LLM Assistant will return an error for guest users rather than failing silently.

## Node Catalog

Curio's nodes ship as **packages**: small, self-contained folders with a `manifest.json` declaring the node kinds inside. The built-in nodes (Data Loading, Vega-Lite, Autark, etc.) live in a pre-installed package called `curio.builtin@1`; you can install more via the **Node Catalog** drawer.

One Autark-specific note: an Autark node's spec references incoming data by name. A single upstream frame is auto-injected as the `upstream` source, while a layer array from an upstream Autark node exposes each layer under its own table name. See [Referencing Upstream Data in Autark Nodes](ARCHITECTURE.md#referencing-upstream-data-in-autark-nodes).

To open the drawer: in the **Tools panel** on the left edge of the canvas, find the **Node Catalog** dropdown (cube icon) and open it; the **Browse Node Catalog +** button sits in the dropdown's footer. From there you can:

- Browse the catalog and install new packages.
- See the packages added to this dataflow, grouped by fork family, in the **In dataflow** tab.
- Import a `.curio.zip` archive from the footer.
- Author your own package directly from the canvas: build the node, click the cog on its header, then **Save as package node…**. Edit per-package metadata later via the pencil button next to the export icon in the **Node Catalog** dropdown.

For the full walkthrough, covering concepts, the Save-As flow, the per-package metadata editor, exporting and importing, versioning, and fork lineage, see [docs/NODE-CATALOG.md](NODE-CATALOG.md). The manifest format is specified in [docs/schemas/node-package.v4.json](schemas/node-package.v4.json), and the committed package catalog lives at `<repo_root>/packages/`.

## Data Catalog

Datasets have their own catalog, built on the same model as the Node Catalog: a **dataset** is a folder with a `manifest.json` and its data file, identified as `<datasetId>@<major>` (e.g. `data.urbanlab.chicago-boundary@1`). Curio ships eleven datasets in the committed catalog at `<repo_root>/datasets/`; they are the inputs to the curated example dataflows.

Three surfaces manage datasets:

- The **Data Catalog drawer** inside the canvas. Open it from the top menu **Data ⏷ → Data Catalog**, or from the **Data Catalog** dropdown in the left Tools panel via **Browse Data Catalog +**. Install datasets into the open dataflow, import files from your machine, publish, or delete.
- The **Data Catalog** dropdown in the Tools panel, listing your installed datasets. Drag one onto the canvas to create (or extend) a node with generated loader code.
- The **`/catalog/data`** page, a read-only library view reached from `/projects` → **Catalog** → the **Data** tab.

A node can also save its output as a **computed dataset** in your account (the database toggle next to each node's play button), so its result can be reused as an input elsewhere. This is off by default, so turn the toggle on for the nodes whose output you want to keep; set `CURIO_DEFAULT_SAVE_NODE_OUTPUT=1` to turn it on for every node instead.

Because the shared catalog root defaults to `<repo_root>/datasets/`, pip installs and Docker deployments should set **`CURIO_CATALOG_ROOT`** (or `--catalog-root`) to a writable, persistent path.

> [!NOTE]
> `CURIO_CATALOG_ROOT` relocates the **dataset** catalog only. The shared *node
> package* catalog is always `<install_root>/packages/`, resolved relative to
> the installed `utk_curio` package with no env override. On a pip install that
> is inside `site-packages`, so publishing a node package there is at best
> non-persistent. That is one more reason to author node packages from a git
> checkout (see [Authoring nodes](AUTHORING-NODES.md)).

For the full walkthrough, covering storage layers, the action matrix, computed datasets and lineage, OSM PBF imports, publishing, and previews, see [docs/DATA-CATALOG.md](DATA-CATALOG.md).

## Agent Catalog

Agents are AI assistants you attach to your dataflow. Curio ships twenty-one of
them, covering chat, debugging, node authoring, dataset discovery, planning and
evaluation. Which model answers is the provider set in **AI Settings** above.

There are two scopes, and they are different writes:

- **`/catalog/agents`**, the third tab beside the node and data catalogs, is
  your **account**. Adding an agent here makes it available to every dataflow.
- **The Agent Catalog drawer**, opened on the canvas from **Data → Agent
  Catalog** or the agents tab in the left rail, adds an agent to **this
  dataflow**.

### Attaching an agent

Drag an agent from the left rail's agents palette onto the canvas. Where you
drop it is what it attaches to:

- **a node**, for agents that reason about one node's content or output,
- **a connection**, for agents that reason about an edge between two nodes,
- **the canvas**, for agents that work over the whole dataflow.

An agent only accepts the targets its manifest declares, so dropping one
somewhere it does not belong is refused rather than silently rebound. Node
agents appear as a badge on their node; canvas and connection agents appear in
the dock at the top of the canvas.

### Working with an agent

Click an agent to open its chat panel. From there you can rename the
conversation, clear it, cycle through every attached agent with the ‹ › arrows,
and edit the initial intent the agent starts from. Agents that propose changes
(new nodes, edges, node content, packages) put them up for review first: nothing
lands on your canvas until you apply it.

The **Dataflow Builder** is the composite agent that plans a whole dataflow. Its
strip adds planning phases, per-node progress, **Solve** (fill in the planned
nodes in one batch) and **Simulation Mode** (walk the plan without executing).

The goal box in the dock is shared with your agents: several of them, the
Dataflow Task Planner most of all, are written around knowing what the dataflow
is for. It is saved with the project.

### What an agent may reach

Agents run under a default-deny egress policy. Web fetches are restricted to
http and https, refused when a host resolves to a non-public address, capped in
body size and redirect count, and bounded per run. A refusal surfaces in the
chat as "refused by the egress policy", which means the address was internal or
otherwise disallowed, not that the site was down.

The agents' web-search tool defaults to DuckDuckGo's keyless Instant Answer API.
Operators who would rather not send queries to a third party can point
`--agent-search-url` at their own provider, or elsewhere entirely.

For the full guide, covering the roster, agent packages, delegation, publishing,
and writing your own, see [docs/AGENT-CATALOG.md](AGENT-CATALOG.md).

## Real-time collaboration

`curio start --collab` opens an opt-in Socket.IO channel that lets multiple signed-in users edit the same project simultaneously: presence indicators, per-node soft locks, code-change proposals with peer approval, and shared execution output. The feature is disabled by default. Passing `--collab` flips an env flag that the frontend reads at runtime, so no rebuild is needed.

See [COLLABORATION.md](COLLABORATION.md) for the full architecture, security model, setup instructions, and current limitations.

## Quick start

For a simple introductory example check [this](QUICK-START.md) tutorial. See [here](README.md) for more examples.

![Tutorial](images/final_result.png?raw=true)

