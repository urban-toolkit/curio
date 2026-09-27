# Data Lake Catalog

The Data Lake Catalog is where Curio lists the **open data portals** and the **storage** it can reach: folders on the Curio machine, public S3 buckets and Hugging Face repositories. You search a portal and download a dataset, or open a storage source and add one of the resources it declares. Either way it lands in your Data Catalog.

Curio has four catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, and the Data Lake Catalog the portals and storage you take datasets from.

This guide is in eight parts, plus operator notes:

- [1. What is the Data Lake Catalog?](#1-what-is-the-data-lake-catalog): sources, what ships, and where things are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the two pages, the action matrix, and walkthroughs.
- [3. Using a lake dataset in a dataflow](#3-using-a-lake-dataset-in-a-dataflow): tables and collections are Data Catalog datasets.
- [4. Downloading and adding](#4-downloading-and-adding): progress, formats, limits, what is copied and what is referenced.
- [5. API tokens](#5-api-tokens): sources that take a token, and where to set yours.
- [6. The Dataset Finder](#6-the-dataset-finder): letting an agent search the portals for you.
- [7. Importing, publishing, and sharing](#7-importing-publishing-and-sharing): how sources are added.
- [8. The manifest](#8-the-manifest): the fields a source declares, and how a storage source declares its files.
- [Operator notes](#operator-notes): adding your own sources, mounting folders, and the cache limit.

---

## 1. What is the Data Lake Catalog?

### Concept

The unit of this catalog is a **source**. A source is not a dataset. There are two kinds:

- **A portal**, such as a city's open data site. Its datasets are found live, when you search it, and you download the ones you want.
- **A storage source**: a folder on the Curio machine, a public S3 bucket, or a Hugging Face repository. Its manifest declares its **resources**, and how the files of each are organized, the way a portal's manifest declares its endpoints. Curio lists what the manifest declares and never guesses a layout.

A storage resource is one of two things:

- **A table**: CSV, JSON, GeoJSON, Parquet, GeoPackage, shapefile or OSM PBF files. Adding it copies it into your Data Catalog, as a download does. Many files of one resource, such as one CSV per sensor and day, become one table.
- **A collection**: rasters, video frames, images, videos, or audio. Adding it indexes it: the Data Catalog gains one dataset with a row per file, and the files stay where they are.

A folder of images is therefore one row in the lake and one dataset in your Data Catalog, not one per image.

A source is a folder with a `manifest.json`, identified by `lake.<publisher>.<source>` and a major version:

```
datalakes/
  lake.cityofchicago.data-portal@1/
    manifest.json
    icon.png          # optional
```

### What ships with Curio

| Source | Provider | Access |
|---|---|---|
| City of Chicago Data Portal | Socrata | Public; a token raises the rate limit |
| data.gov.uk | CKAN | Public |
| ArcGIS Hub Open Data | ArcGIS | Public |
| GeoSampa (São Paulo) | OGC WFS | Public |
| Direct URL | none | Public. Nothing to browse: it downloads one file from an https link |
| Example storage | Folder | Public. A small instance of each way storage is organized, which the storage examples read |
| Sentinel-2 over Chicago | S3 bucket | Public. True-color previews and thumbnails of one month's scenes |
| Hugging Face documentation images | Hugging Face | Public; a token raises the rate limit |

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Sources**, the portals and storage this install can reach | `<repo_root>/datalakes/<sourceId>@<major>/`, or `$CURIO_DATALAKE_ROOT` when set, and `.curio/datalakes/` for an operator's own | The operator. Nothing in the app writes here. |
| **Your token**, for sources that take one | Your account | You, in **AI Settings**. |
| **Downloaded and added datasets** | Your Data Catalog store, `.curio/users/<user-key>/datasets/` | **Download** and **Add to Data Catalog**. A table is an ordinary imported dataset; a collection is its index. |
| **A collection's files** | Where the source keeps them | Nobody. Curio reads them in place. |
| **A bucket collection's cached files** | Your account's media folder | **Cache files**, up to a per-account limit. |

---

## 2. Surfaces and workflows

There are two pages, plus an agent that works on the canvas:

- **The `/catalog/lakes` page** lists the sources. Reach it from `/projects` and the **Data Lake Catalog** tab. Filter by provider or access in the left rail. Type in **Search every portal…** and the cards give way to results from every portal at once, each tagged with the portal it came from. Click a card to describe it in the right-hand drawer, or right-click it for its actions.
- **A source's page**, `/catalog/lakes/<sourceId>@<major>`, is one source on its own. Reach it with **Browse datasets** on a card, in the drawer, or in the right-click menu. A portal's page lists nothing until you search, then shows that portal's matches and how many there are. A storage source's page lists its resources at once, one row each, with a kind (**Rasters**, **Frames**, **Images**, **Videos**, **Photos and videos**, **Audio**, or the table's format), a line saying how many files it holds, what its path fields cover, and its size, and thumbnails of its first files.
- **The Dataset Finder**, an agent you attach on the canvas, can search the portals for you and propose a download. See [part 6](#6-the-dataset-finder).

On both pages the search is kept in the page address, so a search can be linked and survives a reload. On a storage source's page the search filters its resources by name, description and field values.

A storage source is read when it is first opened, and again when its listing is 15 minutes old. While that runs the page says **Scanning `<source>`…**. **Rescan** reads it again at once, for files added since. When the source holds files no resource declares, the page says how many, for whoever writes its manifest.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Search every portal** | The `/catalog/lakes` search box | Nothing | Results from every portal that can be searched, and the storage sources' matching resources, tagged by source. |
| **Browse datasets** | Card, drawer, or right-click menu | Nothing | The source's page, searching that portal only. |
| **View details** | Card, drawer, or right-click menu | Nothing | The source's endpoint, licence, formats, download limit, and token needs; a storage source's resource count. |
| **Download** | A result row, with a format picker when the portal offers more than one | Your Data Catalog gains a dataset | A progress bar, then *"Downloaded `<title>` to your Data Catalog."* with **View details**. |
| **Cancel** | The row's progress bar | Nothing is kept | The download stops. |
| **View dataset** | A row marked **In your Data Catalog** | Nothing | The dataset's details, over the page. |
| **View on the portal ↗** | A result row | Nothing | The dataset's page on the portal's own site, in a new tab. |
| **Add to Data Catalog** | A storage source's row | Your Data Catalog gains a dataset | A dialog to keep only some values of each path field, then a progress bar, then *"Added `<title>` to your Data Catalog."* with **View details**. |
| **Files** | A storage source's row | Nothing | The row's files, 50 at a time, with thumbnails for a collection's. Pick some and **Add N picked files** adds only those. |
| **Rescan** | A storage source's page | Nothing | The source is read again, and its rows are listed as they are now. |
| **Cache files** | A bucket collection's details, in the Data Catalog | Your account's media folder | Its files are copied to the Curio machine, so nodes can read them. |
| **Set a token** | **AI Settings** | Your account | The source's card reads **Token set**. |

### Workflows

**I want a dataset but do not know which portal has it.** Open `/catalog/lakes` and type in the search box. Every searchable portal is asked at once and the results are interleaved. If a portal is slow or down, a line names it and the other portals' results still show.

**I want to download a dataset and use it.** Find it, pick a format if the row offers a choice, and click **Download**. When it finishes, the row offers **View dataset**. To use it in a dataflow, add it from the Data Catalog ([part 3](#3-using-a-lake-dataset-in-a-dataflow)).

**I want to search one portal only.** Click **Browse datasets** on its card. The source's page searches that portal alone.

**A portal needs a token.** Get one from the portal (the source's **View details** links to its instructions), paste it into **AI Settings**, and save. See [part 5](#5-api-tokens).

**I want to know where a downloaded dataset came from.** Open the dataset's details in the Data Catalog. **Downloaded from** names the portal, links the resource on the portal's site, and says when it was downloaded. A table added from a storage source says **Added from** instead, and how many files it was combined from. A collection has a **Collection** section: its kind, **Indexed from** the source and resource, and how many files of each kind it holds.

**I have a folder of orthorectified images, by year.** Its manifest declares one `rasters` resource, `orthos/{year:int}/{tile}.tif`. The lake lists one row with the years it covers; **Add to Data Catalog**, keeping only the years you want, gives one collection with each tile's footprint. On the canvas, a Vega-Lite map draws the footprints and **Mosaic Rasters** joins one year's tiles into one raster: see [example 17](examples/17-storage-orthorectified-imagery.md).

**I have a folder of video frames.** Its manifest declares one `frames` resource, such as `dashcam/{date:date}/{sequence}_{frame:int}.jpg`, with the frame rate as `fps`. The collection orders the frames by sequence and number and gives each its time; a telemetry table declared as `metadata` gives each frame a position. **Simple View** shows the frames in order: see [example 18](examples/18-storage-video-frames.md).

**I have a folder of CSV files, by sensor or by date.** Its manifest declares one `table` resource, such as `air-quality/{sensor}/{day:date}.csv`. Adding it copies every file into one Parquet table with a `sensor` and a `day` column, the rows of every file under the columns of all of them: see [example 19](examples/19-storage-folder-of-csv-files.md). With `"datasets": "per:sensor"` the lake lists one row per sensor instead, and each adds as its own table.

**I have photos and videos.** A `media` resource takes both. Each photo carries its EXIF time and position, and a video plays in **Simple View**; **Sample Video Frames** turns videos into frames: see [example 20](examples/20-storage-photos-and-videos.md).

**I have audio recordings.** An `audio` resource, whose file names can carry the recording time. **Simple View** shows each recording as a spectrogram with **Play**, and **Split Audio** measures the level of each window: see [example 21](examples/21-storage-audio-recordings.md).

**I have a folder of unrelated data files.** Declare one resource per file, as a portal lists its datasets, and add each: see [example 22](examples/22-storage-folder-of-different-files.md). A folder of unrelated files of one format, such as `{name}.csv` with `"datasets": "per-file"`, lists one row per file.

---

## 3. Using a lake dataset in a dataflow

A download, and a table added from a storage source, lands in your Data Catalog as an ordinary imported dataset, with a preview, a schema, and the same loader code as any other. Nothing downstream needs to know where it came from.

A collection lands as a dataset of format **Collection**. Its **Data Loading** node reads it with `curio_collection("<id>")`, which returns one row per file: the path fields, what Curio read from each file, and `path`, where the file can be opened. Rows with a position come back as a GeoDataFrame. **Simple View** shows the rows as cards; a video or a recording plays in its card. The `curio.media` package's nodes work on these rows: **Sample Video Frames**, **Split Audio** and **Mosaic Rasters**. See [DATA-CATALOG.md](DATA-CATALOG.md#collections) for the columns.

Downloading or adding does not add the dataset to a dataflow. Add it from the Data Catalog drawer on the canvas, then drag it onto the canvas: see [DATA-CATALOG.md part 3](DATA-CATALOG.md#3-using-a-dataset-in-a-dataflow).

---

## 4. Downloading and adding

While a download or an add runs, its row shows a progress bar and **Cancel**. The bar fills when the size is known, counts files when a resource has many, and shows what the work is doing otherwise.

- **Two at a time.** Each account runs at most two downloads at once.
- **A restart loses it.** A download still running when the server restarts is lost, and its row says so. Start it again.
- **Downloading again.** A row marked **In your Data Catalog** has already been downloaded in that format. Its button is **View dataset**, and nothing is fetched again. The same resource in another format is a separate download and a separate dataset.
- **Formats.** CSV, GeoJSON, JSON, Parquet, and GeoTIFF, narrowed by what each portal offers.
- **Size.** 64 MiB at most. A source may set a lower limit, which its **View details** shows as **Max download**.
- **Archives** (`.zip`, `.gz`, `.tar` and the like) are refused. Curio downloads single data files and unpacks nothing.

When a download fails, the row says why in the server's own words, for example that the file is an archive or larger than the limit.

### Adding from a storage source

- **Tables are copied.** One file lands as itself. A shapefile brings its `.dbf`, `.shx`, `.prj` and `.cpg` with it and lands as GeoParquet; a GeoPackage or OSM PBF lands as one dataset per layer, as an upload does. Several files land as one Parquet table, with a column per path field and a `source_file` column; geographic files land as one GeoParquet, in EPSG:4326, when they share a coordinate system.
- **Collections are referenced.** The Data Catalog keeps an index; the files stay where the source keeps them, and nothing is written to the source. Deleting the collection deletes its index and never the files.
- **Adding again.** A row marked **In your Data Catalog** offers **View dataset**. After its files change, add it again for a new dataset of what is there now.
- **Narrowing.** Keeping only some values in the **Add** dialog, or picking files under **Files**, adds a separate dataset of just those files. The row stays offered whole.
- **A bucket's files.** In a collection from a bucket or a Hugging Face repository, each image and raster is indexed from its first 64 KiB, and a detail stored past them stays empty. Its videos and recordings are indexed by their path and size only. Thumbnails of its images and rasters are drawn on request; a video's or recording's appears once it is cached. Nodes read its files once **Cache files** has copied them to the Curio machine; until then a row's `path` is empty.
- **Size.** 4 GiB per file from a folder, and the download limit per file from a bucket; 512 MiB for a GeoPackage or PBF. A combined table takes up to 10,000 files, and 16 GiB from a folder or 2 GiB from a bucket. A source lists up to 200,000 files unless its manifest sets another limit.
- **Publishing.** A collection cannot be published: its files are not in the Data Catalog to share.

---

## 5. API tokens

Some sources take an API token. The City of Chicago portal and the Hugging Face source answer without one, and a token raises your rate limit.

A token belongs to your account. Set it in **AI Settings** (the button in the page header, or in the Agent Catalog drawer's header on the canvas), in the **Socrata app token** field for a Socrata portal, or the **HuggingFace token** field for a Hugging Face source. Leave the field blank to keep a saved token; **Remove saved token** clears it. The field's label says whether a token is saved, optional, or inherited from whoever runs this Curio. Your own token overrides the inherited one.

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

Sources are not imported, published, or shared from the app. They ship with the deployment, or the operator adds one by adding its folder (see [part 8](#8-the-manifest) and the [operator notes](#operator-notes)), and every user on the install sees the same sources. On your own machine you are the operator: to list a folder of your own, write a manifest for it in `.curio/datalakes/`.

What you download is yours, like any imported dataset. To offer it to everyone on the install, publish it from the Data Catalog ([DATA-CATALOG.md part 6](DATA-CATALOG.md#6-importing-publishing-and-sharing)).

---

## 8. The manifest

[`docs/schemas/data-lake-source.v1.json`](schemas/data-lake-source.v1.json) is the full reference for a source's `manifest.json`. The shipped sources in [`datalakes/`](../datalakes/) are the canonical examples.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `lake.<publisher>.<source>`: three to six dot-separated lowercase segments, naming who publishes it. |
| `name` | Yes | What the card says. |
| `version` | Yes | The manifest's own version string. |
| `compatibility.major` | | Defaults to 1. Together with `id` it forms the folder name. |
| `description`, `publisher`, `homepage`, `license`, `tags` | | Shown on the card and in the details. |
| `icon` | | A `.png` file in the source's folder, at most 256 KiB. Without one, the card shows the catalog's lake glyph. |
| `provider.type` | Yes | A portal: `socrata`, `ckan`, `arcgis`, `wfs`, or `direct`. Storage: `folder`, `s3`, or `huggingface`. |
| `provider.baseUrl` | Yes, except for `direct` and `folder` | The portal's https address, the bucket's endpoint, or `https://huggingface.co`, with no trailing slash. |
| `provider.root` | For `folder` | The folder, as an absolute path. A source shipped in `datalakes/` may give one relative to the repository. |
| `provider.options` | | Settings for that software: the API path, `landingBase` for a CKAN portal whose pages live on another host, `prefix` for a bucket, `repo` and `revision` for a Hugging Face repository. |
| `auth.mode` | | `public`, `optional-token`, or `required-token`. |
| `auth.secretId`, `auth.headerName`, `auth.scheme`, `auth.valuePrefix` | With a token | Which account credential to send, in which header, and what comes before it (`Bearer ` for Hugging Face). Curio knows `socrata.app-token` and `huggingface.token`, and `scheme` is always `header`. |
| `auth.helpUrl` | | Where a user gets a token. Shown in the details. |
| `capabilities.search`, `describe`, `download` | | What the portal supports. All default to true. |
| `capabilities.formats` | | A portal only: the formats it may deliver, from the five Curio downloads. A storage source's formats follow from its resources. |
| `capabilities.maxDownloadBytes` | | A download limit below the 64 MiB default. |
| `capabilities.allowOffBaseDistributions` | | Lets a download come from a host other than `baseUrl`, for a CKAN portal whose files live on each publisher's own site. Off by default. |
| `limits.requestsPerMinute` | | Requests per minute, per user. Default 30. |
| `limits.maxFiles` | | A storage source: how many files it lists at most. Default 200,000. |
| `resources` | For storage | The resources a storage source declares, below. |

### Resources

A storage source's `resources` say how its files are organized. `provider` says where they are.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | Unique in the source. |
| `name`, `description` | `name` | What the row says. |
| `kind` | Yes | `table`, or a collection: `rasters`, `frames`, `images`, `videos`, `media` (images and videos together), or `audio`. |
| `path` | Yes | Which files belong to it, as a path template relative to the folder, bucket prefix or repository. |
| `format` | For `table` | `csv`, `json`, `geojson`, `parquet`, `gpkg`, `shp`, or `pbf`. |
| `datasets` | | How it adds: `one` dataset of every matched file (the default), `per:<field>` for one per value of a path field, listed as one row each, or `per-file`, for tables and rasters only. |
| `extensions` | | For a collection, the file extensions it takes. Images default to jpg, jpeg, png, webp, gif, bmp and tif; videos to mp4, mov and webm; audio to wav, flac, mp3, ogg, opus, m4a and aiff. |
| `options` | | For a CSV table: `delimiter` and `header`. |
| `fps` | | For `frames`: frames per second, which gives each frame its time. |
| `time` | | For `images`, `videos`, `media` and `audio`: the path field that is each file's time. |
| `metadata` | | For a collection: a table joined onto its rows, as `{"path": ..., "on": ...}`, where `on` is `file_name`, `frame`, or a path field. |

**Path templates.** A template matches each file's path:

| Part | Matches |
|---|---|
| `{name}` | Part of one folder or file name, as text. |
| `{name:int}` | A whole number. |
| `{name:date}` | A date written `2024-05-01`. |
| `{name:%Y%m%d_%H%M%S}` | A time, in the format it is written in. |
| `*` | Anything within one folder or file name. |
| `**` | Any number of folders. |

Each named part becomes a column of the dataset and a field the **Add** dialog can narrow by. For `frames`, `{sequence}` and `{frame:int}` name the sequence and the frame number; without `{sequence}`, a frame's folder is its sequence. Some names are taken by a collection's own columns (`path`, `name`, `kind`, `bytes`, and the like) and a manifest that uses one is refused, with the reason.

One manifest per use case, from the example storage source:

```jsonc
{
  "id": "lake.curio.example-storage", "name": "Example storage", "version": "1.0.0",
  "compatibility": { "major": 1 },
  "provider": { "type": "folder", "root": "docs/examples/data/storage" },
  "auth": { "mode": "public" },
  "resources": [
    // A folder of CSV files, by sensor and day: one table.
    { "id": "air-quality", "name": "Air quality readings", "kind": "table", "format": "csv",
      "path": "air-quality/{sensor}/{day:date}.csv" },
    // Different files in one folder: a resource each.
    { "id": "roads", "name": "Roads", "kind": "table", "format": "shp", "path": "city/roads.shp" },
    { "id": "parks", "name": "Parks", "kind": "table", "format": "geojson", "path": "city/parks.geojson" },
    // Orthorectified images, by year.
    { "id": "orthos", "name": "Drone orthoimagery", "kind": "rasters",
      "path": "orthos/{year:int}/{tile}.tif" },
    // Video frames, with a telemetry file.
    { "id": "dashcam", "name": "Dashcam frames", "kind": "frames", "fps": 10,
      "path": "dashcam/{date:date}/{sequence}_{frame:int}.jpg",
      "metadata": { "path": "dashcam/{date:date}/telemetry.csv", "on": "file_name" } },
    // Photos and videos.
    { "id": "survey", "name": "Street survey", "kind": "media", "path": "survey/{year:int}/**/*" },
    // Audio recordings, timed by their file names.
    { "id": "noise", "name": "Noise recordings", "kind": "audio", "time": "recorded",
      "path": "noise/{sensor}/{recorded:%Y%m%d_%H%M%S}.wav" }
  ]
}
```

A bucket or a Hugging Face repository is declared the same way, with the templates matching object keys:

```jsonc
{ "provider": { "type": "s3", "baseUrl": "https://sentinel-cogs.s3.us-west-2.amazonaws.com",
                "options": { "prefix": "sentinel-s2-l2a-cogs/16/T/DM/2024/7/" } },
  "resources": [ { "id": "previews", "name": "True-color previews", "kind": "rasters",
                   "path": "{scene}/L2A_PVI.tif" } ] }
```

Curio reads public buckets and repositories only. It does not sign S3 requests, reach buckets on a private network, or read images stored inside Parquet files.

[`datalakes/ICONS.md`](../datalakes/ICONS.md) records where each shipped icon came from. Replacing or removing one is a PNG and a manifest line.

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_DATALAKE_ROOT` | none | Reads the shipped sources from this directory instead of `<repo_root>/datalakes`. |
| `CURIO_DEFAULT_SOCRATA_APP_TOKEN` | none | A Socrata app token every account inherits until it saves its own. |
| `CURIO_DEFAULT_HUGGINGFACE_TOKEN` | none | A Hugging Face token every account inherits until it saves its own. |
| `CURIO_MEDIA_CACHE_MAX_GB` | none | How much each account may hold in cached bucket files. Default 20. |

**Sources ship with the deployment.** To change or remove a shipped one, edit the sources directory and restart. The Docker image bakes `datalakes/` in; see [DEPLOYMENT.md § Configure the stack](DEPLOYMENT.md#1-configure-the-stack).

**Your own sources** go in `.curio/datalakes/<sourceId>@<major>/manifest.json`, which the `.curio` volume keeps across image rebuilds. They are listed after the shipped ones after a restart. A `folder` source there takes an absolute `root`, and an id a shipped source already uses is refused. Nodes cannot write to this directory.

**Folders.** Mount a folder read-only; Curio never writes to one. Under `--deploy`, node code runs as `curio-exec`, which must be able to read the folder: at startup the backend logs every folder source it cannot, with the reason. See [DEPLOYMENT.md § Storage sources](DEPLOYMENT.md#storage-sources).

**Outbound requests.** This catalog makes requests to third-party portals on your users' behalf. What bounds them is in [DEPLOYMENT.md § Outbound requests](DEPLOYMENT.md#outbound-requests).

---

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where downloads land, and how a dataset reaches a dataflow.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the Dataset Finder and the other agents.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#data-lake-catalog): how search and downloads work, and how to add a provider.
- [`docs/schemas/data-lake-source.v1.json`](schemas/data-lake-source.v1.json): the manifest JSON Schema.
