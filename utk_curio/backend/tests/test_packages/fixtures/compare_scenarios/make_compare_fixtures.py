"""Make the fixtures that hold what Compare Scenarios' own functions wrote, on
the inputs the SCOUT examples' unit tests build.

Compare Scenarios left Curio in step 6.4 of the plan answering komar41's
review of the #914 merges (PR #1047). Main holds its functions before that
step, at 72f5d3df5 (``utk_curio/sandbox/util/scenario_difference.py`` and
``scenario_stack.py``). This script runs them there, the way main's unit tests
ran them, on the inputs those tests build, and writes what they returned
beside itself, which the tests hold the dataflows' comparing nodes, and the
rules in ``tests/_support/scenario_changes.py``, to:

- ``example06_roads_change.json``: Compare's Difference over example 06's
  Baseline and Twice as tall, on Back Bay's roads (autk-db's load of the
  extract, the minutes ``test_example06_sunlight_change.py`` gives them);
- ``flood_tracts.json``: over the flood example's two Tract depth outputs at
  the dataflow's own settings, keyed on FIPS, in Absolute; over the
  riverside tracts by hand with a tract left out of one side; and its stacked
  tables of the scatter, the grouped bars and the median chart;
- ``park_shade.json``: over each what-if's Shade per park and Existing's,
  keyed on the park, also with a park left out of one side, and its stacked
  table of the three. Deep Umbra's shadow moves with onnxruntime's thread
  count, so these run on fixed tables shaped like Shade per park's output
  (``park_shade_inputs`` in ``_support/scenario_changes.py``) rather than on a
  run's.

Make main's tree, then run this with Curio's Python, with Node's packages
installed in the checkout (``npm ci``) for autk-db:

    git -C <checkout> archive 72f5d3df5 -- utk_curio packages \\
        ':(exclude)packages/*/models' docs/examples vendor/duckdb-extensions \\
        package.json 'datasets/data.scout.flood-*' \\
        'datasets/data.cdc.quad-cities-svi-tracts@1' \\
        'datasets/data.usgs.quad-cities-waterways@1' | tar -x -C <tree>
    ln -s <checkout>/node_modules <tree>/node_modules
    python make_compare_fixtures.py <tree>
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAIN = "72f5d3df5"
SUPPORT = HERE.parents[2] / "_support" / "scenario_changes.py"


def _support():
    """This checkout's ``scenario_changes``, by its path: the fixtures are
    written in the shape the tests read them in."""
    spec = importlib.util.spec_from_file_location("checkout_scenario_changes", SUPPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store(root: Path) -> None:
    """A sandbox store of its own at *root*, as the tests' ``workspace`` makes one."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    root.mkdir(parents=True, exist_ok=True)
    os.environ["CURIO_LAUNCH_CWD"] = str(root)
    os.environ["CURIO_SHARED_DATA"] = str(root / "data")
    release_connection()
    init_db()


