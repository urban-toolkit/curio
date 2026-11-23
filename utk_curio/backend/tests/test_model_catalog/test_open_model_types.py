"""A model package names any type, and nothing in Curio's core keys on one.

A model package's ``model.type`` is any lowercase name: the four Curio's own
packages run (``semantic-segmentation``, ``image-to-image``,
``node-regression``, ``concept-segmentation``) and any other, such as
``depth-estimation``, read alike by the parser (``domain/model_block.py``)
and the schema (``docs/schemas/node-package.v4.json``).

- A template that names no ``source`` opens with Curio's cell, an
  onnxruntime session on the model's ``.onnx`` file
  (``default_cells.run_skeleton``), which a Transformers checkpoint cannot
  open: a template of a ``transformers`` model names its source, whatever its
  type, and one of an ``onnx`` model may name none, whatever its type.
- Every type is parsed alike: ``labels`` and ``input`` are optional and
  checked when given, in either layout. The package that runs a model says
  what it needs of them (the Segmentation package's ``segment_images``,
  ``test_packages/test_segmentation_package.py``).
- What a dataflow that uses a model is filed under is what the model's
  package declares (``dataflowCategories``): ``projects/category_rules.json``
  gives a model type nothing. DDRNet23-Slim and SAM 3 declare Computer
  vision and Imagery themselves.

The code under test is imported inside each test.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
SCHEMA = REPO / "docs" / "schemas" / "node-package.v4.json"
PACKAGES = REPO / "packages"
PACKAGE_ID = "ai.test.depth"
DIR = f"{PACKAGE_ID}@1"


def _block(**change) -> dict:
    """An onnx model's block, of a type no package Curio ships runs; a None in
    *change* removes a key."""
    block = {
        "type": "depth-estimation", "runtime": "onnx", "entry": "models/m.onnx",
        "input": {"width": 64, "height": 32, "dtype": "float32", "scale": 0.00392},
        "license": "MIT", "sizeBytes": 10,
    }
    for key, value in change.items():
        if value is None:
            block.pop(key, None)
        else:
            block[key] = value
    return block


def _template(**change) -> dict:
    """The package's node, with code of its own; a None in *change* removes a key."""
    template = {
        "id": "depth", "label": "Depth", "category": "computation", "engine": "python", "editor": "code",
        "source": "sources/depth.py", "inputPorts": [], "outputPorts": [{"types": ["DATAFRAME"]}],
    }
    for key, value in change.items():
        if value is None:
            template.pop(key, None)
        else:
            template[key] = value
    return template


def _manifest(model: dict | None = None, templates: list | None = None) -> dict:
    return {
        "id": PACKAGE_ID, "version": "1.0.0", "name": "Depth", "publisher": "Test", "license": "MIT",
        "compatibility": {"major": 1}, "kind": "model",
        "templates": templates if templates is not None else [_template()],
        "model": model if model is not None else _block(),
    }


def _parse(raw: dict):
    from utk_curio.backend.app.packages.domain.manifest import package_manifest_from_dict

    return package_manifest_from_dict(raw, manifest_path=Path("manifest.json"), dir_name=DIR)


