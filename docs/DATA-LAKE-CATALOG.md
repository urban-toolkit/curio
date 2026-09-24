# Data Lake Catalog

The fourth catalog, beside the [Node Catalog](NODE-CATALOG.md), the
[Data Catalog](DATA-CATALOG.md) and the [Agent Catalog](AGENT-CATALOG.md).

The Data Catalog holds datasets you already have. This one holds the **places
you can get more**: open data portals and lakes. You browse a portal, download
what you want, and it lands in your Data Catalog as an ordinary dataset.

> **Status.** The catalog works end to end, by hand and through the agents.
> What remains is the end-to-end browser tests.

## 1. A source is a portal, not a dataset

Every other catalog's unit is a thing you can put on a canvas. This one's unit
is a **source connector**: a manifest describing a portal, what software it
runs, whether it needs a token, and what it is allowed to hand you. The
datasets inside are discovered live rather than committed, because a portal
holds thousands of them and they change without us.

```
datalakes/
  lake.cityofchicago.data-portal@1/
    manifest.json
    icon.png              # optional
  lake.uk.data-gov@1/
  lake.esri.hub-opendata@1/
  lake.saopaulo.geosampa@1/
  lake.curio.direct-url@1/
```

The root is `<repo>/datalakes`, overridable with `CURIO_DATALAKE_ROOT`. It is
never created eagerly: a deployment with no sources has no empty directory
suggesting otherwise.

### Source ids

`lake.<publisher>.<portal>`, three to six dot-separated lowercase segments,
with a mandatory `lake.` prefix. The prefix does the same job `agent.` does:
it makes a directory self-describing and makes a lake source impossible to
mistake for a dataset if the two roots are ever misconfigured onto each other.

**The provider type is deliberately not in the id.** `lake.socrata.chicago`
would bake a fact that lives in `provider.type` into an immutable coordinate,
and it is wrong the day a portal migrates from Socrata to CKAN - which
happens. Ids name *who publishes* the portal.

## 2. The manifest

Validated in `utk_curio/backend/app/datalakes/domain/manifest.py`, with a JSON
Schema at [`docs/schemas/data-lake-source.v1.json`](schemas/data-lake-source.v1.json).
A test asserts the two agree, deriving every assertion from the validator so
there is no third thing to keep in sync.

| Field | Required | Notes |
|---|---|---|
| `id` | yes | `lake.<publisher>.<portal>` |
| `name` | yes | What the card says |
| `version` | yes | The manifest's own version |
| `compatibility.major` | | Defaults to 1; forms the directory suffix |
| `description`, `publisher`, `homepage`, `license`, `tags` | | Display |
| `icon` | | A single `.png` filename in the source folder. See §5 |
| `provider.type` | yes | `socrata` \| `ckan` \| `arcgis` \| `wfs` \| `direct` |
| `provider.baseUrl` | yes* | https, no trailing slash. *Optional only for `direct` |
| `provider.options` | | Provider wiring. Never served to a client |
| `auth.mode` | | `public` \| `optional-token` \| `required-token` |
| `auth.secretId` | with a token | Names a credential *slot*, never a value |
| `auth.headerName` | with a token | The header the token is sent in |
| `auth.scheme` | | `header` only. See §6 |
| `auth.helpUrl` | | Where a user gets a token |
| `capabilities.search` / `describe` / `download` | | Default true |
| `capabilities.formats` | | What this portal may deliver |
| `capabilities.maxDownloadBytes` | | May *lower* the server ceiling, never raise it |
| `capabilities.allowOffBaseDistributions` | | See §4 |
| `limits.requestsPerMinute` | | Default 30 |

`capabilities.formats` is an **upper bound**. At download time it is
intersected with the Data Catalog's own `SUPPORTED_FORMATS`, so a manifest can
narrow what may be ingested but never widen it. The acquirable set is `csv`,
`geojson`, `json`, `parquet`, `geotiff` - narrower than the Data Catalog's,
because `shp` is meaningless without its sibling `.dbf`/`.shx` and `bundle` is
a node output rather than anything a portal serves.

## 3. The five shipped sources

| Source | Provider | Access |
|---|---|---|
| City of Chicago Data Portal | Socrata | Public; a token raises the rate limit |
| data.gov.uk | CKAN | Public |
| ArcGIS Hub Open Data | ArcGIS | Public |
| GeoSampa (São Paulo) | OGC WFS | Public |
| Direct URL | — | Public; no search, takes a link to a file |

