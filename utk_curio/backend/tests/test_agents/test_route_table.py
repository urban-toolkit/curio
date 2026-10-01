"""The agents blueprint's route table is a contract (memo dev/142, B4).

``route_table.json`` was captured on enh/agent-catalog when ``routes.py`` was split
into ``routes/``: every rule, its methods and its endpoint name. A presentation
refactor may move handlers between modules; it may not add, drop, rename or
re-method a route. To re-record after an INTENDED API change, run with
``CURIO_ROUTE_TABLE_RECORD=1`` and commit the fixture with the change.
"""

from __future__ import annotations

from pathlib import Path

from utk_curio.backend.app.agents.routes.common import agents_bp
from utk_curio.backend.tests._support.route_table import assert_route_table_unchanged

FIXTURE = Path(__file__).with_name("route_table.json")


def test_route_table_is_unchanged():
    assert_route_table_unchanged(agents_bp, "agents_api.", FIXTURE, what="agents")
