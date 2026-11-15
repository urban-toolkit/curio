"""The ``curio.segmentation@1`` package: a segmentation model's node calls its module.

The Segmentation package is one module, ``semantic_segmentation``, and no
node of its own. DDRNet23-Slim's package names it in ``dependencies.packages``,
as every segmentation model added from the Discovery Catalog does, so their
Image Segmentation nodes import it, and the header above their code lists its
``segment_images`` under Functions. Its node's code is its settings and that
one call.

The module runs here as a run of such a node imports it: staged into a folder
of the run's own (the ``segmentation`` fixture), on the real DDRNet23-Slim
export and on two of example 10's committed photos, and on the synthetic
graph the Hugging Face model fixtures use, as a model added from Hugging Face
is. onnxruntime, numpy, pandas and pillow are what a stack's boot installs
with the examples' packages; they are imported, not skipped, so a stack
without them fails here.
"""

from __future__ import annotations

import ast
import hashlib
import json
import shutil
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[4]
PACKAGE_ID = "curio.segmentation"
PACKAGE = REPO / "packages" / f"{PACKAGE_ID}@1"
MODULE = "semantic_segmentation"
DDRNET_ID = "model.curio.ddrnet23-slim"
DDRNET = REPO / "packages" / f"{DDRNET_ID}@1"
DDRNET_NODE = f"{DDRNET_ID}/image-segmentation"
SAMPLE = "data.curio.mapillary-sample"
STORAGE = REPO / "docs" / "examples" / "data" / "storage"
SYNTHETIC = (
    REPO / "utk_curio" / "backend" / "tests" / "test_discovery" / "fixtures" / "huggingface-models"
    / "synthetic-segmentation.onnx"
)
STREET = ["vegetation", "terrain", "sky", "road", "sidewalk", "building"]
EXAMPLE_10 = REPO / "docs" / "examples" / "10-street-vision-cv-analysis.json"
#: Where shipped dataflows are, as the other packages' guards read them.
SHIPPED_JSON = ("docs/examples/*.json", "docs/examples/dataflows/*.json")
#: The libraries the module imports, by the name a package declares each.
DECLARED_AS = {"numpy": "numpy", "pandas": "pandas", "PIL": "pillow"}


def _manifest(folder: Path) -> dict:
    return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))


def _loaded(folder):
    """The model in *folder*, as ``curio_load_model`` gives it to a node."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel

    return CurioModel(Path(folder).name, str(folder))


@pytest.fixture()
def segmentation(tmp_path):
    """The Segmentation package's module, staged into a folder of the run's
    own as the sandbox stages it for a run of a segmentation model's node
    (``staging.stage_package_modules``), and imported."""
    import importlib

    from utk_curio.sandbox.util.package_modules import importable
    from utk_curio.sandbox.util.staging import stage_package_modules

    run = tmp_path / "run-segmentation"
    run.mkdir()
    staged = stage_package_modules({"root": str(PACKAGE / "sources"), "names": [MODULE]}, str(run))
    assert staged == {"root": "package_modules", "names": [MODULE]}, staged
    with importable(str(run / staged["root"]), staged["names"]):
        yield importlib.import_module(MODULE)


@pytest.fixture()
def photos(tmp_path):
    """Two of the committed photos, as a node's curio_load_collection gives them."""
    from utk_curio.sandbox.util.collections import make_collection_helpers

    index = REPO / "datasets" / f"{SAMPLE}@1" / "data" / "index.parquet"
    helpers = make_collection_helpers(
        lambda _id: str(index), {SAMPLE: {"kind": "images", "root": str(STORAGE)}}, str(tmp_path / "media")
    )
    frame = helpers["curio_load_collection"](SAMPLE).head(2)
    return frame, helpers


def _onnx_model(tmp_path, labels, model_input) -> Path:
    """A flat model folder around the synthetic graph, as the Hugging Face
    fixtures' graph answers: 150 channels."""
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    shutil.copyfile(SYNTHETIC, model / "files" / "model.onnx")
    (model / "manifest.json").write_text(json.dumps({
        "runtime": "onnx", "entry": "files/model.onnx", "labels": labels, "input": model_input,
    }), encoding="utf-8")
    return model


# ---------------------------------------------------------------------------
# The package
# ---------------------------------------------------------------------------