**Not data.gov.** The US federal portal's CKAN API was retired: every
`/api/3/action/*` endpoint 404s and `/dataset` now redirects to the homepage.
Shipping it would ship a card that cannot answer. data.gov.uk is the CKAN
example instead - it serves its API from `ckan.publishing.service.gov.uk`,
which is why that manifest carries a `landingBase` option so links still point
at the site people know.

**Direct URL** is the escape hatch: for a portal Curio has no connector for,
paste the link to the file itself.

**GeoSampa** is a GeoServer publishing OGC services rather than a portal API.
That is why the `wfs` provider exists, and it is worth more than one portal:
GeoServer and MapServer are what most municipal geospatial portals outside the
US run, so one connector reaches a great many of them.

## 4. Browsing

**Two levels, because a manifest describes a portal and the datasets inside it
are discovered live.**

`/catalog/lakes` lists the sources when idle. Type in the search box and it
**fans out across every searchable portal at once**, replacing the cards with
results tagged by the portal each came from - so you can find a dataset without
first guessing which site holds it. Opening a source gives you
`/catalog/lakes/<sourceId>@<major>`, the same search scoped to one portal, and
the only place that paginates: five portals paginate independently and
interleaving them past page one would repeat and drop rows.

The query lives in the URL in both places, so a search is linkable and survives
a reload.

### Partial failure is a result, not an error

A federated search asks several third parties at once, and sometimes one of
them is slow, rate-limiting, or simply down. That must not empty the page. Each
leg reports its own status (`ok`, `failed`, `refused`, `rate-limited`,
`unsupported`, `needs-token`), the rows that arrived are shown, and a line
names the portals that did not answer. The request is a 200 either way.

A link-only source reporting `unsupported` is not surfaced: it says that on
every search, and showing it would train people to ignore the line that also
carries real failures.

### Bounds

- One request per searchable source, run concurrently, at most four at a time.
- The per-source rate limit applies to each leg independently, so a fan-out
  cannot be used to multiply one user's rate past a portal's bucket.
- The search box debounces, and each new keystroke aborts the request in
  flight, so a typed word is one fan-out rather than one per letter.
- Results are interleaved round-robin across portals, so the first screen is
  not monopolised by whichever site returned the most.

### Caching

The source roster is cached; **search results never are**. A portal can
publish, withdraw or rename a dataset between two searches, and serving a stale
row leads to a download that 404s against something the user was just shown.

The one exception is a WFS server's capabilities document, which is a
*catalogue* rather than a query result: it lists every published layer, changes
only when an operator publishes one, and runs to hundreds of kilobytes.
It is cached per source with a short TTL, which also makes a WFS source nearly
free inside a fan-out.

## 5. Downloading

Downloading fetches the bytes server-side and hands them to the same import
path a file upload uses, so the result is an **ordinary Data Catalog dataset**
with a manifest, preview, schema and `curio_dataset_path()` loader. Nothing
downstream needs to know it came from a portal.

The catalog does **not** install it into a dataflow or create a node. Adding a
dataset to a dataflow is the Data Catalog's existing job, it works the same
whether or not a project is open, and keeping it there means this catalog never
needs to know about the current project.

### It is a job, not a request

A 64 MiB file from a municipal portal can outlast any comfortable request
timeout, and the page wants a progress bar rather than a spinner. So a download
returns a job id and the page polls it: determinate when the portal sent a
`Content-Length`, indeterminate with a stage message when it did not, with a
Cancel that takes effect on the next chunk.

Jobs are per account - asking for someone else's id is indistinguishable from
asking for one that does not exist - and finished ones are swept after fifteen
minutes. They are process-local and **lost on restart**: a download in flight
when the backend stops is gone, and the page says so rather than waiting
forever.

Two downloads at a time per account, so nobody can queue fifty against a
municipal portal.

### "Do I already have this?"

The `lakeSource` block on a downloaded dataset records which portal resource it
came from, so the second click on Download answers from what you hold and
**contacts the portal not at all**. The same resource in two formats is two
datasets: holding the CSV is not holding the GeoJSON.

`refresh` forces a fetch. If the bytes hash the same, no second dataset is
created - the download was paid for, a duplicate would not be. If they differ,
a **new** dataset is minted and the old one is left alone: a saved dataflow
loads a dataset by id, and rewriting its bytes would change that dataflow's
results with nothing on screen to explain it.

### What kind of file is this?

Portals disagree about how to say. Detection is a ladder, most-trusted first:

1. **what we asked for** - the provider put the format in the URL, so we know
   what we requested rather than what a server claims;
2. the **final URL's suffix**, after redirects;
3. the **`Content-Disposition`** filename;
4. the **`Content-Type`**, which plenty of sites get wrong;
5. the **first bytes** - `PAR1` for Parquet, the TIFF magic, and a JSON probe
   that tells GeoJSON from plain JSON by looking for a geometry type.