def _written(name: str, held: dict) -> None:
    held = {
        "madeBy": "utk_curio/backend/tests/test_packages/fixtures/compare_scenarios/make_compare_fixtures.py",
        "main": MAIN,
        **held,
    }
    (HERE / name).write_text(json.dumps(held, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print("wrote", name)


def _records(frame, support) -> dict:
    """A stacked table as main's tests read it: its columns, and its rows
    without the outlines."""
    geometry = getattr(frame, "_geometry_column_name", None)
    table = frame.drop(columns=[geometry] if geometry in frame.columns else [])
    return {
        "columns": list(frame.columns),
        "rows": [{key: support._json_value(value) for key, value in row.items()} for row in table.to_dict("records")],
    }


def example06(work: Path, support) -> None:
    """``back_bay_layers`` and ``_compares_difference`` of main's
    ``test_example06_sunlight_change.py``, run as that test ran them."""
    from utk_curio.cli import dependencies
    from utk_curio.common.autk_data_compiler import compile_data_spec
    from utk_curio.sandbox.app.worker import _worker_init, execute_js_code
    from utk_curio.sandbox.tests.test_autk_server_data_load import _FETCH_FROM_DISK
    from utk_curio.sandbox.util.db import init_db, release_connection
    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb
    from utk_curio.sandbox.util.scenario_difference import difference_scenarios

    test = importlib.import_module("utk_curio.backend.tests.test_example06_sunlight_change")
    home = work / "back-bay"
    home.mkdir(parents=True)
    saved_home = Path.home
    os.environ.update({
        "HOME": str(home), "FLASK_BACKEND_HOST": "curio-backend.invalid", "FLASK_BACKEND_PORT": "1",
        "CURIO_LAUNCH_CWD": str(home), "CURIO_SHARED_DATA": str(home / "data"),
    })
    Path.home = lambda: home
    try:
        (loader,) = [n for n in test._dataflow()["nodes"] if n["id"] == test.LOADER]
        (source,) = json.loads(loader["content"])["data"]
        extract = source["pbfFileUrl"]
        code = compile_data_spec(loader["content"])
        serve = _FETCH_FROM_DISK.replace("EXTRACT", json.dumps(extract)).replace("ROOT", json.dumps(str(test.REPO)))
        release_connection()
        init_db()
        dependencies.seed_duckdb_extensions()
        _worker_init()
        result = execute_js_code(serve + code, "", "AUTK_GRAMMAR", "", launch_dir=str(test.REPO), session_id=None)
        assert result["output"]["path"], result["stderr"]
        layers = load_from_duckdb(result["output"]["path"], session_id=None)
        release_connection()
    finally:
        Path.home = saved_home
    assert [layer["name"] for layer in layers] == test.LAYERS
    (roads,) = [layer for layer in layers if layer["name"] == test.ROADS]
    assert len(roads["geojson"]["features"]) == test.ROAD_COUNT

    _store(work / "store-06")

    def compares(baseline, twice):
        values = [load_from_duckdb(art_id) for art_id in test._stored((baseline, twice))]
        written = difference_scenarios(
            [(scenario, name, value) for (scenario, name), value in zip(test.SCENARIOS, values)], layer=test.ROADS,
        )
        return load_from_duckdb(save_to_duckdb(written, node_id="compare-scenarios"))

    baseline, twice = (test._handed_on(layers, scenario) for scenario, _name in test.SCENARIOS)
    in_place = compares(baseline, twice)
    shapes = [json.dumps(feature["geometry"], sort_keys=True) for feature in roads["geojson"]["features"]]
    first: dict = {}
    for road, shape in enumerate(shapes):
        first.setdefault(shape, road)
    order = sorted(range(len(shapes)), key=lambda road: (-first[shapes[road]], road))
    reordered = compares(baseline, test._handed_on(layers, "s-twice", order=order))
    # The values a change writes: the label, and the minutes in their column
    # and in the compute values; the other columns are Twice as tall's tags.
    held = support.frame_fixture(in_place, ["change", "compute", "sunlight"])
    assert support.frame_fixture(reordered, ["change", "compute", "sunlight"]) == held, (
        "Compare's change moved with the order of the roads"
    )
    _written("example06_roads_change.json", {
        "inputs": "Back Bay's roads as test_example06_sunlight_change.py hands them on, Baseline then Twice as tall",
        "call": 'difference_scenarios([("s-baseline", "Baseline", ...), ("s-twice", "Twice as tall", ...)], '
                'layer="table_osm_roads"), read back from the store; the same with Twice as tall\'s roads reordered',
        "change": held,
    })


def flood(work: Path, support) -> None:
    """The Compare Scenarios references of main's ``test_scout_flood.py``,
    run on the inputs its tests build, as they ran them."""
    import numpy as np

    from utk_curio.sandbox.util.parsers import load_from_duckdb, save_to_duckdb

    test = importlib.import_module("utk_curio.backend.tests.test_packages.test_scout_flood")
    root = work / "flood"
    _store(root)
    here = os.getcwd()
    os.chdir(root)
    try:
        ran = test._run_both_scenarios_riverside_part(root)
        run, paths = ran["run"], ran["paths"]

        def run_on(node, part, nbs_path=None):
            output, _ = run(node, repr([paths[("no-nbs", part)], nbs_path or paths[("nbs", part)]]), "outputs",
                            circles=2)
            return load_from_duckdb(output["path"])

        change = run_on(test._reference(("tract depth", "difference")), "tract depth")
        reversed_tracts = save_to_duckdb(ran[("nbs", "tract depth")].iloc[::-1].reset_index(drop=True),
                                         node_id="nbs-tracts-reversed")
        again = run_on(test._reference(("tract depth", "difference")), "tract depth", reversed_tracts)
        assert support.frame_fixture(again) == support.frame_fixture(change), "the change moved with NbS's order"
        scatter = run_on(test._reference(("tract depth", "chart")), "tract depth")
        by_period = run_on(test._reference(("by period", "chart")), "by period")

        loaded, error = test._run_loaders(run)
        assert error is None, error
        statistics = {}
        for scenario, parts in test._scenario_parts(test._dataflow()).items():
            _depth, table, error = test._run_scenario(run, loaded, parts["choose"], parts["statistics"])
            assert error is None, error
            statistics[scenario] = table["path"]
        output, _ = run(test._reference(("statistics", "chart")), repr([statistics["no-nbs"], statistics["nbs"]]),
                        "outputs", circles=2)
        median = load_from_duckdb(output["path"])

        tracts, _water = test._riverside_by_hand()
        none = tracts[[*test.TRACT_COLUMNS, "geometry"]].reset_index(drop=True)
        rng = np.random.default_rng(test.RIVERSIDE_TRACTS)
        none["mean_depth_m"] = np.round(rng.uniform(0, 4, len(none)), 3)
        none["land_km2"] = np.round(rng.uniform(1, 12, len(none)), 3)
        nbs = none.copy()
        nbs["mean_depth_m"] = np.where(np.arange(len(nbs)) % 5 == 0, none["mean_depth_m"],
                                       np.round(none["mean_depth_m"] * 0.7, 3))
        fips = list(none["FIPS"])
        left_out, only_with_nbs = fips[test.LEFT_OUT], fips[test.ONLY_WITH_NBS]
        cases = {
            "removed": (none, nbs[nbs["FIPS"] != left_out].reset_index(drop=True)),
            "added": (none[none["FIPS"] != only_with_nbs].reset_index(drop=True), nbs),
        }
        one_side = {}
        for kind, (before, after) in cases.items():
            inputs = repr([save_to_duckdb(before, node_id=f"no-nbs-{kind}"), save_to_duckdb(after, node_id=f"nbs-{kind}")])
            output, _ = run(test._reference(("tract depth", "difference")), inputs, "outputs", circles=2)
            one_side[kind] = support.frame_fixture(load_from_duckdb(output["path"]))
    finally:
        os.chdir(here)
    _written("flood_tracts.json", {
        "inputs": "test_scout_flood.py's riverside part at the dataflow's own settings (No NbS on circle 0, NbS on "
                  "circle 1), and its riverside tracts by hand for the one-side cases",
        "call": 'curio_difference_scenarios([...], absolute=True, key="FIPS") and curio_stack_scenarios([...]), as '
                "the Compare Scenarios nodes the dataflow held wrote them (_compare_references), read back",
        "change": support.frame_fixture(change),
        "oneSide": one_side,
        "scatter": _records(scatter, support),
        "byPeriod": _records(by_period, support),
        "median": _records(median, support),
    })


def park_shade(work: Path, support) -> None:
    """The Compare Scenarios references of main's
    ``test_lower_manhattan_park_shade.py``, run as its tests ran them
    (``_run_code``), on fixed Shade per park tables."""
    from utk_curio.sandbox.app.worker import _worker_init

    test = importlib.import_module("utk_curio.backend.tests.test_packages.test_lower_manhattan_park_shade")
    root = work / "park"
    _store(root)
    _worker_init()
    tables = support.park_shade_inputs(test.PARKS)
    existing = tables["existing"]
    change, one_side = {}, {}
    for scenario, name, _color, key in test.SCENARIOS[1:]:
        reference = {"id": f"compare-{key}-park-change", "type": test.COMPARE,
                     "content": test._difference_code(scenario, name, key="park")}
        what_if = tables[scenario]
        written, _printed = test._run_code(reference, [existing, what_if], [], root / "media")
        again, _printed = test._run_code(reference, [existing, what_if.iloc[::-1].reset_index(drop=True)], [],
                                         root / "media")
        assert support.frame_fixture(again) == support.frame_fixture(written), "the change moved with the parks' order"
        change[scenario] = support.frame_fixture(written)
        cases = {
            "removed": (existing, what_if[what_if["park"] != test.LEFT_OUT].reset_index(drop=True)),
            "added": (existing[existing["park"] != test.ONLY_IN_THE_WHAT_IF].reset_index(drop=True), what_if),
        }
        one_side[scenario] = {}
        for kind, inputs in cases.items():
            written, _printed = test._run_code(reference, list(inputs), [], root / "media")
            one_side[scenario][kind] = support.frame_fixture(written)
    chart = {"id": "compare-chart", "type": test.COMPARE, "content": test.CHART_CODE}
    stacked, _printed = test._run_code(chart, [tables[scenario] for scenario, _n, _c, _k in test.SCENARIOS], [],
                                       root / "media")
    _written("park_shade.json", {
        "inputs": "park_shade_inputs(PARKS) in tests/_support/scenario_changes.py: Existing on circle 0, the what-if "
                  "on circle 1; the three for the stack, in the dataflow's order",
        "call": 'curio_difference_scenarios([...], key="park") and curio_stack_scenarios([...]), as the Compare '
                "Scenarios nodes the dataflow held wrote them (_difference_code, CHART_CODE), read back",
        "change": change,
        "oneSide": one_side,
        "stack": _records(stacked, support),
    })


def main(argv: list) -> int:
    tree = Path(argv[1]).resolve()
    assert (tree / "utk_curio" / "sandbox" / "util" / "scenario_difference.py").exists(), (
        f"{tree} holds no Compare Scenarios: make it from main at {MAIN}"
    )
    sys.path.insert(0, str(tree))
    import utk_curio

    assert Path(utk_curio.__file__).resolve().is_relative_to(tree), f"utk_curio comes from {utk_curio.__file__}"
    support = _support()
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        example06(work, support)
        flood(work, support)
        park_shade(work, support)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
