import { v4 as uuid } from "uuid";
import { AccessLevelType, BoxType } from "../constants";

export const templates = [
    {
        id: uuid(),
        type: BoxType.DATA_LOADING,
        name: "Parks (OSM)",
        description: "Load parks for Chicago using OSM",
        accessLevel: AccessLevelType.ANY,
        code: "import utk \n\
uc = utk.OSM.load([!! bbox$INPUT_LIST_VALUE$[41.88043474773062,-87.62760230820301,41.89666220782541,-87.59872148227429] !!], layers=[[!! layer$SELECTION$parks$parks;water !!]]) \n\
gdf = uc.layers['gdf']['objects'][0] \n\
gdf.metadata = {'name': [!! layer$SELECTION$parks$parks;water !!]} \n\
return gdf",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_LOADING,
        name: "Load Observation Points",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import pandas as pd \ndf_point = pd.read_csv(\"access_attributes.csv\") \nreturn df_point",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_CLEANING,
        name: "Clean Observation Points",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import pandas as pd\nimport geopandas as gpd\nfrom shapely.geometry import Point\n\ndf_point = arg\n\ncolumns_to_keep = [\"Label Type\", \"Attribute Latitude\", \"Attribute Longitude\", \"Agree Count\", \"Disagree Count\", \"Unsure Count\"]\ndf_point_filtered = df_point[columns_to_keep]\n\ndf_point_filtered[\"Label Type\"] = df_point_filtered[\"Label Type\"].fillna(\"Other\")\ndf_point_filtered = df_point_filtered.dropna(subset=[\"Attribute Latitude\"])\ndf_point_filtered = df_point_filtered.dropna(subset=[\"Attribute Longitude\"])\ndf_point_filtered[\"Agree Count\"] = df_point_filtered[\"Agree Count\"].fillna(0)\ndf_point_filtered[\"Disagree Count\"] = df_point_filtered[\"Disagree Count\"].fillna(0)\ndf_point_filtered[\"Unsure Count\"] = df_point_filtered[\"Unsure Count\"].fillna(0)\n\ndf_point_filtered = df_point_filtered.rename(columns={\"Label Type\": \"label\"})\ndf_point_filtered = df_point_filtered.rename(columns={\"Attribute Latitude\": \"latitude\"})\ndf_point_filtered = df_point_filtered.rename(columns={\"Attribute Longitude\": \"longitude\"})\ndf_point_filtered = df_point_filtered.rename(columns={\"Agree Count\": \"agree\"})\ndf_point_filtered = df_point_filtered.rename(columns={\"Disagree Count\": \"disagree\"})\ndf_point_filtered = df_point_filtered.rename(columns={\"Unsure Count\": \"unsure\"})\n\ndf_point_filtered[\"geometry\"] = df_point_filtered.apply(lambda row: Point(row[\"longitude\"], row[\"latitude\"]), axis=1)\n\ngdf_point = gpd.GeoDataFrame(df_point_filtered, geometry=\"geometry\", crs=\"EPSG:4326\")\n\nreturn gdf_point",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.COMPUTATION_ANALYSIS,
        name: "Uncertainty Points",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "gdf_point = arg.set_crs(4326)\ngdf_point = gdf_point.to_crs(3395)\ngdf_point[\"total_votes\"] = gdf_point[\"agree\"] + gdf_point[\"disagree\"] + gdf_point[\"unsure\"]\ngdf_point['total_votes'] = gdf_point['total_votes'].replace(0, 1)\ngdf_point[\"uncertainty\"] = (abs(gdf_point[\"disagree\"] - gdf_point[\"agree\"]) + gdf_point[\"unsure\"]) / gdf_point[\"total_votes\"]\ngdf_point = gdf_point[[\"uncertainty\", \"geometry\"]]\ngdf_point.metadata = {\n 'name': 'ponctual'\n}\nreturn gdf_point",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_LOADING,
        name: "Load Neighborhood Data",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\ngdf_neighborhood = gpd.read_file(\"access_score_neighborhood.geojson\")[[\"coverage\", \"avg_attribute_count\", \"geometry\", \"neighborhood_name\"]]\nreturn gdf_neighborhood",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_CLEANING,
        name: "Clean Neighborhood Data",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\n\ngdf_neighborhood = arg\n\ngdf_neighborhood = gdf_neighborhood.join(pd.json_normalize(gdf_neighborhood[\"avg_attribute_count\"])).drop(columns=[\"avg_attribute_count\"])\n\ngdf_neighborhood = gdf_neighborhood.dropna(subset=[\"coverage\"])\ngdf_neighborhood = gdf_neighborhood.dropna(subset=[\"geometry\"])\ngdf_neighborhood = gdf_neighborhood.dropna(subset=[\"neighborhood_name\"])\ngdf_neighborhood[\"CurbRamp\"] = gdf_neighborhood[\"CurbRamp\"].fillna(0)\ngdf_neighborhood[\"NoCurbRamp\"] = gdf_neighborhood[\"NoCurbRamp\"].fillna(0)\ngdf_neighborhood[\"Obstacle\"] = gdf_neighborhood[\"Obstacle\"].fillna(0)\ngdf_neighborhood[\"SurfaceProblem\"] = gdf_neighborhood[\"SurfaceProblem\"].fillna(0)\n\nreturn gdf_neighborhood",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.COMPUTATION_ANALYSIS,
        name: "Accessibility Neighborhood",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import numpy as np\n\ngdf_neighborhood = arg.set_crs(4326)\ngdf_neighborhood = gdf_neighborhood.to_crs(3395)\n\nw_noCurb = 1\nw_obstacle = 1\nw_surfaceProblem = 1\nw_curb = 1\n\nnumerator = (w_noCurb * gdf_neighborhood[\"NoCurbRamp\"] + \n             w_obstacle * gdf_neighborhood[\"Obstacle\"] + \n             w_surfaceProblem * gdf_neighborhood[\"SurfaceProblem\"])\n\ndenominator = w_curb * gdf_neighborhood[\"CurbRamp\"]\n\ngdf_neighborhood[\"accessibility\"] = np.where(\n    denominator == 0, \n    0, \n    numerator / denominator\n)\n\nmin_val = gdf_neighborhood[\"accessibility\"].min()\nmax_val = gdf_neighborhood[\"accessibility\"].max()\n\ndenominator = max_val - min_val\n\nif denominator == 0:\n    gdf_neighborhood[\"accessibility\"] = 0  # Set a default value\nelse:\n    gdf_neighborhood[\"accessibility\"] = (gdf_neighborhood[\"accessibility\"] - min_val) / denominator\n\n\ngdf_neighborhood = gdf_neighborhood[[\"geometry\", \"accessibility\", \"neighborhood_name\"]]\n\ngdf_neighborhood.metadata = {\n 'name': 'neighborhood'\n}\n\nreturn gdf_neighborhood",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.VIS_VEGA,
        name: "Accessibility Neighbodhood Barchart",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "{\n    \"$schema\": \"https://vega.github.io/schema/vega-lite/v5.json\",\n    \"params\": [\n        {\n            \"name\": \"highlight\",\n            \"select\": {\"type\": \"point\", \"on\": \"pointerover\"}\n        }\n    ],\n    \"mark\": {\n        \"type\": \"bar\",\n        \"fill\": \"#4C78A8\",\n        \"stroke\": \"black\",\n        \"cursor\": \"pointer\"\n    },\n    \"encoding\": {\n        \"x\": {\n            \"field\": \"neighborhood_name\", \n            \"type\": \"ordinal\",\n            \"sort\": \"y\"\n        },\n        \"y\": {\"field\": \"accessibility\", \"type\": \"quantitative\"},\n        \"fillOpacity\": {\n            \"condition\": {\"param\": \"highlight\", \"value\": 1},\n            \"value\": 0.3\n        },\n        \"color\": { \n            \"field\": \"interacted\", \n            \"type\": \"nominal\", \n            \"condition\": {\n                \"test\": \"datum.interacted === '1'\", \"value\": \"red\", \"else\": \"blue\"\n            } \n        }\n    },\n    \"config\": {\n        \"scale\": {\n            \"bandPaddingInner\": 0.2\n        }\n    }\n}",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_TRANSFORMATION,
        name: "Group Uncertainty by Neighborhood",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\n\ngdf_point = arg[0].set_crs(3395)\ngdf_neighborhood = arg[1].set_crs(3395)\n\ngdf_point = gdf_point.to_crs(gdf_neighborhood.crs)\n\ngdf_neighborhood[\"neighborhood_id\"] = gdf_neighborhood.index \n\ngdf_joined = gpd.sjoin(gdf_point, gdf_neighborhood, predicate=\"within\")\n\ndf_aggregated = gdf_joined.groupby(\"neighborhood_id\")[\"uncertainty\"].mean().reset_index()\n\ngdf_neighborhood_aggregated = gdf_neighborhood.merge(df_aggregated, on=\"neighborhood_id\", how=\"left\")\n\ngdf_neighborhood_aggregated[\"uncertainty\"] = gdf_neighborhood_aggregated[\"uncertainty\"].fillna(0)\n\ngdf_neighborhood_aggregated = gdf_neighborhood_aggregated[[\"geometry\", \"uncertainty\"]]\n\ngdf_neighborhood_aggregated.metadata = {\n 'name': 'neighborhood'\n}\n\nreturn gdf_neighborhood_aggregated",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_LOADING,
        name: "Load Street Data",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\n\ngdf_streets = gpd.read_file(\"access_score_streets.geojson\")[[\"attribute_count\", \"geometry\"]]\n\nreturn gdf_streets",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_CLEANING,
        name: "Clean Street Data",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\n\ngdf_streets = arg\n\ngdf_streets = gdf_streets.join(pd.json_normalize(gdf_streets[\"attribute_count\"])).drop(columns=[\"attribute_count\"])\n\ngdf_streets = gdf_streets.dropna(subset=[\"geometry\"])\ngdf_streets[\"CurbRamp\"] = gdf_streets[\"CurbRamp\"].fillna(0)\ngdf_streets[\"NoCurbRamp\"] = gdf_streets[\"NoCurbRamp\"].fillna(0)\ngdf_streets[\"Obstacle\"] = gdf_streets[\"Obstacle\"].fillna(0)\ngdf_streets[\"SurfaceProblem\"] = gdf_streets[\"SurfaceProblem\"].fillna(0)\n\nreturn gdf_streets",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.COMPUTATION_ANALYSIS,
        name: "Accessibility Street",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import numpy as np\n\ngdf_streets = arg.set_crs(4326)\ngdf_streets = gdf_streets.to_crs(3395)\n\nw_noCurb = 1\nw_obstacle = 1\nw_surfaceProblem = 1\nw_curb = 1\n\nnumerator = (w_noCurb * gdf_streets[\"NoCurbRamp\"] + \n             w_obstacle * gdf_streets[\"Obstacle\"] + \n             w_surfaceProblem * gdf_streets[\"SurfaceProblem\"])\n\ndenominator = w_curb * gdf_streets[\"CurbRamp\"]\n\ngdf_streets[\"accessibility\"] = np.where(\n    denominator == 0, \n    0, \n    numerator / denominator\n)\n\nmin_val = gdf_streets[\"accessibility\"].min()\nmax_val = gdf_streets[\"accessibility\"].max()\n\ndenominator = max_val - min_val\n\nif denominator == 0:\n    gdf_streets[\"accessibility\"] = 0  # Set a default value\nelse:\n    gdf_streets[\"accessibility\"] = (gdf_streets[\"accessibility\"] - min_val) / denominator\n\ngdf_streets = gdf_streets[[\"geometry\", \"accessibility\"]]\n\ngdf_streets.metadata = {\n 'name': 'street'\n}\n\nreturn gdf_streets",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_TRANSFORMATION,
        name: "Street Buffer",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\nfrom shapely.geometry import box\n\ngdf_streets = arg.set_crs(3395)\n\ngdf_streets = gdf_streets.to_crs(epsg=4326)\n\nmin_lat, max_lat = 47.616220289927874, 47.634222478980206\nmin_lon, max_lon = -122.30315628410251, -122.2731115883161\nbbox = box(min_lon, min_lat, max_lon, max_lat)\ngdf_streets = gdf_streets[gdf_streets.geometry.intersects(bbox)]\n\ngdf_streets = gdf_streets.to_crs(epsg=3857)  # Web Mercator (meters)\n\ngdf_polygons = gdf_streets.copy()\ngdf_polygons[\"geometry\"] = gdf_polygons.geometry.buffer(5)\n\ngdf_polygons = gdf_polygons.to_crs(epsg=3395)  # WGS84 (lat/lon)\n\ngdf_polygons.metadata = {\n 'name': 'street'\n}\n\nreturn gdf_polygons",
        custom: false,
    },
    {
        id: uuid(),
        type: BoxType.DATA_TRANSFORMATION,
        name: "Group Uncertainty by Street",
        description: "",
        accessLevel: AccessLevelType.ANY,
        code: "import geopandas as gpd\nfrom shapely.ops import nearest_points\n\ngdf_points = arg[0].set_crs(3395)\ngdf_streets = arg[1].set_crs(3395)\n\ngdf_streets = gdf_streets.sjoin_nearest(gdf_points[['geometry', 'uncertainty']], how=\"left\", distance_col=\"distance\")\n\ngdf_streets = gdf_streets[[\"geometry\", \"uncertainty\"]]\n\n\ngdf_streets.metadata = {\n 'name': 'street'\n}\n\nreturn gdf_streets",
        custom: false,
    },
];

// [41.88043474773062, -87.62760230820301, 41.89666220782541, -87.59872148227429], layers=['parks']
// layers=[!! layers$INPUT_LIST_TEXT$[\"parks\"] !!]
// [!! layer$INPUT_TEXT$parks !!]
