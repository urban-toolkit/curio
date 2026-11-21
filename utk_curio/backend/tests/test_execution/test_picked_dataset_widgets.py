"""A dataset widget an input picks (``options.pickedBy`` and ``options.choices``)
in the scans of a saved dataflow, which have no input to pick by: each scan
names every choice, so what a run of the dataflow may read is staged for it
whichever the input picks (Solve's validation, an agent's run through a node,
the collections a dataflow's runs read).

The shared cases of ``codeReferences.cases.json`` pin what a run writes once
it has read the input's value; these pin what a scan reads without it.
``code_references`` is imported inside each test, so a checkout without it
fails each test on its own.
"""

from __future__ import annotations

CHOICES = {
    "W042": "data.test.w042-records",
    "W065": "data.test.w065-records",
    "W06E": "data.test.w06e-records",
}


def _picked(name="data", choices=None, picked_by="input_0.camera"):
    return {
        "name": name, "type": "dataset", "label": "Data", "default": "",
        "options": {"pickedBy": picked_by, "choices": dict(choices or CHOICES)},
    }


def _loader(code="data = curio_load_data([!! data !!])\nreturn data", widgets=None):
    return {
        "id": "load", "type": "curio.builtin/data-loading", "content": code,
        "metadata": {"widgets": list(widgets) if widgets is not None else [_picked()]},
    }


def test_a_scan_of_a_saved_node_names_every_choice():
    from utk_curio.backend.app.datasets.domain.code_refs import collection_ids_in_code, dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import node_run_code

    scanned = node_run_code(_loader())

    assert dataset_ids_in_code(scanned) == list(CHOICES.values()), scanned
    assert collection_ids_in_code(scanned) == list(CHOICES.values()), scanned


def test_a_scan_names_every_choice_of_each_picked_widget():
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import node_run_code

    depths = {"2020 - 2050": "data.test.depth-2020", "2050 - 2080": "data.test.depth-2050"}
    node = _loader(
        code="a = curio_load_data([!! data !!])\nb = curio_load_data([!! depth !!], bounds=bounds)\nreturn a, b",
        widgets=[_picked(), _picked(name="depth", choices=depths, picked_by="input_1")],
    )

    scanned = node_run_code(node)

    assert sorted(dataset_ids_in_code(scanned)) == sorted([*CHOICES.values(), *depths.values()]), scanned


def test_a_scan_of_a_plain_dataset_widget_names_its_dataset_as_before():
    from utk_curio.backend.app.datasets.domain.code_refs import dataset_ids_in_code
    from utk_curio.backend.app.execution.code_references import node_run_code

    plain = {"name": "data", "type": "dataset", "label": "Data", "default": "", "value": "data.test.trees"}

    assert dataset_ids_in_code(node_run_code(_loader(widgets=[plain]))) == ["data.test.trees"]


def test_the_collections_a_saved_dataflow_reads_are_every_choice(monkeypatch):
    """``resolve_spec_collections``, which Solve's validation and an agent's
    run through a node read a dataflow's collections with, asks for each
    choice, so the one the input picks is there when the node runs."""
    from utk_curio.backend.app.discovery.application import exec_collections

    asked = []

    def resolve(ids, user_key, **_kwargs):
        asked.extend(ids)
        return {}

    monkeypatch.setattr(exec_collections, "resolve_collections", resolve)
    monkeypatch.setattr(exec_collections, "media_dir_for", lambda *_args, **_kwargs: None)

    exec_collections.resolve_spec_collections(
        {"dataflow": {"nodes": [_loader()], "edges": []}}, "4242", user=object(),
    )

    assert asked == list(CHOICES.values())
