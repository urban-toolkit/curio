"""Node code reads the files Curio ships in ``docs/`` by the path it spells.

The dataflows Curio ships read their example data by a path relative to the
folder node code runs in (``docs/examples/data/...``). A clone started from its
root holds that folder; a pip install keeps ``docs/`` inside ``utk_curio/``
(``utk_curio/shipped.py``) and starts from a folder of the user's. A relative
path in ``docs/`` that the folder does not hold reads the file Curio ships,
in-process and in an isolated child alike; one the folder holds reads the
folder's, and every other path reads as it always has.
"""

import hashlib
import textwrap

import pytest

from utk_curio import shipped

RASTER = "docs/examples/data/niteroi_lst_verao_2001_2024.tif"


def _node(body):
    """*body* as the sandbox receives a node's code: indented for
    ``def userCode(arg):``."""
    return textwrap.indent(textwrap.dedent(body), "    ")


PRINT_RASTER_DIGEST = _node(f"""\
    import hashlib
    with open({RASTER!r}, 'rb') as f:
        print(hashlib.sha256(f.read()).hexdigest())
    return 1
""")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def launch(tmp_path, monkeypatch):
    """An empty folder Curio started from, which holds no ``docs/``, with the
    sandbox's artifact store beside it."""
    from utk_curio.sandbox.util.db import init_db, release_connection

    folder = tmp_path / "launch"
    folder.mkdir()
    monkeypatch.setenv("CURIO_LAUNCH_CWD", str(folder))
    monkeypatch.setenv("CURIO_SHARED_DATA", str(tmp_path / "data"))
    release_connection()
    init_db()
    yield folder
    release_connection()


def _in_process(code, launch):
    """What the sandbox reports for *code* run in-process in *launch*."""
    from utk_curio.sandbox.app import worker

    worker._worker_init()
    return worker.execute_code(
        code, "", "curio.builtin/data-loading", "",
        launch_dir=str(launch), session_id="shipped-docs", save_dataset=False,
    )


def _in_a_child(code, scratch):
    """The manifest an isolated child writes for *code*, run in the current
    folder as ``child.confine`` leaves it."""
    import builtins

    from utk_curio.sandbox.isolation import child

    scratch.mkdir(exist_ok=True)
    return child.run_node({
        "code": code,
        "node_type": "curio.builtin/data-loading",
        "data_type": "",
        "scratch_dir": str(scratch),
        "input": {"kind": "none"},
        "dataset_paths": {},
        "session_imports": [],
        "limits": {},
    }, lambda: {"__builtins__": builtins})


def test_an_in_process_node_reads_the_shipped_file_from_a_folder_without_docs(launch):
    result = _in_process(PRINT_RASTER_DIGEST, launch)

    assert result["stderr"] == "", result["stderr"]
    assert result["stdout"] == [_digest(shipped.path(RASTER).read_bytes())]
    assert not (launch / "docs").exists(), "the run wrote docs/ into the folder Curio started from"


def test_an_isolated_child_reads_the_shipped_file_from_a_folder_without_docs(launch, tmp_path, monkeypatch):
    """A run without a user's work directory (an unauthenticated launch) runs
    in the folder Curio started from."""
    monkeypatch.chdir(launch)

    manifest = _in_a_child(PRINT_RASTER_DIGEST, tmp_path / "scratch")

    assert manifest["ok"], manifest["stderr"]
    assert manifest["stdout"] == [_digest(shipped.path(RASTER).read_bytes())]


def test_a_folder_that_holds_the_path_reads_its_own_file(launch):
    """A clone started from its root, the Docker image and CI hold
    ``docs/``: their files are the ones read."""
    own = launch / RASTER
    own.parent.mkdir(parents=True)
    own.write_bytes(b"the launch folder's own raster")

    result = _in_process(PRINT_RASTER_DIGEST, launch)

    assert result["stderr"] == "", result["stderr"]
    assert result["stdout"] == [_digest(b"the launch folder's own raster")]


def test_a_traceback_gives_the_line_of_the_code_as_written(launch):
    """Line 1 is ``def userCode(arg):``, so the raise on the code's third
    line is line 4, as it is for code that reads no shipped file."""
    code = _node(f"""\
        with open({RASTER!r}, 'rb') as f:
            size = len(f.read())
        raise ValueError(size)
    """)

    result = _in_process(code, launch)

    assert 'File "<string>", line 4, in userCode' in result["stderr"], result["stderr"]
    assert f"ValueError: {len(shipped.path(RASTER).read_bytes())}" in result["stderr"], result["stderr"]


def test_a_path_nothing_holds_fails_as_the_code_spells_it(launch):
    result = _in_process(_node("""\
        with open('docs/examples/data/not-shipped.bin', 'rb') as f:
            return f.read()
    """), launch)

    assert "No such file or directory: 'docs/examples/data/not-shipped.bin'" in result["stderr"], result["stderr"]


def test_code_that_does_not_compile_fails_as_it_always_has(launch):
    result = _in_process(_node(f"""\
        data = open({RASTER!r}, 'rb').read(
        return data
    """), launch)

    assert 'File "<string>", line 2' in result["stderr"], result["stderr"]
    assert "SyntaxError" in result["stderr"], result["stderr"]
