"""DDRNet23-Slim as a model package, and the cell a model package's node opens with.

- DDRNet23-Slim is ``packages/model.curio.ddrnet23-slim@1``: its weights, their
  license, and one node, Image Segmentation, with no ``sources/``. The node is
  the one Curio writes for a segmentation model, the same a model downloaded
  from the Discovery Catalog gets. It replaces ``curio.streetvision@1`` and
  ``models/``, which are gone, and example 10 runs it.
- A model package's template that ships no ``source`` opens with the cell the
  backend writes for its model's type (``application/starters.py``): a
  segmentation model's loads it by id and calls ``curio_segment``, and runs as
  it is (the sandbox's ``test_vision.py`` runs it); an ``image-to-image`` or
  ``node-regression`` model's is a ``model.run`` skeleton naming each array
  its ONNX graph takes, read from the weights without onnxruntime and without
  downloading anything.

The code under test is imported inside each test, so a tree without it fails
test by test.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
DDRNET_ID = "model.curio.ddrnet23-slim"
DDRNET = REPO / "packages" / f"{DDRNET_ID}@1"
EXAMPLE_10 = REPO / "docs" / "examples" / "10-street-vision-cv-analysis.json"
LOCAL_RELIEF_GRAPH = REPO / "docs" / "bring-your-own-model" / "model.example.local-relief@1" / "models" / "local_relief.onnx"
WEATHER_GNN_GRAPH = REPO / "packages" / "model.scout.weather-gnn@1" / "models" / "weather_gnn.onnx"

SEGMENTATION_CELL = (
    f'model = curio_load_model("{DDRNET_ID}")\n'
    "classes = None  # every class the model names\n"
    "\n"
    "return curio_segment(input_0, model, classes)\n"
)


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _starters(user_key: str) -> dict[str, dict]:
    from utk_curio.backend.app.packages.application.starters import generate_package_starters

    return {starter["type"]: starter for starter in generate_package_starters(user_key)}


def _model_package(root: Path, package_id: str, model_type: str, graph: Path, *, model_input: dict | None = None) -> Path:
    """A model package of *model_type* around *graph*, whose one template
    ships no ``source``."""
    folder = root / f"{package_id}@1"
    (folder / "models").mkdir(parents=True)
    shutil.copyfile(graph, folder / "models" / "graph.onnx")
    block = {"type": model_type, "runtime": "onnx", "entry": "models/graph.onnx", "labels": [],
             "license": "MIT", "sizeBytes": graph.stat().st_size}
    if model_input is not None:
        block["input"] = model_input
    (folder / "manifest.json").write_text(json.dumps({
        "id": package_id, "version": "1.0.0", "name": package_id, "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model", "model": block,
        "templates": [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                       "editor": "code", "hasCode": True, "behavior": "code",
                       "inputPorts": [{"types": ["RASTER"]}], "outputPorts": [{"types": ["RASTER"]}]}],
    }), encoding="utf-8")
    return folder


def _install_archive(user_key: str, folder: Path) -> None:
    from utk_curio.backend.app.packages.application.store_install import install_package_from_archive
    from utk_curio.backend.app.packages.repositories.archive import zip_package_tree

    install_package_from_archive(user_key, zip_package_tree(folder))


# ---------------------------------------------------------------------------
# DDRNet23-Slim's model package
# ---------------------------------------------------------------------------

def test_ddrnet_is_a_read_only_model_package_that_validates():
    """Against the node-package schema and the parser: kind ``model``, its
    code's license MIT with Curio as publisher, its weights' license in its
    model block, onnxruntime its one library."""
    from jsonschema import Draft202012Validator

    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    schema = json.loads((REPO / "docs" / "schemas" / "node-package.v4.json").read_text(encoding="utf-8"))
    raw = _manifest(DDRNET)
    Draft202012Validator(schema).validate(raw)
    manifest = load_package_manifest(DDRNET)
    assert (manifest.package_id, manifest.kind, manifest.license, manifest.publisher, manifest.read_only) == (
        DDRNET_ID, "model", "MIT", "Curio", True,
    )
    assert dict(manifest.python_deps) == {"onnxruntime": ">=1.17"}
    assert (manifest.model.license, manifest.model.license_file) == ("MIT; trained on Cityscapes", "LICENSE")
    assert (DDRNET / "LICENSE").is_file() and (DDRNET / "README.md").is_file()


def test_ddrnet_ships_no_code_and_its_node_is_the_one_curio_writes_for_a_segmentation_model():
    """No ``sources/``: its Image Segmentation node is the template a
    downloaded segmentation model gets, field for field, with no ``source``."""
    from utk_curio.backend.app.packages.domain.default_cells import model_template

    raw = _manifest(DDRNET)
    assert not (DDRNET / "sources").exists()
    [template] = raw["templates"]
    assert template == model_template("semantic-segmentation")
    assert (template["id"], template["label"], template["category"]) == (
        "image-segmentation", "Image Segmentation", "computation")
    assert "source" not in template


def test_ddrnet_replaces_the_street_vision_package_and_the_models_folder():
    """``curio.streetvision@1`` is retired and ``models/`` is gone; example 10's
    two Image Segmentation nodes are DDRNet23-Slim's, and its lockfile and its
    prompt fixture name DDRNet23-Slim's package."""
    assert not (REPO / "packages" / "curio.streetvision@1").exists()
    assert not (REPO / "models").exists()
    spec = json.loads(EXAMPLE_10.read_text(encoding="utf-8"))["dataflow"]
    segmentation = [node for node in spec["nodes"] if node["type"].endswith("/image-segmentation")]
    assert [node["type"] for node in segmentation] == [f"{DDRNET_ID}/image-segmentation"] * 2
    assert spec["packages"] == [f"{DDRNET_ID}@1"]
    fixture = json.loads(
        (REPO / "docs" / "examples" / "prompts" / "10-street-vision-cv-analysis.prompt.json").read_text(encoding="utf-8")
    )
    assert fixture["required"]["packages"] == [f"{DDRNET_ID}@1"]


