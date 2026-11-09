"""What a node's code can call, as the header above its code lists it, and a
package's functions, as its details list them.

- A module offers what its ``__all__`` names. The shipped packages name, in the
  module node code imports it from, only what node code calls: Deep Umbra's
  ``deep_umbra`` offers ``accumulated_shadow`` and ``season_factor``, and its
  other modules nothing; Rasterization's modules the calls its README lists,
  the mosaics in ``scout_rasters.mosaic``; Media's ``media_collections`` the
  two its video and audio nodes call; the weather model's ``weather_routing``
  its route. Every name a shipped ``__all__`` lists is a function its module
  offers, with a docstring.
- ``GET /api/packages/node-functions?nodeType=``: the engine of the node's
  template, Curio's functions for that engine from the page that lists them
  (``skills/node-functions/SKILL.md``), and, for a Python node, the functions
  the modules a run hands it offer, its own package's first, as Accumulated
  Shadow's and Mosaic Rasters' headers list Rasterization's after their own
  package's. Each with the call a click on it writes.
- ``GET /api/packages/<dir>/functions``: each module of a package with the
  functions it offers, from the account's copy, else the catalog's.

New code is imported inside each test, so a checkout without it fails each
test on its own instead of the whole module at collection.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGES = REPO / "packages"
DEEP_UMBRA = PACKAGES / "model.scout.deep-umbra@1"
RASTERIZATION = PACKAGES / "curio.rasterization@1"
MEDIA = PACKAGES / "curio.media@1"
WEATHER_GNN = PACKAGES / "model.scout.weather-gnn@1"
SHADOW = "model.scout.deep-umbra/accumulated-shadow"
MOSAIC = "curio.media/mosaic-rasters"

#: Rasterization's modules that offer a function, as a header lists them
#: after the node's own package's, in module order.
RASTERIZATION_LISTED = [
    ("curio.rasterization@1", "scout_rasters.mosaic"),
    ("curio.rasterization@1", "scout_rasters.node_outputs"),
    ("curio.rasterization@1", "scout_rasters.raster_algebra"),
    ("curio.rasterization@1", "scout_rasters.web_tiles"),
]


def _offered(package: Path) -> dict[str, list[tuple[str, str]]]:
    """``{module: [(name, call)]}`` for each module of the shipped *package*."""
    from utk_curio.backend.app.packages.application.function_nodes import module_functions
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    rows = module_functions(package, load_package_manifest(package))
    assert all(row["problem"] is None for row in rows), rows
    return {row["module"]: [(f["name"], f["call"]) for f in row["functions"]] for row in rows}


# ---------------------------------------------------------------------------
# What the shipped packages offer
# ---------------------------------------------------------------------------

def test_deep_umbra_offers_accumulated_shadow_and_season_factor_from_the_package():
    assert _offered(DEEP_UMBRA) == {
        "deep_umbra": [
            ("accumulated_shadow", "accumulated_shadow(value, season, model, output_file)"),
            ("season_factor", "season_factor(season)"),
        ],
        "deep_umbra.deep_umbra": [],
        "deep_umbra.node_outputs": [],
    }


def test_rasterization_offers_the_calls_its_readme_lists_and_the_weather_model_its_route():
    assert _offered(RASTERIZATION) == {
        "scout_rasters": [],
        "scout_rasters.convert_to_raster": [],
        "scout_rasters.mosaic": [
            ("mosaic_rasters", "mosaic_rasters(tiles, path, *, crs, dtype, bands=1, nodata=None, resolution=None, "
                               "fill=0, band_descriptions=None, tags=None)"),
            ("mosaic_collection", "mosaic_collection(tiles, output_file)"),
        ],
        "scout_rasters.node_outputs": [
            ("rasterize_buildings", "rasterize_buildings(buildings, attribute, zoom, max_height, output_file)"),
        ],
        "scout_rasters.raster_algebra": [
            ("raster_calculate", "raster_calculate(operation, rasters, codes=None, *, absolute=False, output_file=None)"),
            ("raster_statistics", "raster_statistics(raster, band=1, mask=None, mask_values=None, where=None)"),
        ],
        # mosaic_web_tiles writes with mosaic_rasters, which scout_rasters.mosaic offers.
        "scout_rasters.web_tiles": [
            ("tile_bounds", "tile_bounds(x, y, zoom, crs='EPSG:3395')"),
            ("mosaic_web_tiles", "mosaic_web_tiles(tiles, zoom, path, *, crs='EPSG:3395', tile_size=256, "
                                 "dtype='float32', fill=0, nodata=None, band_descriptions=None, tags=None)"),
        ],
    }
    offered = _offered(WEATHER_GNN)
    routing = offered.pop("weather_routing")
    assert [name for name, _call in routing] == ["calculate_weather_route"]
    assert offered == {
        "weather_routing.calculate_isochrones": [],
        "weather_routing.road_graph": [],
        "weather_routing.weather_routing": [],
        "weather_routing.weight_calculation": [],
    }


def test_media_offers_the_calls_of_its_video_and_audio_nodes_from_media_collections():
    assert _offered(MEDIA) == {
        "media_collections": [
            ("sample_video_frames", "sample_video_frames(media, derived_file, *, every_seconds=2.0, max_frames_per_video=300)"),
            ("split_audio", "split_audio(media, derived_file, *, window_seconds=5.0, max_windows_per_recording=2000)"),
        ],
    }


def _values(tree: ast.Module) -> set[str]:
    """The names the module's top level assigns a value to."""
    targets = [
        target for node in tree.body if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (node.targets if isinstance(node, ast.Assign) else [node.target])
    ]
    return {name.id for target in targets for name in ast.walk(target) if isinstance(name, ast.Name)}


