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
- [Widgets](#widgets)
- [Scenarios](#scenarios)
- [Node Catalog](#node-catalog)
- [Vega-Lite node](#vega-lite-node)
- [Autark node](#autark-node)
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
| `--collab` | Real-time collaborative editing. Experimental, LAN-only |

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
| `--models-root PATH` | `<repo_root>/models/` | Where the shipped Model Catalog models are read from |
| `--save-node-outputs` / `--no-save-node-outputs` | off | Whether a new node's **Save output dataset** toggle starts on. Users can still flip it on each node |
| `--allow-publish` / `--no-allow-publish` | on | Whether the node and data catalogs allow Publish/Unpublish |
| `--testing` | off | Run against the dedicated test database under `.curio/test/` and mount the test-only `/api/testing/*` routes. Also the one exemption to `--deploy` requiring isolated execution. Never for a real instance: those routes reset the database and sign in as any user without a password |
| `--with-examples` | off | Seed the use cases, examples and tests from `docs/examples/` |
| `--reseed` | off | Force re-seeding catalog packages into the guest package store |
| `--exec-memory-mb` / `--exec-timeout` / `--exec-parallelism` | 4096 / 300 / half the host's cores, from 2 to 8 | Limits for isolated execution. `exec-memory-mb` is what a node may allocate on top of the interpreter its child starts with, with a floor of 64. The real host memory ceiling is `exec-memory-mb x exec-parallelism` |

`--deploy` turns on node-execution isolation, and refuses to start on a host that cannot provide it: isolation needs Linux and an unprivileged execution account, which the Docker image creates as `curio-exec`. Two environment variables override that, for test stacks and for an operator who wants it off: `CURIO_ISOLATION=off|fork` and `CURIO_EXEC_USER=<account>` (empty means none). `CURIO_ISOLATION=fork` is fail-closed: a host that cannot provide isolation refuses to start. See [ARCHITECTURE.md](ARCHITECTURE.md#isolated-node-execution-opt-in-linux-only).

**Hosts, ports, and diagnostics**

`--backend-host` / `--backend-port` (127.0.0.1:5002), `--sandbox-host` / `--sandbox-port` (127.0.0.1:2000), `--frontend-host` / `--frontend-port` (localhost:8080), and `--verbose N` (0=silent, 1=normal, 2=debug).

> [!WARNING]
> Leave `--sandbox-host` at `127.0.0.1` unless you are genuinely running the backend on another machine. The sandbox executes arbitrary node code and, while it requires a shared secret, there is no reason to offer that surface to the network.

> [!NOTE]
> `--force-rebuild` deletes `node_modules/`, `dist/` and `build/` and rebuilds from source, so it needs the frontend sources and a working npm; the Docker image ships only the built `dist/` and cannot rebuild in place.

Because these flags are set as environment variables on every start, putting the corresponding `CURIO_*` var in a `.env` has no effect when you launch through `curio.py`. Use the flag.

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

On a Curio started with `--deploy`, guests cannot add LLM configurations: every guest answers with the **guest configuration** the operator sets. Without `--deploy`, Curio signs you in as the shared guest, which adds configurations and saves its tokens in API Settings like any account; they are shared by everyone using that Curio, and the guest configuration is its Deployment default.

The guest configuration is set through environment variables in **`utk_curio/backend/.env`**. A `.env` at the repo root is read only by Docker Compose, for values like `BACKEND_URL` in `docker-compose.yml`; the backend does not read it.

```bash
GUEST_LLM_API_KEY=sk-...
GUEST_LLM_MODEL=gpt-4o-mini
GUEST_LLM_API_TYPE=openai_compatible   # openai_compatible | anthropic | gemini
GUEST_LLM_BASE_URL=                    # blank: the provider's own endpoint
```

Each one that is unset takes the matching `CURIO_DEFAULT_LLM_*` value (see the [deployment guide](DEPLOYMENT.md#llm-configurations)). A guest configuration needs both a key and a model; without either, agents refuse guest runs and say so.

**Examples:**

OpenAI:
```bash
GUEST_LLM_API_KEY=sk-proj-abc123...
GUEST_LLM_MODEL=gpt-4o-mini
```

Local Ollama server (it takes any key, so give it a placeholder):
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
4. In an Autark spec, an input that carries several layers (an upstream Autark
   node's tables) lists a tag for each layer, `[!! input 1:roads !!]`, followed
   by that layer's columns, `[!! input 1:roads.lanes !!]`.

When the node runs:

- In Python and JavaScript, an input chip becomes the input: `arg` when the node
  has one input, and `arg[1]` when it has several, counted in circle order.
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
  data loaders, widget values, code and specs.
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
- A `data` section runs in the sandbox, where the input is not available: its
  `join` and `heatmap` sources cannot read the input. Join it in a Python node,
  or name it from a map, plot or compute block.

Before it runs, a node that reads its input says what a `Vega-Lite` node says:
connect a node, run the node feeding this one, the node feeding this one
failed, or what this input lacks. A node whose document loads everything it
draws only says it has not run yet. A run that ends on an input the node
cannot draw names the reason in the node body and in its error.

A map or a plot redraws on its own when new data reaches it, as a `Vega-Lite`
chart does: when a project opens with its input restored, and when the node
feeding it runs again. It does not redraw while it is being wired up or while
a run is going, and a selection only highlights it (see
[Linking charts](#linking-charts)). A data or compute step runs only when you
press play or run the dataflow. Without WebGPU nothing is drawn on its own;
pressing play says why.

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
| no geometry | the editor stays empty |

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

A node can also save its output as a **computed dataset** in your account (the database toggle next to its play button), so its result can be reused as an input elsewhere.

Because the shared catalog root defaults to `<repo_root>/datasets/`, pip installs should set **`CURIO_CATALOG_ROOT`** (or `--catalog-root`) to a writable, persistent path.

> [!NOTE]
> `CURIO_CATALOG_ROOT` relocates the **dataset** catalog only. The shared *node
> package* catalog is `<install_root>/packages/`, relocated with `CURIO_PACKAGES_ROOT`.
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