# ---------------------------------------------------------------------------
# The default cells
# ---------------------------------------------------------------------------

def test_an_added_ddrnet_opens_with_the_segmentation_cell(tmp_curio):
    """Added (its copy holds no weights), DDRNet23-Slim's node opens with the
    cell that loads it by id and segments every class it names, named for the
    template's id, as the starters the canvas fills a fresh node from."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    install_package_from_directory("guest", DDRNET)
    starter = _starters("guest")[f"{DDRNET_ID}/image-segmentation@1"]
    assert (starter["name"], starter["code"]) == ("image-segmentation", SEGMENTATION_CELL)


def test_an_image_to_image_model_opens_with_a_run_skeleton_naming_its_input(tmp_curio):
    """Local Relief's graph takes one float32 array, ``height``, 1 by 1 by
    rows by columns: the skeleton names it, with its type and shape."""
    folder = _model_package(tmp_curio / "incoming", "ai.test.relief", "image-to-image", LOCAL_RELIEF_GRAPH,
                            model_input={"width": 64, "height": 64, "dtype": "float32"})
    _install_archive("guest", folder)
    assert _starters("guest")["ai.test.relief/run@1"]["code"] == (
        'model = curio_load_model("ai.test.relief")\n'
        "\n"
        "# The arrays the model reads: make each one from input_0.\n"
        "outputs = model.run({\n"
        '    "height": ...,  # float32 [1, 1, rows, cols]\n'
        "})\n"
        "\n"
        "return outputs[0]\n"
    )


def test_a_node_regression_model_opens_with_a_run_skeleton_naming_each_input(tmp_curio):
    """The weather GNN's graph takes the node features and the edges."""
    folder = _model_package(tmp_curio / "incoming", "ai.test.graph", "node-regression", WEATHER_GNN_GRAPH)
    _install_archive("guest", folder)
    assert _starters("guest")["ai.test.graph/run@1"]["code"] == (
        'model = curio_load_model("ai.test.graph")\n'
        "\n"
        "# The arrays the model reads: make each one from input_0.\n"
        "outputs = model.run({\n"
        '    "x": ...,  # float32 [nodes, 7]\n'
        '    "edge_index": ...,  # int64 [2, edges]\n'
        "})\n"
        "\n"
        "return outputs[0]\n"
    )


