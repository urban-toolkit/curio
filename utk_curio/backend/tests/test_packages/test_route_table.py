"""The packages blueprint's route table is a contract (memo dev/143, B4).

``route_table.json`` was captured at e16cc254, before ``routes.py`` was split
into ``routes/``: every rule, its methods and its endpoint name. The recorder
is ``tests/_support/route_table.py``, shared with the agents suite.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.packages.routes import packages_bp
from utk_curio.backend.tests._support.route_table import assert_route_table_unchanged

FIXTURE = Path(__file__).with_name("route_table.json")


def test_route_table_is_unchanged():
    assert_route_table_unchanged(packages_bp, "packages_api.", FIXTURE, what="packages")