def test_the_package_validates_and_is_one_module_and_no_node():
    """Against the node-package schema and the parser: a package of one
    module, which names what node code calls in ``__all__``, its libraries
    declared, and no template: the nodes of the packages that name it call
    it."""
    from jsonschema import Draft202012Validator

    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    schema = json.loads((REPO / "docs" / "schemas" / "node-package.v4.json").read_text(encoding="utf-8"))
    raw = _manifest(PACKAGE)
    Draft202012Validator(schema).validate(raw)
    manifest = load_package_manifest(PACKAGE)
    assert (manifest.package_id, manifest.name, manifest.kind, manifest.read_only) == (
        PACKAGE_ID, "Segmentation", "node", True,
    )
    assert raw["templates"] == [] and manifest.templates == []
    assert module_names(PACKAGE, manifest) == frozenset({MODULE})
    assert dict(manifest.package_deps) == {}
    assert sorted(manifest.python_deps) == sorted(DECLARED_AS.values())
    assert (PACKAGE / "README.md").is_file()


#: Words the loader refuses a package with no node and no module with, as it
#: refused every package with no template before there were libraries.
NO_TEMPLATES = r"manifest\.json\.templates must be a non-empty list"
#: A module of a package of modules alone.
A_MODULE = {"street_shares.py": "def share(part, whole):\n    return 100.0 * part / whole\n"}


def _written(tmp_path, package_id: str, raw: dict, sources: dict | None = None) -> Path:
    """A package folder holding *raw* as its manifest, with *package_id* as
    its ``id``, and each of *sources* under ``sources/``."""
    folder = tmp_path / f"{package_id}@1"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({**raw, "id": package_id}), encoding="utf-8")
    for relative, text in (sources or {}).items():
        path = folder / "sources" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return folder


def _schema_errors(raw: dict) -> list[list]:
    from jsonschema import Draft202012Validator

    schema = json.loads((REPO / "docs" / "schemas" / "node-package.v4.json").read_text(encoding="utf-8"))
    return [list(error.absolute_path) for error in Draft202012Validator(schema).iter_errors(raw)]


def test_a_package_with_no_node_and_a_module_is_a_library(tmp_path):
    """A package that is not a model package may define no template when it
    ships a Python module in ``sources/``, as Segmentation does: the packages
    that name it import the module. Main refused every package with no
    template."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    library = _written(tmp_path, "ai.test.library", _manifest(PACKAGE), A_MODULE)
    manifest = load_package_manifest(library)
    assert manifest.templates == []
    assert module_names(library, manifest) == frozenset({"street_shares"})
    assert _schema_errors(_manifest(library)) == []


@pytest.mark.parametrize("sources", [
    None,
    {"notes.txt": "no Python here\n"},
    {"not-a-name.py": "X = 1\n"},
    {"class.py": "X = 1\n"},
], ids=["no-sources", "no-python", "not-a-name", "a-keyword"])
def test_a_package_with_no_node_and_no_module_is_refused_as_before(tmp_path, sources):
    """With no module either, the package is refused with the words main
    refuses any package with no template with."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    nothing = _written(tmp_path, "ai.test.nothing", _manifest(PACKAGE), sources)
    with pytest.raises(ManifestError, match=NO_TEMPLATES):
        load_package_manifest(nothing)


def test_a_model_package_defines_the_node_that_runs_its_model(tmp_path):
    """A model package with no template is refused, modules or not, with
    main's words, and the schema says so of its ``templates``; ``templates``
    is still a list."""
    from utk_curio.backend.app.packages.domain.manifest import ManifestError
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    nodeless_model = _written(tmp_path, "model.test.nodeless", {**_manifest(DDRNET), "templates": []}, A_MODULE)
    with pytest.raises(ManifestError, match=NO_TEMPLATES):
        load_package_manifest(nodeless_model)
    assert _schema_errors(_manifest(nodeless_model)) == [["templates"]]

    not_a_list = _written(tmp_path, "ai.test.not-a-list", {**_manifest(PACKAGE), "templates": {"id": "x"}}, A_MODULE)
    with pytest.raises(ManifestError, match=NO_TEMPLATES):
        load_package_manifest(not_a_list)
    unnamed = {key: value for key, value in _manifest(PACKAGE).items() if key != "templates"}
    with pytest.raises(ManifestError, match=NO_TEMPLATES):
        load_package_manifest(_written(tmp_path, "ai.test.unnamed", unnamed, A_MODULE))


