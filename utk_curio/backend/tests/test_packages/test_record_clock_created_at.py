"""A package that arrives without ``createdAt`` is dated by the record clock.

An e2e test that photographs catalog ages sets that clock to its browser's
date (``/api/testing/clock``, ``common/record_clock.py``); a package it saves
or imports must carry that date, or the Node Catalog shows it as made after
the page's own "now".
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

CALENDAR = datetime(2026, 10, 7, 6, 0, tzinfo=timezone.utc)


def test_a_missing_created_at_is_stamped_from_the_record_clock(tmp_path):
    from utk_curio.backend.app.common import record_clock  # main has no record clock
    from utk_curio.backend.app.packages.repositories.manifests import (
        merge_missing_manifest_created_at,
    )

    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"id": "example.dated"}), encoding="utf-8")
    record_clock.set_now(CALENDAR)
    try:
        assert merge_missing_manifest_created_at(tmp_path) is True
    finally:
        record_clock.set_now(None)
    stamped = json.loads(manifest.read_text(encoding="utf-8"))["createdAt"]
    when = datetime.fromisoformat(stamped.replace("Z", "+00:00"))
    assert CALENDAR <= when < CALENDAR + timedelta(minutes=1), stamped
