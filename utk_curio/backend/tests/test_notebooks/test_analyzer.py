"""What the notebook analyzer says about each cell.

``analyzer.py`` had no coverage at all, which is uncomfortable for a module
that decides the shape of every imported dataflow *and* ``exec()``s notebook
code to render Altair charts. These cases pin the contract the importer relies
on, so a change to the AST walk fails here rather than in someone's canvas.

The ``is_import_only`` cases are the ones added for #235: a notebook with ten
small setup cells used to import as ten disconnected "Python Computation"
nodes, because an import cell can have no edges by construction. Recognising
them is what lets the frontend merge them into one Setup node.

Run::

    pytest utk_curio/backend/tests/test_notebooks/test_analyzer.py -v
"""
from __future__ import annotations

import textwrap

from utk_curio.backend.app.notebooks.analyzer import analyze_cells


def _cells(*sources: str) -> list[str]:
    return [textwrap.dedent(s).strip("\n") for s in sources]


def _flags(*sources: str) -> list[bool]:
    result = analyze_cells(_cells(*sources))
    return [c["is_import_only"] for c in result["analysis"]]


class TestImportOnlyDetection:
    def test_a_pure_import_cell_is_import_only(self):
        assert _flags(
            """
            import pandas as pd
            import numpy as np
            from sklearn.cluster import KMeans
            """
        ) == [True]

    def test_imports_with_a_docstring_or_pass_still_count(self):
        # A stripped `%matplotlib inline` leaves a bare string behind, and
        # neither it nor a `pass` is code the user needs to see.
        assert _flags(
            """
            "setup"
            import pandas as pd
            pass
            """
        ) == [True]

    def test_a_blank_cell_is_import_only(self):
        # Notebooks are full of these. Better merged away than rendered as an
        # empty node.
        assert _flags("", "   \n\n", "# just a comment") == [True, True, True]

    def test_an_import_that_also_assigns_is_not(self):
        # `df` is a real producer that later cells will edge from; folding this
        # into the Setup node would break the graph.
        assert _flags(
            """
            import pandas as pd
            df = pd.read_csv("a.csv")
            """
        ) == [False]

    def test_an_import_that_also_calls_is_not(self):
        assert _flags(
            """
            import warnings
            warnings.filterwarnings("ignore")
            """
        ) == [False]

    def test_a_config_assignment_is_not(self):
        assert _flags("RANDOM_SEED = 42") == [False]

    def test_a_function_definition_is_not(self):
        assert _flags(
            """
            import math

            def area(r):
                return math.pi * r ** 2
            """
        ) == [False]

    def test_a_syntax_error_cell_is_not(self):
        # It keeps its own node and its content verbatim: merging code we could
        # not parse would hide the cell the user has to go fix.
        assert _flags("this is not python ===") == [False]


class TestDependencyEdges:
    def test_a_producer_edges_to_its_consumer(self):
        result = analyze_cells(_cells("df = load()", "print(df)"))
        assert result["edges"] == [{"source": 0, "target": 1}]

    def test_import_names_never_produce_edges(self):
        # The reason import-only cells are disconnected in the first place: an
        # edge from the import cell to every cell using `pd` would be noise.
        result = analyze_cells(
            _cells("import pandas as pd", "df = pd.DataFrame()", "print(df)")
        )
        assert {"source": 0, "target": 1} not in result["edges"]
        assert {"source": 1, "target": 2} in result["edges"]

    def test_last_var_names_the_cell_output(self):
        # The importer titles nodes from this, so a wall of identically-named
        # "Python Computation" boxes becomes readable.
        result = analyze_cells(_cells("a = 1\nresult = a + 1"))
        assert result["analysis"][0]["last_var"] == "result"

    def test_every_cell_reports_the_full_key_set(self):
        result = analyze_cells(_cells("import os", "broken ===", "x = 1"))
        for entry in result["analysis"]:
            assert set(entry) == {
                "defined", "used", "last_var", "altair_spec", "is_import_only",
            }
