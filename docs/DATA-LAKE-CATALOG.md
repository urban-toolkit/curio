# Data Lake Catalog

The Data Lake Catalog is where Curio lists the **open data portals** it can reach. You search a portal, download a dataset, and it lands in your Data Catalog as an ordinary dataset.

Curio has four catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, and the Data Lake Catalog the open data portals you download datasets from.

This guide is in eight parts, plus operator notes:

- [1. What is the Data Lake Catalog?](#1-what-is-the-data-lake-catalog): sources, what ships, and where things are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the two pages, the action matrix, and walkthroughs.
- [3. Using a downloaded dataset in a dataflow](#3-using-a-downloaded-dataset-in-a-dataflow): it is a Data Catalog dataset.
- [4. Downloading](#4-downloading): progress, formats, limits, and downloading again.
- [5. API tokens](#5-api-tokens): portals that take a token, and where to set yours.
- [6. The Dataset Finder](#6-the-dataset-finder): letting an agent search the portals for you.
- [7. Importing, publishing, and sharing](#7-importing-publishing-and-sharing): how sources are added.
- [8. The manifest](#8-the-manifest): the fields a source declares.
- [Operator notes](#operator-notes): relocating the sources and supplying a shared token.

---

## 1. What is the Data Lake Catalog?

### Concept

The unit of this catalog is a **source**: one data portal, such as a city's open data site. A source is not a dataset. The datasets inside a portal are found live, when you search it, and you download the ones you want.

A source is a folder with a `manifest.json`, identified by `lake.<publisher>.<portal>` and a major version:

```
datalakes/
  lake.cityofchicago.data-portal@1/
    manifest.json
    icon.png          # optional
```

### What ships with Curio

| Source | Portal software | Access |
|---|---|---|
| City of Chicago Data Portal | Socrata | Public; a token raises the rate limit |
| data.gov.uk | CKAN | Public |
| ArcGIS Hub Open Data | ArcGIS | Public |
| GeoSampa (São Paulo) | OGC WFS | Public |
| Direct URL | none | Public. Nothing to browse: it downloads one file from an https link |

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Sources**, the portals this install can reach | `<repo_root>/datalakes/<sourceId>@<major>/`, or `$CURIO_DATALAKE_ROOT` when set | The operator. Nothing in the app writes here. |
| **Your token**, for portals that take one | Your account | You, in **AI Settings**. |
| **Downloaded datasets** | Your Data Catalog store, `.curio/users/<user-key>/datasets/` | **Download**. Each download is an ordinary imported dataset. |

---

## 2. Surfaces and workflows

There are two pages, plus an agent that works on the canvas:

- **The `/catalog/lakes` page** lists the sources. Reach it from `/projects` and the **Data Lake Catalog** tab. Filter by provider or access in the left rail. Type in **Search every portal…** and the cards give way to results from every portal at once, each tagged with the portal it came from. Click a card to describe it in the right-hand drawer, or right-click it for its actions.
- **A source's page**, `/catalog/lakes/<sourceId>@<major>`, is one portal on its own. Reach it with **Browse datasets** on a card, in the drawer, or in the right-click menu. It lists nothing until you search, then shows that portal's matches and how many there are.
- **The Dataset Finder**, an agent you attach on the canvas, can search the portals for you and propose a download. See [part 6](#6-the-dataset-finder).

On both pages the search is kept in the page address, so a search can be linked and survives a reload.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Search every portal** | The `/catalog/lakes` search box | Nothing | Results from every portal that can be searched, tagged by portal. |
| **Browse datasets** | Card, drawer, or right-click menu | Nothing | The source's page, searching that portal only. |
| **View details** | Card, drawer, or right-click menu | Nothing | The source's endpoint, licence, formats, download limit, and token needs. |
| **Download** | A result row, with a format picker when the portal offers more than one | Your Data Catalog gains a dataset | A progress bar, then *"Downloaded `<title>` to your Data Catalog."* with **View details**. |
| **Cancel** | The row's progress bar | Nothing is kept | The download stops. |
| **View dataset** | A row marked **In your Data Catalog** | Nothing | The dataset's details, over the page. |
| **View on the portal ↗** | A result row | Nothing | The dataset's page on the portal's own site, in a new tab. |
| **Set a token** | **AI Settings** | Your account | The source's card reads **Token set**. |

### Workflows

**I want a dataset but do not know which portal has it.** Open `/catalog/lakes` and type in the search box. Every searchable portal is asked at once and the results are interleaved. If a portal is slow or down, a line names it and the other portals' results still show.

**I want to download a dataset and use it.** Find it, pick a format if the row offers a choice, and click **Download**. When it finishes, the row offers **View dataset**. To use it in a dataflow, add it from the Data Catalog ([part 3](#3-using-a-downloaded-dataset-in-a-dataflow)).

**I want to search one portal only.** Click **Browse datasets** on its card. The source's page searches that portal alone.

**A portal needs a token.** Get one from the portal (the source's **View details** links to its instructions), paste it into **AI Settings**, and save. See [part 5](#5-api-tokens).

**I want to know where a downloaded dataset came from.** Open the dataset's details in the Data Catalog. **Downloaded from** names the portal, links the resource on the portal's site, and says when it was downloaded.

---

## 3. Using a downloaded dataset in a dataflow

A download lands in your Data Catalog as an ordinary imported dataset, with a preview, a schema, and the same loader code as any other. Nothing downstream needs to know it came from a portal.

Downloading does not add the dataset to a dataflow. Add it from the Data Catalog drawer on the canvas, then drag it onto the canvas: see [DATA-CATALOG.md part 3](DATA-CATALOG.md#3-using-a-dataset-in-a-dataflow).

---

## 4. Downloading

While a download runs, its row shows a progress bar and **Cancel**. The bar fills when the portal says how large the file is, and shows what the download is doing when it does not.

- **Two at a time.** Each account runs at most two downloads at once.
- **A restart loses it.** A download still running when the server restarts is lost, and its row says so. Start it again.
- **Downloading again.** A row marked **In your Data Catalog** has already been downloaded in that format. Its button is **View dataset**, and nothing is fetched again. The same resource in another format is a separate download and a separate dataset.
- **Formats.** CSV, GeoJSON, JSON, Parquet, and GeoTIFF, narrowed by what each portal offers.
- **Size.** 64 MiB at most. A source may set a lower limit, which its **View details** shows as **Max download**.
- **Archives** (`.zip`, `.gz`, `.tar` and the like) are refused. Curio downloads single data files and unpacks nothing.

When a download fails, the row says why in the server's own words, for example that the file is an archive or larger than the limit.

---

## 5. API tokens

Some portals take an API token. The City of Chicago portal answers without one, and a token raises your rate limit.

A token belongs to your account. Set it in **AI Settings** (the button in the page header, or in the Agent Catalog drawer's header on the canvas), in the **Socrata app token** field. Leave the field blank to keep a saved token; **Remove saved token** clears it. The field's label says whether a token is saved, optional, or inherited from whoever runs this Curio. Your own token overrides the inherited one.

Guest accounts cannot save a token.

A source that takes a token shows its state on the card:

| Badge | Meaning |
|---|---|
| **Token set** | A token will be sent: yours, or the inherited one. |
| **Token optional** | The portal works without one; a token raises the rate limit. |
| **Token needed** | The portal will not answer without one. The card offers no **Browse datasets** until a token is set. |

Curio never shows a token's value, only whether one is set.

---

## 6. The Dataset Finder

The **Dataset Finder** agent can look beyond your Data Catalog. Its candidate card has two lanes, **From your Data Catalog** and **External sources**, and an external row Curio can download from one of these portals is marked **Downloadable**.

Selecting rows writes a confirmation into the chat for you to send. A download the agent proposes appears as a review card, and nothing is downloaded until you apply it. The card shows the portal's own name, format and size for the resource, and an applied download lands in your Data Catalog like any other.

An external source Curio has no connector for goes to **Node Builder**, which writes code to fetch it.

To add the Dataset Finder to a dataflow, see the [Agent Catalog](AGENT-CATALOG.md).

---

## 7. Importing, publishing, and sharing

Sources are not imported, published, or shared from the app. They ship with the deployment: the operator adds a source by adding its folder (see [part 8](#8-the-manifest)), and every user on the install sees the same sources.

What you download is yours, like any imported dataset. To offer it to everyone on the install, publish it from the Data Catalog ([DATA-CATALOG.md part 6](DATA-CATALOG.md#6-importing-publishing-and-sharing)).

---

## 8. The manifest

A source's `manifest.json` is validated against [`docs/schemas/data-lake-source.v1.json`](schemas/data-lake-source.v1.json), which is the full reference. The shipped sources in [`datalakes/`](../datalakes/) are the canonical examples.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `lake.<publisher>.<portal>`: three to six dot-separated lowercase segments, naming who publishes the portal. |
| `name` | Yes | What the card says. |
| `version` | Yes | The manifest's own version string. |
| `compatibility.major` | | Defaults to 1. Together with `id` it forms the folder name. |
| `description`, `publisher`, `homepage`, `license`, `tags` | | Shown on the card and in the details. |
| `icon` | | A `.png` file in the source's folder, at most 256 KiB. Without one, the card shows the catalog's lake glyph. |
| `provider.type` | Yes | `socrata`, `ckan`, `arcgis`, `wfs`, or `direct`. |
| `provider.baseUrl` | Yes, except for `direct` | The portal's https address, with no trailing slash. |
| `provider.options` | | Settings for that portal software, such as the API path, or `landingBase` for a CKAN portal whose pages live on another host. |
| `auth.mode` | | `public`, `optional-token`, or `required-token`. |
| `auth.secretId`, `auth.headerName`, `auth.scheme` | With a token | Which account credential to send, and in which header. `socrata.app-token` is the one credential Curio knows, and `scheme` is always `header`. |
| `auth.helpUrl` | | Where a user gets a token. Shown in the details. |
| `capabilities.search`, `describe`, `download` | | What the portal supports. All default to true. |
| `capabilities.formats` | | The formats this portal may deliver, from the five Curio downloads. |
| `capabilities.maxDownloadBytes` | | A download limit below the 64 MiB default. |
| `capabilities.allowOffBaseDistributions` | | Lets a download come from a host other than `baseUrl`, for a CKAN portal whose files live on each publisher's own site. Off by default. |
| `limits.requestsPerMinute` | | Requests per minute, per user. Default 30. |

[`datalakes/ICONS.md`](../datalakes/ICONS.md) records where each shipped icon came from. Replacing or removing one is a PNG and a manifest line.

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_DATALAKE_ROOT` | none | Reads the sources from this directory instead of `<repo_root>/datalakes`. |
| `CURIO_DEFAULT_SOCRATA_APP_TOKEN` | none | A Socrata app token every account inherits until it saves its own. |

**Sources ship with the deployment.** To add, change, or remove one, edit the sources directory and restart. The Docker image bakes `datalakes/` in; see [DEPLOYMENT.md § Configure the stack](DEPLOYMENT.md#1-configure-the-stack).

**Outbound requests.** This catalog makes requests to third-party portals on your users' behalf. What bounds them is in [DEPLOYMENT.md § Outbound requests](DEPLOYMENT.md#outbound-requests).

---

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where downloads land, and how a dataset reaches a dataflow.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the Dataset Finder and the other agents.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#data-lake-catalog): how search and downloads work, and how to add a provider.
- [`docs/schemas/data-lake-source.v1.json`](schemas/data-lake-source.v1.json): the manifest JSON Schema.