def test_every_name_a_shipped_modules_all_lists_is_there_and_each_function_says_what_it_does():
    """A name in a shipped ``__all__`` that nothing answers would be offered
    to nobody: each one is a function the module offers, one it defines or
    imports from its package, or a value it defines, such as Deep Umbra's
    model's input and output names; and each function says what it does in
    its docstring."""
    from utk_curio.backend.app.packages.application.function_nodes import PackageModules
    from utk_curio.backend.app.packages.domain.function_nodes import offered_names
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    checked = 0
    for folder in sorted(path.parent for path in PACKAGES.glob("*/manifest.json")):
        modules = PackageModules(folder, load_package_manifest(folder))
        for module, path in modules.files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            names = offered_names(tree)
            if names is None:
                continue
            functions = [f.name for f in modules.functions(module)]
            values = _values(tree)
            stray = [name for name in names if name not in functions and name not in values]
            assert not stray, f"{folder.name}: {module}'s __all__ names {stray}, which it neither offers nor defines"
            assert functions == [name for name in names if name in functions], (folder.name, module, functions)
            for function in modules.functions(module):
                assert function.doc, f"{folder.name}: {module}.{function.name} says nothing in its docstring"
            checked += 1
    # Deep Umbra's three, Rasterization's five, the weather model's five and Media's one.
    assert checked >= 14, checked


# ---------------------------------------------------------------------------
# The header's route
# ---------------------------------------------------------------------------

def _get(client, token: str | None, query: str):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get(f"/api/packages/node-functions{query}", headers=headers)


def _account(user) -> str:
    from utk_curio.backend.app.packages.application.seeding import seed_dev_packages
    from utk_curio.backend.app.projects.services import _user_dir_key

    key = _user_dir_key(user)
    seed_dev_packages(user_key=key)
    return key


def test_the_header_lists_what_accumulated_shadows_code_can_call(client, user_and_token):
    from utk_curio.backend.app.agents.domain import node_functions
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    key = _account(user)
    for package in (RASTERIZATION, DEEP_UMBRA):
        install_package_from_directory(key, package)

    answer = _get(client, token, f"?nodeType={SHADOW}")
    assert answer.status_code == 200, answer.get_data(as_text=True)
    listed = answer.get_json()
    assert listed["engine"] == "python"
    # Its own package's module first, then Rasterization's, which Deep Umbra
    # names in dependencies.packages; a module that offers nothing is left out.
    assert [(row["package"], row["module"]) for row in listed["modules"]] == [
        ("model.scout.deep-umbra@1", "deep_umbra"),
        *RASTERIZATION_LISTED,
    ]
    shadow, season = listed["modules"][0]["functions"]
    assert shadow == {
        "name": "accumulated_shadow",
        "call": "accumulated_shadow(value, season, model, output_file)",
        "doc": "The accumulated shadow of the heights in *value*, in *season*, from the Deep Umbra session "
               "*model*: a raster in minutes on the heights' own grid. *output_file(name)* names where it is written.",
        "insert": "accumulated_shadow(value, season, model, output_file)",
    }
    assert (season["call"], season["insert"]) == ("season_factor(season)", "season_factor(season)")
    assert season["doc"].startswith("Minutes of shadow a pixel at 1 stands for")
    algebra = listed["modules"][3]["functions"]
    assert [(f["name"], f["insert"]) for f in algebra] == [
        ("raster_calculate", "raster_calculate(operation, rasters)"),
        ("raster_statistics", "raster_statistics(raster)"),
    ]
    # Curio's functions for Python, as the page that lists them gives them.
    page = node_functions.for_engine("python")
    assert [f["name"] for f in listed["curio"]] == [f.name for f in page]
    by_name = {f["name"]: f for f in listed["curio"]}
    assert by_name["curio_load_model"] == {
        "name": "curio_load_model", "call": "curio_load_model(model_id)",
        "doc": next(f.does for f in page if f.name == "curio_load_model"), "insert": "curio_load_model(model_id)",
    }
    assert by_name["curio_derived_file"]["insert"] == "curio_derived_file(dataset_id, file_id, t_ms)"
    assert by_name["curio_derived_file"]["call"] == (
        'curio_derived_file(dataset_id, file_id, t_ms, ext=None, *, kind="video", tag=None)'
    )