def _schema_errors(raw: dict) -> list[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
    return [f"{list(error.absolute_path)}: {error.message}" for error in validator.iter_errors(raw)]


# ---------------------------------------------------------------------------
# Any type
# ---------------------------------------------------------------------------

def test_a_model_package_may_name_a_type_no_package_curio_ships_runs():
    """A depth estimation model, a type none of Curio's own packages runs, is
    read as its manifest says, by the parser and by the schema."""
    manifest = _parse(_manifest())
    assert (manifest.kind, manifest.model.type, manifest.model.runtime) == ("model", "depth-estimation", "onnx")
    assert _schema_errors(_manifest()) == []


@pytest.mark.parametrize("model_type", ["semantic-segmentation", "image-to-image", "depth-estimation"])
def test_every_type_is_read_alike_with_no_labels_no_input_or_either_layout(model_type):
    """``labels`` and ``input`` are optional for every type and checked when
    given, in NCHW or NHWC: the package that runs a model says what it needs
    of them, as the Segmentation package does."""
    no_labels = _manifest(model=_block(type=model_type, labels=[]))
    no_input = _manifest(model=_block(type=model_type, input=None))
    nhwc = _manifest(model=_block(type=model_type, input={"width": 64, "height": 32, "layout": "NHWC"}))
    assert _parse(no_labels).model.labels == ()
    assert _parse(no_input).model.input is None
    assert _parse(nhwc).model.input.layout == "NHWC"
    for raw in (no_labels, no_input, nhwc):
        assert _schema_errors(raw) == [], raw["model"]


@pytest.mark.parametrize("model_type", ["Depth", "depth_estimation", "depth estimation", "-depth", "depth-",
                                        "depth--estimation", "2d-depth", "a" * 65, ""])
def test_a_type_that_is_not_a_lowercase_name_is_refused(model_type):
    """A type is lowercase letters and digits in words joined by single
    hyphens, starting with a letter, up to 64 characters: the parser refuses
    any other, saying so, and so does the schema."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError

    raw = _manifest(model=_block(type=model_type))
    with pytest.raises(ManifestError, match=r"\.model: type must be"):
        _parse(raw)
    assert _schema_errors(raw)


# ---------------------------------------------------------------------------
# A template with no source
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_type", ["semantic-segmentation", "concept-segmentation", "depth-estimation"])
def test_a_transformers_models_template_names_its_source_whatever_its_type(model_type):
    """A template that names no source opens with Curio's cell, an
    onnxruntime session on the model's .onnx file, which a Transformers
    checkpoint cannot open: the parser and the schema refuse such a template
    of a transformers model, saying why, and take one of an onnx model."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError

    checkpoint = _block(type=model_type, runtime="transformers", entry="models/checkpoint", input=None)
    refused = _manifest(model=checkpoint, templates=[_template(), _template(id="plain", source=None)])
    with pytest.raises(ManifestError, match=re.escape(
        "manifest.json.templates['plain']: a transformers model's node runs the code its package ships: "
        "Curio's cell opens an .onnx file, so the template names its source (sources/<file>.py)"
    )):
        _parse(refused)
    assert _schema_errors(refused)

    onnx = _manifest(model=_block(type=model_type), templates=[_template(source=None)])
    assert _parse(onnx).templates[0].source is None
    assert _schema_errors(onnx) == []


# ---------------------------------------------------------------------------
# What a dataflow that uses a model is filed under
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("folder", ["model.curio.ddrnet23-slim@1", "model.curio.sam3@1"])
def test_a_segmentation_model_curio_ships_declares_what_its_dataflows_are_filed_under(folder):
    """DDRNet23-Slim's and SAM 3's manifests file a dataflow that uses them
    under Computer vision and Imagery themselves, as SAM 3 declares PyTorch:
    the category table names no model type."""
    raw = json.loads((PACKAGES / folder / "manifest.json").read_text(encoding="utf-8"))
    declared = raw.get("dataflowCategories") or {}
    assert "Computer vision" in declared.get("tags", []), (folder, declared)
    assert "Imagery" in declared.get("dataTypes", []), (folder, declared)


@pytest.mark.parametrize("model_type", ["semantic-segmentation", "concept-segmentation", "depth-estimation"])
def test_a_model_package_that_declares_nothing_files_a_dataflow_under_nothing(tmp_path, model_type):
    """Whatever its type, a model package that declares nothing files a
    dataflow that uses it, by a node of it or by a ``curio_load_model``
    call, under nothing: what a type once gave comes from each package's own
    ``dataflowCategories``."""
    from utk_curio.backend.app.projects.categories import DatasetKinds, ManifestLookup, derive
    from utk_curio.backend.app.projects.template_grammars import TemplateGrammars

    folder = tmp_path / "packages" / DIR
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps(_manifest(model=_block(type=model_type, labels=["road", "sky"]))), encoding="utf-8")
    lookup = ManifestLookup(
        packages=TemplateGrammars(None, roots=[tmp_path / "packages"]), datasets=DatasetKinds(None, roots=[]))

    def filed(node: dict) -> dict:
        return derive({"dataflow": {"nodes": [node], "edges": []}}, lookup=lookup)

    by_node = filed({"id": "n", "type": f"{PACKAGE_ID}/depth", "content": ""})
    by_call = filed({"id": "n", "type": "curio.builtin/python-computation",
                     "content": f'model = curio_load_model("{PACKAGE_ID}")\nreturn model.path\n'})
    assert by_node == by_call == {"tags": [], "data_type": []}
