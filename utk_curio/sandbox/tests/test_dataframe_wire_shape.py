"""The wire shape of a DataFrame, pinned (#194).

``parseOutput`` is the only thing that decides what a ``dataframe`` payload
looks like to the browser, and every custom-UI node that reads one depends on
the answer. Nothing asserted it, so when the reference example package
(``curio.example-ui@1``'s Column Filter) was written against the *other*
plausible encoding — a row map, which a bare ``DataFrame.to_dict()`` produces —
the mismatch was invisible: ``asFrame`` returned ``None``, the node rendered its
"connect something upstream" hint forever, and nothing threw.

The node now accepts both encodings. This file pins the one Curio actually
sends, so a change here fails loudly instead of silently emptying every
custom-UI node that consumes a DataFrame.
"""
import pandas as pd
import pytest

from utk_curio.sandbox.util.parsers import parseOutput


def test_a_dataframe_is_column_to_list():
    df = pd.DataFrame(
        {"population": [2746, 8804, 12], "name": ["Andersonville", "Loop", "Tiny"]}
    )

    out = parseOutput(df)

    assert out["dataType"] == "dataframe"
    # Column-oriented, and each column an ARRAY (`to_dict(orient='list')`), not
    # an object keyed by row index. This is the whole contract.
    assert out["data"] == {
        "population": [2746, 8804, 12],
        "name": ["Andersonville", "Loop", "Tiny"],
    }
    for column in out["data"].values():
        assert isinstance(column, list), (
            "a column arrived as something other than a list; every custom-UI "
            "node that reads a DataFrame is written against the list form"
        )


def test_row_order_is_positional():
    # The row index is the position in each column's list. A node filtering
    # rows relies on the columns staying aligned with one another.
    df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

    data = parseOutput(df)["data"]

    assert data["a"] == [1, 2, 3]
    assert data["b"] == ["x", "y", "z"]
    assert len(data["a"]) == len(data["b"])


def test_an_empty_dataframe_still_names_its_columns():
    # An empty result must not look like "no columns" — a node would then show
    # its connect-upstream hint rather than an honest zero-row state.
    df = pd.DataFrame({"population": [], "name": []})

    out = parseOutput(df)

    assert out["dataType"] == "dataframe"
    assert set(out["data"]) == {"population", "name"}
    assert out["data"]["population"] == []


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, None),
        (float("nan"), None),
    ],
)
def test_missing_values_survive_as_null(value, expected):
    # `normalize_dataframe_for_json` runs first; a NaN that reached the browser
    # as a raw float would break `JSON.parse` on the other side.
    df = pd.DataFrame({"population": [1, value]})

    data = parseOutput(df)["data"]

    assert data["population"][1] is expected
