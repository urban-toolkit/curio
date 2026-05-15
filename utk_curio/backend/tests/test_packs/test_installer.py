"""Tests for :mod:`utk_curio.backend.app.packs.installer`.

Covers the happy path, the zip-slip guards, layout enforcement, manifest
cross-checks, replace=True / replace=False semantics, uninstall, and
round-trip export.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from utk_curio.backend.app.packs.installer import (
    InstallerError,
    export_pack_archive,
    install_pack_from_archive,
    install_pack_from_directory,
    uninstall_pack,
)
from utk_curio.backend.app.packs.storage import pack_dir


def test_install_happy_path(tmp_curio, make_archive):
    result = install_pack_from_archive("guest", make_archive())
    assert result.manifest.pack_id == "ai.test.demo"
    assert result.manifest.major == 1
    assert result.replaced_existing is False
    target = pack_dir("guest", "ai.test.demo@1")
    assert (target / "manifest.json").is_file()
    assert (target / "templates" / "demo-kind" / "Default.py").is_file()
    integrity = json.loads((target / "integrity.json").read_text())
    assert "manifest.json" in integrity["sha256"]
    assert "templates/demo-kind/Default.py" in integrity["sha256"]


def test_install_rejects_duplicate_without_replace(tmp_curio, make_archive):
    install_pack_from_archive("guest", make_archive())
    with pytest.raises(InstallerError, match="already installed"):
        install_pack_from_archive("guest", make_archive())


def test_install_replace_overwrites(tmp_curio, make_archive, manifest_dict):
    install_pack_from_archive("guest", make_archive())
    new_archive = make_archive(
        manifest=manifest_dict(version="2.0.0"),
        sources={"demo-kind": {"Default.py": "def run():\n    return {'v': 2}\n"}},
    )
    result = install_pack_from_archive("guest", new_archive, replace=True)
    assert result.replaced_existing is True
    assert result.manifest.version == "2.0.0"
    target = pack_dir("guest", "ai.test.demo@1")
    body = (target / "templates" / "demo-kind" / "Default.py").read_text()
    assert "'v': 2" in body


@pytest.mark.parametrize(
    "bad_member",
    [
        "../etc/passwd",                       # classic traversal
        "templates/../escape.py",               # interior traversal
        "/abs/path",                            # absolute
        "templates/demo-kind/..\\evil",        # backslash separator
        "templates/demo-kind/with space.py",   # space outside charset
    ],
)
def test_install_blocks_unsafe_member(tmp_curio, make_archive, bad_member):
    archive = make_archive(extra_files={bad_member: b"x"})
    with pytest.raises(InstallerError):
        install_pack_from_archive("guest", archive)


def test_install_rejects_disallowed_top_level(tmp_curio, manifest_dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_dict()))
        zf.writestr("bin/evil.sh", "#!/bin/sh\necho boom\n")
    with pytest.raises(InstallerError, match="not allowed"):
        install_pack_from_archive("guest", buf.getvalue())


def test_install_rejects_missing_manifest(tmp_curio):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("templates/demo-kind/Default.py", "")
    with pytest.raises(InstallerError, match="manifest"):
        install_pack_from_archive("guest", buf.getvalue())


def test_install_rejects_invalid_json(tmp_curio):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", "{not valid")
    with pytest.raises(InstallerError, match="valid JSON|invalid JSON"):
        install_pack_from_archive("guest", buf.getvalue())


def test_install_rejects_bad_zip(tmp_curio):
    with pytest.raises(InstallerError, match="valid zip"):
        install_pack_from_archive("guest", b"plain text, not a zip")


def test_install_rejects_size_cap(tmp_curio, make_archive, manifest_dict, monkeypatch):
    # Synthesize a member whose declared file_size exceeds the per-file
    # cap. The installer reads ZipInfo.file_size before extraction, so a
    # crafted but legitimate large file is rejected before any bytes are
    # written.
    from utk_curio.backend.app.packs import installer as mod
    monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 1024)
    big = b"x" * 4096
    archive = make_archive(
        sources={"demo-kind": {"Default.py": big.decode()}},
    )
    with pytest.raises(InstallerError, match="exceeds per-file"):
        install_pack_from_archive("guest", archive)


def test_uninstall_removes_directory(tmp_curio, make_archive):
    install_pack_from_archive("guest", make_archive())
    assert uninstall_pack("guest", "ai.test.demo@1") is True
    target = pack_dir("guest", "ai.test.demo@1")
    assert not target.exists()
    assert uninstall_pack("guest", "ai.test.demo@1") is False


def test_export_roundtrip(tmp_curio, make_archive):
    install_pack_from_archive("guest", make_archive())
    archive_bytes = export_pack_archive("guest", "ai.test.demo@1")
    uninstall_pack("guest", "ai.test.demo@1")
    # Re-install from the exported bytes; must succeed.
    result = install_pack_from_archive("guest", archive_bytes)
    assert result.manifest.pack_id == "ai.test.demo"


def test_export_unknown_pack(tmp_curio):
    with pytest.raises(InstallerError, match="not installed"):
        export_pack_archive("guest", "ai.test.demo@1")


def test_install_pack_from_directory_uses_committed_fixture(tmp_curio):
    """The catalog install path turns a fixture dir into an installed pack."""
    from pathlib import Path

    fixtures_root = (
        Path(__file__).resolve().parents[2] / "fixtures" / "packs"
    )
    fixture = fixtures_root / "ai.urbanlab.uhvi@1"
    if not fixture.is_dir():
        pytest.skip("UHVI fixture missing")
    result = install_pack_from_directory("guest", fixture)
    assert result.manifest.pack_id == "ai.urbanlab.uhvi"
    target = pack_dir("guest", "ai.urbanlab.uhvi@1")
    assert (target / "templates" / "uhvi-load").is_dir()


# ---------------------------------------------------------------------------
# Orphan staging directory cleanup
# ---------------------------------------------------------------------------

def test_install_purges_orphan_staging_dirs(tmp_curio, make_archive):
    """A previous install that was SIGKILL'd / lost power leaves a
    ``stage-XXXX`` directory in ``<user>/.pack-staging/``. The next
    install must sweep it so the orphans don't accumulate forever."""
    from utk_curio.backend.app.packs.storage import (
        user_pack_staging_dir,
        user_packs_dir,
    )

    staging_base = user_pack_staging_dir("guest")
    staging_base.mkdir(parents=True, exist_ok=True)
    orphan_a = staging_base / "stage-abcd"
    orphan_b = staging_base / "stage-zzzz"
    orphan_a.mkdir()
    orphan_b.mkdir()
    (orphan_a / "leftover.txt").write_text("junk")

    # And a legacy orphan from older builds that staged inside the
    # pack store — the sweep also has to clear that out so the watchdog
    # reloader doesn't keep tripping over its ``.py`` files.
    legacy_base = user_packs_dir("guest")
    legacy_base.mkdir(parents=True, exist_ok=True)
    legacy_orphan = legacy_base / ".staging-legacy"
    legacy_orphan.mkdir()
    (legacy_orphan / "leftover.py").write_text("# old")

    install_pack_from_archive("guest", make_archive())

    assert not orphan_a.exists(), "stale staging dir should have been swept"
    assert not orphan_b.exists()
    assert not legacy_orphan.exists(), "legacy in-store staging dir must also be swept"
    # And the new install is intact.
    target = pack_dir("guest", "ai.test.demo@1")
    assert target.is_dir()


