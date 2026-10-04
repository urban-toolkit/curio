# Discovery Catalog

The Discovery Catalog is where Curio lists the **open data portals**, the **storage**, the **services** and the **models** it can reach: folders on the Curio machine, public S3 buckets, Hugging Face dataset repositories, OpenStreetMap, street-level images from Mapillary and Google Street View, and image segmentation models on Hugging Face. You search a portal and download a dataset, open a storage source and add one of the resources it declares, tell a service where and what and download its answer, or add a model. A dataset lands in your Data Catalog, and a model in your Model Catalog.

Curio has five catalogs: the [Node Catalog](NODE-CATALOG.md) holds the nodes you drop on the canvas, the [Data Catalog](DATA-CATALOG.md) the datasets they read, the [Model Catalog](MODEL-CATALOG.md) the models they run, the [Agent Catalog](AGENT-CATALOG.md) the assistants you attach to them, and the Discovery Catalog the portals, storage, services and models you take datasets and models from.

This guide is in eight parts, plus operator notes:

- [1. What is the Discovery Catalog?](#1-what-is-the-discovery-catalog): sources, what ships, and where things are stored.
- [2. Surfaces and workflows](#2-surfaces-and-workflows): the two pages, the action matrix, and walkthroughs.
- [3. Using a discovered dataset in a dataflow](#3-using-a-discovered-dataset-in-a-dataflow): tables and collections are Data Catalog datasets.
- [4. Downloading and adding](#4-downloading-and-adding): what a download asks, progress, formats, limits, what is copied and what is referenced, street-level images, and models.
- [5. API tokens](#5-api-tokens): sources that take a key, how to set yours step by step, and what a card says.
- [6. The Dataset Finder](#6-the-dataset-finder): letting an agent search the portals for you.
- [7. Importing, publishing, and sharing](#7-importing-publishing-and-sharing): how sources are added.
- [8. The manifest](#8-the-manifest): the fields a source declares, what it asks before a download, and how a storage source declares its files.
- [Operator notes](#operator-notes): adding your own sources, mounting folders, and the cache limit.

---

## 1. What is the Discovery Catalog?

### Concept

The unit of this catalog is a **source**. A source is not a dataset. There are four kinds:

- **A portal**, such as a city's open data site. Its datasets are found live, when you search it, and you download the ones you want.
- **A storage source**: a folder on the Curio machine, a public S3 bucket, or a Hugging Face dataset repository. Its manifest declares its **resources**, and how the files of each are organized, the way a portal's manifest declares its endpoints. Curio lists what the manifest declares and never guesses a layout.
- **A service**, such as OpenStreetMap, Mapillary or Google Street View. It has nothing to browse: you say where (an area) and what (one of the resources its manifest declares, such as Buildings or Street-level images), and it answers with one download.
- **A model source**, **Hugging Face models**. You search it as you search a portal, and **Add to Model Catalog** puts a model in your [Model Catalog](MODEL-CATALOG.md), for a node to run.

A storage resource is one of two things:

- **A table**: CSV, JSON, GeoJSON, Parquet, GeoPackage, shapefile or OSM PBF files. Adding it copies it into your Data Catalog, as a download does. Many files of one resource, such as one CSV per sensor and day, become one table.
- **A collection**: rasters, video frames, images, videos, or audio. Adding it indexes it: the Data Catalog gains one dataset with a row per file, and the files stay where they are.

A folder of images is therefore one row in the Discovery Catalog and one dataset in your Data Catalog, not one per image.

A source is a folder with a `manifest.json`, identified by `source.<publisher>.<source>` and a major version:

```
discovery/
  source.cityofchicago.data-portal@1/
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
| OpenStreetMap | OpenStreetMap (Autark) | Public. Buildings, roads, parks, water, land surface, points of interest and features by tag for a box or for named areas, loaded by Autark |
| Example storage | Folder | Public. A small instance of each way storage is organized, which the storage examples read |
| Sentinel-2 over Chicago | S3 bucket | Public. True-color previews and thumbnails of one month's scenes |
| Hugging Face documentation images | Hugging Face | Public; a token raises the rate limit |
| Mapillary | Mapillary | Token needed. Street-level photos for a box, each credited to its photographer (CC BY-SA 4.0), and the signs and objects detected in them, as points |
| Google Street View | Google | Key needed; Google bills its requests to you. Street View images for a box, one per panorama and heading |
| Overture Maps | Overture Maps | Public. Buildings, building parts, places and road segments for a box, from Overture's latest release |
| Hugging Face models | Hugging Face | Public; a token opens the gated models your account can read. Image segmentation models a node can run |

### Storage layers

| Layer | On disk | Written by |
|---|---|---|
| **Sources**, the portals and storage this install can reach | `<repo_root>/discovery/<sourceId>@<major>/`, or the directory `--discovery-root` names, and `.curio/discovery/` for an operator's own | The operator. Nothing in the app writes here. |
| **Your token**, for sources that take one | Your account | You, on the **API keys** tab of **API Settings**. |
| **Downloaded and added datasets** | Your Data Catalog store, `.curio/users/<user-key>/datasets/` | **Download** and **Add to Data Catalog**. A table is an ordinary imported dataset; a collection is its index. |
| **A collection's files** | Where the source keeps them | Nobody. Curio reads them in place. |
| **A service's images**, from Mapillary or Google Street View | Your Data Catalog store, with the collection | **Download**. |
| **A bucket collection's cached files** | Your account's media folder | **Cache files**, up to a per-account limit. |
| **Added models** | Your Model Catalog store, `.curio/users/<user-key>/models/` | **Add to Model Catalog**. |

---

## 2. Surfaces and workflows

There are two pages and a drawer on the canvas, plus an agent that works on the canvas:

- **The `/catalog/discovery` page** lists the sources. Reach it from `/projects` and the **Discovery Catalog** tab. Filter by provider or access in the left rail. Type in **Search every portal…** and the cards give way to results from every source at once, each tagged with the source it came from. With a filter set in the rail, the search asks only the sources the filter shows. Click a card to describe it in the right-hand drawer, or right-click it for its actions.
- **A source's page**, `/catalog/discovery/<sourceId>@<major>`, is one source on its own. Reach it with **Browse datasets** on a card, in the drawer, or in the right-click menu, or **Add by link** for Direct URL. A portal's page lists nothing until you search, then shows that portal's matches and how many there are. Direct URL's page has a **Link to a file** field. A service's page lists what it can be asked for, a row each. A storage source's page lists its resources at once: a row for each, or for each value or file when its manifest splits it. A row has a kind (**Table**, **Rasters**, **Frames**, **Images**, **Videos**, **Photos and videos**, or **Audio**) and its format, a line saying what it holds (files, images and videos, frames in sequences, or recordings), what its path fields cover, and its size. A collection's row also shows its first files as thumbnails.
- **The canvas drawer**: on the canvas, the **Discovery Catalog** button in the top bar opens the sources beside the dataflow. **Search every portal…** searches every source at once; **Browse datasets** on a card opens that source in the drawer, as its page shows it, and **All portals** goes back to the cards. What you download or add lands in the Data or Model Catalog, as it does from the pages, and a model's **View model** opens the Model Catalog drawer.
- **The Dataset Finder**, an agent you attach on the canvas, can search the portals for you and propose a download. See [part 6](#6-the-dataset-finder).

On both pages the search is kept in the page address, so a search can be linked and survives a reload. On a storage source's page the search filters its resources by name, description and field values.

GeoSampa, storage sources and services match a search the same way: each word you type on its own, in any order, with or without accents. A word of four letters or more that ends in *s* also finds the word without the *s*. `ponto onibus`, `pontos de ônibus` and `onibus ponto` all find GeoSampa's *Pontos de ônibus*, and `distritos` finds its *Distrito*. GeoSampa lists first the layers whose name or title holds the most of your words. Other portals search in their own way.

A storage source is read when it is first opened, and again when its listing is 15 minutes old. While that runs the page says **Scanning `<source>`…**, and keeps the rows of the last reading. **Rescan** reads it again at once, for files added since. When the source holds files no resource declares, the page says how many.

### Action matrix

| Action | Where | What it changes | What you see |
|---|---|---|---|
| **Search every portal** | The `/catalog/discovery` search box | Nothing | Results from every portal that can be searched, and the storage sources' matching resources, tagged by source. |
| **Browse datasets** | Card, drawer, or right-click menu | Nothing | The source's page, searching that portal only. |
| **Show more** | Below a portal's results, on its page | Nothing | The portal's next page of results, added below the ones shown. |
| **View details** | Card, drawer, or right-click menu | Nothing | The source's endpoint, licence, formats, download limit, and token needs; a storage source's resource count. |
| **Add by link** | Direct URL's card, drawer, or right-click menu | Nothing | Direct URL's page, with its **Link to a file** field. |
| **Download** | A result row, with a format picker when the portal offers more than one | Your Data Catalog gains a dataset | A progress bar, then *"Downloaded `<title>` to your Data Catalog."* with **View details**. A row that needs an answer first, such as a service row's area, opens the **Download** dialog. |
| **Narrow…** | A portal row that can download part of itself, also once it is in your Data Catalog | Nothing until you download | The **Download** dialog, to download only the rows inside an area. |
| **Cancel** | The row's progress bar | Nothing is kept | The download stops. |
| **View dataset** | A row marked **In your Data Catalog** | Nothing | The dataset's details, over the page. |
| **View on the portal ↗** | A result row | Nothing | The dataset's page on the portal's own site, in a new tab. |
| **Add to Data Catalog** | A storage source's row | Your Data Catalog gains a dataset | A dialog to keep only some values of each path field, when there are any to choose from, then a progress bar, then *"Added `<title>` to your Data Catalog."* with **View details**. |
| **Add again** | A storage source's row marked **In your Data Catalog** | Your Data Catalog gains a dataset, when the row's files changed | A progress bar, then *"Added `<title>` to your Data Catalog."*, or *"Nothing has changed in `<title>` since it was added."* |
| **Files** | A storage source's row | Nothing | The row's files, 50 at a time, with thumbnails for a collection's. Pick some and **Add N picked files** adds only those. |
| **Rescan** | A storage source's page | Nothing | The source is read again, and its rows show what it holds. |
| **Cache files** | A bucket collection's details, in the Data Catalog | Your account's media folder | Its files are copied to the Curio machine, so nodes can read them. |
| **Add to Model Catalog** | A Hugging Face models row | Your Model Catalog gains a model | A progress bar, then *"Added `<name>` to your Model Catalog."* with **View model**. A guest on a `--deploy` instance is refused before anything downloads. |
| **View model** | A row marked **In your Model Catalog** | Nothing | The model's details, in the Model Catalog. |
| **Set a token** | **API Settings**, **API keys** tab | Your account | The source's card reads **Token set**. |

### Workflows

**I want a dataset but do not know which portal has it.** Open `/catalog/discovery` and type in the search box. Every searchable portal and every storage source is asked at once and the results are interleaved. If a portal is slow or down, a line names it and the other results still show. A storage source still being read for the first time is named in a line of its own, and its rows join the results when it is done.

**I want to download a dataset and use it.** Find it, pick a format if the row offers a choice, and click **Download**. When it finishes, the row offers **View dataset**. To use it in a dataflow, add it from the Data Catalog ([part 3](#3-using-a-discovered-dataset-in-a-dataflow)).

**I want to search one portal only.** Click **Browse datasets** on its card. The source's page searches that portal alone and lists 20 results at a time; **Show more** below them adds the next 20.

**I want only the rows inside an area.** On a Chicago Data Portal or GeoSampa row, click **Narrow…**, set the **Area**, and click **Download**. A dataset with no location column offers no **Narrow…**.

**I want OpenStreetMap buildings for a neighbourhood.** Open the OpenStreetMap card's page and click **Download** on **Buildings**. Set the **Area**: a place, coordinates or a dataset's extent give a box; **Named areas** takes a place and the boundaries inside it, as OpenStreetMap names them. **Download** loads them through Autark, and the dataset is named after the area: one row per building or building part, with its tags and its `osm_id`. Footprints that touch share a `building_id`, as an Autark map draws them as one building. **All layers** adds buildings, roads, parks, water and surface as one group.

**I want the cafés in a neighbourhood.** Open the OpenStreetMap card's page and click **Download** on **Features by tag**. Set the **Area**, type `amenity=cafe` in **Tags** and press Enter, and click **Download**. The cafés land as one group named after the tags and the area: a points dataset for cafés mapped as a point, and a polygons dataset for those mapped as a building or an area. **Points of interest** does the same for amenities, shops, tourism, leisure, offices, crafts, healthcare and historic sites, with no tags to type.

**I want Overture's buildings, places or roads for an area.** Open the Overture Maps card's page and click **Download** on **Buildings**, **Building parts**, **Places** or **Road segments**. Set the **Area** to a box (a place, coordinates or a dataset's extent) and click **Download**. The rows land as one GeoParquet dataset named after the area, each with the columns Overture gives it, such as `height`, `num_floors`, `class`, `names` and `sources` for a building.

**I want street-level photos of an area.** Set your Mapillary access token ([part 5](#5-api-tokens)), open the Mapillary card's page, and click **Download** on **Street-level images**. Set the **Area**, and if you like **Taken between**, **Images** (all, panoramas only, or no panoramas), **Size** and **Most images**. The photos land as one collection of images, each row with its photographer (`creator`), `captured_at`, `compass_angle`, `is_pano`, `sequence` and position. **Map features** downloads the signs and objects Mapillary detected in a box, as a table of points. [Example 10](examples/10-street-vision-cv-analysis.md) segments a set of these photos.

**I want Google Street View images.** Set your Google Maps API key, with the Street View Static API enabled on it ([part 5](#5-api-tokens)). Open the Google Street View card's page and click **Download** on **Street View images**. Set the **Area**, the **Spacing** of the points Curio asks for a panorama, the **Headings**, **Field of view**, **Pitch** and **Size** of each image, and **Most images**. The images land as one collection, a row per panorama and heading, each with its `pano_id`, `heading`, the month it was `captured`, and its position. Google bills each request to your key.

**I want a model a node can run.** Open the **Hugging Face models** card's page and search it, for example for `segformer`. Each row names the model's task, its weights (ONNX or safetensors), its downloads and its license. Click **Add to Model Catalog**; when it is done, the row offers **View model**. On the canvas, drag the model from **Model Catalog** in the left Tools panel onto an **Image Segmentation** node: see [MODEL-CATALOG.md](MODEL-CATALOG.md).

**I have a link to a file.** Click **Add by link** on the Direct URL card, paste the link into **Link to a file**, and click **Download**. The link gets a row of its own, which offers **View dataset** once the file is in your Data Catalog.

**A source needs a token.** Get one from the source (its **View details** links to its instructions), add it with **Add configuration** on the **API keys** tab of **API Settings**, and save. [Part 5](#5-api-tokens) walks through it step by step.

**I want to know where a downloaded dataset came from.** Open the dataset's details in the Data Catalog. **Downloaded from** names the portal, links the resource on the portal's site, lists what the download was narrowed by (its **Area**, for one), and says when it was downloaded. A table added from a storage source says **Added from** instead, and how many files it was combined from. A collection has a **Collection** section: its kind, **Indexed from** the source and resource, how many files of each kind it holds, what its **Path fields** cover, the **Coverage** of its footprints or positions, and its rasters' **Raster CRS**.

**I have a folder of orthorectified images, by year.** Its manifest declares one `rasters` resource, `orthos/{year:int}/{tile}.tif`. The catalog lists one row with the years it covers; **Add to Data Catalog**, keeping only the years you want, gives one collection with each tile's footprint. On the canvas, a Vega-Lite map draws the footprints and **Mosaic Rasters** joins one year's tiles into one raster: see [example 18](examples/18-storage-orthorectified-imagery.md).

**I have a folder of video frames.** Its manifest declares one `frames` resource, such as `dashcam/{date:date}/{sequence}_{frame:int}.jpg`, with the frame rate as `fps`. The collection orders the frames by sequence and number and gives each its time; a telemetry table declared as `metadata` gives each frame a position. **Simple View** shows the frames in order: see [example 19](examples/19-storage-video-frames.md).

**I have a folder of CSV files, by sensor or by date.** Its manifest declares one `table` resource, such as `air-quality/{sensor}/{day:date}.csv`. Adding it copies every file into one Parquet table with a `sensor` and a `day` column, the rows of every file under the columns of all of them: see [example 20](examples/20-storage-folder-of-csv-files.md). With `"datasets": "per:sensor"` the catalog lists one row per sensor instead, and each adds as its own table.

**I have photos and videos.** A `media` resource takes both. Each photo carries its EXIF time and position, and a video plays in **Simple View**; **Sample Video Frames** turns videos into frames: see [example 21](examples/21-storage-photos-and-videos.md).

**I have audio recordings.** An `audio` resource, whose file names can carry the recording time. **Simple View** shows each recording as a spectrogram with **Play**, and **Split Audio** measures the level of each window: see [example 22](examples/22-storage-audio-recordings.md).

**I have a folder of unrelated data files.** Declare one resource per file, as a portal lists its datasets, and add each: see [example 23](examples/23-storage-folder-of-different-files.md). A folder of unrelated files of one format, such as `{name}.csv` with `"datasets": "per-file"`, lists one row per file.

---

## 3. Using a discovered dataset in a dataflow

A download, and a table added from a storage source, lands in your Data Catalog as an ordinary imported dataset, with a preview, a schema, and the same loader code as any other. Nothing downstream needs to know where it came from.

A collection lands as a dataset of format **Collection**. Its **Data Loading** node reads it with `curio_load_collection("<id>")`, which returns one row per file: the path fields, what Curio read from each file, and `path`, where the file can be opened. Rows with a position come back as a GeoDataFrame. **Simple View** shows the rows as cards; a video or a recording plays in its card. The `curio.media` package's nodes work on these rows: **Sample Video Frames**, **Split Audio** and **Mosaic Rasters**. See [DATA-CATALOG.md](DATA-CATALOG.md#collections) for the columns.

Downloading or adding does not add the dataset to a dataflow. Add it from the Data Catalog drawer on the canvas, then drag it onto the canvas: see [DATA-CATALOG.md part 3](DATA-CATALOG.md#3-using-a-dataset-in-a-dataflow).

---

## 4. Downloading and adding

### What a download asks

A source's manifest declares what it asks before a download, and the **Download** dialog asks it: an **Area**, dates, choices, numbers or a link. **Name in your Data Catalog** is the dataset's title. The dialog says what is missing or out of range, for example *"Area is needed."*, and downloads only once every answer is right.

The **Area** offers the ways the source takes:

| Way | What you do | What it sends |
|---|---|---|
| **Place** | Type a place, click **Search** or press Enter, and pick a match | The match's box, with its name |
| **Coordinates** | Type **West**, **South**, **East** and **North**, in degrees | That box |
| **A dataset's extent** | Pick a dataset with a location from your Data Catalog | The box around it, with its name |
| **Named areas** | Type a place in **Within**, a name in **Find areas**, click **Search**, and pick the boundaries found | The boundaries' names inside the place |

A box is shown under the field with its size, and refused when it is larger than the source allows. Place search is OpenStreetMap's Nominatim: it searches when you click **Search** and not as you type, and the results credit © OpenStreetMap contributors.

A portal row whose area is optional downloads all of itself from **Download**, and part of itself from **Narrow…**. Once all of it is in your Data Catalog, the row offers **View dataset** and **Narrow…**. After a download for an area, the row offers **View dataset** for it and keeps its **Download** and **Narrow…**, for another area or all of it. A service row's **Download** opens the dialog first, and its dataset is named after its area unless you type a name.

### Progress

While a download or an add runs, its row shows a progress bar and **Cancel**. The bar fills when the size is known, counts files when a resource has many, and shows what the work is doing otherwise.

- **Two at a time.** Each account runs at most two downloads, adds and **Cache files** at once.
- **A restart loses it.** A download still running when the server restarts is lost, and its row shows it as failed. Start it again.
- **Downloading again.** A row marked **In your Data Catalog as CSV** has been downloaded in that format; picking CSV offers **View dataset**, and nothing is fetched again, while another format still downloads. A download narrowed by an area is held for that area: the same answers again fetch nothing and keep the dataset you have, and another area downloads again. A file you downloaded by hand and imported from a Dataset Finder row counts too: a download and a hand import of the same bytes are one dataset, whichever arrived first.
- **Formats.** CSV, GeoJSON, JSON, Parquet, and GeoTIFF, narrowed by what each portal offers. A GeoTIFF download that is not a TIFF file is refused.
- **Size.** 1 GiB at most, or what the operator sets with `curio.py --discovery-max-download-mb`. A source may set a lower limit, which its **View details** shows as **Max download**. For an archive, the limit is on the download, not on what it unpacks to.
- **Archives.** A `.zip` or a `.gz` is unpacked, and what it holds lands in your Data Catalog:

  | The archive holds | It lands as |
  |---|---|
  | One file, gzipped (`wac.csv.gz`) | That file (`wac.csv`) |
  | One data file (CSV, GeoJSON, JSON, Parquet or GeoTIFF), with documentation such as `.txt`, `.pdf`, `.xml` or `.html` files beside it | That file. The documentation is left out |
  | A shapefile: its `.shp`, `.dbf` and `.shx`, and its `.prj` and `.cpg` when there are | One GeoParquet dataset, in EPSG:4326 |
  | A GTFS feed: `stops.txt` and another GTFS table, such as `routes.txt`, at the archive's root or in one top folder | One group, named after the download, with a dataset for each table: `stops` as points, `shapes` as one line per `shape_id`, and every other table (`routes`, `trips`, `stop_times`, ...) as a table. Every column is text, so ids keep their leading zeros, except the coordinates, `stop_sequence` and `shape_pt_sequence`, which are numbers. A stop without coordinates keeps its row, with no point |

  Anything else is refused, and the message names what the archive holds: several data files, for example, or none. A `.tar`, `.tgz`, `.7z`, `.bz2` or `.rar` archive is refused, before it is downloaded when its link or the server says what it is. An archive may hold at most 1,000 files and unpack to at most 4 GiB. A file in it of more than 1 MiB that expands to more than 200 times its compressed size, a link, a file whose path leads outside the archive, and an archive inside the archive are refused.

When a download fails, the row says why in the server's own words, for example that an archive holds several data files or that the file is larger than the limit.

### Downloading from OpenStreetMap

- **Autark loads it,** with the same code an Autark map uses. **Buildings**, **Roads**, **Parks**, **Water** and **Surface** (the land inside the area) are Autark's layers. One layer lands as one GeoJSON dataset, in EPSG:4326. **All layers** lands as one group, a dataset for each layer the area has features in, as an uploaded `.osm.pbf` lands as a group. An uploaded `.pbf` gives GDAL's layers (points, lines, multipolygons); a download gives Autark's.
- **Points of interest and Features by tag.** They load the nodes, ways and multipolygon relations with any of their tags: for **Points of interest**, `amenity`, `shop`, `tourism`, `leisure`, `office`, `craft`, `healthcare` or `historic`, with any value; for **Features by tag**, the tags you enter in **Tags**, each `key=value`, or `key=*` for the key with any value. They land as one group of up to three datasets, **points**, **polylines** and **polygons**, a dataset for each that has features.
- **What a row is.** Each row but the surface's is one OpenStreetMap node, way or relation. Every tag it has is a column, named as OpenStreetMap names it (`name`, `building:levels`, `highway`), and `osm_type` (`node`, `way` or `relation`) and `osm_id` name it on openstreetmap.org. A points row is a node; a polylines or polygons row is a way or a multipolygon relation. A building of several parts is one row per part. `building_id` groups footprints that touch, as an Autark map draws them as one building: a part shares it with its building, and separate buildings that share a wall, such as row houses, share one too. Each row's own building is its `osm_id`. **Surface** rows have no tags and no `osm_id`.
- **Numbers.** These tags are numbers, in metres for a length and kilometres per hour for a speed: `height`, `min_height`, `roof:height`, `building:height`, `width`, `est_width`, `maxheight`, `maxwidth`, `maxlength`, `ele` and `depth` (metres); `maxspeed`, `maxspeed:forward`, `maxspeed:backward` and `minspeed` (km/h); and the counts `building:levels`, `building:min_level`, `building:levels:underground`, `roof:levels`, `levels`, `min_level`, `lanes`, `lanes:forward`, `lanes:backward`, `lanes:both_ways`, `layer`, `capacity`, `seats`, `beds`, `rooms` and `building:flats`. A unit written in OpenStreetMap is converted: `40 ft` is 12.19, `12'6"` is 3.81, `30 mph` is 48.28. A value that is not one number, such as `maxspeed=none` or `building:levels=3;4`, is empty. Every other tag is text, as OpenStreetMap has it.
- **The area.** A box of at most 25 km², or named areas, held to the same 25 km² for the box around them. The names, and the place in **Within**, must match OpenStreetMap's names exactly, which are in the local language (**Find areas** finds Cologne as Köln), and a name with no boundary fails with a message naming it. Parks and water are cut at the box around the area. When **Surface** is loaded with them, as in **All layers**, roads, parks and water are also cut at the area's own outline, and a building outside it is left out. A building that crosses the edge is kept whole, and so is a road when **Surface** is not loaded. **Points of interest** and **Features by tag** are never cut: each feature is whole.
- **Time.** A download can take minutes: Autark waits for a free slot on OpenStreetMap's Overpass service before each request, pauses between requests, and fetches buildings in four parts. A download that takes more than 15 minutes, or comes to more than 512 MiB of GeoJSON, is stopped and says so.
- **On an Autark map.** The Data Loading node a layer makes on the canvas names the layer (`gdf.metadata = {"layerType": "buildings"}`), so an Autark map it feeds draws **Buildings** as buildings, raised to their height, and **Roads**, **Parks**, **Water** and **Surface** in their own colours.

What each layer holds:

| Layer | Rows | Shape |
|---|---|---|
| **Buildings** | Ways and relations tagged `building` or `building:part`, except sheds, garages, carports, huts, kiosks, toilets, service buildings, transformer towers, sties and containers | Areas |
| **Roads** | Ways tagged `highway`, except footways, cycleways, steps, pedestrian streets, platforms, elevators, raceways, roads that are proposed, under construction or abandoned, and ways tagged `area=yes` | Lines |
| **Parks** | Ways and relations tagged `leisure` park, playground, dog park or recreation ground; `landuse` wood, grass, forest, orchard, village green, vineyard, cemetery or meadow; or `natural` wood, grass, grassland, forest, scrub, heath or meadow | Areas |
| **Water** | Ways and relations tagged `natural` water, wetland, strait or spring, or `water` pond, reservoir, lagoon, stream pool, lake, pool, canal or river | Areas |
| **Surface** | The land inside the box, or inside the named areas' outline | Areas |
| **Points of interest** | Nodes, ways and multipolygon relations tagged `amenity`, `shop`, `tourism`, `leisure`, `office`, `craft`, `healthcare` or `historic` | Points, lines and areas |
| **Features by tag** | Nodes, ways and multipolygon relations with any of the tags entered | Points, lines and areas |

A way that is tagged as an area but does not close is a line. In **Points of interest** and **Features by tag**, a way that closes is an area unless it is tagged `area=no`, or is a `highway`, `barrier`, `railway` or `waterway` without `area=yes`; then it is a line.

### Downloading from Overture Maps

- **The latest release.** Each download reads the release Overture's catalog names as its latest. The dataset's description names the release and its license.
- **Only what the area needs.** Overture publishes each feature type as GeoParquet files, each with the box it covers. Curio reads the footers of the files whose box meets the area, then only their row groups whose box meets it, one request each.
- **What a row is.** One Overture feature whose bounding box meets the area, with every column Overture gives it, named as Overture names it. Nested columns such as `names` and `sources` stay nested. **Road segments** keeps the segments whose `subtype` is `road`. A feature that crosses the edge is kept whole.
- **The area.** A box of at most 100 km². A download that would read more than 512 MB of Overture's files is refused before any row is read, and says so.
- **On an Autark map.** **Buildings** and **Road segments** name their layer (`df.metadata = {"layerType": "buildings"}`), so an Autark map draws them as buildings, raised to their height, and as roads.
- **Credit.** Buildings and road segments are ODbL 1.0; Overture says how to credit each theme at [docs.overturemaps.org/attribution](https://docs.overturemaps.org/attribution/).

### Downloading street-level images

- **Mapillary.** A box of at most 25 km². Photos are taken from across the box, newest first, up to **Most images** (at most 1,000). Each one is CC BY-SA 4.0 and keeps its photographer in `creator`, so a figure made from them can credit each photo. Your token goes to Mapillary's API only, never to the hosts the photos come from.
- **Google Street View.** A box of at most 2 km². Curio asks Google for the panorama nearest each point of a grid with the **Spacing** you set, and keeps each panorama once, outdoor ones only unless you say otherwise. Then it downloads one image per panorama and heading. An image Google answers with its no-image placeholder is skipped. Your key is added to each request as Google's `key` parameter when the request is sent; the URLs a dataset records never hold it. The images are kept in your Data Catalog like any other download. Google's terms allow storing only panorama IDs, so check them before you keep the images.
- **Both** land as a collection of images whose files are copied to your Data Catalog store. Downloading again with the same answers fetches nothing and keeps the dataset you have. Such a collection does not offer **Cache files**, and a request to cache it is refused with *"`<title>` is already on this machine"*.
- **An image that cannot be fetched** is skipped, and the download keeps the rest. The message when the download finishes says how many could not be fetched, and so does the dataset's description on its Data Catalog card. When none can be fetched, the download fails.

### Adding a model

- **What Curio runs.** Semantic segmentation models, as ONNX graphs or as Transformers checkpoints with safetensors weights. A model with only `.bin` weights is refused, since loading those runs code from the model; so is a model of another task, one whose `config.json` names no labels, and one larger than 2 GB. The row says why.
- **The files.** Curio downloads the model's files as they are at the commit the Hub lists, with its `config.json` and `preprocessor_config.json`, which say how to read an image and what each class is called.
- **Libraries.** A Transformers model needs `torch`, `transformers` and `safetensors`, which Curio installs when the model is added, the way a node package's libraries install. When they do not install, the model is kept and the message says why. An account that may not install libraries cannot add a Transformers model; an ONNX model needs nothing more.
- **Gated models.** A model whose page asks you to accept its terms downloads once you have accepted them on Hugging Face and saved your Hugging Face token.
- **Adding again.** A row marked **In your Model Catalog** offers **View model**; adding it again keeps the model you have.

### Adding from a storage source

- **Tables are copied.** One file lands as itself. A shapefile brings its `.dbf`, `.shx`, `.prj` and `.cpg` with it, in whatever letter case they are named, and lands as GeoParquet; a GeoPackage or OSM PBF lands as one dataset per layer, as an upload does. A CSV declared with `options` is read with them and lands as Parquet. Several files land as one Parquet table, with a column per path field and a `source_file` column; a file's own column of the same name keeps its name, and the added one ends in `_from_path`. Geographic files land as one GeoParquet, in EPSG:4326, when they share a coordinate system. GeoPackage and PBF files are added one at a time, with `"datasets": "per-file"`.
- **Collections are referenced.** The Data Catalog keeps an index; the files stay where the source keeps them, and nothing is written to the source. Deleting the collection deletes its index and never the files.
- **Adding again.** A row marked **In your Data Catalog** offers **View dataset** and **Add again**. **Add again** reads the row's files: when they changed, it adds a new dataset of them, which the row then holds; when they did not, you keep the dataset you have, and a message says so.
- **Narrowing.** Keeping only some values in the **Add** dialog, or picking files under **Files**, adds a separate dataset of just those files. The row stays offered whole.
- **A bucket's files.** In a collection from a bucket or a Hugging Face dataset repository, each image and raster is indexed from its first 64 KiB, and a detail stored past them stays empty. Its videos and recordings are indexed by their path and size only. Thumbnails of its images and rasters are drawn on request; a video's or recording's appears once it is cached. Nodes read its files once **Cache files** has copied them to the Curio machine; until then a row's `path` is empty.
- **Size.** 4 GiB per file from a folder, and the download limit per file from a bucket; 512 MiB for a GeoPackage or PBF. A combined table takes up to 10,000 files, and 16 GiB from a folder or 2 GiB from a bucket. A source lists up to 200,000 matched files, or fewer when its manifest sets a lower limit, and its page says when it holds more. Adding a resource with more files than that limit is refused: pick files under **Files**, or narrow it in the **Add** dialog when its row offers **Add to Data Catalog**.
- **Rows that cannot be added.** A row over one of these limits, a shapefile without its `.dbf` or `.shx`, and GeoPackage or PBF files declared as one table say why under the row's name, and **Add to Data Catalog** is off. A row of several files still offers **Files**, to add some of them.
- **Publishing.** A collection cannot be published.

---

## 5. API tokens

Some sources take an API key. Mapillary and Google Street View need one. The City of Chicago portal and the Hugging Face sources answer without one, and a token raises your rate limit. A Hugging Face token also opens the gated and private repositories your account can read.

### Set a key, step by step

1. **Get the key** from the service. The key's form in API Settings links to where you get one (**Get a Mapillary access token**, for example), and so does the source's **View details**.
   - **Mapillary access token**: sign in at [mapillary.com/dashboard/developers](https://www.mapillary.com/dashboard/developers), register an application, and copy its **Client Token**. It starts with `MLY|`.
   - **Google Maps API key**: in the [Google Cloud console](https://developers.google.com/maps/documentation/streetview/get-api-key), create an API key and enable the **Street View Static API** for its project. Google bills its requests to you.
   - **Hugging Face token**: at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens), create a token with read access.
   - **Socrata app token**: sign up at [evergreen.data.socrata.com](https://evergreen.data.socrata.com/signup) and create an app token.
2. **Open API Settings** from the top bar. On `/projects` and the catalog pages it opens the settings page; on the canvas it opens on the right side. A source's **Add yours in API Settings** (**Change it in API Settings** once a key is saved), in its details, opens API Settings on that key's form.
3. On the **API keys** tab, click **Add configuration**.
4. In **Kind**, under **Data source**, choose the key's name: **Socrata app token**, **Hugging Face token**, **Google Maps API key** or **Mapillary access token**. The form says which sources use it.
5. **Paste the key** into the field and click **Save**. A line confirms it, for example *Saved the Mapillary access token.*
6. **Check the list and the card.** The key's row shows **saved** in its **Key** column. In the Discovery Catalog, the source's card reads **Token set** as soon as you save, also on a page that was already open, and its rows download.

### Your key and your account

A key belongs to your account, and is sent only to the source's own address. A saved key's row offers **Replace** and **Remove**. When whoever runs this Curio set one for everyone, the key is listed with **set by this Curio** in its **Key** column, and its **Override** saves your own key, which takes its place for your account.

A guest on a Curio started with `--deploy` cannot save a token. Without `--deploy`, the shared guest saves one like any account, and everyone using that Curio shares it.

A source that takes a token shows its state on the card:

| Badge | Meaning |
|---|---|
| **Token set** | A token will be sent: yours, or the inherited one. |
| **Token optional** | The portal works without one; a token raises the rate limit. |
| **Token needed** | The portal will not answer without one. The card offers no **Browse datasets** until a token is set. |

Curio never shows a token's value, only whether one is set.

---

## 6. The Dataset Finder

The **Dataset Finder** agent can look beyond your Data Catalog. Its candidate card has two lanes, **From your Data Catalog** and **External sources**, and an external row Curio can download is marked **Downloadable**: a row from one of these portals that offers downloads, or a plain https link to a file in a format Curio downloads, which goes through Direct URL.

Selecting rows writes a confirmation into the chat for you to send. A download the agent proposes appears as a review card, and nothing is downloaded until you apply it. The card shows the portal's own name, format and size for the resource, and an applied download lands in your Data Catalog like any other.

A **Downloadable** row has a **Download** button. It is this catalog's own download: the same job, which keeps going after you close the chat, and the resource shows one download on the card and on this catalog's page. The dataset it lands becomes the node's source. Confirming a Downloadable row downloads it the same way, and so does an applied download proposal.

An external source Curio has no connector for goes to **Node Builder**, which writes code to fetch it.

The Dataset Finder does not list, search or propose storage sources: you add their rows from this catalog's pages.

To add the Dataset Finder to a dataflow, see the [Agent Catalog](AGENT-CATALOG.md).

---

## 7. Importing, publishing, and sharing

Sources are not imported, published, or shared from the app. They ship with the deployment, or the operator adds one by adding its folder (see [part 8](#8-the-manifest) and the [operator notes](#operator-notes)), and every user on the install sees the same sources. On your own machine you are the operator: to list a folder of your own, write a manifest for it in `.curio/discovery/`.

What you download is yours, like any imported dataset. To offer it to everyone on the install, publish it from the Data Catalog ([DATA-CATALOG.md part 6](DATA-CATALOG.md#6-importing-publishing-and-sharing)).

---

## 8. The manifest

[`docs/schemas/discovery-source.v1.json`](schemas/discovery-source.v1.json) is the full reference for a source's `manifest.json`. The shipped sources in [`discovery/`](../discovery/) are the canonical examples.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | `source.<publisher>.<source>`: three to six dot-separated lowercase segments, naming who publishes it. |
| `name` | Yes | What the card says. |
| `version` | Yes | The manifest's own version string. |
| `compatibility.major` | | Defaults to 1. Together with `id` it forms the folder name. |
| `description`, `publisher`, `homepage`, `license`, `tags` | | Shown on the card and in the details. |
| `icon` | | A `.png` file in the source's folder, at most 256 KiB. Without one, the card shows the catalog's source glyph. |
| `provider.type` | Yes | A portal: `socrata`, `ckan`, `arcgis`, `wfs`, or `direct`. Storage: `folder`, `s3`, or `huggingface`. A service: `autark-osm`, `mapillary`, `google-streetview`, or `overture`. A model source: `huggingface-models`. |
| `provider.baseUrl` | Yes, except for `direct` and `folder` | The portal's https address, the bucket's endpoint, or `https://huggingface.co`, with no trailing slash. `https://overpass-api.de` for `autark-osm`, where Autark sends its requests; `https://graph.mapillary.com` for `mapillary`; `https://maps.googleapis.com` for `google-streetview`; `https://stac.overturemaps.org`, Overture's catalog, for `overture`. |
| `provider.root` | For `folder` | The folder, as an absolute path. A source shipped in `discovery/` may give one relative to the repository. |
| `provider.options` | | Settings for that software: the API path, `landingBase` for a CKAN portal whose pages live on another host, `prefix` for a bucket, `repo` and `revision` for a Hugging Face dataset repository, `imageHosts` for `mapillary` (the hosts its images come from; a domain covers its subdomains), `dataHosts` for `overture` (the hosts its GeoParquet files are read from), and `pipelineTag` for `huggingface-models` (the Hub task searched, `image-segmentation` by default). |
| `auth.mode` | | `public`, `optional-token`, or `required-token`. |
| `auth.secretId`, `auth.scheme` | With a token | Which account credential to send, and how. Curio knows `socrata.app-token`, `huggingface.token`, `google.maps-key` and `mapillary.token`. `scheme` is `header` (the default) or `query`, for an API that documents no other way. |
| `auth.headerName`, `auth.valuePrefix` | With `header` | The header, and what comes before the credential in it (`Bearer ` for Hugging Face, `OAuth ` for Mapillary). |
| `auth.paramName` | With `query` | The query parameter, `key` for Google. It is added when a request is sent, and no URL Curio records holds it. |
| `auth.helpUrl` | | Where a user gets a token. Shown in the details. |
| `capabilities.search`, `describe`, `download` | | What the portal supports. All default to true. |
| `capabilities.formats` | | A portal only: the formats it may deliver, from the five Curio downloads. A storage or service source's formats follow from its resources, and a manifest of either that declares them is refused. |
| `capabilities.maxDownloadBytes` | | A download limit for this source, below the server's (1 GiB unless `--discovery-max-download-mb` sets another). A larger value is read as the server's. |
| `capabilities.allowOffBaseDistributions` | | Lets a download come from a host other than `baseUrl`, for a CKAN portal whose files live on each publisher's own site. Off by default. |
| `limits.requestsPerMinute` | | Requests per minute to a portal, per user. Default 30. A storage source's requests are not counted. |
| `limits.maxFiles` | | A storage source: how many matched files it lists and adds at once. Default and most 200,000. |
| `resources` | For storage and services | What a storage or service source offers, below. |
| `parameters` | | What a download asks, below. A resource's own `parameters` replace the source's entries with the same `id`. |

### Parameters

Each entry of `parameters` is one question the **Download** dialog asks, and the server checks every answer against it.

| Field | What it declares |
|---|---|
| `id` | What the answer is called. A source may declare only the ids its provider reads: `area` for `socrata`, `wfs` and `autark-osm`, and `tags` for one `autark-osm` resource at a time, declared on that resource and required; `area`, `captured`, `imageType`, `size` and `maxImages` for `mapillary`; `area`, `spacing`, `headings`, `fov`, `pitch`, `size`, `outdoorOnly` and `maxImages` for `google-streetview`; `area` for `overture`; none for the others. |
| `type` | `area`, `dateRange`, `choice` (one, or several with `multiple`), `number`, `integer`, `boolean`, `text` (with a `pattern`), `url` (https), or `tags` (1 to 16 OpenStreetMap tags, each `key=value` or `key=*`, in any order). |
| `label`, `description` | What the dialog says. |
| `required` | Whether the download needs an answer. |
| `default`, `min`, `max`, `step`, `unit`, `options` | A number's range and a choice's options. |
| `accepts` | For an `area`: `box`, `names`, or both. `socrata`, `wfs`, `mapillary`, `google-streetview` and `overture` take a box; `autark-osm` takes both. |
| `maxAreaKm2` | For an `area`: the largest box, in km². |
| `suggestions` | For `tags`: OpenStreetMap keys the field offers as you type, such as `amenity` or `shop`. |

A Socrata dataset takes an area when it has a point, location, line or polygon column, and keeps the rows inside the box. A WFS layer takes it as its `bbox`.

### Resources

A service's `resources` say what it can be asked for: each has an `id`, a `name` and `description`, and a `kind`. A `table` resource has `format` `geojson`, or `parquet` for `overture`; an `images` resource lands as a collection. For `autark-osm`, each has one of: `options.layers`, the Autark layers it loads (`buildings`, `roads`, `parks`, `water`, `surface`); `options.tags`, the tags whose features it loads, each `key=value` or `key=*`; or a required `tags` parameter, the tags a person enters. For `mapillary`, `options.endpoint` is `images` for an `images` resource and `map_features` for a table. For `overture`, `options.theme` and `options.type` name the feature type as Overture's catalog does (`buildings` and `building`, `transportation` and `segment`), `options.subtype` keeps one subtype of it, and `options.layer` is the Autark layer an Autark map draws it as. A service resource has no `path`. A model source declares no resources: its models are found by searching it.

A storage source's `resources` say how its files are organized. `provider` says where they are.

| Field | Required | What it declares |
|---|---|---|
| `id` | Yes | Unique in the source. |
| `name`, `description` | `name` | What the row says. |
| `kind` | Yes | `table`, or a collection: `rasters`, `frames`, `images`, `videos`, `media` (images and videos together), or `audio`. |
| `path` | Yes | Which files belong to it, as a path template relative to the folder, bucket prefix or repository. |
| `format` | For `table` | `csv`, `json`, `geojson`, `parquet`, `gpkg`, `shp`, or `pbf`. |
| `datasets` | | How it adds: `one` dataset of every matched file (the default), `per:<field>` for one per value of a path field, listed as one row each, or `per-file`, for tables and rasters only. |
| `extensions` | | The file extensions it takes. A collection's follow its kind: images and frames take jpg, jpeg, png, webp, gif, bmp, tif and tiff; videos mp4, mov, m4v, webm, mkv and avi; media both; audio wav, flac, mp3, ogg, opus, m4a, aiff and aif; rasters tif, tiff and jp2. A table's follow its format: geojson and json for `geojson`, the format's own for the others. |
| `options` | | For a CSV table: `delimiter` and `header`. A table read with them lands as Parquet. |
| `fps` | | For `frames`: frames per second. A frame's `t_s` is its number over it. |
| `time` | | For a collection: the date or time path field that is each file's time, as `recorded_at` for audio and `taken_at` for the other kinds. |
| `metadata` | | For a collection: a CSV, Parquet or JSON table of up to 256 MiB, in the same source, joined onto its rows, as `{"path": ..., "on": ...}`, where `on` is `file_name`, `frame`, or a path field. Its `lat` and `lon` (or `latitude` and `longitude`) columns give a file its position. |

**Path templates.** A template matches each file's path:

| Part | Matches |
|---|---|
| `{name}` | Part of one folder or file name, as text. |
| `{name:int}` | A whole number. |
| `{name:date}` | A date written `2024-05-01`. |
| `{name:%Y%m%d_%H%M%S}` | A time, in the format it is written in. |
| `*` | Anything within one folder or file name. |
| `**` | Any number of folders. |

Each named part becomes a column of the dataset and a field the **Add** dialog can narrow by. For `frames`, `{sequence}` and `{frame:int}` name the sequence and the frame number; without `{sequence}`, a frame's folder is its sequence. Some names are taken by a collection's own columns (`path`, `name`, `kind`, `bytes`, and the like). A manifest that uses one is not listed, and the source's page gives the reason.

The example storage source's manifest, with one resource per use case (abridged):

```jsonc
{
  "id": "source.curio.example-storage", "name": "Example storage", "version": "1.0.0",
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

A bucket or a Hugging Face dataset repository is declared the same way, with the templates matching object keys:

```jsonc
{ "provider": { "type": "s3", "baseUrl": "https://sentinel-cogs.s3.us-west-2.amazonaws.com",
                "options": { "prefix": "sentinel-s2-l2a-cogs/16/T/DM/2024/7/" } },
  "resources": [ { "id": "previews", "name": "True-color previews", "kind": "rasters",
                   "path": "{scene}/L2A_PVI.tif" } ] }
```

Curio reads public S3 buckets, and Hugging Face dataset repositories, with your token for one that needs it. It does not sign S3 requests, reach buckets on a private network, or read images stored inside Parquet files.

[`discovery/ICONS.md`](../discovery/ICONS.md) records where each shipped icon came from. Replacing or removing one is a PNG and a manifest line.

---

## Operator notes

| Variable | Flag | Effect |
|---|---|---|
| `CURIO_DISCOVERY_ROOT` | `--discovery-root` | Reads the shipped sources from this directory instead of `<repo_root>/discovery`. |
| `CURIO_DISCOVERY_MAX_DOWNLOAD_MB` | `--discovery-max-download-mb` | The largest file a download or a bucket add takes, in megabytes. Default 1024. A source's manifest may set a lower limit for itself. |
| `CURIO_DEFAULT_SOCRATA_APP_TOKEN` | none | A Socrata app token every account inherits until it saves its own. |
| `CURIO_MEDIA_CACHE_MAX_GB` | none | How much each account may hold in cached bucket files and downloaded street-level images. Default 20. |

**Sources ship with the deployment.** To change or remove a shipped one, edit the sources directory and restart. The Docker image bakes `discovery/` in; see [DEPLOYMENT.md § Configure the stack](DEPLOYMENT.md#1-configure-the-stack).

**Your own sources** go in `.curio/discovery/<sourceId>@<major>/manifest.json`, which the `.curio` volume keeps across image rebuilds. They appear the next time the page loads. A `folder` source there takes an absolute `root`, and one whose folder name a shipped source already uses is not listed; the server's log says so. Under `--deploy`, nodes cannot write to this directory.

**Folders.** Mount a folder read-only; Curio never writes to one. Under `--deploy`, node code runs as `curio-exec`, which must be able to read the folder: at startup the backend logs every folder source it cannot, naming the folder or file in the way. See [DEPLOYMENT.md § Storage sources](DEPLOYMENT.md#storage-sources).

**Outbound requests.** This catalog makes requests to third-party portals, buckets and repositories on your users' behalf. What bounds them is in [DEPLOYMENT.md § Outbound requests](DEPLOYMENT.md#outbound-requests).

---

## See also

- [`docs/DATA-CATALOG.md`](DATA-CATALOG.md): where downloads land, and how a dataset reaches a dataflow.
- [`docs/MODEL-CATALOG.md`](MODEL-CATALOG.md): where added models land, and how a node runs one.
- [`docs/AGENT-CATALOG.md`](AGENT-CATALOG.md): the Dataset Finder and the other agents.
- [`docs/NODE-CATALOG.md`](NODE-CATALOG.md): the node package catalog.
- [`docs/ARCHITECTURE.md`](ARCHITECTURE.md#discovery-catalog): how search and downloads work, and how to add a provider.
- [`docs/schemas/discovery-source.v1.json`](schemas/discovery-source.v1.json): the manifest JSON Schema.