def test_the_module_offers_segment_images_and_imports_nothing_of_curios():
    """``__all__`` names the one function node code calls, whose docstring's
    first paragraph says what it does. The module imports nothing from
    ``utk_curio``, and each library it imports at its top is one its package
    declares; a runtime (onnxruntime, torch, transformers) is imported only
    when a model of it runs, and the model's package declares it."""
    from utk_curio.backend.app.packages.application.function_nodes import PackageModules
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest

    source = (PACKAGE / "sources" / f"{MODULE}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert "utk_curio" not in source
    top = sorted({
        (node.module if isinstance(node, ast.ImportFrom) else alias.name).split(".")[0]
        for node in tree.body if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if not (isinstance(node, ast.ImportFrom) and node.module == "__future__")
    })
    libraries = [name for name in top if name in DECLARED_AS]
    assert set(top) - set(libraries) <= {"colorsys", "hashlib", "os", "re"}, top
    declared = set(load_package_manifest(PACKAGE).python_deps)
    assert {DECLARED_AS[name] for name in libraries} <= declared, (libraries, declared)
    functions = PackageModules(PACKAGE, load_package_manifest(PACKAGE)).functions(MODULE)
    assert [f.name for f in functions] == ["segment_images"]
    assert "Label every pixel of each image" in functions[0].doc, functions[0].doc


def test_its_derived_ids_are_the_ones_curio_derived_file_names():
    """The module tells a frame a node sampled from a video by its id, as the
    media route reads it: its pattern is ``collections.DERIVED_ID_RE``'s."""
    from utk_curio.sandbox.util.collections import DERIVED_ID_RE

    source = (PACKAGE / "sources" / f"{MODULE}.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    [assigned] = [
        node.value for node in tree.body
        if isinstance(node, ast.Assign) and [getattr(t, "id", None) for t in node.targets] == ["_DERIVED_ID_RE"]
    ]
    assert ast.literal_eval(assigned.args[0]) == DERIVED_ID_RE.pattern


# ---------------------------------------------------------------------------
# DDRNet23-Slim's node, which calls it
# ---------------------------------------------------------------------------

def test_ddrnet_names_the_package_and_its_node_is_its_settings_and_one_call():
    """DDRNet23-Slim names the Segmentation package in
    ``dependencies.packages``, and its Image Segmentation node's code is its
    docstring, the import of ``segment_images``, its two settings (the model
    by its id and the classes) and the return of that one call, which reads
    both and hands it ``curio_derived_file``. DDRNet23-Slim ships no module:
    its source is its node's."""
    from utk_curio.backend.app.packages.repositories.manifests import load_package_manifest
    from utk_curio.backend.app.packages.repositories.python_modules import module_names

    raw = _manifest(DDRNET)
    assert raw["dependencies"]["packages"] == {f"{PACKAGE_ID}@1": "*"}
    [template] = raw["templates"]
    assert (template["id"], template["label"], template["source"]) == (
        "image-segmentation", "Image Segmentation", "sources/image-segmentation.py",
    )
    assert module_names(DDRNET, load_package_manifest(DDRNET)) == frozenset()
    code = (DDRNET / template["source"]).read_text(encoding="utf-8")
    assert "utk_curio" not in code
    body = ast.parse("def node():\n" + "\n".join("    " + line for line in code.splitlines())).body[0].body
    kinds = [type(statement).__name__ for statement in body]
    assert kinds == ["Expr", "ImportFrom", "Assign", "Assign", "Return"], kinds
    assert ast.unparse(body[1]) == f"from {MODULE} import segment_images"
    assert ast.unparse(body[2]) == f"model = curio_load_model('{DDRNET_ID}')"
    assert ast.unparse(body[3]) == "classes = None"
    assert ast.unparse(body[4].value) == "segment_images(input_0, model, curio_derived_file, classes=classes)"


def test_ddrnets_node_runs_its_code_as_it_is(segmentation, photos):
    """DDRNet23-Slim's node's code, run as the sandbox runs a node's code,
    with the module a run of it is handed: every class the model names gets
    its share of each photo, the shares cover the image, and each photo gets
    its overlay."""
    from utk_curio.sandbox.util.catalog_helpers import CurioModel
    from utk_curio.sandbox.util.input_names import call_as_node

    frame, helpers = photos
    code = (DDRNET / "sources" / "image-segmentation.py").read_text(encoding="utf-8")
    namespace = {
        "curio_load_model": lambda model_id: CurioModel(model_id, str(DDRNET)),
        "curio_derived_file": helpers["curio_derived_file"],
    }
    out = call_as_node("\n".join("    " + line for line in code.splitlines()), namespace, frame, [0])

    labels = _manifest(DDRNET)["model"]["labels"]
    assert len(out) == 2 and len(labels) == 19
    assert out[[f"{label}_pct" for label in labels]].sum(axis=1).between(99.5, 100.5).all()
    assert out["dominant_class"].isin(labels).all()
    assert out["overlay_url"].notna().all() and out["segment_error"].isna().all()


def test_example_10s_nodes_are_ddrnets_and_call_the_function(segmentation):
    """Example 10's two Image Segmentation nodes are DDRNet23-Slim's, each
    the settings and one call of ``segment_images``, and its lockfile names
    the Segmentation package beside DDRNet23-Slim's."""
    spec = json.loads(EXAMPLE_10.read_text(encoding="utf-8"))["dataflow"]
    nodes = [node for node in spec["nodes"] if node["type"].endswith("/image-segmentation")]
    assert [node["type"] for node in nodes] == [DDRNET_NODE] * 2
    for node in nodes:
        assert "curio_segment" not in node["content"]
        assert f"from {MODULE} import segment_images" in node["content"]
        assert node["content"].rstrip().endswith(
            "return segment_images(input_0, model, curio_derived_file, classes=classes)"
        )
    assert spec["packages"] == [f"{PACKAGE_ID}@1", f"{DDRNET_ID}@1"]


# ---------------------------------------------------------------------------
# Installed with DDRNet23-Slim
# ---------------------------------------------------------------------------

def test_a_run_of_ddrnets_node_is_handed_the_module(tmp_curio):
    """A run of an Image Segmentation node is handed the module of the
    package its package names (``python_modules.modules_for_node``), and
    DDRNet23-Slim's own package ships none."""
    from utk_curio.backend.app.packages.application.python_modules import modules_for_node
    from utk_curio.backend.app.packages.application.store_install import install_package_from_directory
    from utk_curio.backend.app.packages.repositories.store import package_dir

    for package in (PACKAGE, DDRNET):
        install_package_from_directory("guest", package)
    assert modules_for_node("guest", DDRNET_NODE) == {
        "root": str(package_dir("guest", PACKAGE.name) / "sources"), "names": [MODULE],
    }


def test_adding_ddrnet_adds_the_package(tmp_curio):
    """The Model Catalog's Add, a card dropped on the canvas and opening a
    dataflow that names DDRNet23-Slim copy it from the catalog with the
    package it needs, Segmentation first (``install_to_store``, the closure
    every add asks)."""
    from utk_curio.backend.app.packages.application.store_install import install_to_store
    from utk_curio.backend.app.packages.repositories.store import package_dir

    outcome = install_to_store("guest", DDRNET.name)
    assert outcome.packages == (PACKAGE.name, DDRNET.name), outcome
    assert (package_dir("guest", PACKAGE.name) / "sources" / f"{MODULE}.py").is_file()
    assert (package_dir("guest", DDRNET.name) / "sources" / "image-segmentation.py").is_file()


def test_an_install_of_ddrnet_from_the_catalog_brings_the_package(client, user_and_token, tmp_curio):
    """``POST /api/packages/catalog/install``, a catalog's Update and the
    models a skill evaluation's account holds, brings the package too: on
    main it copied DDRNet23-Slim alone. An Update brings it back to an
    account that removed it."""
    from utk_curio.backend.app.packages.repositories.store import package_dir
    from utk_curio.backend.app.projects.services import _user_dir_key

    user, token = user_and_token
    key = _user_dir_key(user)
    headers = {"Authorization": f"Bearer {token}"}

    def install(replace: bool):
        return client.post(
            "/api/packages/catalog/install", json={"dirName": DDRNET.name, "replace": replace}, headers=headers,
        )

    added = install(False)
    assert added.status_code == 201, added.get_data(as_text=True)
    assert (package_dir(key, PACKAGE.name) / "sources" / f"{MODULE}.py").is_file()
    assert client.delete(f"/api/packages/{PACKAGE.name}", headers=headers).status_code == 204
    assert not package_dir(key, PACKAGE.name).exists()
    updated = install(True)
    assert updated.status_code == 201, updated.get_data(as_text=True)
    assert (package_dir(key, PACKAGE.name) / "sources" / f"{MODULE}.py").is_file()


def test_the_examples_seeding_brings_it():
    """``--with-examples`` seeds the packages the shipped dataflows declare and
    those they need, read from the catalog: Segmentation is among them both
    ways, as example 10 declares it and DDRNet23-Slim needs it."""
    from utk_curio.backend.app.packages.application.package_dependencies import catalog_packages_to_add
    from utk_curio.backend.app.packages.application.seeding import example_dep_package_ids

    assert {PACKAGE_ID, DDRNET_ID} <= set(example_dep_package_ids())
    assert catalog_packages_to_add([DDRNET.name]) == [PACKAGE.name, DDRNET.name]


def test_every_shipped_dataflow_with_a_node_that_calls_it_declares_the_package():
    """A dataflow's lockfile is how opening it, a scenario dropped from it and
    ``--with-examples`` add a package: each shipped dataflow with a node of a
    package that names Segmentation in ``dependencies.packages`` names
    ``curio.segmentation@1``, and no other does."""
    dependents = set()
    for manifest_path in sorted((REPO / "packages").glob("*/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if f"{PACKAGE_ID}@1" in ((manifest.get("dependencies") or {}).get("packages") or {}):
            dependents.add(manifest["id"])
    assert dependents == {DDRNET_ID}, dependents
    with_a_dependents_node, declaring = set(), set()
    for pattern in SHIPPED_JSON:
        for path in sorted(REPO.glob(pattern)):
            dataflow = json.loads(path.read_text(encoding="utf-8")).get("dataflow") or {}
            key = path.relative_to(REPO).as_posix()
            types = {str(n.get("type", "")).split("@")[0] for n in dataflow.get("nodes") or []}
            if any(node_type.split("/")[0] in dependents for node_type in types):
                with_a_dependents_node.add(key)
            if f"{PACKAGE_ID}@1" in (dataflow.get("packages") or []):
                declaring.add(key)
    assert with_a_dependents_node == {"docs/examples/10-street-vision-cv-analysis.json"}, with_a_dependents_node
    assert declaring == with_a_dependents_node, (declaring, with_a_dependents_node)


# ---------------------------------------------------------------------------
# segment_images, on DDRNet23-Slim
# ---------------------------------------------------------------------------

def test_ddrnet_labels_the_photos(segmentation, photos):
    frame, helpers = photos
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    assert len(out) == 2 and type(out).__name__ == "GeoDataFrame"
    for name in STREET:
        assert out[f"{name}_pct"].between(0, 100).all()
    # Street panoramas: sky and road are always there.
    assert (out["sky_pct"] > 5).all() and (out["road_pct"] > 5).all()
    assert out["dominant_class"].isin(STREET).all()
    assert out["segment_error"].isna().all()


def test_a_share_is_of_all_the_pixels(segmentation, photos):
    """Not of the classes asked for: asked for vegetation alone, an image with
    some vegetation does not read 100% (HF CV Inference's renormalization)."""
    frame, helpers = photos
    derive = helpers["curio_derived_file"]
    alone = segmentation.segment_images(frame, _loaded(DDRNET), derive, classes=["vegetation"])
    every = segmentation.segment_images(frame, _loaded(DDRNET), derive, classes=None)
    assert (alone["vegetation_pct"] < 100).all()
    assert list(alone["vegetation_pct"]) == list(every["vegetation_pct"])
    labels = _manifest(DDRNET)["model"]["labels"]
    totals = every[[f"{name}_pct" for name in labels]].sum(axis=1)
    assert totals.between(99.5, 100.5).all()


def test_each_photo_gets_an_overlay_served_by_id(segmentation, photos):
    """The id names the photo and the model (#621): the first twelve hex digits
    of the SHA-1 of the model's id."""
    frame, helpers = photos
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    model = hashlib.sha1(DDRNET.name.encode("utf-8")).hexdigest()[:12]
    for url, file_id in zip(out["overlay_url"], frame["file_id"]):
        assert url == f"/api/datasets/{SAMPLE}/media/{file_id}@0-{model}?variant=original"


def test_a_frame_sampled_from_a_video_gets_its_overlay_beside_the_video(segmentation, photos, tmp_path):
    """Sample Video Frames names each frame by its video and time,
    ``<videoId>@<t_ms>``, which is no file of the collection: the node
    stopped with "not a collection file". The overlay is the video's, at the
    frame's time; a frame that carries a tag of its own gets none."""
    frame, helpers = photos
    derive = helpers["curio_derived_file"]
    video = "e" * 16
    rows = []
    for t_ms, tag in ((2000, None), (4000, "other")):
        sampled = derive(SAMPLE, video, t_ms, tag=tag)
        shutil.copyfile(frame["path"].iloc[0], sampled["path"])
        rows.append({"dataset_id": SAMPLE, "file_id": sampled["file_id"], "kind": "frame", "path": sampled["path"]})
    out = segmentation.segment_images(pd.DataFrame(rows), _loaded(DDRNET), derive, classes=STREET)
    model = hashlib.sha1(DDRNET.name.encode("utf-8")).hexdigest()[:12]
    assert out["overlay_url"].iloc[0] == f"/api/datasets/{SAMPLE}/media/{video}@2000-{model}.png?variant=original"
    assert (tmp_path / "media" / "overlays" / SAMPLE / video / f"2000-{model}.png").is_file()
    assert pd.isna(out["overlay_url"].iloc[1])
    assert out["segment_error"].isna().all() and out["dominant_class"].isin(STREET).all()


def test_the_results_lead_the_row(segmentation, photos):
    """A card's caption is the row's first columns, so what the model found
    has to come before the collection's own file columns."""
    frame, helpers = photos
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    assert list(out.columns[:2]) == ["dominant_class", "dominant_pct"]
    assert list(out.columns[2:2 + len(STREET)]) == [f"{name}_pct" for name in STREET]
    assert list(out.columns[2 + len(STREET):]) == [
        "overlay_url", "segment_error", *frame.columns,
    ]


def test_without_a_collection_there_is_no_overlay(segmentation, photos):
    frame, _helpers = photos
    out = segmentation.segment_images(frame, _loaded(DDRNET), None, classes=STREET)
    assert out["overlay_url"].isna().all() and out["dominant_class"].notna().all()


def test_overlays_false_writes_none(segmentation, photos, tmp_path):
    frame, helpers = photos
    out = segmentation.segment_images(
        frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET, overlays=False,
    )
    assert out["overlay_url"].isna().all() and out["dominant_class"].notna().all()
    assert not list((tmp_path / "media").rglob("*.png"))


def test_a_class_the_model_lacks_names_the_ones_it_has(segmentation, photos):
    frame, helpers = photos
    with pytest.raises(ValueError, match="no class 'tree'.*vegetation"):
        segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=["tree"])


def test_a_row_without_its_file_says_so(segmentation, photos):
    frame, helpers = photos
    frame = frame.copy()
    frame.loc[frame.index[0], "path"] = None
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    assert out["segment_error"].iloc[0] == "the image is not on this machine"
    assert out["dominant_class"].iloc[1] in STREET


def _unreadable(kind, tmp_path, photo):
    """A file the row points at that is not an image Pillow can read: bytes
    that are no image at all (refused at open), or the first half of a real
    photo (opened, then refused when its pixels are read)."""
    target = tmp_path / f"{kind}.jpg"
    if kind == "garbage":
        target.write_bytes(b"these bytes are not an image\n" * 64)
    else:
        whole = Path(photo).read_bytes()
        target.write_bytes(whole[: len(whole) // 2])
    return str(target)


@pytest.mark.parametrize("kind", ["garbage", "truncated"])
def test_an_unreadable_image_says_so_and_the_rest_are_labelled(segmentation, kind, tmp_path, photos):
    frame, helpers = photos
    frame = frame.copy()
    frame.loc[frame.index[0], "path"] = _unreadable(kind, tmp_path, frame["path"].iloc[0])
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    assert out["segment_error"].iloc[0] == "the image could not be read"
    assert pd.isna(out["dominant_class"].iloc[0]) and pd.isna(out["overlay_url"].iloc[0])
    assert out["dominant_class"].iloc[1] in STREET and pd.isna(out["segment_error"].iloc[1])


def test_an_image_too_large_to_decode_says_it_could_not_be_read(segmentation, photos, monkeypatch):
    from PIL import Image

    frame, helpers = photos
    # Every photo is now over Pillow's decompression bomb limit.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1)
    out = segmentation.segment_images(frame, _loaded(DDRNET), helpers["curio_derived_file"], classes=STREET)
    assert list(out["segment_error"]) == ["the image could not be read"] * len(frame)


def test_rows_without_paths_are_refused(segmentation):
    with pytest.raises(ValueError, match="rows with a path"):
        segmentation.segment_images(pd.DataFrame({"x": [1]}), _loaded(DDRNET), None)


def test_street_classes_keep_their_colours(segmentation):
    colours = segmentation.palette(["road", "vegetation", "something else", "Sky"])
    assert colours[0] == segmentation.CLASS_COLOURS["road"]
    assert colours[1] == segmentation.CLASS_COLOURS["vegetation"]
    assert colours[3] == segmentation.CLASS_COLOURS["sky"]
    assert colours[2] not in segmentation.CLASS_COLOURS.values()


# ---------------------------------------------------------------------------
# segment_images, on a model added from Hugging Face
# ---------------------------------------------------------------------------

def test_a_float_graph_with_normalized_input(segmentation, tmp_path, photos):
    """An ONNX export from Hugging Face, as the Discovery Catalog adds one:
    float32 pixels, scaled and normalized as its preprocessor config says."""
    frame, helpers = photos
    model = _onnx_model(tmp_path, [f"c{i}" for i in range(150)], {
        "width": 64, "height": 64, "dtype": "float32", "scale": 1 / 255,
        "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
    })
    out = segmentation.segment_images(frame, _loaded(model), helpers["curio_derived_file"])
    labels = [f"c{i}_pct" for i in range(150)]
    assert out[labels].sum(axis=1).between(99.5, 100.5).all()


def test_a_class_named_like_a_column_keeps_the_column(segmentation, tmp_path, photos):
    """ADE20K labels a class "path": its share must not replace the image's."""
    frame, helpers = photos
    model = _onnx_model(tmp_path, ["path", *[f"c{i}" for i in range(1, 150)]],
                        {"width": 64, "height": 64, "dtype": "float32"})
    out = segmentation.segment_images(frame, _loaded(model), helpers["curio_derived_file"])
    assert list(out["path"]) == list(frame["path"])
    assert out["path_pct"].between(0, 100).all()


def test_a_manifest_naming_other_labels_is_refused(segmentation, tmp_path, photos):
    frame, _helpers = photos
    model = _onnx_model(tmp_path, ["a", "b"], {"width": 64, "height": 64, "dtype": "float32"})
    with pytest.raises(RuntimeError, match="answered 150 classes; its manifest names 2"):
        segmentation.segment_images(frame, _loaded(model), None)


def test_a_transformers_model_without_its_libraries_says_what_to_install(segmentation, tmp_path, photos, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_torch(name, *args, **kwargs):
        if name in ("torch", "transformers"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_torch)
    model = tmp_path / "model"
    (model / "files").mkdir(parents=True)
    (model / "manifest.json").write_text(json.dumps({"runtime": "transformers", "entry": "files"}), encoding="utf-8")
    frame, _helpers = photos
    with pytest.raises(RuntimeError, match="runs on Transformers.*ask whoever runs this Curio "
                                           "to install torch, transformers and safetensors") as raised:
        segmentation.segment_images(frame, _loaded(model), None)
    # Deleting the model and adding it again gives it a new id, and every node
    # that names the old one stops finding it.
    message = str(raised.value)
    assert "delete" not in message and "again" not in message


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------

def _flat_model(tmp_path, manifest: dict) -> Path:
    folder = tmp_path / "model.example.tiny@1"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def test_an_image_to_image_model_is_refused(segmentation, tmp_path):
    folder = _flat_model(tmp_path, {"runtime": "onnx", "task": "image-to-image", "labels": []})
    with pytest.raises(ValueError, match="does not label pixels"):
        segmentation.segment_images(pd.DataFrame({"path": []}), _loaded(folder), None)


def test_a_concept_segmentation_model_is_refused(segmentation, tmp_path):
    """A model whose labels are text prompts, as SAM 3's are: its node loads
    the checkpoint itself."""
    folder = _flat_model(tmp_path, {"runtime": "transformers", "task": "concept-segmentation",
                                    "labels": ["person", "bicycle"], "entry": "models/checkpoint"})
    with pytest.raises(ValueError, match="finds the things text prompts name"):
        segmentation.segment_images(None, _loaded(folder), None)


def test_it_runs_a_loaded_model_not_a_folder(segmentation, tmp_path):
    with pytest.raises(TypeError, match="curio_load_model"):
        segmentation.segment_images(pd.DataFrame({"path": []}), str(tmp_path), None)