def test_a_model_whose_weights_are_not_here_opens_with_an_empty_skeleton_and_nothing_is_downloaded(
    tmp_curio, monkeypatch,
):
    """A pip install that left the weight out and has not fetched it yet: the
    starters, which every canvas load asks for, download nothing, so the
    skeleton names no input."""
    from utk_curio.backend.app.datasets.infrastructure import left_out_files
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    catalog = tmp_curio / "catalog"
    folder = _model_package(catalog, "ai.test.away", "node-regression", WEATHER_GNN_GRAPH)
    (folder / "models" / "graph.onnx").unlink()
    monkeypatch.setenv("CURIO_PACKAGES_ROOT", str(catalog))
    fetched = []
    monkeypatch.setattr(left_out_files, "fetch", lambda *a, **k: fetched.append(a) or None)
    install_package_from_directory("guest", folder)

    assert _starters("guest")["ai.test.away/run@1"]["code"] == (
        'model = curio_load_model("ai.test.away")\n'
        "\n"
        "# model.run takes {input name: array}, one array for each input of the model,\n"
        "# made from input_0.\n"
        "outputs = model.run({})\n"
        "\n"
        "return outputs[0]\n"
    )
    assert fetched == []


def test_a_template_with_a_source_keeps_it_and_a_node_package_writes_none(tmp_curio):
    """Deep Umbra's Accumulated Shadow ships its own cell, which stays its
    starter; a node package's template without a source still has none."""
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory

    deep_umbra = REPO / "packages" / "model.scout.deep-umbra@1"
    install_package_from_directory("guest", deep_umbra)
    node_package = tmp_curio / "incoming" / "ai.test.plain@1"
    node_package.mkdir(parents=True)
    (node_package / "manifest.json").write_text(json.dumps({
        "id": "ai.test.plain", "version": "1.0.0", "name": "Plain", "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1},
        "templates": [{"id": "run", "label": "Run", "category": "computation", "engine": "python",
                       "editor": "code", "inputPorts": [], "outputPorts": [{"types": ["JSON"]}]}],
    }), encoding="utf-8")
    _install_archive("guest", node_package)

    starters = _starters("guest")
    shadow = starters["model.scout.deep-umbra/accumulated-shadow@1"]
    source = (deep_umbra / "sources" / "accumulated-shadow.py").read_text(encoding="utf-8")
    assert (shadow["name"], shadow["code"]) == ("accumulated-shadow", source)
    assert "ai.test.plain/run@1" not in starters


# ---------------------------------------------------------------------------
# What an ONNX graph reads, without onnxruntime
# ---------------------------------------------------------------------------

def _inputs(path: Path):
    from utk_curio.backend.app.datasets.domain.onnx_model import graph_inputs

    with path.open("rb") as handle:
        return graph_inputs(handle, path.stat().st_size)


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def _field(number: int, payload: bytes) -> bytes:
    """A length-delimited protobuf field."""
    return _varint(number << 3 | 2) + _varint(len(payload)) + payload


def test_the_graph_inputs_of_the_shipped_graphs():
    assert [(i.name, i.dtype, i.shape) for i in _inputs(LOCAL_RELIEF_GRAPH)] == [
        ("height", "float32", (1, 1, "rows", "cols")),
    ]
    assert [(i.name, i.dtype, i.shape) for i in _inputs(WEATHER_GNN_GRAPH)] == [
        ("x", "float32", ("nodes", 7)), ("edge_index", "int64", (2, "edges")),
    ]
    # DDRNet23-Slim's graph keeps its weights in a file beside it.
    assert [(i.name, i.dtype, i.shape) for i in _inputs(DDRNET / "models" / "ddrnet23_slim.onnx")] == [
        ("image", "uint8", (1, 3, 1024, 2048)),
    ]


def test_an_input_an_initializer_fills_is_not_one_the_node_feeds(tmp_path):
    """An older export lists its weights among the graph's inputs too; those
    are filled from the file, so only the others are read as inputs."""
    tensor_type = _field(1, _varint(1 << 3 | 0) + _varint(1))  # TypeProto.tensor_type, elem_type float
    graph = (
        _field(5, _field(8, b"weight"))  # initializer named "weight"
        + _field(11, _field(1, b"weight") + _field(2, tensor_type))
        + _field(11, _field(1, b"pixels") + _field(2, tensor_type))
    )
    model = tmp_path / "old.onnx"
    model.write_bytes(_varint(1 << 3 | 0) + _varint(3) + _field(7, graph))
    assert [(i.name, i.dtype, i.shape) for i in _inputs(model)] == [("pixels", "float32", None)]


def test_a_file_that_is_not_a_model_has_no_inputs(tmp_path):
    for name, body in (("text", b"not a model at all"), ("empty", b""), ("truncated", b"\x3a\xff\xff\x01")):
        path = tmp_path / f"{name}.onnx"
        path.write_bytes(body)
        assert _inputs(path) is None, name
