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
- [Inside a node](#inside-a-node)
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
| `--models-root PATH` | `<repo_root>/models/` | Where the shipped Model Catalog models are read from |
| `--packages-root PATH` | `<repo_root>/packages/` | Where the shared Node Catalog is read from and published to. Start it from a copy of `packages/`: the built-in nodes are installed from it |
| `--save-node-outputs` / `--no-save-node-outputs` | off | Whether a new node's **Save output dataset** toggle starts on. Users can still flip it on each node |
| `--allow-publish` / `--no-allow-publish` | on | Whether the node and data catalogs allow Publish/Unpublish |
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

Five large files are not in the pip package: the data of four Data Catalog datasets (Milan Mean Radiant Temperature, Project Sidewalk Chicago Labels, Chicago Red-Light Violations and Chicago Speed Camera Violations) and the Model Catalog's Deep Umbra model. Curio downloads each one from GitHub the first time something reads it: a preview in the Data Catalog, adding the dataset to a dataflow, or a node that loads it. Downloaded files go to `.curio/fetched/` in the folder you start Curio from.

Offline, reading one of those files fails with a message that gives its address on GitHub and the path to save it to. Download the file from that address on a machine that is online and copy it to that path, or install Curio from git, which holds every file.

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
5. Type a **Label**, choose the **Provider**, paste the **API key**, and type the **Model**, or click **Fetch models** and pick one. **Custom** also asks for the **Base URL**.
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

## Inside a node

A node's header shows **Play** at its left, the node's name and kind, and its run
status. Its other buttons show while the pointer is over the node or the node is
selected: the editor's tabs (code, widgets, spec, provenance, output), the **Save
output dataset** toggle, settings, about, pin, comments, delete and **Minimize**.
Code and specs sit in a gray box, and a code node's output is below its code.

Drag a node's bottom-right corner to resize it. A minimized node is a small chip;
click it to open the node again. Double-click a node where you would drag it, such
as its header, to zoom the view onto it.

## Running a dataflow

**Run All** runs every node. A node's **Play** button, or Ctrl+Enter (Cmd+Enter
on a Mac), runs that node and the nodes above it whose output is out of date.

On your own dataflow, a run saves the dataflow first and then runs on the
server, so it goes on when you close the tab. A dataflow you never saved is
saved under its title by its first run.

- Charts, maps and the other nodes that draw in the browser draw while the
  dataflow is open.
- A node that needs data only the browser makes (an Autark data or compute
  node, a Spatial Join) runs, with the nodes below it, in a tab. The tab that
  started the run runs them by itself; otherwise opening the dataflow offers
  **Finish run**.
- While a run goes, **Run All** stops it. The run ends before its next node
  starts; a node already running finishes, and its result is not kept.

A dataflow opened while it runs shows the run going on. Opened afterwards in the
same browser, every node shows its output; in another browser, or after signing
in again, the nodes whose **Save output dataset** toggle is on do.

Guests, viewers of a shared dataflow, and a Curio started with `--no-project`
run dataflows in the browser, and a run stops when its tab closes.

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
3. Drag the widget's tag from the strip above the code into the code, or click
   the tag to insert it at the cursor. It appears as a chip; hover it to see the
   value it stands for.
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
new run, so **Run** and **Run All** run it again. A name the node has no widget
for, or a marker in the older `[!! name$TYPE$default !!]` form, stops the run
with a message naming it; the **Widgets** tab lists them too.