def test_install_stages_outside_pack_store(tmp_curio, make_archive):
    """Installs must write ``.py`` template files outside the user's
    pack store. Staging inside ``<user>/packs/`` triggers Werkzeug's
    watchdog reloader mid-install and kills the response — which is
    exactly the "Failed to fetch" bug the new staging layout fixes."""
    from utk_curio.backend.app.packs.storage import (
        user_pack_staging_dir,
        user_packs_dir,
    )

    install_pack_from_archive("guest", make_archive())

    staging_base = user_pack_staging_dir("guest")
    legacy_base = user_packs_dir("guest")

    # No stage-* leftovers in either location after a clean install.
    if staging_base.exists():
        leftovers = [p.name for p in staging_base.iterdir() if p.is_dir()]
        assert leftovers == [], f"unexpected staging dirs left over: {leftovers}"
    in_store_staging = [
        p.name
        for p in legacy_base.iterdir()
        if p.is_dir() and (p.name.startswith(".staging-") or p.name.startswith("stage-"))
    ]
    assert in_store_staging == [], (
        "install must not leave .staging-/stage- dirs inside the pack store "
        "— the dev-server watchdog reloader would fire on the .py files"
    )


def test_seeder_purges_orphan_staging_dirs(tmp_curio):
    """The dev seeder runs on cold startup; it also has to sweep orphan
    staging dirs so a user who has not yet hit an install endpoint can
    still recover from a previously crashed install cycle."""
    from utk_curio.backend.app.packs.seed import seed_dev_packs
    from utk_curio.backend.app.packs.storage import (
        user_pack_staging_dir,
        user_packs_dir,
    )

    staging_base = user_pack_staging_dir("guest")
    staging_base.mkdir(parents=True, exist_ok=True)
    new_orphan = staging_base / "stage-deadbeef"
    new_orphan.mkdir()

    legacy_base = user_packs_dir("guest")
    legacy_base.mkdir(parents=True, exist_ok=True)
    legacy_orphan = legacy_base / ".staging-legacy"
    legacy_orphan.mkdir()

    seed_dev_packs(user_key="guest")
    assert not new_orphan.exists()
    assert not legacy_orphan.exists()