That last distinction matters: GeoJSON filed as `json` produces a node that
returns a dict where the user expected a GeoDataFrame.

Whatever it decides is checked against what the source is allowed to deliver,
and anything it cannot identify is an honest error rather than a guess.

### Bounds and refusals

- **64 MiB**, the server's ceiling; a manifest may lower it, never raise it.
  `Content-Length` over the bound is refused before a body byte is read, and
  the stream is capped again while writing so a lying or absent length cannot
  get past it.
- **Archives are refused**, by content type and by extension. Nothing is
  unpacked: that is the decompression-bomb surface and it deserves its own
  design rather than arriving as a side effect of a download.
- Remote filenames are sanitised, and the dataset *directory* is minted as
  `imported.x<uuid>` by the importer - which no remote input can influence at
  all, and is the reason a hostile `Content-Disposition` cannot reach the
  filesystem even if the sanitiser were wrong.
- Bytes land in a per-user staging directory under `.curio/users/<id>/`, not
  `/tmp`: they are user data under a tree we already scope, and a crashed job
  leaves an orphan somewhere a sweep can find it.

Failures are reported in the server's own words - "that resource is a
application/zip archive", "the response declares 999999999 bytes" - because any
of those is more use than "download failed".

## 6. Icons

A source may ship an `icon.png`. A source without one, or whose icon is
missing or oversized, renders the shared lake glyph instead - so a broken icon
costs a logo, not a page.

PNG only. An SVG served from the app's own origin can carry script, and the
icon is the only file in this feature whose bytes are rendered rather than
parsed. The file is served with a fixed content type, `nosniff`, an `ETag` and
a 256 KiB cap, and is resolved inside its own source folder.

The shipped marks are the portals' own, fetched from each portal and used
nominatively - to identify the portal a card refers to, in a catalog that
exists to point at those portals.
[`datalakes/ICONS.md`](../datalakes/ICONS.md) records where each came from,
when, and the reasoning; removing one is deleting a PNG and a manifest line,
after which the card renders the glyph.

## 7. Credentials

Some portals take an API token. Socrata app tokens are the case that matters
today: the portals answer without one, but a token raises the caller's rate
limit sharply.

**A token is a per-person entitlement, so it lives on your account**, exactly
as your LLM provider key does. One shared secret would mean everyone on an
install spending the same allowance and being throttled together.

Set it in **AI Settings**, from the button in the top bar, beside the LLM
provider key. Blank means keep what is saved; there is an explicit *Remove
saved token* for clearing one.

**Guests are refused out loud** - a 403, the way the LLM key refuses them -
rather than having the value quietly discarded. A guest account is shared, so a
personal token on it would be everyone's, and accepting the value silently
would leave someone believing they are authenticated when they are not.

Curio reports only *whether* a token is stored, never its value: a source card
shows "Token set" or "Token needed", and the API answers with a boolean.

### A deployment can supply one for everybody

Set `CURIO_DEFAULT_SOCRATA_APP_TOKEN` and every user who has not saved their
own inherits it; anyone can still override it with theirs. The same per-field
inheritance the LLM provider config has, and useful for the same reason: an
operator running Curio for a class raises the rate limit for the whole room
with one environment variable.

There is deliberately **no `curio.py start` flag** for it, matching
`--llm-api-key`'s absence and for the same reason: a secret passed as an
argument is visible in the process list to every user on the host.

The settings screen says which applies - `(optional)`, `(inherited - leave
blank to use it)`, or `(saved)` - and the "is a token set" the source card
shows means *will one be sent*, so an inherited token satisfies a portal that
requires one.

### Slots are a server-owned allowlist

A manifest names the credential it wants (`auth.secretId`), but **which
credentials can exist is decided in code**, by `SLOT_COLUMNS` in
`datalakes/infrastructure/credentials.py`. A manifest naming an unknown slot
fails to load, with a message saying so.

This is the same posture the agent tool registry takes, and for the same
reason: a manifest is operator-authored configuration, and letting it invent a
credential slot would let it invent somewhere for a secret to live. Adding a
slot is a column on the user row, a migration, and one line in that registry -
deliberately the same cost as adding any other account credential, because
that is what it is.

### `auth.scheme` is `header` only

That single constraint is what keeps a secret out of every URL, which in turn
makes the egress audit record, every refusal message and every job record safe
to store verbatim. Providers are handed a header *name* and a slot; the
transport is the only code that turns that into a value, and it binds it at
construction so no provider ever handles a token or could put one in a URL it
builds.

## 8. Adding a provider

