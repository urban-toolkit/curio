# Usage

- [Installation overview](#installation-overview)
- [Installation from pip](#installation-from-pip)
- [Installation from git](#installation-from-git)
  - [Installing via Docker](#installing-via-docker)
  - [Installing manually (with `curio.py`)](#installing-manually-with-curiopy)
- [LLM configurations](#llm-configurations)
  - [Your configurations](#your-configurations)
  - [Keys for node code](#keys-for-node-code)
  - [Guest users](#guest-users)
- [The Tools panel](#the-tools-panel)
- [Inside a node](#inside-a-node)
- [Notes](#notes)
- [Running a dataflow](#running-a-dataflow)
- [Widgets](#widgets)
- [Scenarios](#scenarios)
  - [Comparing scenarios](#comparing-scenarios)
- [Node Catalog](#node-catalog)
- [Vega-Lite node](#vega-lite-node)
- [Autark node](#autark-node)
- [Rasters](#rasters)
- [Notebook view](#notebook-view)
- [Dashboards](#dashboards)
- [Data Catalog](#data-catalog)
- [Discovery Catalog](#discovery-catalog)
- [Model Catalog](#model-catalog)
- [Agent Catalog](#agent-catalog)
- [Real-time collaboration](#real-time-collaboration)
- [Quick start](#quick-start)

> [!NOTE]
> This guide covers running Curio locally for development or single-user use. To host a multi-user instance on a server with HTTPS, see the [deployment guide](DEPLOYMENT.md).

## Installation overview

Curio includes a multi-server management tool that orchestrates three key components: the **Backend** for user management, projects and the catalogs, the **Sandbox** for executing code modules, and the **Frontend** for building visual workflows.

The `curio` launcher is a unified command-line tool for starting, stopping, and rebuilding the various Curio servers. If Curio is installed via pip (see instructions [here](#installation-from-pip)), the tool is accessed using the `curio` command, which can be run from any directory; this command internally maps to the installed `curio.py` script. If Curio is installed from the Git repository (see instructions [here](#installation-from-git)), the tool should be executed using `python curio.py` from within the cloned project folder.

You can inspect its help message by running:

```bash
curio --help
```

If installed from Git:

```bash
python curio.py --help
```

There are three commands. `start` launches the servers (running `setup` first automatically); `setup` installs the framework and every installed package's Python dependencies for the current interpreter, then exits without starting anything, which is useful for warming a container image or a CI job; `test` runs the test suite (`test --help` lists the suites).

```bash
curio start                  # all three servers
curio start backend          # one server: all | frontend | backend | sandbox
curio setup                  # install deps and exit
```

**Startup mode**

| Flag | Effect |
|---|---|
| *(none)* | Auto sign-in as shared guest, projects page shown |
| `--no-project` | Skip both login and projects; open the canvas directly |
| `--deploy` | Auth **and** projects on, and isolated node execution, which it requires. The only way to turn auth on, so use it locally too when you need the login page |
| `--collab` | Real-time collaborative editing. Experimental, LAN-only. `--collab-origins` and `--collab-namespace` set the origins it accepts and its Socket.IO namespace; see [COLLABORATION.md](COLLABORATION.md) |

**Frontend**

| Flag | Default | Effect |
|---|---|---|
| `--dev` | off | Serve the frontend from the webpack dev server, with hot reload and a development bundle. Use it when you are editing frontend source |
| `--base-path PATH` | the root | The URL path the web app is served under, such as `/app` behind a reverse proxy. Applies to the built bundle, so not with `--dev`. See [DEPLOYMENT.md](DEPLOYMENT.md) |
| `--backend-url URL` | `http://<backend-host>:<backend-port>` | The address the browser reaches the backend at, such as `https://example.org/app/api` behind a reverse proxy |

Without `--dev`, Curio serves the built bundle in `utk_curio/frontend/urban-workflows/dist/`. That bundle is a production webpack build, roughly a third the size of the development one, so the page loads much faster; the trade is that frontend edits need a rebuild to appear. A pip install and the Docker image ship a built `dist/` and never compile anything.

`curio.py start` builds the frontend when there is no build to serve, or when the existing build is a development build. The first build on a fresh clone takes a few minutes. Source edits do not trigger a build, so use `--dev` while working on the frontend, or `--force-rebuild` to force one.

Curio needs Node.js 26 and refuses to start on an earlier version, naming the one to install. Switching to another Node major reinstalls `node_modules/` on the next start; the frontend build is kept unless one of the rules above calls for a new one.

**Catalogs**

| Flag | Default | Effect |
|---|---|---|
| `--catalog-root PATH` | `<repo_root>/datasets/` | Where the shared Data Catalog is read from and published to |
| `--discovery-root PATH` | `<repo_root>/discovery/` | Where the shipped Discovery Catalog sources are read from. Your own sources stay in `.curio/discovery/` |
| `--discovery-max-download-mb MB` | `1024` | The largest file the Discovery Catalog downloads, or adds from a bucket. A source's manifest may set a lower limit for itself |
| `--media-cache-max-gb GB` | `20` | How much each account may hold in cached bucket files and downloaded street-level images |
| `--packages-root PATH` | `<repo_root>/packages/` | Where the shared Node Catalog is read from and published to. Start it from a copy of `packages/`: the built-in nodes are installed from it |
| `--save-node-outputs` / `--no-save-node-outputs` | off | Whether a new node's **Save output dataset** toggle starts on. Users can still flip it on each node |
| `--allow-publish` / `--no-allow-publish` | on | Whether the node, data and agent catalogs allow Publish/Unpublish |
| `--testing` | off | Run against the dedicated test database under `.curio/test/` and mount the test-only `/api/testing/*` routes. Also the one exemption to `--deploy` requiring isolated execution. Never for a real instance: those routes reset the database and sign in as any user without a password |
| `--with-examples` | off | Seed the use cases, examples and tests from `docs/examples/` |
| `--reseed` | off | Force re-seeding catalog packages into the guest package store |
| `--exec-memory-mb` / `--exec-timeout` / `--exec-parallelism` | 4096 / 300 / half the host's cores, from 2 to 8 | Limits for isolated execution. `exec-memory-mb` is what a node may allocate on top of the interpreter its child starts with, with a floor of 64. The real host memory ceiling is `exec-memory-mb x exec-parallelism` |

`--deploy` turns on node-execution isolation, and refuses to start on a host that cannot provide it: isolation needs Linux and an unprivileged execution account, which the Docker image creates as `curio-exec`. Two environment variables override that, for test stacks and for an operator who wants it off: `CURIO_ISOLATION=off|fork` and `CURIO_EXEC_USER=<account>` (empty means none). `CURIO_ISOLATION=fork` is fail-closed: a host that cannot provide isolation refuses to start. See [ARCHITECTURE.md](ARCHITECTURE.md#isolated-node-execution-opt-in-linux-only).

**Server**

| Flag | Default | Effect |
|---|---|---|
| `--state-dir PATH` | `.curio/` in the directory Curio starts from | Where Curio keeps its state: every user's store, the caches and the launcher's log |
| `--js-parallelism N` | half the host's cores, from 2 to 16 | How many JavaScript nodes the sandbox runs at once |
| `--package-workers N` | half the host's cores, from 2 to 8 | How many package backend handlers run at once |
| `--js-registry-url URL` | none | The npm registry a package build fetches JavaScript dependencies from. Without one, a build that needs a JavaScript dependency is refused |
| `--js-block-unpinned` / `--no-js-block-unpinned` | off | Whether a package build refuses a JavaScript dependency without a pinned version, rather than warning |
| `--db-pool-size N` / `--db-pool-overflow N` / `--db-pool-timeout SECONDS` | 64 / 128 / 30 | The backend's database connections: how many it keeps open, how many more it may open while those are all in use, and how long a request waits for one |
| `--shared-guest-name NAME` / `--shared-guest-username NAME` | `Shared Guest` / `guest_shared` | The shared guest, the one account every guest sign-in uses. A new username gives guests a new, empty account |
| `--log-to-stdout` / `--no-log-to-stdout` | on | Whether the backend and sandbox write their logs to their output, which the launcher keeps in its own log, or to `utk_curio/logs/` |

**Hosts, ports, and diagnostics**

`--backend-host` / `--backend-port` (127.0.0.1:5002), `--sandbox-host` / `--sandbox-port` (127.0.0.1:2000), `--frontend-host` / `--frontend-port` (localhost:8080), and `--verbose N` (0=silent, 1=normal, 2=debug).

> [!WARNING]
> Leave `--sandbox-host` at `127.0.0.1` unless you are genuinely running the backend on another machine. The sandbox executes arbitrary node code and, while it requires a shared secret, there is no reason to offer that surface to the network.

> [!NOTE]
> `--force-rebuild` deletes `node_modules/`, `dist/` and `build/` and rebuilds from source, so it needs the frontend sources and a working npm; the Docker image ships only the built `dist/` and cannot rebuild in place.

Some flags set their variable on every start, passed or not: the backend and sandbox host and port flags, `--backend-url`, `--dev`, `--with-examples`, `--reseed`, `--allow-publish`, `--save-node-outputs`, `--deploy`, `--no-project` and `--collab`. For those, the matching variable in a `.env` has no effect when you launch through `curio.py`; use the flag. Every other flag sets its variable only when it is passed.

`CURIO_BACKEND_DEBUG=1` turns on Flask's debug mode for the backend, which is off by default. It has no flag of its own, so, unlike the variables above, setting it in a `.env` does work when you launch through `curio.py`. Auto-reload is a separate switch (`FLASK_USE_RELOADER`) and is unaffected.

The three startup modes control which pages are shown when a user first opens Curio:

| Mode | Login page | Project page | Typical use |
|------|-----------|--------------|-------------|
| *(default)* | No (auto sign-in as shared guest) | Yes | Local single-user development |
| `--deploy` | Yes | Yes | Multi-user instance, locally or on a server |
| `--no-project` | No (auto sign-in as shared guest) | No, opens the canvas directly | Demos or embedding Curio in a kiosk |
| `--collab` | Stackable with other modes (pairs naturally with `--deploy`) | n/a | Real-time multi-user editing. See [COLLABORATION.md](COLLABORATION.md). |

> [!NOTE]
> When reading files from inside Curio's dataflow nodes, paths are resolved relative to the directory where you started Curio. If you see a "No such file or directory" error while loading a file, double-check the folder you're running Curio from, because the file path you provide is interpreted relative to that location. A path written out as `docs/examples/data/...` that this folder does not hold reads the example data Curio ships.

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

A pip install keeps the datasets, Discovery sources, models and node packages that Curio's catalogs ship, its scripts, DuckDB's extensions, and the example dataflows, the example data they read and the Example storage folder from `docs/` in `utk_curio/_shipped/` in site-packages. It puts nothing in site-packages but `utk_curio/` and its metadata.

Autark data nodes and OpenStreetMap downloads need Node.js 26 and npm (`conda install -c conda-forge nodejs=26`). On every start, `curio start` installs their Node.js packages with `npm install` into `.curio/nodejs/` in the folder you start Curio from.

Twelve files are not in the pip package: the data of eleven Data Catalog datasets (Milan Mean Radiant Temperature, Project Sidewalk Chicago Labels, Chicago Red-Light Violations, Chicago Speed Camera Violations and SCOUT's seven flood rasters) and the Model Catalog's Deep Umbra model. Curio downloads each one from GitHub the first time something reads it: a preview in the Data Catalog, adding the dataset to a dataflow, or a node that loads it. Downloaded files go to `.curio/fetched/` in the folder you start Curio from.

Offline, reading one of those files fails with a message that gives its address on GitHub and the path to save it to. Download the file from that address on a machine that is online and copy it to that path, or install Curio from git, which holds every file.

## Installation from git



Begin by cloning Curio's repository:

```bash
git clone https://github.com/urban-toolkit/curio.git
cd curio
```

Curio consists of three core components:

* **Backend**: user management, projects and the catalogs.
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

This will build and start all required servers. Curio's frontend will be available at http://localhost:8080.

⚠️ **Note:** Initial builds can take time. Use `--build` to rebuild if needed.

### Installing manually (with `curio.py`)

To install all requirements, inside the root folder:

```console
pip install -r requirements.txt
conda install -c conda-forge nodejs=26
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

This will re-initialize the backend database and apply all migrations.

If you want to manually perform `npm install`, you should then:

```bash
cd utk_curio/frontend/urban-workflows
npm install
npm run build
```


## LLM configurations

Curio's AI surfaces (the Agent Catalog's agents, the node-authoring assistants, and chat) answer with an **LLM configuration** set up in **API Settings**: the one chosen for the agent, else your default.

Curio ships no endpoint of its own. Until you add a configuration, or the operator of your Curio sets a Deployment default, the AI surfaces report that no LLM configuration answers.

### Your configurations

**API Settings** is in the top bar. On the **Projects page**, the catalog pages and **Monitor** it opens the settings page, `/settings`; on the canvas and the dashboard it opens on the right side, and the dataflow stays open. It has two tabs:

- **API keys** lists every key your account uses in one table, with the columns **Name**, **Kind**, **Details**, **Key** and **Actions**. Your LLM configurations are of kind **Language model**, the keys the Discovery Catalog sends to data sources are of kind **Data source**, and the keys your node code reads are of kind **Node code**. **Add configuration**, under the table, adds any of them.
- **Agent configuration** chooses your default configuration in **Default for agents**, and the configuration each agent runs on in **Agent models**.

A button elsewhere that opens API Settings, such as **Add key for** a host or **Change in API Settings**, opens it on one form or row: from the Projects page or a catalog page it goes to the settings page, and on the canvas it opens API Settings on the right side.

To add an LLM configuration:

1. Get an API key from the provider (the table below links to the OpenAI, Anthropic and Gemini key pages).
2. Open **API Settings** from the top bar (on the canvas it opens on the right).
3. On the **API keys** tab, click **Add configuration**.
4. In **Kind**, choose **Language model**.
5. Type a **Label**, choose the **Provider**, paste the **API key**, and type the **Model** (the provider's default model is shown in grey), or click **Fetch models** and pick one. **Custom** also asks for the **Base URL**.
6. Click **Add configuration**. The configuration's row shows in the list, with **saved** in its **Key** column when you gave a key.

Configurations and choices belong to your account and apply to all of your projects; the fields, the row actions and which configuration answers a run are in [AGENT-CATALOG.md part 4](AGENT-CATALOG.md#4-llm-configurations).

Keys are write-only: once saved, a key is never shown again, and the table says only whether one is saved. Keys are kept per account in a file readable by the server only; they are not encrypted at rest.

The following providers are supported:

| Provider | Notes |
|---|---|
| **OpenAI** | Uses the standard OpenAI API. Requires an OpenAI API key from [platform.openai.com/api-keys](https://platform.openai.com/api-keys). |
| **Anthropic** | Uses the Anthropic API. Requires an API key from [console.anthropic.com/keys](https://console.anthropic.com/keys). |
| **Gemini** | Uses the Gemini API. Requires an API key from [aistudio.google.com/apikey](https://aistudio.google.com/apikey). |
| **Custom** | Any OpenAI-compatible endpoint. Covers self-hosted models (Ollama, LM Studio, vLLM), Groq, Azure OpenAI, and others. Provide the base URL of the endpoint; the API key is optional for keyless local servers. |

A **Data source** key is one the Discovery Catalog sends to a source: the Socrata app token, the Hugging Face token, the Google Maps API key or the Mapillary access token. In **Add configuration**, the **Kind** list offers each one you have not saved, under **Data source**. A saved one is listed with **Replace** and **Remove**, and its **Details** say which sources use it. A key whoever runs this Curio set for everyone is listed with **set by this Curio** in its **Key** column, and **Override** saves your own. [DISCOVERY-CATALOG.md part 5](DISCOVERY-CATALOG.md#5-api-tokens) walks through setting one, step by step.

### Keys for node code

A **Node code** key is an API key a node's code reaches by name. It holds a
name, the host it is for, how the API expects it (in the code, as a query
parameter, or as an HTTP header), and the key itself, in a masked field that is
never read back. To save one:

1. Get the key from the API's provider.
2. Open **API Settings** from the top bar (on the canvas it opens on the right).
3. On the **API keys** tab, click **Add configuration**.
4. In **Kind**, choose **Another API, for node code**.
5. Type a **Name** (for example `census`) and the **Host** (for example
   `api.census.gov`), choose how it is **Sent as** (with the **Parameter name**
   or **Header name** when it is not sent in the code), and paste the **Key**.
6. Click **Save key**. The key's row shows in the list, with **saved** in its
   **Key** column; its **Details** show the host, how the key is sent and when
   it was last used. When the name is already saved for another host, the form
   offers **Replace the host binding**.

Then write, in the node's code:

```python
api_key = curio_secret("census")
```

Curio resolves the name when the node runs, on Play and when an agent's Solve
runs it, and hands the value to the sandbox for that run only. The key never
appears in your saved dataflow, in proposals, in the chat or in the run log, and
a key the code prints is redacted. A node that names a key you have not saved
fails with one sentence naming the key. When an agent's Solve reaches an
endpoint that wants a key you have not saved, the failure offers **Add key for
<host>**, which opens this form with the host filled in.

Keys are stored per account in a file readable by the server only; they are not
encrypted at rest. A dataflow you publish carries the key names, and whoever
installs it saves their own key under the same name. When authentication is
off, every guest shares one key store.

If the code you type or paste holds something shaped like an API key (a long
token assigned to a name like `api_key`, `token` or `Authorization`), a bar
above the editor names the line and offers **Save as API key**, which
opens this form with the host from the code filled in. It is a hint: Play
and save work, the code is never changed for you, and the detected text never
leaves your browser. Dismiss it if the value is not a key.

### Guest users

On a Curio started with `--deploy`, guests cannot add LLM configurations: every guest answers with the **guest configuration** the operator sets. They cannot save data source or node code keys either, and **Add key for** and **Save as API key** do not appear for them. Without `--deploy`, Curio signs you in as the shared guest, which adds configurations and saves its tokens in API Settings like any account; they are shared by everyone using that Curio, and the guest configuration is its Deployment default.

The guest configuration's provider, endpoint and model are `curio.py` flags: `--guest-llm-provider` (`openai_compatible`, `anthropic` or `gemini`), `--guest-llm-base-url` (empty for the provider's own endpoint) and `--guest-llm-model`. Its key is `GUEST_LLM_API_KEY` in **`utk_curio/backend/.env`**.

Each one that is not set takes the deployment's value (see the [deployment guide](DEPLOYMENT.md#llm-configurations)). A guest configuration needs both a key and a model; without either, agents refuse guest runs and say so.

**Examples**, each with its key in `utk_curio/backend/.env`:

OpenAI (`GUEST_LLM_API_KEY=sk-proj-abc123...`):
```bash
python curio.py start --deploy --guest-llm-model gpt-4o-mini
```

Local Ollama server (it takes any key, so give it a placeholder: `GUEST_LLM_API_KEY=ollama`):
```bash
python curio.py start --deploy --guest-llm-provider openai_compatible \
  --guest-llm-base-url http://localhost:11434/v1 --guest-llm-model llama3.2
```

Anthropic Claude (`GUEST_LLM_API_KEY=sk-ant-...`):
```bash
python curio.py start --deploy --guest-llm-provider anthropic --guest-llm-model claude-haiku-4-5
```

## The Tools panel

The Tools panel on the left edge of the canvas holds five buttons: **Built-in**,
**Node Catalog**, **Data Catalog**, **Agent Catalog** and **Model Catalog**,
with **Run All** at its foot. Each button opens its palette beside the panel and
closes the one that was open; click it again to close it. The canvas opens with
every palette closed.

**Built-in** holds Curio's own nodes, from **Data Loading** to **Note**, in three
groups: data, computation, and views. Hover over a tile to see its name, and
drag it onto the canvas to add the node. Each catalog's palette is described
with its catalog: [Node Catalog](#node-catalog), [Data Catalog](#data-catalog),
[Agent Catalog](#agent-catalog) and [Model Catalog](#model-catalog).

## Inside a node

A node's header shows **Play** at its left, the node's name and kind, and its run
status. Its other buttons show while the pointer is over the node or the node is
selected: the editor's tabs (code, widgets, spec, output), **Provenance** (the
node's runs, see [Provenance](#provenance)), the **Save output dataset** toggle,
settings, about, pin, **Minimize** and delete.
Code and specs sit in a gray box, and a code node's output is below its code.

Above the code or spec, one row lists every chip the node can use, by category:
**Inputs**, **Scenarios**, **Widgets**, **Selections** and **Shared**, each with
its count, and each only when it has chips. The categories start closed. Click
one to list its chips under the row, and click it again to close it. Several
can be open, and a category stays open on that node while the dataflow is
open. On the canvas the header takes at most half of the node's editor, and the
open chips scroll inside it. Drag a chip's tag into the code or spec, or click
it to insert the chip at the cursor.

- **Inputs**: a line for each input, with its tag and what it holds, whose
  chevron lists its columns under the line (see [Several inputs](#several-inputs)),
  and in a Vega-Lite spec the line of the **inputs** tag
  ([Every input in one dataset](#every-input-in-one-dataset)).
- **Scenarios**: in a Vega-Lite or Autark spec whose node has an input from a
  scenario box, the chips of the boxes' colors and names
  ([Scenario colors and order](#scenario-colors-and-order)).
- **Widgets**, **Selections** and **Shared**: the node's widgets, its selection
  tags and the Parameter nodes' values ([Widgets](#widgets)).

Drag a node's bottom-right corner to resize it. For viewers of a shared dataflow,
nodes keep their size and have no delete. A minimized node is a small chip, and a
save keeps it one; click it to open the node again. Double-click a node where you
would drag it, such as its header, to zoom the view onto it.

## Notes

A **Note** node holds a title and a short text on a color, to explain a part of
the dataflow. Drag **Note** from the **Built-in** palette onto the canvas, write
its title and text, pick its color and click **Save**. **Edit** on the note
opens them again.

- The text is simple markdown: `#` headings, `-` lists, `**bold**`,
  `*italics*`, `` `code` `` and links. Only an `https` link is a link, and it
  opens in a new tab. HTML in the text is not shown, and an image shows its alt
  text.
- A note has no inputs or outputs, and a run skips it.
- The **Researcher** answers questions from the web with notes (see
  [Agent Catalog](#agent-catalog)).
- On the dashboard and on a shared dataflow, a note shows its text and cannot be
  edited.

## Running a dataflow

**Run All** runs every node. A node's **Play** button, or Ctrl+Enter (Cmd+Enter
on a Mac), runs that node and the nodes above it whose output is out of date.

On your own dataflow, a run saves the dataflow first and then runs on the
server, so it goes on when you close the tab. A dataflow you never saved is
saved under its title by its first run.

- Charts, maps and the other nodes that draw in the browser draw while the
  dataflow is open.
- An Autark node that only loads data (a `data` section, with no map, plot or
  compute step) runs on the server, like a code node.
- A node that needs data only the browser makes (an Autark compute node, a
  Spatial Join) runs, with the nodes below it, in a tab. The tab that
  started the run runs them by itself; otherwise opening the dataflow offers
  **Finish run**.
- While a run goes, **Run All** stops it. The run ends before its next node
  starts; a node already running finishes, and its result is not kept.

A dataflow opened while it runs shows the run going on. Opened afterwards in the
same browser, every node shows its output; in another browser, or after signing
in again, the nodes whose **Save output dataset** toggle is on do.

Guests, viewers of a shared dataflow, and a Curio started with `--no-project`
run dataflows in the browser, and a run stops when its tab closes.

### Running stale nodes automatically

**View > Run stale nodes automatically** turns on running after a change. A
change to a widget's value or a Parameter node's value then runs the nodes that
use it and the nodes below them, half a second after the last change, as a run
on the server. Moving a slider runs them once, after it stops. A change made
during a run waits for it to end, then runs once. **Run All** shows a small
bolt while it is on.

- The setting is saved with the dataflow and is off for a new one.
- Code you type, a new connection, and a selection in a chart do not start a
  run: the nodes they change wait for **Run** or **Run All**.
- It is offered where a run goes on the server: not to guests, viewers of a
  shared dataflow, a Curio started with `--no-project`, or a dashboard.

## Provenance

**View > Provenance** opens the dataflow's version history in a drawer on the
right. Each node or connection added or removed makes a version.

- The versions are listed in the order they were made, on a line that leads to
  the newest. Versions made from an earlier one you went back to fold under the
  version they left from; click the fold to show them.
- The pin keeps the drawer open when you click outside it or press Escape.

Click a version to open it: its thumbnail, when it was recorded, and its nodes
and connections. **Put this version on the canvas** goes back to it. The history
stays, the dataflow reads **Unsaved**, and the next change branches from that
version.

A node's **Provenance** button, in its header, lists the node's runs in the same
drawer, with the same folds. Each run reads what it took in and gave back
("In: DATAFRAME | Out: GEODATAFRAME", or ERROR for a run that failed). Click a
run to open it: when it ran, for how long, and its code. **Put this code back in
the node** puts that code in the node's editor without running it, and the
node's next run branches from that run.

## Widgets

A widget is a value a node's code reads that you set in a form, without editing
the code: a threshold, a season, a list of years. Python, Vega-Lite and Autark
nodes have them.

1. Open the node's **Widgets** tab (toolbox icon) and click **Add widget**.
2. Give it a name (letters, digits and underscores), a type, a label, and a
   default. A **Choice**, **Checkbox group** or **Multi-select** also takes its
   choices, separated by commas, and a **Choice** shows as a dropdown or as
   radio buttons. A **Number** can take a minimum, a maximum, a step and units;
   a **Slider** needs the minimum and the maximum.
3. Open **Widgets** above the code or spec and drag the widget's tag into it,
   or click the tag to insert it at the cursor. It appears as a chip; hover it
   to see the value it stands for.
4. Set the value in the **Widgets** tab and run the node.

| Type | Control | Value in Python |
|---|---|---|
| Number | a number field | a number, such as `2.5` |
| Slider | a slider between its minimum and maximum | a number |
| Text | a text field | a text, such as `"winter"` |
| Choice | a dropdown, or radio buttons | one of its choices |
| Checkbox | a checkbox | `True` or `False` |
| Checkbox group | a checkbox for each choice | the checked choices, such as `["water", "forest"]` |
| Multi-select | a list to add choices from | the chosen choices, as for a checkbox group |
| Date and time | a date and time field | a text, such as `"2026-06-21T12:00:00"` (local time) |
| Date | a date field, with a calendar | a text, such as `"2026-06-21"` |
| Location | a latitude and a longitude, or a place search | `{"lat": 41.8781, "lon": -87.6298}` |
| List of numbers | a field, such as `[1, 2.5]` | a list of numbers |
| List of texts | a field, such as `["a", "b"]` | a list of texts |
| Range | two numbers, the first not larger than the second | `[0, 5]` |
| Text file | a file you pick (up to 1,000,000 characters) | the file's text |

A checkbox group and a multi-select list their choices in the order the choices
are given. A location's place search finds a place by name, on Enter or
**Search**, through OpenStreetMap's Nominatim, and takes the center of the
place's box; only the coordinates are kept.

In the code, a widget is written `[!! name !!]`. When the node runs, each one is
replaced by its value:

- On its own, it becomes a value of the code's language: `season = [!! season !!]`
  runs as `season = "winter"` in Python, and `"opacity": [!! opacity !!]` as
  `"opacity": 0.5` in a Vega-Lite spec.
- Inside a quoted text, it becomes the value's text: `"Season: [!! season !!]"`
  runs as `"Season: winter"`.

Values are saved with the dataflow. Changing one marks the node as needing a
new run, so **Run** and **Run All** run it again, or the change runs it (see
[Running stale nodes automatically](#running-stale-nodes-automatically)). A name the node has no widget
for, or a marker in the older `[!! name$TYPE$default !!]` form, stops the run
with a message naming it; the **Widgets** tab lists them too.

Widgets are not connections: a value you set is not data from another node. Data
from the node's inputs reaches its code as `input_0`, `input_1`, and so on, one
variable per input circle, or through input chips (see
[Several inputs](#several-inputs)).

### Shared values: the Parameter node

A **Parameter** node holds one widget that any node can use, such as a season
that several nodes read.

1. Drag **Parameter** from the **Built-in** palette onto the canvas. Give it a
   name, a type, a label and a default, as for a widget, and click **Add parameter**.
2. Its tag, **@name**, shows under **Shared** above every node's code or spec
   and in every node's **Widgets** tab. Drag it into the code, or click it to
   insert it at the cursor. In the code it is written `[!! @name !!]` and drawn
   as an amber chip; it runs as a widget's value does.
3. Set the value in the Parameter node.

A Parameter node has no edges, and it lists the nodes whose code uses it.
Changing its value marks those nodes as needing a new run, or runs them when
the dataflow runs stale nodes automatically. **Edit** renames it,
and their code follows the new name. A reference to a name no Parameter node
has, or that two Parameter nodes have, stops the run with a message naming it.
Pinned to the dashboard, a Parameter node shows its value.

### Selection tags

A selection tag gives a node's code what you selected in a view: a brush or a
click in a Vega-Lite chart, or a pick or a brush in an Autark map or plot. The
code gets the ids of the selected rows. A selection of key values (see
[Linking charts](#linking-charts)) selects every row that holds them.

1. Run the view, so its rows are known.
2. In the node's **Widgets** tab, under **Selections**, click **Add selection**.
   Pick the view, and the column whose values identify its rows: `osm_id` or
   `building_id` when the rows have them, or any column whose values differ
   from row to row. A view whose rows have no such column is refused. Give the
   tag a name and click **Add selection tag**.
3. Open **Selections** above the code or spec and drag the tag,
   **selection name**, into it, or click it to insert it at the cursor. In the
   code it is written `[!! selection name !!]` and drawn as a peach chip.
4. Select in the view and run the node.

The reference becomes the list of the selected rows' ids, each once:

```python
picked = [!! selection buildings !!]
return input_0[input_0["osm_id"].isin(picked)]
```

runs as `picked = [101, 104]` when two buildings are selected, and as
`picked = []` when nothing is. The **Widgets** tab shows how many ids each tag
holds. A new selection in the view marks the node as needing a new run, and the
ids are saved with the dataflow. A tag holds at most 10,000 ids: a larger
selection stops the run with a message saying so.

A view is drawn again when it runs again and when the dataflow is opened. The
selection its tags hold then shows in it again, or the tags are emptied, so the
view and its tags agree:

- A Vega-Lite chart selects the rows that hold the tags' ids again with its
  point selection, as clicks on them would.
- A brush cannot be drawn again from ids. A chart whose selection is a brush,
  or that has a brush beside a point selection, empties its tags, and so does
  a chart none of whose rows holds the ids.
- An Autark node empties its tags each time it draws.

A node that reads an emptied tag needs a new run, which reads `[]`. A run that
started before the view was drawn again reads the ids the tag held when it
started.

## Several inputs

Python Computation, Data Transformation, JS Computation, Data Pool, Vega-Lite and
Autark nodes take several input edges, and so does a package node whose input port
allows more than one. Connect an edge to the node's input circle and a new empty
circle appears below it; each new edge takes the next circle. Circles are numbered
from 0, top to bottom. A Data Pool shows each input as a tab, and each frame of
an input that holds several, a Python tuple or a dict of frames, as a tab too: a
dict's tab is named after its key.

In code and in a Vega-Lite or Autark spec, each input is a chip:

1. Open **Inputs** above the code or spec: it shows a line for each input, in
   circle order, with its tag, **input_0**, **input_1**, and so on. The line
   says where the input comes from, its scenario box or else the kind the
   header of the node that feeds it shows, and, once that node has run, what it
   holds: **from Data Loading: 5 columns**, or **no columns** for an input that
   is not a table.
2. Drag a tag into the code, or click it to insert it at the cursor. It appears
   as a green chip, written `[!! input_1 !!]`.
3. Click the chevron at the start of an input's line to list its columns. The
   list opens under the line, and the lines below it move down. Several lists
   can be open at once, and each stays open on that node while the dataflow is
   open, with its input when the circles above it close up. Drag a
   column's tag where a column name goes; it is written
   `[!! input_1.population !!]`. Click the chevron again to close the list.
4. An input that carries several layers (an upstream Autark node's tables)
   lists a line for each layer: the layer's tag,
   `[!! input_1:table_osm_roads !!]`, then that layer's columns,
   `[!! input_1:table_osm_roads.lanes !!]`. A layer is named as the Autark node
   names its table.
5. An input that is a tuple, such as a Python node's `return means, peaks` or
   `return means, 3`, says how many values it holds:
   **from Python Computation: 2 values, a tuple**. In code, read them as
   `input_1[0]` and `input_1[1]`.
6. A Vega-Lite spec with an input also lists the line of **inputs**,
   `[!! inputs !!]`, the dataset that stacks its inputs
   ([Every input in one dataset](#every-input-in-one-dataset)). The color of the
   scenario box an input comes from is under **Scenarios**
   ([Scenario colors and order](#scenario-colors-and-order)).

When the node runs:

- In Python and JavaScript, an input chip becomes the variable that holds that
  circle's input: `[!! input_1 !!]` runs as `input_1` (see
  [Input names](#input-names)).
- In Python and JavaScript, a layer chip becomes that layer of the input:
  `roads = [!! input_0:table_osm_roads !!]` runs as
  `roads = curio_layer(input_0, "table_osm_roads", 0)`, which gives a GeoDataFrame
  in Python and a GeoJSON FeatureCollection in JavaScript. An input that is one
  frame with no layer name, such as a GeoDataFrame a Python node returns, is
  that layer. An input with several frames needs one of that name; if it has
  none, the node fails with a message naming the input and the layers it has.
- In a Vega-Lite or Autark spec, an input chip becomes the name the input is read
  by, `"input_1"`: a Vega-Lite dataset or an Autark table (see
  [Vega-Lite node](#vega-lite-node) and [Autark node](#autark-node)). A layer
  chip becomes the layer's name. On an input that is one frame with no layer
  name, such as a GeoDataFrame a Python node returns, it is that frame, as in
  code: `"dataRef": [!! input_0:roads !!]` becomes `"dataRef": "input_0"`. A
  GeoDataFrame that names its layer only in `gdf.metadata` is that frame too,
  whatever the chip names.
- A column chip becomes the column's name: `df[[!! input_0.population !!]]` runs
  as `df["population"]`, `"field": [!! input_0.population !!]` as
  `"field": "population"`, and inside a quoted text it is the plain name. In a
  Vega-Lite spec, a name with a `.` or a `[` in it is escaped where Vega-Lite
  reads a field: `"field": [!! input_0.rain.mm !!]` runs as
  `"field": "rain\\.mm"` (see [Vega-Lite node](#vega-lite-node)).
- In Python and JavaScript you can also type an input's name instead of
  dragging its chip: `input_0`, `input_1`, and so on, the names a Vega-Lite or
  Autark spec reads its inputs by too. `roads = input_1.to_crs(3857)` reads
  the input on circle 1. Because `input_0` names an input, no widget can take
  that name, nor `inputs`, which names every input's rows stacked
  ([Every input in one dataset](#every-input-in-one-dataset)).

A node with several inputs runs once every one of them has a value. Deleting an
edge closes the gap: the circles below it move up one, and their chips in the
code are renumbered, and so are typed names such as `input_2`. A chip or typed
name for the deleted input becomes `[!! input_? !!]` and stops the run until
you replace it. Deleting the edge of a node's only input, or of its last, moves
no circle, so the code is kept as written, and the next edge into that circle
is read by it. A chip for a circle with no edge, or for a column its input does
not have, is drawn in red and stops the run with a message naming it.

### Input names

In Python and JavaScript, each input circle is its own variable, named after the
circle:

| Circle | Variable | Holds |
|---|---|---|
| 0 (`in`) | `input_0` | what the edge on circle 0 delivers |
| 1 (`in_1`) | `input_1` | what the edge on circle 1 delivers |
| k (`in_k`) | `input_k` | and so on |

A circle's variable keeps its name when another edge is connected, so code that
reads `input_0.crs` keeps working beside a second input. A circle with no edge
is `None` (`undefined` in JavaScript), which lets a node take an optional
input, such as the mask on circle 1 of a Raster Calculator's statistics. Code that reads
its inputs when none has arrived stops with a message naming the circle.

A tuple a Python node returns leaves by its one output circle, so it is one
input: on circle 1 it is `input_1`, and `input_1[0]` is its first item. Several
edges into one circle, as a port that takes many has, are that circle's list,
in edge order.

[Example 26](examples/26-several-inputs.md) wires several inputs into each of
these node kinds, with a tuple on one of them.

## Scenarios

A scenario is a named selection of a dataflow's nodes, or the whole dataflow, used
to compare alternatives: the same analysis with buildings twice as tall, say. Its
boundary splits the dataflow into three parts:

- **Fixed context:** the nodes outside the scenario that it reads, through an edge
  into it or through a Parameter node's tag its code uses. The scenario takes their
  outputs as given. A node two alternatives share sits outside both, as their
  common context.
- **Levers:** the nodes in the scenario, which is what an alternative changes: its
  data loaders, widget values, code and specs, and the features it removes or
  changes by hand (see [The Map Edits node](#the-map-edits-node)).
- **Outcomes:** the outputs of the scenario's last nodes, which is what gets
  compared.

A node belongs to one scenario at most. A scenario of the whole dataflow has no
fixed context.

To make one:

1. Select its nodes: hold Shift and drag a box around them.
2. Choose **View → Save selection as scenario**, or **File → Save dataflow as
   scenario** for the whole dataflow.
3. To build an alternative, choose **View → Duplicate as scenario**. The
   selected nodes are copied below themselves with the edges between them, every
   edge entering the selection feeds the copy too, and the selection and the copy
   become two scenarios. **Duplicate selection** copies the nodes without making
   scenarios.

Then change the copy's levers: a widget value, a line of code. Each copy remembers
the node it was copied from.

The dataflow's scenarios are in the Scenario Catalog drawer's **In project** tab:
click **Scenario** in the top bar, then **In project**, which shows how many the
dataflow has. Saving a selection or duplicating it as a scenario opens that tab.
On top of it are **Save selection as scenario** and **Duplicate as scenario**,
and each scenario's card offers:

- **Run scenario**: run its levers, and of its fixed context only the nodes that
  have not run or have changed since;
- **Collapse** or **Expand**;
- **Add selected** or **Remove selected**: the nodes selected on the canvas
  before the drawer opened;
- **Delete**. Its nodes stay on the canvas.

**View details** on a card renames, recolors and describes the scenario, and
lists its fixed context, levers and outcomes. Pointing at a card marks the
scenario's fixed context on the canvas. In a dataflow someone shares with you,
the tab lists the scenarios without these controls.

On the canvas, an expanded scenario's nodes wear its color inside a frame, with its
name and a **Collapse** button above. A collapsed scenario is one box in its color
that lists its fixed context and its outcomes with their latest output. The edges
into and out of the scenario are drawn to the box, and dragging the box moves it.
Double-click the box to expand it. A collapsed scenario's nodes still run with
**Run All**, and the context they share runs once.

Defining a scenario saves the outputs of its fixed context and outcomes to your Data
Catalog, whatever their **Save output** setting, as pinning a dashboard tile does. A
chart or a Data Pool saves nothing itself: the node feeding it does. Scenarios,
their colors, descriptions, collapsed state and box positions are saved with the
dataflow. Deleting a node removes it from its scenario.

### The Map Edits node

The **Map Edits** node edits a map's layers on the map. It removes features,
changes their values, reshapes or moves them, draws new ones, and adds
properties and layers.

1. Connect the nodes that load your layers to Map Edits, and Map Edits to an
   Autark map.
2. Link them with an interaction edge, from the dot on top of Map Edits to the
   dot on top of the map, so a feature picked on the map is picked in Map Edits.
3. Pick a layer, then **Add**, **Edit**, **Remove** or **Add a property**. Pick
   features on the map with a click (shift-click adds more), or by a rule such
   as `height > 100`.
4. The map shows each edit at once, and **Commit edits** runs the nodes below
   with them.

Each edit is an entry in the node's list and in its Provenance drawer: switch it
off, delete it, or **Undo** and **Redo** it (Ctrl+Z and Shift+Ctrl+Z, Cmd on a
Mac). Edits find features by a column whose values differ in every feature, such
as `osm_id` or `building_id`, and an edit by `building_id` changes every part of
a building.

A rule or an expression reads a feature's columns by name (`height`, or
`` `Mean Acc shadow` `` in backticks). It takes numbers, quoted texts, `true`,
`false`, `null`, `+ - * / %`, `== != < <= > >=`, `and`, `or`, `not`,
parentheses, `abs`, `round`, `min` and `max`.

In a scenario, a Map Edits node is a lever.

### Comparing scenarios

To compare scenarios, connect each scenario's outcome to an input circle of its own
on a node outside the scenario boxes. Each edge takes the next circle, as on any
node with several inputs.

- **A chart.** A Vega-Lite node whose spec reads its inputs as the dataset its chip
  `[!! inputs !!]` names ([Every input in one dataset](#every-input-in-one-dataset)) draws every input's
  rows, each named by the scenario box its input comes from, and its scenario chips
  draw them in the boxes' colors and order
  ([Scenario colors and order](#scenario-colors-and-order)). The Scout package's
  charts, below, are such nodes.
- **The difference of two rasters.** A [Raster Calculator](#rasters) subtracts them
  cell by cell: `raster_calculate("subtract", [input_1, input_0],
  output_file=curio_output_file)` gives input_1 minus input_0, and with
  `absolute=True` the size of that difference, 0 where nothing changed. A cell that
  has no value in either raster has none in the difference, and the two rasters must
  lie on one grid.
- **The difference of two tables or layers.** A Python node joins the two inputs'
  rows on a column both have, such as `osm_id` or `building_id`, and subtracts their
  numbers:

  ```python
  before, after = input_0.set_index("osm_id"), input_1.set_index("osm_id")
  change = after[["sunlight"]] - before[["sunlight"]]
  return after.drop(columns=["sunlight"]).join(change).reset_index()
  ```

A raster's difference is a raster, which a Python node reads as a `rasterio`
dataset, and a layer's difference is a layer. To draw either on a map, connect the
node's output to an [Autark node](#autark-node), whose spec picks what the map colors
by, its scale and its legend's `title`. A signed difference of rasters reads best on a
diverging scheme centered on 0, and an absolute one on a sequential scheme:

```json
{
  "map": {
    "layerRefs": [
      {
        "dataRef": "[!! input_0 !!]",
        "getFnv": "band_1",
        "colorMapInterpolator": "interpolateRdBu",
        "colorMapCenter": 0,
        "title": "Shadow change (minutes)"
      }
    ]
  }
}
```

The Scout package (`curio.scout@1`) has fifteen charts that compare scenarios:
**Lines with a band**, **Curves by group**, **Bars with error bars**, **Ensemble
strips**, **Stacked bars with totals**, **Donuts**, **Weighted matrix**, **Dots with a
range**, **Bars**, **Grouped bars**, **Lines**, **Points**, **Pie**, **Lollipops** and
**Table**. Each is a Vega-Lite node that takes one input per scenario: connect each
scenario's outcome to one of its circles. Its spec reads its inputs as the dataset
`[!! inputs !!]` ([Every input in one dataset](#every-input-in-one-dataset)), every row named by
the scenario box its input comes from, and its scenario chips draw each scenario in its
box's color, in the order the dataflow lists the boxes. Set the columns it plots in its **Widgets** tab,
and the Vega-Lite aggregate Bars, Grouped bars, Lines, Pie and Lollipops combine a
scenario's rows with (**Combine**: `mean`, `sum`, `median`, `min`, `max` or `count`). A
new node's widgets hold their own names (`y`, `part`), so the chart says which column
its inputs lack until you set them. A new chart opens with its template's spec,
which you can edit. The [package's README](../packages/curio.scout@1/README.md) lists
each chart's widgets. Add the package to a dataflow from the Node Catalog drawer; the
charts are then under **Scout** in the Tools panel's **Node Catalog** dropdown.

The **Scenario Catalog** lists the scenarios of all your projects, each with its
fixed context, levers and outcomes and the results its project saved. Open it from
the **Scenario Catalog** tab, or from the **Scenario** button in the canvas's top
bar. Drag a scenario from the **Scenario** drawer onto the canvas to bring a copy
of it into the open dataflow: it arrives collapsed, with its results, and its
fixed context arrives as Data Loading nodes that read copies of what its project
saved. See [docs/SCENARIO-CATALOG.md](SCENARIO-CATALOG.md#4-using-a-scenario-in-a-dataflow).

## Node Catalog

Curio's nodes ship as **packages**: small, self-contained folders with a `manifest.json` declaring the node kinds inside. The built-in nodes (Data Loading, Vega-Lite, Autark, etc.) live in a pre-installed package called `curio.builtin@1`; you can install more via the **Node Catalog** drawer.

One Autark-specific note: an Autark node's document references incoming data by name. Each input is the table `input_0`, `input_1`, and so on, while a layer array from an upstream Autark node exposes each layer under its own table name. See [Autark node](#autark-node).

To open the drawer: in the **Tools panel** on the left edge of the canvas, find the **Node Catalog** dropdown (cube icon) and open it; the **Browse Node Catalog +** button sits in the dropdown's footer. From there you can:

- Browse the catalog and install new packages.
- See the packages added to this dataflow in the **In project** tab.
- Import a `.curio.zip` archive from the footer.
- Author your own package directly from the canvas: build the node, click the cog on its header, then **Save as package node…**. Edit per-package metadata later via the pencil button next to the export icon in the **Node Catalog** dropdown.

For the full guide, covering the storage layers, the action matrix, **Save as package node**, the metadata editor, exporting and importing, publishing, and versions, see [docs/NODE-CATALOG.md](NODE-CATALOG.md). The manifest format is specified in [docs/schemas/node-package.v4.json](schemas/node-package.v4.json), and the committed package catalog lives at `<repo_root>/packages/`.

## Vega-Lite node

The `Vega-Lite` node takes the rows of an upstream `DataFrame` or `GeoDataFrame`
and renders a spec against them. Columns are addressed by their bare pandas
names: a column `pop` is `{"field": "pop"}`. Vega-Lite reads a `.` or a `[` in a
field as a path into the row, so a column such as `rain.mm` is
`{"field": "rain\\.mm"}`, a backslash before each `.`, `[` and `]`. A widget or
column chip writes a name so where Vega-Lite reads a field: a `field`, a
`fold`, `groupby` or `flatten` list, the field a transform reads, a lookup's
`key` and `fields`, a selection's `fields` and a `repeat`'s lists. In a title,
a sort, an expression such as `datum['rain.mm']`, a name a transform writes
(`as`), or a row of `data` or `datasets`, it writes the name as it is. A
widget that holds the escaped name, `rain\.mm`, is written as it is.

### Several inputs

With one input, the spec draws it with no `data` block of its own. With several,
each input is the dataset `input_0`, `input_1`, and so on, in circle order. The
spec draws `input_0` unless it names another, and a layer, a concatenated view or
a lookup draws another input by naming it, written with that input's chip:

```json
{
  "layer": [
    {"mark": "bar", "encoding": {"x": {"field": "month"}, "y": {"field": "rain", "type": "quantitative"}}},
    {"data": {"name": [!! input_1 !!]}, "mark": "rule",
     "encoding": {"y": {"field": "normal", "type": "quantitative"}}}
  ]
}
```

A Python tuple arrives the same way, one dataset per frame. An input the chart
cannot read, such as a raster, stops it with a message naming its position.

Each input's geometry is handled in the views that draw it. A selection, a Data
Pool link and a direct link between charts cover the rows of `input_0`, and, in
a spec that reads `inputs`, that input's rows there, also when the spec reads
nothing else.

### Every input in one dataset

A spec that names the dataset `inputs` by its chip, `[!! inputs !!]`, in its own
`data`, a layer's, a concatenated view's or a lookup's, also reads every input's
rows in one table, in circle order. The chip writes the name `inputs`. It is for
a spec, not for Python or JavaScript code, and on a node with no input it is red
until you connect one. Each row has three more columns:

- `__input__`, the circle its input came in on;
- `scenario`, the id of the scenario box the node feeding that input is in,
  empty for a node in no box;
- `scenario_name`, that box's name, or the node's name for a node in no box.

```json
{
  "data": {"name": "[!! inputs !!]"},
  "mark": "bar",
  "encoding": {
    "x": {"field": "scenario_name", "type": "nominal", "sort": [!! scenario order !!]},
    "y": {"field": "sunlight", "type": "quantitative", "aggregate": "mean"},
    "color": {"field": "scenario_name", "type": "nominal", "scale": [!! scenario colors !!]}
  }
}
```

Over two inputs, one from a box named Baseline and one from a box named Twice
as tall, the rows read:

| `__input__` | `scenario` | `scenario_name` | `segment` | `sunlight` |
|---|---|---|---|---|
| 0 | s-base | Baseline | r1 | 6 |
| 0 | s-base | Baseline | r2 | 5 |
| 1 | s-tall | Twice as tall | r1 | 3 |

On a Vega-Lite node with an input, **Inputs** above the spec ends with the line
of **inputs**, after the lines of `input_0`, `input_1`. Its tag drags the
dataset's chip, `[!! inputs !!]`, and the line names the inputs it stacks and,
once they have run, how many fields these rows carry:
**input_0 and input_1, stacked: 5 fields**. Its chevron lists the fields under
the line: `scenario_name`, `scenario` and `__input__`, then every column of the
inputs but a GeoDataFrame's geometry, each with its type in its tooltip. An
input that carries layers adds no field. A field's chip,
`[!! inputs.sunlight !!]`, writes its name.

The inputs stack this way: a table keeps its rows, and a column one input
lacks is empty in its rows; a table with no rows is still a
table; a value (a number, a text, true or false, or a list of them) is one row
each under `value`, which only a spec that reads `inputs` takes, and a number
that is none (NaN) is a row with no value. The rows never carry geometry: a
GeoDataFrame's rows are its other columns, so it stacks beside a plain table
and in any coordinate system. Draw a map from the input's own dataset,
`input_<k>`. A table beside a value, an input with no value, an input that
already has a `scenario` or `scenario_name` column, and one input that carries
several tables (a tuple, or a list of DataFrames) or an Autark node's several
layers stop the chart, with a message naming the input: with one input wired,
everything that input carries is its own. A spec that does not name `inputs`
stacks nothing, and reads a tuple as before, one dataset per frame.

A notebook exported from the dataflow writes the same rows with
`stack_inputs` and `input_rows` from `utk_curio.sandbox.util.scenario_stack`,
so it runs where Curio is installed, and the spec with its scenario chips
written as the canvas writes them.

### Scenario colors and order

A chart draws exactly its spec. The scenario chips write the boxes' colors and
names into it, from the boxes its inputs come from:

| Chip | Writes | For |
|---|---|---|
| `[!! scenario colors !!]` | `{"domain": [names], "range": [colors]}` | the `scale` of a color, fill or stroke on `scenario_name` |
| `[!! scenario text_colors !!]` | the same scale, each color in its shade that reads on white | the `scale` of a text mark's color |
| `[!! scenario order !!]` | `[names]` | the `sort` of an axis, an offset or a facet on `scenario_name` |
| `[!! scenario input_1 !!]` | the color of input_1 in that scale | a map layer's `color`, or a mark's, inside quotes or standing on its own |

The boxes come in the order the dataflow lists them, each once, and each input
from no box comes after them, named by its node, in a gray of its own, so two
of them stay apart. Two boxes named alike, or untitled nodes of one kind in no
box, are one name. When no input comes from a box, `[!! scenario colors !!]`
and `[!! scenario text_colors !!]` write the names alone, `{"domain": [names]}`,
and the chart's own palette colors them.

The chips' tags are under **Scenarios** above the spec, on a node with an input
from a scenario box:

- In a Vega-Lite spec, first one tag that inserts `[!! scenario colors !!]`: a
  swatch with its name for each box, then each input from no box in its gray.
  Then **text colors** and **order** for the other two.
- In a Vega-Lite or an Autark spec, a tag for each input, such as
  **input_1 ■ Twice as tall**, which inserts `[!! scenario input_1 !!]`. Its
  swatch is the color the chip writes: its box's, or the gray of an input from
  no box.
- An Autark spec lists the inputs' tags alone, each a layer's color.

Dropped or clicked where a value goes, an input's tag under **Scenarios** writes
its chip in quotes, `"[!! scenario input_1 !!]"`, as the **inputs** tag and a
field of it do, so the spec stays JSON. The tag of an input itself, under
**Inputs**, writes `[!! input_1 !!]` with no quotes. A node with no input from
a box has no **Scenarios**, and the hover of a scenario chip in its spec says
what the chip writes there.

Renaming or recoloring a box, or drawing one around a node that feeds the chart,
draws the chart again with what its chips write then, with no run. A map takes
the new colors at its next run. A spec without the chips draws in Vega-Lite's or
Autark's own colors, and the chips are for a spec: Python and JavaScript code
does not take them.

### Drawing a GeoDataFrame

Return a `GeoDataFrame` from a Python node and draw it with `mark: "geoshape"`.
No conversion step is needed:

```python
import geopandas as gpd

gdf = gpd.read_file(curio_data_path("data.utk.chicago-boundary"))
return gdf
```

```json
{
  "mark": "geoshape",
  "encoding": { "color": { "field": "zip", "type": "nominal" } }
}
```

Two things are filled in for you, and only when you have not written them
yourself:

- **`encoding.shape`** is wired to the frame's *active* geometry column.
- **`projection`** is added and fitted to the data: `mercator` for lon/lat
  coordinates, `{"type": "identity", "reflectY": true}` for a projected CRS
  such as EPSG:3395. An explicit `projection` of your own is never replaced.

### Several geometry columns

A `GeoDataFrame` can hold more than one geometry column, each under its own
pandas name. The active column is wired automatically; name any other
explicitly:

```json
{ "shape": { "field": "centroid", "type": "geojson" } }
```

A `geoshape` mark draws a `Point` as a small filled circle. If a spec asks for
`geoshape` and the node cannot tell which column to draw, it says so in the node
body and lists the candidates.

If you paste a spec into a vanilla Vega editor, add the projection yourself.
An interval brush on a map with a projection selects nothing in the views
linked to it; a point selection does.

Geometry is attached only when the spec draws it; a bar chart over a
`GeoDataFrame` sees its non-geometry columns.

Worked example: [GeoDataFrame maps in Vega-Lite](examples/12-vega-lite-geodataframe-maps.md).

### The starter spec

A newly dropped `Vega-Lite` node opens **empty**. When an input arrives, and
only while the spec buffer is still empty, the editor fills with a complete
starter spec chosen from the input's column types. It never overwrites anything
you have typed or anything written into the node for you (by an agent, or by
dropping a dataset on it), and it never runs the node: you still press play.

Connecting an edge is not enough on its own. An edge carries no column types
until the upstream node has actually produced output, so a connected-but-unrun
node stays empty and says *"Run the node feeding this one"*. The spec appears
the moment that run finishes.

Columns are classified by pandas dtype:

| pandas dtype | role |
|---|---|
| `geometry`, the frame's active geometry column, or the one `DataFrame` column that holds geometries | geometry |
| `datetime64[*]`, `period[*]`, `timedelta64[*]` | temporal |
| `int*`, `uint*`, `float*` | quantitative |
| `bool`, `object`, `str`, `string`, `category` | nominal |
| `__row_index__`, `interacted`, and nominal columns with one distinct value per row (identifiers) | ignored |

The first matching rule wins:

| the input has | you get |
|---|---|
| geometry + at least one quantitative | `geoshape` choropleth, coloured by the first quantitative column |
| geometry only | `geoshape`, no colour |
| temporal + quantitative | `line`, time on x |
| nominal + quantitative | `bar`, **explicitly aggregated** with `mean` |
| two or more quantitative | `point` scatter of the first two |
| one quantitative | `bar` histogram: binned x, `count` y |
| a nominal column | `bar` of counts |
| nothing usable | the editor stays empty |

### Linking charts

An interaction edge carries selections between two views, never data. Draw one between the top handles of two charts, maps or plots, and a selection in either highlights the matching rows in the other. The receiving view marks each of its rows in a column named `interacted`, `"1"` when selected and `"0"` otherwise, and styles the marked rows through its spec, for example `"color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"}`. A selection only restyles the rows; the view is not redrawn, and its own selection stays where it is. A chart styles its own selection by the selection's name, for example `{"param": "brush", "empty": false, "value": "red"}`.

Link the views through a Data Pool instead when a Simple View shows the selection, when selections are combined with Merge (AND) or Merge (OR), when a Vega-Lite chart marks its own selection in `interacted`, or when three or more views share one selection. Draw an interaction edge from each view to the pool, and feed the views from the pool: the pool marks the rows the selections pick, and every view it feeds receives the marked rows.

Removing an interaction edge, or a node at either end, removes the highlight it gave.

A point selection over fields (`"select": {"type": "point", "fields": ["unit_id"]}`) sends the values of the points picked, such as `{"unit_id": 103}`, and the receiving chart marks every row that holds them, in whatever order it holds its rows. A point selection without fields matches rows by position, so both charts must read the same rows in the same order. An interval selection matches by column name, so the receiving chart needs the columns the interval names.

When several selections reach a Data Pool, the two selects at the top of the pool decide which rows it marks. **Conflict inside visualization** combines the selections of one chart, and **Conflict between visualizations** combines the latest selection of each linked chart:

- **Overwrite**: the most recent selection alone.
- **Merge (AND)**: the rows every selection picked. A chart with nothing selected is left out.
- **Merge (OR)**: the rows any selection picked.

The chosen modes are saved with the dataflow.

An Autark map takes part the same way: a selection highlights its features, and a pick on the map, or a selection in an Autark plot, is a selection the others receive.

A Map Edits node and the map it edits on are linked the same way, by an interaction edge that carries selections both ways: a feature picked on the map is picked in the node, and what the node picks lights up on the map.

An Autark view names the columns that identify its rows with `selectFields`, on the pickable map layer or on the plot. A pick or a brush on it then sends their values, as a point selection over fields does, and a feature that holds none selects nothing. Without `selectFields`, it matches rows by position.

```json
{"map": {"layerRefs": [{"dataRef": "input_0", "isPick": true, "selectFields": ["unit_id"]}]}}
```

The values are read from the node's input, so the table must come from an input, not from the document's own `data` section, and each column must be one its features have; otherwise the run fails and says which. The map highlights the feature picked, while a Vega-Lite chart highlights every mark that holds the value picked.


## Autark node

The `Autark` node draws an Autark document: map layers or a plot, and GPU
compute over tables. A table comes from the document's own `data` section (an
OSM extract, a GeoJSON or CSV file) or from the node's input. The document
writes no `data` entry for its input; it names the tables the input provides.

Each feature of an OpenStreetMap layer the node hands on has its OpenStreetMap
id in `osm_id`, and a building's parts share its `building_id`.

A node draws one view: one map or one plot. A document with a map and a plot,
or whose `map` or `plot` lists more than one, does not run, and the node's
error says to put each in its own `Autark` node and link them with interaction
edges (see [Linking charts](#linking-charts)).

### Its input

- Each input is the table `input_0`, `input_1`, and so on, in the order of the
  node's input circles: a `GeoDataFrame`, a GeoJSON FeatureCollection, or a
  `DataFrame` with a geometry column. An input chip, `[!! input_1 !!]`, writes
  the name for you. A frame that arrives under its own name (a Data Pool tab, a
  compute step's layer) keeps that name, and `input_<k>` also names it.
- Several layers keep their own names: a Python tuple, a Python dict of frames
  (each frame named after its key), a Data Pool with tabs, or the tables of an
  upstream Autark node. A layer without a name is named after
  its position, `input_0`, `input_1`, and so on. When two inputs bring a layer
  of one name, the name means the first input's layer. The second input's layer
  is still its `input_<k>` when it is the only layer that input brings, and is
  left out otherwise; the node's message says which.
- Of its input, the node loads only the tables its document names: its map's
  layers, its plot's table and the map the plot links to, and the tables its
  compute blocks read. A layer of an OpenStreetMap load (`table_osm_roads`)
  brings that load's surface (`table_osm_surface`) when the input has it,
  loaded first, whether or not the document draws it. The layers of an
  OpenStreetMap download from the Discovery Catalog, named `parks`, `roads` and
  so on, bring its `surface` the same way.
- Autark clips every table after the first to the box around the first, and to
  the first's outline when it holds polygons. So a map of OpenStreetMap layers
  is cut to its load's area, and the tables one document draws lie in one
  area. Draw another area in its own node.
- A map draws only tables with geometry. A `DataFrame` is read through the one
  column that holds geometries; with none, or with several, the node draws
  nothing and says which. Return a `GeoDataFrame` with its active geometry set.
- A `GeoDataFrame` whose `metadata` names one of Autark's layer types loads as
  that layer: `gdf.metadata = {"layerType": "buildings"}` draws its rows as
  buildings, raised to their height. A building's height comes from `height`,
  else `building:height`, else `building:levels` (3.4 m a level); one with none
  of them stands 6 m high. The
  loader of an OpenStreetMap layer downloaded from the Discovery Catalog sets it.
- Coordinates are read in the CRS the frame declares. A frame with no CRS is
  read as EPSG:4326 when its coordinates look like longitude and latitude, and
  as EPSG:3395 otherwise, so declare a projected CRS to place it correctly.
- A row without a geometry stays in the table and draws nothing; a selection
  still lands on the row it names.
- A raster is a table too: a `rasterio` dataset from a Python node, or a raster
  another Autark node hands on. A map draws it as a raster layer coloured by one
  band, `{"dataRef": "input_0", "getFnv": "band_1"}`; its bands are `band_1`,
  `band_2`, and so on. Every cell with a value is drawn opaque, 0 included, in
  the layerRef's `colorMapInterpolator` (reds without one) from the band's lowest
  value to its highest, and a cell with no value is clear: the raster's nodata,
  or 0 when the GeoTIFF names no nodata. A raster with
  a `colorMapInterpolator` shows its legend, with that scheme and range;
  `"isColorMap": false` hides the legend and keeps the colours. It is drawn at
  its own size, cell for cell, up to 4096 by 4096 cells and 8192 on a side. A
  larger one is not drawn and the node says so:
  crop it in the node that makes it, for example with a rasterio window read or
  the `bounds` of `curio_load_data` (see the [Data Catalog](DATA-CATALOG.md)).
  It needs a CRS with an EPSG code and a north-up grid. A plot or a compute step
  does not read a raster.
- A raster the node hands on reaches a Python node as a `rasterio` dataset on
  the same grid: its bands, origin, cell size and CRS.
- A `data` section runs in the sandbox, where the input is not available: its
  `join` and `heatmap` sources cannot read the input. Join it in a Python node,
  or name it from a map, plot or compute block.

Before it runs, a node that reads its input says what a `Vega-Lite` node says:
connect a node, run the node feeding this one, the node feeding this one
failed, or what this input lacks. A node whose document loads everything it
draws only says it has not run yet. A run that ends on an input the node
cannot draw names the reason in the node body and in its error.

A map opens framed on what its layers draw: it looks straight down on their
middle, with all of them in view and a little room around them. Pressing R on
the map frames it again.

A map or a plot redraws on its own when new data reaches it, as a `Vega-Lite`
chart does: when a project opens with its input restored, and when the node
feeding it runs again. It does not redraw while it is being wired up or while
a run is going, and a selection only highlights it (see
[Linking charts](#linking-charts)). A data or compute step runs only when you
press play or run the dataflow. Without WebGPU nothing is drawn on its own;
pressing play says why.

### Layer titles and colors

A `layerRef`'s `title` names its layer in the legend. Without one, the legend
reads the layer's table: `input_0` for the node's input, `table_osm_roads` for
a table the document loads. Two layers of one map cannot have the same title.

```json
{
  "map": {
    "layerRefs": [
      {
        "dataRef": "input_0",
        "title": "Building height (m)",
        "getFnv": "height",
        "getFnvType": "quantitative",
        "colorMapInterpolator": "interpolateViridis"
      }
    ]
  }
}
```

A layer can also be drawn in one `color` (`"#d62728"`), with no legend. A
line layer takes a `width` in meters, and a polygon layer a `stroke` color, or
`"stroke": false` for no outline. A raster layer takes `colorMapReverse` to
run its scheme from its highest value to its lowest, `colorMapCenter` to put a
value at the middle of its scheme, and `transferFunction` for how opaque its
cells are; every cell with a value is opaque unless it says otherwise. A
layer colored by a number takes `colorMapRange`, `[low, high]`, to color from
`low` to `high` instead of from its own lowest value to its highest, so maps
that set the same range color a value alike.

A map draws its layers as its document writes them. To draw a layer in the
color of the scenario box its input comes from, write that input's scenario
chip as its color, which its tag under **Scenarios** above the spec drags in
([Scenario colors and order](#scenario-colors-and-order)):

```json
{"dataRef": "[!! input_1 !!]", "width": 80, "title": "Fastest route", "color": "[!! scenario input_1 !!]"}
```

The chip writes the box's color, and for an input from no box a gray of its
own. A box recolored gives the layer its new color on the map's next run.

### The starter document

A newly dropped `Autark` node opens **empty**, like a `Vega-Lite` node, and
fills itself the same way: when an input arrives, and only while the editor is
still empty, it fills with a complete starter document. It never overwrites
anything you have typed or anything written into the node for you, and it
never runs the node. Columns are classified as for the Vega-Lite starter.

The first matching rule wins:

| the input has | you get |
|---|---|
| two or more layers with geometry | a map with one layer per table |
| one layer with a quantitative column | a map coloured by the first quantitative column, `interpolateViridis`, its legend titled with the column |
| one layer with a nominal column | a map coloured by the first nominal column, `schemeTableau10`, its legend titled with the column |
| one layer with geometry only | a plain map |
| no geometry, or only rasters | the editor stays empty |

## Spatial Join node

The `Spatial Join` node pairs the rows of two GeoDataFrames whose shapes meet.
It has two input circles: **input_0**, the upper, blue one, and **input_1**,
the lower, green one. input_0 is the left side of the join and input_1 the
right. Either circle takes points, lines or polygons, and one node can feed
both.

Its body reads as a sentence, *Pair each input_0 row with the input_1 rows
it ...*, finished by the operation you pick. A point on an edge follows
[shapely](https://shapely.readthedocs.io/)'s rule for each:

| Operation | Pairs input_0's shape with input_1's when | A point on a polygon's edge |
|---|---|---|
| intersects (the default) | they share at least one point | pairs |
| within | input_0's lies inside input_1's | does not pair |
| contains | input_0's holds input_1's | is not contained |
| touches | they meet only along their edges | pairs |
| overlaps | two shapes of one kind share part of themselves, and neither holds the other | |
| crosses | a line runs through the other shape, partly inside and partly outside it | |
| nearest | input_1's is the closest to input_0's, ties included | |

The output is one of:
- **One row per pair**, the default: input_0's row and shape, with input_1's
  columns added. A column whose name input_0 already has comes in as
  `<column>_right`. A row with no pair is left out. `nearest` also adds
  `distance`, in meters.
- **Counts**: input_1's rows, each with `point_count`, the number of input_0
  rows paired with it.

When an operation can never match the shapes given, such as polygons within
points, the node says so and names the operation or the swap that would.
Example 25 runs every operation, one flow each
([Spatial Join operations](examples/25-spatial-join-operations.md)). On a
dashboard the node shows the output saved with the dataflow and never joins.

## Rasters

The **Raster Calculator** works on rasters: a `rasterio` dataset from a Python
node or the Data Catalog, or a raster an Autark node hands on. It is a node of
Scout (`curio.scout@1`), a package that ships with Curio: once the
package is in the dataflow (**Add to project** in the Node Catalog drawer), the
node is under **Scout** in the Tools panel's **Node Catalog** dropdown.
It is a Python node whose code is written for it when it
is dropped: input_0 minus input_1, with its other operations listed above it,
statistics among them. Return another call to change what it does. Connect the
rasters to its input circles, in order. The code imports the operations from
the package:

```python
from scout_rasters.raster_algebra import raster_calculate, raster_statistics

return raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)
```

A Python node of no package has no raster operations, so a raster step is a
Raster Calculator node. A node of another package uses them when its package
names Scout in `dependencies.packages` (see the
[package's README](../packages/curio.scout@1/README.md#raster-math-in-another-package)).

**Cell by cell**, an operation over rasters on one grid gives a raster, which
`output_file=curio_output_file` writes where the node writes its files:

| operation | result |
|---|---|
| `raster_calculate("add", [input_0, input_1], output_file=curio_output_file)` | input_0 plus input_1 |
| `raster_calculate("subtract", [input_0, input_1], output_file=curio_output_file)` | input_0 minus input_1 |
| `raster_calculate("multiply", [input_0, input_1], output_file=curio_output_file)` | input_0 times input_1 |
| `raster_calculate("divide", [input_0, input_1], output_file=curio_output_file)` | input_0 over input_1; a cell divided by 0 has no value |
| `raster_calculate("choose", [input_0, input_1, input_2], codes=[21, 31], output_file=curio_output_file)` | input_1 where input_0's class is one of the codes, input_2 elsewhere |
| `raster_calculate("subtract", [input_1, input_0], absolute=True, output_file=curio_output_file)` | the size of input_1 minus input_0: how much each cell changed, 0 where it did not |

- `absolute=True` gives the size of any operation's result; a cell with no
  value keeps none.
- A cell with no value (the raster's nodata, or a number that is not finite) in
  an input the operation reads there has no value in the result. In `choose`, a
  class with no value is no class, so its cell takes input_2.
- The rasters must share their size, origin, cell size and CRS; otherwise the
  node stops and describes both grids. Bands are computed one by one; a class
  raster of one band applies to every band.
- The result keeps the inputs' number type, at least float32, so a float64
  raster keeps every digit. Its cells with no value are NaN.

**Statistics** give a raster's `mean`, `median`, `min`, `max` and `count` over
its cells with a value, as a table of one row, for example for a chart that
compares scenarios. `raster_statistics(input_0, band=2)` reads another
band. A condition keeps only some cells:

| call | counts |
|---|---|
| `raster_statistics(input_0, where=lambda value: value < 1.08)` | the cells whose value is under 1.08 |
| `raster_statistics(input_0, where=lambda value: (value >= 2) & (value < 5))` | the cells from 2 up to 5 |
| `raster_statistics(input_0, mask=input_1, mask_values=[0])` | with a second raster on input_1, on the same grid: the cells where its value is 0 |
| `raster_statistics(input_0, mask=input_1, where=lambda height: height < 1.08)` | with a second raster on input_1: the cells where its value is under 1.08 |

`where` receives the values as an array, with NaN for a cell with no value, and
a cell with no value is never counted.

**A layer** (a GeoDataFrame) on an input circle is no raster: the node's code
reads it as zones or a mask, for example with `rasterio.features.rasterize` on a
raster's grid. The Quad Cities flood test dataflow's Average depth by period
reads the riverside tracts and the waterways that way.

## Notebook view

The **Canvas | Notebook** switch, at the right of the canvas bar beside **Monitor**, shows a dataflow two ways. **Notebook**
lists the same nodes as a column of cells across the page, one under the other, and the
page scrolls.

- **Order.** A cell comes after every cell it reads from, in the order **File → Export as
  notebook** writes: each cell is followed by the cells it feeds, the most recently
  connected first, before the next cell that reads from nothing.
- **Cells** grow with their code and output, and cannot be resized, minimized or
  deleted. A cell's header and its other buttons are its node's (see
  [Inside a node](#inside-a-node)). A code cell shows its code with its output below;
  a Vega-Lite or Autark cell shows its spec above its chart or map. An editor is as tall
  as its lines, from three lines up to 400 pixels for code and 240 for a spec, and
  scrolls inside past that. A chart is 320 pixels tall and an Autark map or plot 400. A
  code output takes its own height up to 320 pixels, a table or a summary up to 360,
  and scrolls inside past it.
- **Connections** run in the bar to the right of the cells. Each cell has its dots on its
  right edge: its inputs at the top, numbered as their chips are (dot 0 is
  `[!! input_0 !!]`), its interaction dot halfway down, and its output at the bottom.
  The dots follow their cell as it grows. Hover a dot to see what feeds it. Selecting
  a cell rings it in its kind's color and darkens its connections.
- **Editing.** Nodes and connections are added and removed on the canvas: the notebook
  view has no node rail, takes no drop, its dots do not connect, and Delete removes
  neither a cell nor a connection there. In it, edit and run a cell's code. **Run all**
  sits at the top right of the page.
- **Nothing is saved** about the view: the dataflow keeps its canvas layout, and
  **Canvas** shows it as it was. The address carries the view (`?view=notebook`), so a
  reload, or the address copied from the browser, opens it the same way.

## Dashboards

A dataflow's dashboard is a page of its own at `/dashboard/<dataflow id>`: the nodes you
pinned, and nothing else. Anyone with the link can open it, and the tiles draw without
running anything.

- **Pin** the nodes to show, with the pin control in each node's header. Pinning saves
  the dataflow, and saves the outputs feeding those nodes to your Data Catalog, which is
  what the page draws from later.
- **Open** it from **Share → Open dashboard**, which opens a new tab. The same menu
  copies either link.
- **Save the dataflow** after changing anything else the page shows, such as a chart's
  spec: the page shows what is on disk.
- **Edit layout** (the owner, signed in on this browser) unlocks the tiles to drag by
  their title band and resize, and **Save layout** records where they sit, without
  touching the canvas positions.
- **Scenarios** each get a column, framed under a header in the scenario's color. The
  tiles they share (their fixed context, and pinned Parameter nodes outside them) come
  first, and tiles that read their outcomes, such as a comparison, come last. Tiles
  without a saved place are laid out this way when the page opens; while editing the
  layout, **Arrange by scenario** puts every tile back in its column.
- **Sharing**: the page is served with its data inside it, whether `--backend-url` is an
  address or a path such as `/api`, so a viewer needs no account and the dashboard keeps
  working if the server is unreachable. It is read-only for everyone but its owner.

Two dashboards cannot be served this way: one whose data is too large to travel with the
page (25 MB), and one with a pinned Autark tile that loads its own data. Opening either
shows why, naming the nodes to change, and draws nothing. For the second, move the tile's
`data` section into its own node upstream so its output is saved.

An Autark map tile draws in the viewer's browser, so it needs WebGPU there. A map over a
raster draws too: the raster travels with the page, and its size counts toward the 25 MB.
A code node's console output is not restored: no saved dataset carries it.

## Finding a dataflow

The **Projects** page lists your dataflows next to the ones that ship with Curio, and
the rail on its left filters them. Pick one entry in each section; the sections
combine, and **All dataflows** clears them.

| Section | What it holds |
|---|---|
| **Your dataflows** | the ones you created, imported or duplicated |
| **By source** | Use cases, Examples and Tests that ship with Curio |
| **Tags** | the tools a dataflow uses, such as Autark, Vega-Lite, GeoPandas, Pandas, GPU compute, Computer vision and SCOUT, plus tags you add |
| **Data type** | the data it works on, such as Tables, Geometries, Imagery, OpenStreetMap, Rasters, Video and Audio |
| **City**, **Topic**, **Complexity** | what you or Curio set for the dataflow |

A dataflow file opened with **File → Load dataflow** is a new dataflow: saving it adds it to
your dataflows under its own name, and the dataflow that was open stays as it was.

Tags and data types come from the dataflow and from what it uses: the libraries its code
imports and the files it names, the grammar each node draws with, the type of each model
it runs (a segmentation model gives Computer vision and Imagery), the format of each
dataset (a GeoTIFF gives Rasters), and the tags and data types its packages, models and
datasets declare in their manifests' `dataflowCategories` (SCOUT's give SCOUT). A package
or dataset of your own can declare them too ([Authoring nodes](AUTHORING-NODES.md#tags-and-data-types),
[Data Catalog](DATA-CATALOG.md#7-the-manifest)), and a new name adds an entry to the
rail. They change when you save, and cannot be removed by hand. Add a tag, a
city, a topic or a complexity with **+ Category** under the dataflow's title on the
canvas, which saves with the dataflow, or with **Edit categories** on the Projects page.

## Data Catalog

Datasets have their own catalog, built on the same model as the Node Catalog: a **dataset** is a folder with a `manifest.json` and its data file, identified as `<datasetId>@<major>` (e.g. `data.utk.chicago-boundary@1`). Curio ships twenty datasets in the committed catalog at `<repo_root>/datasets/`.

Three surfaces manage datasets:

- The **Data Catalog drawer** inside the canvas. Open it from the **Data Catalog** button in the top bar, or from the **Data Catalog** dropdown in the left Tools panel via **Browse Data Catalog +**. Add datasets to the open dataflow, import files from your machine, or delete.
- The **Data Catalog** dropdown in the Tools panel, listing the datasets added to the open dataflow and, under **Saved outputs**, the outputs its nodes saved. Drag one onto the canvas to create (or extend) a node with generated loader code.
- The **`/catalog/data`** page, the library view for your whole account, reached from `/projects` and the **Data Catalog** tab. **Add to all projects** there adds a dataset to every dataflow you have.

A node can also save its output as a **computed dataset** in your account (the database toggle among the buttons in its header), so its result can be reused as an input elsewhere.

The shared catalog root defaults to the `datasets/` folder Curio ships, which a pip install keeps inside `site-packages`, so pip installs should set **`CURIO_CATALOG_ROOT`** (or `--catalog-root`) to a writable, persistent path.

> [!NOTE]
> `CURIO_CATALOG_ROOT` relocates the **dataset** catalog only. The shared *node
> package* catalog is the `packages/` folder Curio ships, relocated with `--packages-root`.
> On a pip install that folder is inside `site-packages`, so author node packages
> from a git checkout (see [Authoring nodes](AUTHORING-NODES.md)).

For the full guide, covering the storage layers, the action matrix, computed datasets and lineage, previews, OSM PBF and GeoPackage imports, and publishing, see [docs/DATA-CATALOG.md](DATA-CATALOG.md).

## Discovery Catalog

The Data Catalog holds datasets you already have; the **Discovery Catalog** holds the places you can get more. It lists the open data portals this install can reach (Chicago's Socrata portal, data.gov.uk, ArcGIS Hub, São Paulo's GeoSampa, and a direct-link fallback), so you can search them and download a dataset into your Data Catalog instead of writing fetch code. The Dataset Finder uses it too: a candidate row it can download has a **Download** button that runs the same download. It also lists **storage sources**: folders on the Curio machine, public S3 buckets and Hugging Face dataset repositories, whose manifests declare how their files are organized. A folder of CSV files adds as one table; a folder of orthoimagery, video frames, photos and videos, or audio adds as one **collection** whose files stay where they are. And it lists **services**: OpenStreetMap downloads buildings, roads, parks, water and land surface for an area you give, as a box or as named areas, loaded by Autark; Mapillary and Google Street View download street-level images for a box, with your own key. **Hugging Face models** lists image segmentation models, and adding one puts it in your Model Catalog.

Sources are JSON manifests under `<repo_root>/discovery/`, relocated with **`--discovery-root`** the same way `--catalog-root` relocates the dataset catalog, and under `.curio/discovery/` for your own. Users cannot import one from the app.

For the full guide, covering searching, downloading, storage sources, collections, street-level images, models, API tokens step by step, and the Dataset Finder, see [docs/DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md).

## Model Catalog

The **Model Catalog** holds the trained models your nodes can run. A model is a package: its weights and the node that runs it. DDRNet23-Slim, which labels street photos with the 19 Cityscapes classes, ships with Curio, with an **Image Segmentation** node; models you add from the Discovery Catalog's **Hugging Face models** land here too, each with an Image Segmentation node of its own. A node runs the model its code names with `curio_load_model("<id>")`. Drag a model's card from the Model Catalog drawer onto the canvas to add its node, or onto a node to change the node's model for another of the same type. **Model Catalog** in the left Tools panel lists the models added to this dataflow, to drag the same way. **Save as package node…** on a node that loads a model makes a model package of your own, a copy of the model.

A node runs a model once the model's package is in your account: added from the Model Catalog (**Add to project** in its canvas drawer, **Add to all projects** on its page), or brought by a dataflow that names it, such as example 10. Shipped models are packages under `<repo_root>/packages/`, relocated with **`--packages-root`**; models you add from the Discovery Catalog are yours, in your package store.

For the full guide, covering runtimes, libraries, the manifest, and sharing a dataflow that names a model, see [docs/MODEL-CATALOG.md](MODEL-CATALOG.md).

## Agent Catalog

Agents are AI assistants you attach to your dataflow. The catalog lists four:

- **Researcher**: explains a node or the whole dataflow, diagnoses errors,
  helps you define what to build, answers questions from the web as
  [notes](#notes), and checks facts.
- **Node Builder**: builds a node or rewrites one's content, suggests nodes for
  a connection, and installs or writes the node packages your nodes need.
- **Dataflow Builder**: plans a whole dataflow, then solves its nodes.
- **Dataset Finder**: finds datasets in the Data Catalog and in portals.

What each does in chat, the tools it uses and the modes other agents ask it
for are in [AGENT-CATALOG.md](AGENT-CATALOG.md#the-agents). Each agent answers
with the LLM configuration chosen for it on the **Agent configuration** tab of
**API Settings** (above), else your default.

There are two scopes:

- **`/catalog/agents`**, the **Agent Catalog** tab, is your **account**.
  **Add to all projects** there adds an agent to every dataflow you have, and
  to every new one.
- **The Agent Catalog drawer**, opened on the canvas from the **Agent
  Catalog** button in the top bar or the **Agent Catalog** dropdown in the left Tools panel, adds an
  agent to **this dataflow**.

### Catalog settings

**Settings** on `/catalog/agents` holds values agents work with that are yours
to decide, such as the keyword types used to describe a dataflow. They belong
to your account and apply in every project. See
[Catalog settings](AGENT-CATALOG.md#catalog-settings).

### Attaching an agent

Drag an agent from the left rail's agents palette onto the canvas. Where you
drop it is what it attaches to:

- **a node**, for agents that reason about one node's content or output,
- **a connection**, for agents that reason about an edge between two nodes,
- **the canvas**, for agents that work over the whole dataflow.

An agent only accepts the targets its manifest declares, so dropping one
somewhere it does not belong is refused. Node
agents appear as a badge on their node; canvas and connection agents appear in
the dock at the top of the canvas.

### Working with an agent

Click an agent to open its chat panel. From there you can rename the
conversation, clear it, cycle through every attached agent with the ‹ › arrows,
and edit the initial intent the agent starts from. Agents that propose changes
(new nodes, edges, node content, packages) put them up for review first: nothing
lands on your canvas until you apply it.

The **Dataflow Builder** is the composite agent that plans a whole dataflow. Its
strip adds planning phases, per-node progress, and **Solve**, which fills in the
planned nodes in one batch: it runs each node's code in the sandbox, corrects
it when the run fails, and writes only code that ran. Applying a plan also
gives every created node a **Node Builder**, and every data-loading node a
**Dataset Finder**, which Solve asks for candidates when the node's source is
not settled. See [Solve](AGENT-CATALOG.md#solve) in the Agent Catalog guide.
A plan can also declare the widgets each node's code reads, and save
[scenarios](#scenarios), including a copy of one with a widget value changed;
see [Widgets and scenarios](AGENT-CATALOG.md#widgets-and-scenarios).

The goal box in the dock is shared with your agents: several of them, the
Dataflow Builder most of all, are written around knowing what the dataflow is
for. It is saved with the project.

### What an agent may reach

Agents run under a default-deny egress policy. Web fetches are restricted to
http and https, refused when a host resolves to a non-public address, capped in
body size and redirect count, and bounded per run. A refused fetch shows its
reason under the agent's reply.

The agents' web-search tool defaults to DuckDuckGo's keyless Instant Answer API.
Operators who would rather not send queries to a third party can point
`--agent-search-url` at their own provider, or elsewhere entirely.

For the full guide, covering the roster, the storage layers, attaching, the
provider, publishing, and writing your own, see [docs/AGENT-CATALOG.md](AGENT-CATALOG.md).

## Real-time collaboration

`curio start --collab` opens an opt-in Socket.IO channel that lets multiple signed-in users edit the same project simultaneously: presence indicators, per-node soft locks, code-change proposals with peer approval, and shared execution output. The feature is disabled by default and needs no rebuild to turn on.

See [COLLABORATION.md](COLLABORATION.md) for the full architecture, security model, setup instructions, and current limitations.

## Quick start

For a simple introductory example check [this](QUICK-START.md) tutorial. See [here](README.md) for more examples.

![Tutorial](images/final_result.png?raw=true)