def test_mosaic_rasters_lists_medias_module_then_rasterizations_whose_mosaic_its_code_calls(client, user_and_token):
    """A Media node is handed Media's module, then Rasterization's, which Media
    names in dependencies.packages: Mosaic Rasters' code returns
    ``mosaic_collection``'s call, under ``scout_rasters.mosaic``."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    key = _account(user)
    for package in (RASTERIZATION, MEDIA):
        install_package_from_directory(key, package)

    answer = _get(client, token, f"?nodeType={MOSAIC}")
    assert answer.status_code == 200, answer.get_data(as_text=True)
    listed = answer.get_json()
    assert listed["engine"] == "python"
    assert [(row["package"], row["module"]) for row in listed["modules"]] == [
        ("curio.media@1", "media_collections"),
        *RASTERIZATION_LISTED,
    ]
    assert [(f["name"], f["insert"]) for f in listed["modules"][0]["functions"]] == [
        ("sample_video_frames", "sample_video_frames(media, derived_file)"),
        ("split_audio", "split_audio(media, derived_file)"),
    ]
    assert [(f["name"], f["insert"]) for f in listed["modules"][1]["functions"]] == [
        ("mosaic_rasters", "mosaic_rasters(tiles, path, crs=crs, dtype=dtype)"),
        ("mosaic_collection", "mosaic_collection(tiles, output_file)"),
    ]
    assert all(f["doc"] for row in listed["modules"] for f in row["functions"]), listed["modules"]


def test_a_javascript_node_lists_curios_functions_for_javascript_and_a_spec_nothing(client, user_and_token):
    from utk_curio.backend.app.agents.domain import node_functions

    user, token = user_and_token
    _account(user)

    javascript = _get(client, token, "?nodeType=curio.builtin/js-computation").get_json()
    assert javascript["engine"] == "javascript" and javascript["modules"] == []
    assert [f["name"] for f in javascript["curio"]] == [f.name for f in node_functions.for_engine("javascript")]
    assert javascript["curio"][0]["insert"] == "curio_layer(value, layer)"

    python = _get(client, token, "?nodeType=curio.builtin/python-computation").get_json()
    assert python["engine"] == "python" and python["modules"] == []
    assert [f["name"] for f in python["curio"]] == [f.name for f in node_functions.for_engine("python")]

    for spec in ("curio.builtin/vis-vega", "curio.builtin/autk-grammar", "ai.nobody/nothing"):
        assert _get(client, token, f"?nodeType={spec}").get_json() == {"engine": None, "curio": [], "modules": []}


@pytest.mark.parametrize("query", ["", "?nodeType=", "?nodeType=" + "x" * 201])
def test_the_route_wants_a_node_type(client, user_and_token, query):
    _user, token = user_and_token
    refused = _get(client, token, query)
    assert refused.status_code == 400 and "'nodeType'" in refused.get_json()["error"], refused.get_json()


def test_the_route_wants_a_session(client):
    assert _get(client, None, f"?nodeType={SHADOW}").status_code == 401


# ---------------------------------------------------------------------------
# A package's details
# ---------------------------------------------------------------------------

def test_the_details_list_each_module_with_its_functions_from_the_account_else_the_catalog(client, user_and_token):
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    user, token = user_and_token
    key = _account(user)
    headers = {"Authorization": f"Bearer {token}"}

    def shown() -> dict:
        answer = client.get(f"/api/packages/{DEEP_UMBRA.name}/functions", headers=headers)
        assert answer.status_code == 200, answer.get_data(as_text=True)
        body = answer.get_json()
        assert body["dirName"] == DEEP_UMBRA.name
        return {row["module"]: [f["call"] for f in row["functions"]] for row in body["modules"]}

    expected = {
        "deep_umbra": ["accumulated_shadow(value, season, model, output_file)", "season_factor(season)"],
        "deep_umbra.deep_umbra": [],
        "deep_umbra.node_outputs": [],
    }
    # The catalog's copy, before the account adds it, then the account's.
    assert shown() == expected
    install_package_from_directory(key, RASTERIZATION)
    install_package_from_directory(key, DEEP_UMBRA)
    assert shown() == expected
    for missing in ("ai.nobody@1", "not-a-package"):
        assert client.get(f"/api/packages/{missing}/functions", headers=headers).status_code == 404
