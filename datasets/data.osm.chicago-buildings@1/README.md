# Chicago OSM Buildings

1,117,259 building footprints, copied from the existing local SCOUT extract
`backend/data/catalog/osm/chicago/buildings.feather` and converted losslessly
in geometry/attribute content to GeoParquet for Curio's Data Catalog.

Columns: `osm_id`, `osm_type`, `min_height`, `height`, `geometry`.
CRS: EPSG:4326. Heights are preprocessed values in metres. SCOUT's extraction
code can estimate missing heights from levels or apply defaults. The height
column must not be interpreted as exclusively surveyed measurements.

Original OSM snapshot date was not supplied with the Feather file. The manifest
creation date describes packaging in Curio, not the age of the underlying data.

Attribution: © OpenStreetMap contributors; preprocessing by SCOUT.
Database license: Open Data Commons Open Database License (ODbL) 1.0.
https://www.openstreetmap.org/copyright

Used by **Building Height Rasterizer**. Keep this folder in the shared dataset
catalog when moving that computation package to another installation.
