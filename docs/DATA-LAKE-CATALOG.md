# Data Lake Catalog

The fourth catalog, beside the [Node Catalog](NODE-CATALOG.md), the
[Data Catalog](DATA-CATALOG.md) and the [Agent Catalog](AGENT-CATALOG.md).

The Data Catalog holds datasets you already have. This one holds the **places
you can get more**: open data portals and lakes. You browse a portal, download
what you want, and it lands in your Data Catalog as an ordinary dataset.

> **Status.** This document describes the catalog as it stands today: the
> source roster, the manifest format and the browse page. Live search of a
> portal, downloading, and per-user tokens arrive with the provider
> connectors. Sections describing those are marked *(not yet wired)* rather
> than omitted, so the shape is reviewable before the code lands.

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
  lake.us.data-gov@1/
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
| Data.gov | CKAN | Public |
| ArcGIS Hub Open Data | ArcGIS | Public |
| GeoSampa (São Paulo) | OGC WFS | Public |
| Direct URL | — | Public; no search, takes a link to a file |

**Direct URL** is the escape hatch: for a portal Curio has no connector for,
paste the link to the file itself.

**GeoSampa** is a GeoServer publishing OGC services rather than a portal API.
That is why the `wfs` provider exists, and it is worth more than one portal:
GeoServer and MapServer are what most municipal geospatial portals outside the
US run, so one connector reaches a great many of them.

## 4. Browsing and downloading *(not yet wired)*

The browse page lists sources. Opening one gives you its own page, where a
search box queries the portal live and each result offers a download.

Downloading fetches the bytes server-side and hands them to the same import
path a file upload uses, so the result is an **ordinary Data Catalog dataset**
with a manifest, preview, schema and `curio_dataset_path()` loader. Nothing
downstream needs to know it came from a portal. It carries a `lakeSource`
block recording which portal, which resource, and the content hash, which is
what lets Curio answer "do I already have this?" without downloading it again.

The catalog does **not** install the dataset into a dataflow or create a node.
Adding a dataset to a dataflow is the Data Catalog's existing job, it works
the same whether or not a project is open, and keeping it there means this
catalog never needs to know about the current project.

### Off-portal distributions

A CKAN package on `catalog.data.gov` often points at a file on the publishing
agency's own host. Following that link is necessary and is also the one place
a download leaves the portal's base URL, so it is opt-in per manifest
(`capabilities.allowOffBaseDistributions`) rather than a provider default. It
widens what a hostile search response could aim a request at, which makes it
an operator's decision. Those URLs still pass the full address policy.

## 5. Icons

A source may ship an `icon.png`. A source without one, or whose icon is
missing or oversized, renders the shared lake glyph instead - so a broken icon
costs a logo, not a page.

PNG only. An SVG served from the app's own origin can carry script, and the
icon is the only file in this feature whose bytes are rendered rather than
parsed. The file is served with a fixed content type, `nosniff`, an `ETag` and
a 256 KiB cap, and is resolved inside its own source folder.

The shipped marks are neutral lettermarks, **not** the portals' logos: a
portal's logo is that portal's trademark and this repo cannot verify
redistribution rights for one. An operator may well be in a different position,
and replacing one is a matter of dropping in a PNG.
[`datalakes/ICONS.md`](../datalakes/ICONS.md) records each one's origin.

## 6. Credentials *(not yet wired)*

Some portals take an API token: Socrata app tokens raise rate limits, some
CKAN instances require a key. A manifest names a **slot** (`auth.secretId`),
never a value, and slots are shared across a family - one `socrata.app-token`
serves every Socrata portal.

Tokens are per-user, stored the way the Hugging Face token already is, and
responses report only whether a slot is filled, never its contents.

**`auth.scheme` is `header` only.** That single constraint means no secret ever
enters a URL, which in turn makes the egress audit record, every refusal
message and every job record safe to store verbatim.

## 7. Adding a provider

A provider is one entry in `datalakes/providers/`, implementing search,
describe and download-url against the `LakeProvider` protocol, plus one line in
the registry. The manifest format, the roster, the routes and the UI need no
changes.

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