A provider is one module in `datalakes/providers/`, implementing search,
describe and download-url against the `LakeProvider` protocol, plus one line in
the registry. The manifest format, the roster, the routes and the UI need no
changes.

Each module also exports a transport-free `recognize(url)` and
`metadata_evidence(payload)`. Those are what `agents/verify.py` uses to add
richer evidence to an agent's external-source check, so a provider's URL
knowledge lives in one place rather than being half-copied into the verifier.

Two invariants a provider is held to, because they are what stops a hostile or
merely broken portal response from steering a request:

1. a `resourceId` is validated against the provider's own pattern **before** it
   is interpolated into any URL - ids arrive from search results, saved agent
   proposals and URLs people typed, so none is trusted;
2. every URL a provider builds starts with the manifest's `baseUrl`. Redirects
   *off* the base are fine and each hop is re-checked; it is request
   *construction* that is pinned.

### Testing one

No test in this package opens a socket. Providers take their transport as a
required constructor argument, so forgetting to inject a fake is a `TypeError`
rather than a real request, and the suite-wide guard in
`utk_curio/backend/tests/netguard.py` catches anything that slips past.

The fixture corpus under `tests/test_datalakes/fixtures/` was recorded by
driving the real providers against the live portals
(`scripts/record_datalake_fixtures.py`), so tests assert against what the sites
actually answered. `test_provider_contracts.py` is the drift detector: it hits
the real portals in CI, asserts only response *shape*, and **skips** whenever
anything is unreachable, non-2xx or not JSON - so it can tell you a portal
changed without ever failing a build for someone else's outage.

## 9. The agents

The Dataset Finder's candidate card has always had two lanes: datasets already
in your Data Catalog, and external ones it found elsewhere. **The external lane
used to dead-end.** It could name a portal dataset, and Curio could verify the
URL was real, but nothing could act on it - so the only move was a handoff to
Node Builder to write fetch code.

Three tool contracts change that:

| Tool | Effect | What it does |
|---|---|---|
| `datalake.sources` | read | The roster. Disk only, so it costs no web budget. |
| `datalake.search` | read | Searches portals live. |
| `datalake.acquire` | **mutate** | Proposes a download. |

A download writes bytes into your store and mints a catalog row, so it is a
**mutate**: it goes through the review path and **cannot be executed by the
model loop at all**. The read executor has no branch for it. Nothing is
downloaded without your explicit approval, and the proposal card is grounded in
a real `describe()` call - it shows the portal's own name, format and size
rather than the model's claim about them.

`agent.node-builder` stays among the Dataset Finder's delegates: a source no
provider covers is still real, and writing fetch code is still the right answer
for it. It just stops being the only answer.

### Only the runtime says a row is actionable

A candidate row may carry a `sourceId` and `resourceId` copied from a
`datalake.search` result. Whether Curio can actually download it is decided
**server-side**, against the real roster and the run's own grants - the model
may name a source, it may not claim the run can act on one. Any `acquirable`
the model sets is stripped before the check.

This is the same discipline the catalog lane already has, where a row without a
`datasetId` from `catalog.search` is dropped.

### What a fan-out costs

`datalake.search` without a `sourceId` contacts every searchable portal, and
the per-run web budget is charged **per portal** rather than per tool call. A
flat tick would let one call issue five requests against a budget of four. The
tool's own description says so, so a model can choose to name a source and
spend one instead.

`datalake.sources` is free: it reads manifests off disk.

## Operator notes

### `CURIO_DATALAKE_ROOT`

Points the catalog at a directory other than `<repo>/datalakes`. Set it to a
persistent volume in a container deployment, as you would `CURIO_CATALOG_ROOT`
for the Data Catalog.

### Manifests are operator-authored, and there is no import route

Deliberate, and an asymmetry with the Node and Agent catalogs worth stating.
Importing a node package or an agent puts an artifact in *your own* account,
and its blast radius is your account. A lake manifest declares a host **the
server will make outbound requests to, with a credential attached, on a user's
behalf** - its blast radius is the server's network position. So sources ship
with the deployment; there is no upload endpoint, and adding one would need a
different trust story than "the user asked for it".

### Outbound requests

Every request this catalog makes goes through the same policy the agent tools
use: https/http only, private and link-local addresses refused after DNS
resolution, every redirect hop re-checked, and the connected peer confirmed
before any response body is read. The residual documented in
`app/common/egress_policy.py` applies here too: the request line is on the wire
before the peer check, so a blind request to an internal service is not
prevented, only its response is withheld.

A source manifest can never exempt a host from that policy. The one exemption
in the codebase is for an operator-configured search provider, and this catalog
does not use it.