# ---------------------------------------------------------------------------
# Werkzeug reloader exclude patterns
# ---------------------------------------------------------------------------

def _matches_exclude(path: str, patterns: list[str]) -> bool:
    """Match Werkzeug's ``_should_reload`` exclude semantics."""
    import fnmatch
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def test_reloader_excludes_dot_curio_runtime_data():
    """Every runtime path under ``.curio/`` must match
    :data:`RELOADER_EXCLUDE_PATTERNS` under :mod:`fnmatch` — that is what
    Werkzeug's **stat** reloader uses. Watchdog mode uses ``pathlib``
    ``Path.match()`` instead, which fails for deep trees (see
    :envvar:`FLASK_RELOADER_TYPE` default in ``server.py``)."""
    from utk_curio.backend.server import RELOADER_EXCLUDE_PATTERNS

    paths_that_must_be_ignored = [
        "/abs/repo/.curio/users/guest/packs/foo@1/templates/x.py",
        "/abs/repo/.curio/users/guest/.pack-staging/stage-abcd/templates/y.py",
        "/abs/repo/.curio/users/guest/packs/.staging-zzzz/templates/z.py",
        "/abs/repo/.curio/data/anything.py",
        "/abs/repo/.curio/messages.log",
        "/abs/repo/.curio/users/u/provenance.db",
    ]
    for p in paths_that_must_be_ignored:
        assert _matches_exclude(p, RELOADER_EXCLUDE_PATTERNS), (
            f"reloader exclude patterns must ignore runtime path: {p}"
        )

    # Sanity: real source files in the backend tree must NOT match,
    # otherwise we'd silently break the dev-server hot-reload UX.
    paths_that_must_still_reload = [
        "/abs/repo/utk_curio/backend/app/packs/installer.py",
        "/abs/repo/utk_curio/backend/app/api/routes.py",
        "/abs/repo/utk_curio/backend/server.py",
    ]
    for p in paths_that_must_still_reload:
        assert not _matches_exclude(p, RELOADER_EXCLUDE_PATTERNS), (
            f"reloader exclude patterns wrongly ignore source path: {p}"
        )


def test_watchdog_pathlib_ignore_fails_deep_curio_paths_documentation():
    """Watchdog's ``PatternMatchingEventHandler`` uses pathlib matching;
    ``**/.curio/**`` does not ignore deep install paths — so Curio defaults
    ``FLASK_RELOADER_TYPE=stat``. If this assertion fails, pathlib fixed
    upstream and we might re-evaluate the default."""
    from pathlib import PurePosixPath

    from utk_curio.backend.server import RELOADER_EXCLUDE_PATTERNS

    deep = PurePosixPath(
        "/abs/repo/.curio/users/guest/packs/pkg@1/templates/sub/foo.py"
    )
    assert not deep.match("**/.curio/**"), (
        "expected pathlib to miss deep .curio trees (Watchdog ignore bug)"
    )
    assert _matches_exclude(str(deep), list(RELOADER_EXCLUDE_PATTERNS))
