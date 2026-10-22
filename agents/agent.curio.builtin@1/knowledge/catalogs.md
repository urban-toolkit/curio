## Catalogs

Curio has six catalogs, each holding what the account that runs an agent has. An agent reaches each through the tools below that it has, and writes an id from a catalog exactly as a tool gave it, never from memory.

- Node Catalog: the node packages, each with its templates, the types a node is made from. A run that can place or plan nodes receives the templates this dataflow can use; packages.catalog lists the catalog's packages and whether this project has each, packages.resolve gives a package's dependencies, the packages it names, its permissions and the functions its modules define, and package.install proposes adding one to this project.
- Model Catalog: the trained models this account added, which node code loads with `curio_load_model("<id>")`. models.search lists them, each with the line that loads it.
- Data Catalog: the datasets this account holds, collections among them, which node code reads with `curio_load_data("<id>")`, `curio_data_path("<id>")` or `curio_load_collection("<id>")`. catalog.search lists them, each with the line that loads it when its file is here, and dataset.install proposes adding one to this project.
- Discovery Catalog: the data portals, storage, services and model sources this Curio connects to. discovery.sources lists the portals, discovery.search searches them, and discovery.acquire proposes downloading one resource into the Data Catalog, where it becomes a dataset.
- Agent Catalog: the agents. An agent that can hand a task to another is told which, and hands it over by the capability it delegates.
- Scenario Catalog: the scenarios saved in this account's projects. This dataflow's own scenarios, with their levers, fixed context and outcomes, are in dataflow.read.

A key node code sends to an API is saved in API Settings as a Node code key, under a name, for one host. Node code reads it only as `api_key = curio_secret("<name>")`, never as a value written in the code.

A run that writes code receives what this dataflow can use, as context data beside its task: its datasets and models, each with the line that loads it, the names of the account's Node code keys, and, for the node it writes, its template's whole description, its starter and the functions its code can import. Whatever that leaves out is counted there, with the tool that lists the rest when the run has it.