Widgets are not connections: a value you set is not data from another node. Data
from the node's inputs reaches its code as `arg`, or through input chips (see
[Several inputs](#several-inputs)).

### Shared values: the Parameter node

A **Parameter** node holds one widget that any node can use, such as a season
that several nodes read.

1. Drag **Parameter** from the palette onto the canvas. Give it a name, a type,
   a label and a default, as for a widget, and click **Add parameter**.
2. Its tag, **@name**, shows under **Shared** in the strip above every node's
   code and in every node's **Widgets** tab. Drag it into the code, or click it
   to insert it at the cursor. In the code it is written `[!! @name !!]` and
   drawn as an amber chip; it runs as a widget's value does.
3. Set the value in the Parameter node.

A Parameter node has no edges, and it lists the nodes whose code uses it.
Changing its value marks those nodes as needing a new run. **Edit** renames it,
and their code follows the new name. A reference to a name no Parameter node
has, or that two Parameter nodes have, stops the run with a message naming it.
Pinned to the dashboard, a Parameter node shows its value.

### Selection tags

A selection tag gives a node's code what you selected in a view: a brush or a
click in a Vega-Lite chart, or a pick or a brush in an Autark map or plot. The
code gets the ids of the selected rows.

1. Run the view, so its rows are known.
2. In the node's **Widgets** tab, under **Selections**, click **Add selection**.
   Pick the view, and the column whose values identify its rows: `osm_id` or
   `building_id` when the rows have them, or any column whose values differ
   from row to row. A view whose rows have no such column is refused. Give the
   tag a name and click **Add selection tag**.
3. Drag the tag, **selection name**, from the strip above the code into the
   code, or click it to insert it at the cursor. In the code it is written
   `[!! selection name !!]` and drawn as a peach chip.
4. Select in the view and run the node.

The reference becomes the list of the selected rows' ids, each once:

```python
picked = [!! selection buildings !!]
return arg[arg["osm_id"].isin(picked)]
```

runs as `picked = [101, 104]` when two buildings are selected, and as
`picked = []` when nothing is. The **Widgets** tab shows how many ids each tag
holds. A new selection in the view marks the node as needing a new run, and the
ids are saved with the dataflow. A tag holds at most 10,000 ids: a larger
selection stops the run with a message saying so.

## Several inputs

Python Computation, Data Transformation, JS Computation, Data Pool, Vega-Lite and
Autark nodes take several input edges, and so does a package node whose input port
allows more than one. Connect an edge to the node's input circle and a new empty
circle appears below it; each new edge takes the next circle. Circles are numbered
from 0, top to bottom. A Data Pool shows each input as a tab.

In code and in a Vega-Lite or Autark spec, each input is a chip:

1. The strip above the code shows a tag for each input: **input 0**,
   **input 1**, and so on. Hover one to see which node feeds it.
2. Drag a tag into the code, or click it to insert it at the cursor. It appears
   as a green chip, written `[!! input 1 !!]`.
3. Click the arrow beside an input's tag to list its columns, once the node that
   feeds it has run. Drag a column's tag where a column name goes; it is written
   `[!! input 1.population !!]`.
4. An input that carries several layers (an upstream Autark node's tables)
   lists a tag for each layer, `[!! input 1:table_osm_roads !!]`, followed by
   that layer's columns, `[!! input 1:table_osm_roads.lanes !!]`. A layer is
   named as the Autark node names its table.

When the node runs:

- In Python and JavaScript, an input chip becomes the input: `arg` when the node
  has one input, and `arg[1]` when it has several, counted in circle order.
- In Python and JavaScript, a layer chip becomes that layer of the input:
  `roads = [!! input 0:table_osm_roads !!]` runs as
  `roads = curio_layer(arg, "table_osm_roads", 0)`, which gives a GeoDataFrame
  in Python and a GeoJSON FeatureCollection in JavaScript. An input that is one
  frame with no layer name, such as a GeoDataFrame a Python node returns, is
  that layer. An input with several frames needs one of that name; if it has
  none, the node fails with a message naming the input and the layers it has.
- In a Vega-Lite or Autark spec, an input chip becomes the name the input is read
  by, `"input_1"`: a Vega-Lite dataset or an Autark table (see
  [Vega-Lite node](#vega-lite-node) and [Autark node](#autark-node)). A layer
  chip becomes the layer's name.
- A column chip becomes the column's name: `df[[!! input 0.population !!]]` runs
  as `df["population"]`, `"field": [!! input 0.population !!]` as
  `"field": "population"`, and inside a quoted text it is the plain name.

A node with several inputs runs once every one of them has a value. Deleting an
edge closes the gap: the circles below it move up one, and their chips in the
code are renumbered. A chip for the deleted input becomes `[!! input ? !!]` and
stops the run until you replace it. A chip for a circle with no edge, or for a
column its input does not have, is drawn in red and stops the run with a message
naming it.

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
  changes by hand (see [Editing features by hand](#editing-features-by-hand)).
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

**View → Show scenarios** opens the Scenarios panel. For each scenario it shows
its fixed context, levers and outcomes, and lets you:

- rename it, recolor it and describe it;
- **Run scenario**: run its levers, and of its fixed context only the nodes that
  have not run or have changed since;
- **Collapse** or **Expand** it;
- **Add selected** or **Remove selected** nodes;
- **Delete** it. Its nodes stay on the canvas.

Pointing at a scenario in the panel marks its fixed context on the canvas.

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

### Editing features by hand

The **Edit Features** node removes features from a layer, or changes them, by hand:
two towers taken out of a city's buildings, say.

1. Drag **Edit Features** from the palette onto the canvas and connect a layer to it:
   a Python node's GeoDataFrame, or the layers an Autark node or a Data Pool hands on.
2. Pick the layer to edit in **Layer**, when the input carries several, and the column
   that identifies a feature in **Id**: `osm_id` or `building_id` when the layer has
   them, or another column whose values differ in every feature. A layer with no such
   column is refused: a feature's place in a layer is not an id. While the node has
   edits, the two menus stay as they are: delete the edits to pick another.
3. Double-click features on the node's map to pick them. **Picked** lists their ids.
4. Press **Remove**, **Restore**, or **Set value** with a column and a value. Each
   press adds an edit to the node's list, under the map: Remove drops the picked
   features, Set value writes the value into their column, and Restore puts them
   back as the input has them. The × beside an edit deletes it.
5. Run the node.

The edits apply in order, to every feature whose id is one of the edit's ids. A
building's parts share its `building_id`, so an edit by `building_id` applies to the
whole building, every part. The output is the edited layer, with the input's other
layers as they came; the input itself is never changed. An id no feature has is
reported in the node's output, and the run goes on.

The edit list is saved with the dataflow, and the node's code is written from it:

```python
return curio_edit_features(arg, [
    {"op": "remove", "ids": [119, 136]},
    {"op": "set", "ids": [42], "column": "height", "value": 30},
], key="building_id", layer="table_osm_buildings")
```

A change of the list writes the code again, and the node then waits for a run. In a
scenario, an Edit Features node is a lever, and **What differs** lists its edits.

### Comparing scenarios

The **Compare Scenarios** node compares scenarios' outcomes on the canvas:

1. Drag **Compare Scenarios** from the palette onto the canvas.
2. Connect each scenario's outcome to one of its input circles. Each edge takes the
   next circle, as on any node with several inputs, and each input is labelled by
   the scenario its node belongs to.
3. Run it. In **Chart** it stacks its inputs into one table, with the scenario's id
   in a `scenario` column and its name in a `scenario_name` column on every row. In
   **Difference** it subtracts one input from the other. What it makes is its
   output: other nodes can read it, and the node can be pinned to the dashboard.

The node shows **Difference** when it has two inputs that are rasters, or two that
are layers, once the nodes feeding them have run, and **Chart** otherwise. **Compare
as** switches it.

Its code is written for it, one line per input, reading the input through its chip
under its scenario's id and name. It is written again when an input changes, a
scenario is renamed or recolored, or the node switches between Chart and
Difference, and the node then waits for a run.

It stacks inputs of one kind:

- tables (a DataFrame, a GeoDataFrame, a list of records, a dict of columns, or a
  dict of values, which is one row), keeping their rows. A column one input lacks is
  empty in its rows.
- values (a number, a text, true or false, or a list of them), one row each under a
  `value` column.

An Autark node hands on every layer of its workspace. From such an input the node
reads the layer picked in **Layer**, in Chart and in Difference alike; the menu lists
the layers every such input has.

A table beside a value, a GeoDataFrame beside a plain table, two coordinate systems,
an input with no value, an input that holds several tables, or a raster stops the run
with a message naming the input.

In Difference it takes two inputs: input 0 is the reference and input 1 the
comparison, and every number it gives is the comparison's minus the reference's.

- Two rasters are subtracted cell by cell, band by band. A cell that is nodata in
  either is nodata in the difference. Both must lie on one grid, with the same size,
  origin, cell size and CRS; otherwise the run stops with a message naming both. Each
  is read as an Autark map reads a raster, at its own size, up to 2048 by 2048 cells.
- Two layers, or two tables, are matched row by row on a stable id: `osm_id`, else
  `building_id`, or the column picked in **Key**. Two layers with neither id are
  matched by their shapes: rows with the same geometry are one row, and a shape that
  repeats is matched in order. A row on both sides holds, in each
  number column both have, the difference, and a `change` column says `changed` or
  `unchanged`. A column of nested values, such as the `compute` values an Autark
  compute step writes, holds the difference of each number in it. A row only in the
  reference is `removed` and one only in the comparison `added`; their numbers are
  empty. The other columns and the geometry are the comparison's, or the reference's
  for a removed row. A key that is empty or repeated on one side stops the run, as
  does a layer beside a table.

A raster's difference is a raster, which an Autark map draws and a Python node reads
as a `rasterio` dataset.

The node has two tabs:

- **Chart** draws the stacked table in the scenarios' colors, as **Bars**, **Grouped
  bars**, **Lines**, **Points**, a **Pie**, **Lollipops** or a **Table**. Pick the
  columns it reads (**X**, **Y**) and how the Y values of a group are combined
  (**Combine**: mean, sum, median, minimum, maximum, or a count of rows).
- **Difference**, in its place in Difference, maps a raster's or a layer's
  difference, colored by a band or a number column, or by `change` (**Color by**).
  The legend is titled with what it shows: `sunlight change` for the column
  `sunlight`, or `change`. A raster's or a layer's colors run from the lowest
  difference, dark purple, to the highest, yellow; a raster cell that is nodata in
  either raster is clear. A table's difference is shown as a table, each
  row in the color of its change.
- **What differs** lists the levers that differ between the scenarios: for each, the
  widget values and the code lines that changed, read against the first scenario's,
  or, for an Edit Features node, each scenario's edits. A node and the copies made
  from it with **Duplicate selection** or **Duplicate as scenario** are one lever. A
  node with no copy in another scenario is listed as only in the scenarios that have
  it, with its edits when it is an Edit Features node.

Above both tabs it warns when the scenarios read different fixed context, naming the
inputs and the context only one of them reads, when an input comes from a node in no
scenario (its rows carry that node's name, and What differs leaves it out), and when
two inputs come from one scenario.

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
names: a column `pop` is `{"field": "pop"}`.

### Several inputs

With one input, the spec draws it with no `data` block of its own. With several,
each input is the dataset `input_0`, `input_1`, and so on, in circle order. The
spec draws `input_0` unless it names another, and a layer, a concatenated view or
a lookup draws another input by naming it, written with that input's chip:

```json
{
  "layer": [
    {"mark": "bar", "encoding": {"x": {"field": "month"}, "y": {"field": "rain", "type": "quantitative"}}},
    {"data": {"name": [!! input 1 !!]}, "mark": "rule",
     "encoding": {"y": {"field": "normal", "type": "quantitative"}}}
  ]
}
```

A Python tuple arrives the same way, one dataset per frame. An input the chart
cannot read, such as a raster, stops it with a message naming its position.

Each input's geometry is handled in the views that draw it. A selection, a Data
Pool link and a direct link between charts cover the rows of `input_0`.

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
Interval brushing over a projection does not propagate downstream:
Vega-Lite rewrites those selections to internal row ids, so no named columns
reach the Data Pool. Point selection works normally.

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

A selection in one chart highlights the matching rows in the charts linked to it. Link them with an interaction edge, either through a Data Pool or directly:

- **Through a Data Pool.** Draw an interaction edge between the chart and the pool, and feed the charts from the pool. The pool marks each row in a column named `interacted`, `"1"` when selected and `"0"` otherwise, and every chart it feeds receives the marked rows.
- **Directly.** Draw an interaction edge between two charts. The receiving chart marks its own rows the same way.

The receiving chart styles the marked rows through its spec, for example `"color": {"condition": {"test": "datum.interacted === '1'", "value": "red"}, "value": "blue"}`. A selection only restyles the rows; the chart is not redrawn, and its own selection stays where it is.

A point selection matches rows by position, so both charts must read the same rows in the same order. An interval selection matches by column name, so the receiving chart needs the columns the interval names.

When several selections reach a Data Pool, the two selects at the top of the pool decide which rows it marks. **Conflict inside visualization** combines the selections of one chart, and **Conflict between visualizations** combines the latest selection of each linked chart:

- **Overwrite**: the most recent selection alone.
- **Merge (AND)**: the rows every selection picked. A chart with nothing selected is left out.
- **Merge (OR)**: the rows any selection picked.

The chosen modes are saved with the dataflow.

An Autark map takes part the same way: a selection highlights its features, and a pick on the map, or a selection in an Autark plot, is a selection the others receive.


## Autark node

The `Autark` node draws an Autark document: map layers, plots and GPU compute
over tables. A table comes from the document's own `data` section (an OSM
extract, a GeoJSON or CSV file) or from the node's input. The document writes
no `data` entry for its input; it names the tables the input provides.

### Its input

- Each input is the table `input_0`, `input_1`, and so on, in the order of the
  node's input circles: a `GeoDataFrame`, a GeoJSON FeatureCollection, or a
  `DataFrame` with a geometry column. An input chip, `[!! input 1 !!]`, writes
  the name for you. A frame that arrives under its own name (a Data Pool tab, a
  compute step's layer) keeps that name, and `input_<k>` also names it.
- Several layers keep their own names: a Python tuple, a Data Pool with tabs, or
  the tables of an upstream Autark node. A layer without a name is named after
  its position, `input_0`, `input_1`, and so on. When two inputs bring a layer
  of one name, the second input's is left out and the node names both.
- A map draws only tables with geometry. A `DataFrame` is read through the one
  column that holds geometries; with none, or with several, the node draws
  nothing and says which. Return a `GeoDataFrame` with its active geometry set.
- A `GeoDataFrame` whose `metadata` names one of Autark's layer types loads as
  that layer: `gdf.metadata = {"layerType": "buildings"}` draws its rows as
  buildings, raised to their height. A building's height comes from `height`,
  else `building:levels` (3.4 m a level); one with neither stands 6 m high. The
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
  its own size, cell for cell, up to 2048 by 2048 cells and 8192 on a side. A
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

### Legend titles

A `layerRef`'s `legendTitle` titles the legend of its layer, on a vector or a
raster layer. Without one, a layer of the node's input (`input_0`) is titled
with the column it is coloured by (`getFnv`), and a table the document loads
itself keeps the table's name (`table_osm_roads`). `legendTitle` is Curio's own
key, not the Autark grammar's.

```json
{
  "map": {
    "layerRefs": [
      {
        "dataRef": "input_0",
        "getFnv": "height",
        "getFnvType": "quantitative",
        "colorMapInterpolator": "interpolateViridis",
        "legendTitle": "Building height (m)"
      }
    ]
  }
}
```

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
| one layer with a quantitative column | a map coloured by the first quantitative column, `interpolateViridis` |
| one layer with a nominal column | a map coloured by the first nominal column, `schemeTableau10` |
| one layer with geometry only | a plain map |
| no geometry, or only rasters | the editor stays empty |

## Rasters

Two nodes in the palette's computation group work on rasters: a `rasterio`
dataset from a Python node or the Data Catalog, or a raster an Autark node hands
on. Each is a Python node whose code is written for it when it is dropped; edit
the call to change what it does.

**Raster Calculator** computes one operation over rasters on one grid, cell by
cell. Connect the rasters to its input circles, in order:

| operation | result |
|---|---|
| `curio_raster_calculate("add", arg)` | input 0 plus input 1 |
| `curio_raster_calculate("subtract", arg)` | input 0 minus input 1 |
| `curio_raster_calculate("multiply", arg)` | input 0 times input 1 |
| `curio_raster_calculate("divide", arg)` | input 0 over input 1; a cell divided by 0 has no value |
| `curio_raster_calculate("choose", arg, codes=[21, 31])` | input 1 where input 0's class is one of the codes, input 2 elsewhere |

- A cell with no value (the raster's nodata, or a number that is not finite) in
  an input the operation reads there has no value in the result. In `choose`, a
  class with no value is no class, so its cell takes input 2.
- The rasters must share their size, origin, cell size and CRS; otherwise the
  node stops and describes both grids. Bands are computed one by one; a class
  raster of one band applies to every band.
- The result keeps the inputs' number type, at least float32, so a float64
  raster keeps every digit. Its cells with no value are NaN.

**Raster Statistics** gives a raster's `mean`, `median`, `min`, `max` and
`count` over its cells with a value, as a table of one row, for example for
**Compare Scenarios** to chart. `curio_raster_statistics(arg, band=2)` reads
another band. A condition keeps only some cells:

| call | counts |
|---|---|
| `curio_raster_statistics(arg, where=lambda value: value < 1.08)` | the cells whose value is under 1.08 |
| `curio_raster_statistics(arg, where=lambda value: (value >= 2) & (value < 5))` | the cells from 2 up to 5 |
| `curio_raster_statistics(arg, mask_values=[0])` | with a second raster on input 1, on the same grid: the cells where its value is 0 |
| `curio_raster_statistics(arg, where=lambda height: height < 1.08)` | with a second raster on input 1: the cells where its value is under 1.08 |

`where` receives the values as an array, with NaN for a cell with no value, and
a cell with no value is never counted.

## Notebook view

The **Canvas | Notebook** switch, at the right of the canvas bar beside **Monitor**, shows a dataflow two ways. **Notebook**
lists the same nodes as a column of cells across the page, one under the other, and the
page scrolls.

- **Order.** A cell comes after every cell it reads from, in the order **File → Export as
  notebook** writes: each cell is followed by the cells it feeds, the most recently
  connected first, before the next cell that reads from nothing.
- **Cells** grow with their code and output, and cannot be resized or minimized. A
  cell's header and buttons are its node's (see [Inside a node](#inside-a-node)). A
  code cell shows its code with its output below; a Vega-Lite or Autark cell shows
  its spec above its chart or map. An editor is as tall
  as its lines, from three lines up to 400 pixels for code and 240 for a spec, and
  scrolls inside past that. A chart is 320 pixels tall and an Autark map or plot 400. A
  code output takes its own height up to 320 pixels, a table or a summary up to 360,
  and scrolls inside past it.
- **Connections** run in the bar to the right of the cells. Each cell has its dots on its
  right edge: its inputs at the top, numbered as their chips are (dot 0 is
  `[!! input 0 !!]`), its interaction dot halfway down, and its output at the bottom.
  The dots follow their cell as it grows. Hover a dot to see what feeds it. Selecting
  a cell rings it in its kind's color and darkens its connections.
- **Editing.** Nodes are added and connected on the canvas: the notebook view has no
  node rail, takes no drop, and its dots do not connect. In it, edit and run a cell's
  code, delete a cell, or select a connection and press Delete to remove it. **Run
  all** sits at the top right of the page.
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
- **Edit layout** (owner only) unlocks the tiles to drag by their title band and resize,
  and **Save layout** records where they sit, without touching the canvas positions.
- **Scenarios** each get a column, framed under a header in the scenario's color. The
  tiles they share (their fixed context, and pinned Parameter nodes outside them) come
  first, and tiles that read their outcomes, such as a comparison, come last. Tiles
  without a saved place are laid out this way when the page opens; while editing the
  layout, **Arrange by scenario** puts every tile back in its column.
- **Sharing** works like a `/dataflow/<id>` link, read-only for everyone but the owner.
  The page is served with its data inside it, so a viewer needs no account and the
  dashboard keeps working if the server is unreachable.

Two dashboards cannot be served this way, and both say so when you open them: one whose
data is too large to travel with the page, and one with a pinned Autark tile that loads
its own data. For the second, move the tile's `data` section into its own node upstream
so its output is saved.

An Autark map tile draws in the viewer's browser, so it needs WebGPU there. A code node's
console output is not restored: no saved dataset carries it.

## Finding a dataflow

The **Projects** page lists your dataflows next to the ones that ship with Curio, and
the rail on its left filters them. Pick one entry in each section; the sections
combine, and **All dataflows** clears them.

| Section | What it holds |
|---|---|
| **Your dataflows** | the ones you created, imported or duplicated |
| **By source** | Use cases, Examples and Tests that ship with Curio |
| **Tags** | the tools a dataflow uses, such as Autark, Vega-Lite, GeoPandas, Pandas, GPU compute and Computer vision, plus tags you add |
| **Data type** | Tables, Geometries, Imagery, OpenStreetMap, Rasters, Video, Audio |
| **City**, **Topic**, **Complexity** | what you or Curio set for the dataflow |

A dataflow file opened with **File → Load dataflow** is a new dataflow: saving it adds it to
your dataflows under its own name, and the dataflow that was open stays as it was.

Tags and data types come from the dataflow itself: its nodes, the libraries its code
imports and the formats of its datasets. They change when you save, and cannot be
removed by hand. Add a tag, a city, a topic or a complexity with **+ Category** under
the dataflow's title on the canvas, which saves with the dataflow, or with **Edit
categories** on the Projects page.

## Data Catalog

Datasets have their own catalog, built on the same model as the Node Catalog: a **dataset** is a folder with a `manifest.json` and its data file, identified as `<datasetId>@<major>` (e.g. `data.utk.chicago-boundary@1`). Curio ships twenty datasets in the committed catalog at `<repo_root>/datasets/`.

Three surfaces manage datasets:

- The **Data Catalog drawer** inside the canvas. Open it from the **Data Catalog** button in the top bar, or from the **Data Catalog** dropdown in the left Tools panel via **Browse Data Catalog +**. Add datasets to the open dataflow, import files from your machine, or delete.
- The **Data Catalog** dropdown in the Tools panel, listing the datasets added to the open dataflow and, under **Saved outputs**, the outputs its nodes saved. Drag one onto the canvas to create (or extend) a node with generated loader code.
- The **`/catalog/data`** page, the library view for your whole account, reached from `/projects` and the **Data Catalog** tab. **Add to all projects** there adds a dataset to every dataflow you have.

A node can also save its output as a **computed dataset** in your account (the database toggle among the buttons in its header), so its result can be reused as an input elsewhere.

Because the shared catalog root defaults to `<repo_root>/datasets/`, pip installs should set **`CURIO_CATALOG_ROOT`** (or `--catalog-root`) to a writable, persistent path.

> [!NOTE]
> `CURIO_CATALOG_ROOT` relocates the **dataset** catalog only. The shared *node
> package* catalog is `<install_root>/packages/`, relocated with `--packages-root`.
> On a pip install that path is inside `site-packages`, so author node packages
> from a git checkout (see [Authoring nodes](AUTHORING-NODES.md)).

For the full guide, covering the storage layers, the action matrix, computed datasets and lineage, previews, OSM PBF and GeoPackage imports, and publishing, see [docs/DATA-CATALOG.md](DATA-CATALOG.md).

## Discovery Catalog

The Data Catalog holds datasets you already have; the **Discovery Catalog** holds the places you can get more. It lists the open data portals this install can reach (Chicago's Socrata portal, data.gov.uk, ArcGIS Hub, São Paulo's GeoSampa, and a direct-link fallback), so you can search them and download a dataset into your Data Catalog instead of writing fetch code. The Dataset Finder uses it too: a candidate row it can download has a **Download** button that runs the same download. It also lists **storage sources**: folders on the Curio machine, public S3 buckets and Hugging Face dataset repositories, whose manifests declare how their files are organized. A folder of CSV files adds as one table; a folder of orthoimagery, video frames, photos and videos, or audio adds as one **collection** whose files stay where they are. And it lists **services**: OpenStreetMap downloads buildings, roads, parks, water and land surface for an area you give, as a box or as named areas, loaded by Autark; Mapillary and Google Street View download street-level images for a box, with your own key. **Hugging Face models** lists image segmentation models, and adding one puts it in your Model Catalog.

Sources are JSON manifests under `<repo_root>/discovery/`, relocated with **`--discovery-root`** the same way `--catalog-root` relocates the dataset catalog, and under `.curio/discovery/` for your own. Users cannot import one from the app.

For the full guide, covering searching, downloading, storage sources, collections, street-level images, models, API tokens step by step, and the Dataset Finder, see [docs/DISCOVERY-CATALOG.md](DISCOVERY-CATALOG.md).

## Model Catalog

The **Model Catalog** holds the trained models your nodes can run. DDRNet23-Slim, which labels street photos with the 19 Cityscapes classes, ships with Curio; models you add from the Discovery Catalog's **Hugging Face models** land here too. An **Image Segmentation** node, from the Street Vision package, runs the model its code names with `curio_load_model("<id>")`: drag a model from **Model Catalog** in the left Tools panel onto the node to change it.

Shipped models are folders under `<repo_root>/models/`, relocated with **`--models-root`**; models you add are yours, under `.curio/users/<user-key>/models/`.

For the full guide, covering runtimes, libraries, the manifest, and sharing a dataflow that names a model, see [docs/MODEL-CATALOG.md](MODEL-CATALOG.md).

## Agent Catalog

Agents are AI assistants you attach to your dataflow. The catalog lists ten:
**Chat**, which explains a node or the whole dataflow, diagnoses errors and
helps you define what to build, and nine that build dataflows and nodes, find
data, connect nodes, research, and recommend or author packages. Each agent
answers with the LLM configuration chosen for it on the **Agent configuration**
tab of **API Settings** (above), else your default.

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
body size and redirect count, and bounded per run.

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

