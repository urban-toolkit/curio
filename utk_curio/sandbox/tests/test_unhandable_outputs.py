"""A node that returns a value Curio cannot hand on is told what it can return.

A node's output is stored so the nodes after it can read it: a table, a
raster, a number, text, true or false, or a list, dict or tuple of those. An
xarray Dataset (a NetCDF file read whole), an onnxruntime session or any other
object fails the node with one plain sentence naming what it returned and what
a node can return, in process and in the isolated child alike, as the last line
of the node's error, which its outcome strip shows.
"""

from __future__ import annotations

import pandas as pd
import pytest

CAN_RETURN = (
    "Return a table (a DataFrame or GeoDataFrame), a raster (an open rasterio dataset), "
    "a number, text, true or false, a list, a dict or a tuple made from it."
)

CASES = [
    pytest.param("    return object()\n", "an object", id="an-object"),
    pytest.param("    return {'rows': 2, 'model': object()}\n", "an object", id="a-dict-holding-one"),
    pytest.param("    import xarray as xr\n    return xr.Dataset()\n", "an xarray Dataset", id="an-xarray-dataset"),
]


def _last_line(stderr: str) -> str:
    return [line for line in stderr.splitlines() if line.strip()][-1]


@pytest.mark.parametrize("code, named", CASES)
def test_an_in_process_node_is_told_what_a_node_can_return(code, named):
    from utk_curio.sandbox.app.worker import _worker_init, execute_code
    from utk_curio.sandbox.util.db import init_db

    _worker_init()
    init_db()
    result = execute_code(code, "", "PYTHON_COMPUTATION", "", save_dataset=False)

    assert result["output"]["path"] == ""
    assert _last_line(result["stderr"]) == f"TypeError: A node cannot hand on {named}. {CAN_RETURN}"


@pytest.mark.parametrize("code, named", CASES)
def test_an_isolated_node_is_told_the_same(code, named, tmp_path):
    from utk_curio.sandbox.isolation import child

    result = child.run_node({
        "code": code, "node_type": "curio.builtin/computation-analysis", "data_type": "",
        "scratch_dir": str(tmp_path), "input": {"kind": "none"}, "dataset_paths": {},
        "session_imports": [], "limits": {},
    }, lambda: {"pd": pd})

    assert not result["ok"] and result["output"] is None
    assert _last_line(result["stderr"]) == f"TypeError: A node cannot hand on {named}. {CAN_RETURN}"
