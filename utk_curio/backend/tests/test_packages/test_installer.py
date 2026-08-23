"""Tests for :mod:`utk_curio.backend.app.packages.installer`.

Covers the happy path, the zip-slip guards, layout enforcement, manifest
cross-checks, replace=True / replace=False semantics, uninstall, and
round-trip export.
"""

from __future__ import annotations

import io
import json
import os
import zipfile

import pytest

from utk_curio.backend.app.packages.installer import (
    InstallerError,
    export_packageage_archive,
    install_packageage_from_archive,
    install_packageage_from_directory,
    uninstall_packageage,
)
from utk_curio.backend.app.packages.storage import package_dir


def test_install_happy_path(tmp_curio, make_archive):
    result = install_packageage_from_archive("guest", make_archive())
    assert result.manifest.package_id == "ai.test.demo"
    assert result.manifest.major == 1
    assert result.replaced_existing is False
    target = package_dir("guest", "ai.test.demo@1")
    assert (target / "manifest.json").is_file()
    assert (target / "starters" / "demo-kind" / "Default.py").is_file()
    integrity = json.loads((target / "integrity.json").read_text())
    assert "manifest.json" in integrity["sha256"]
    assert "starters/demo-kind/Default.py" in integrity["sha256"]


def test_install_rejects_duplicate_without_replace(tmp_curio, make_archive):
    install_packageage_from_archive("guest", make_archive())
    with pytest.raises(InstallerError, match="already installed"):
        install_packageage_from_archive("guest", make_archive())


def test_install_replace_overwrites(tmp_curio, make_archive, manifest_dict):
    install_packageage_from_archive("guest", make_archive())
    new_archive = make_archive(
        manifest=manifest_dict(version="2.0.0"),
        sources={"demo-kind": {"Default.py": "def run():\n    return {'v': 2}\n"}},
    )
    result = install_packageage_from_archive("guest", new_archive, replace=True)
    assert result.replaced_existing is True
    assert result.manifest.version == "2.0.0"
    target = package_dir("guest", "ai.test.demo@1")
    body = (target / "starters" / "demo-kind" / "Default.py").read_text()
    assert "'v': 2" in body


def test_install_refreshes_manifest_mtime_for_api_recency(tmp_curio, make_archive, manifest_dict):
    """Reinstall must bump manifest mtime even when bundled zip entries carry stale timestamps."""
    install_packageage_from_archive("guest", make_archive())
    target = package_dir("guest", "ai.test.demo@1")
    mp = target / "manifest.json"
    stale = 1_000_000.0
    os.utime(mp, (stale, stale))

    reinstall = make_archive(manifest=manifest_dict(version="1.0.1"))
    install_packageage_from_archive("guest", reinstall, replace=True)
    assert mp.stat().st_mtime > stale


@pytest.mark.parametrize(
    "bad_member",
    [
        "../etc/passwd",                       # classic traversal
        "starters/../escape.py",               # interior traversal
        "/abs/path",                            # absolute
        "starters/demo-kind/..\\evil",        # backslash separator
        "starters/demo-kind/with space.py",   # space outside charset
    ],
)
def test_install_blocks_unsafe_member(tmp_curio, make_archive, bad_member):
    archive = make_archive(extra_files={bad_member: b"x"})
    with pytest.raises(InstallerError):
        install_packageage_from_archive("guest", archive)


def test_install_rejects_disallowed_top_level(tmp_curio, manifest_dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest_dict()))
        zf.writestr("bin/evil.sh", "#!/bin/sh\necho boom\n")
    with pytest.raises(InstallerError, match="not allowed"):
        install_packageage_from_archive("guest", buf.getvalue())


def test_install_rejects_missing_manifest(tmp_curio):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("starters/demo-kind/Default.py", "")
    with pytest.raises(InstallerError, match="manifest"):
        install_packageage_from_archive("guest", buf.getvalue())


def test_install_rejects_invalid_json(tmp_curio):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w") as zf:
        zf.writestr("manifest.json", "{not valid")
    with pytest.raises(InstallerError, match="valid JSON|invalid JSON"):
        install_packageage_from_archive("guest", buf.getvalue())


def test_install_rejects_bad_zip(tmp_curio):
    with pytest.raises(InstallerError, match="valid zip"):
        install_packageage_from_archive("guest", b"plain text, not a zip")


def test_install_rejects_size_cap(tmp_curio, make_archive, manifest_dict, monkeypatch):
    # Synthesize a member whose declared file_size exceeds the per-file
    # cap. The installer reads ZipInfo.file_size before extraction, so a
    # crafted but legitimate large file is rejected before any bytes are
    # written.
    from utk_curio.backend.app.packages import installer as mod
    monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 1024)
    big = b"x" * 4096
    archive = make_archive(
        sources={"demo-kind": {"Default.py": big.decode()}},
    )
    with pytest.raises(InstallerError, match="exceeds per-file"):
        install_packageage_from_archive("guest", archive)


def test_uninstall_removes_directory(tmp_curio, make_archive):
    install_packageage_from_archive("guest", make_archive())
    assert uninstall_packageage("guest", "ai.test.demo@1") is True
    target = package_dir("guest", "ai.test.demo@1")
    assert not target.exists()
    assert uninstall_packageage("guest", "ai.test.demo@1") is False


def test_export_roundtrip(tmp_curio, make_archive):
    install_packageage_from_archive("guest", make_archive())
    archive_bytes = export_packageage_archive("guest", "ai.test.demo@1")
    uninstall_packageage("guest", "ai.test.demo@1")
    # Re-install from the exported bytes; must succeed.
    result = install_packageage_from_archive("guest", archive_bytes)
    assert result.manifest.package_id == "ai.test.demo"


def test_export_unknown_packageage(tmp_curio):
    with pytest.raises(InstallerError, match="not installed"):
        export_packageage_archive("guest", "ai.test.demo@1")


def test_export_omits_integrity_and_reinstall_rebuilds_it(tmp_curio, make_archive):
    """``integrity.json`` is never shipped in an archive, only recomputed on install.

    The builder and the exporter both skip it deliberately: hashes describe the
    files as installed, so carrying a stale copy in the zip would either be
    ignored or actively wrong. Nothing verifies it on install, so a regression
    here is silent - hence asserting the absence, not just the presence.
    """
    install_packageage_from_archive("guest", make_archive())
    installed = package_dir("guest", "ai.test.demo@1")
    assert (installed / "integrity.json").is_file(), "install should write integrity.json"

    archive_bytes = export_packageage_archive("guest", "ai.test.demo@1")
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        names = set(zf.namelist())
    assert "manifest.json" in names
    assert any(n.startswith("starters/") for n in names), names
    assert "integrity.json" not in names, (
        f"exported archive must not carry integrity.json: {sorted(names)}"
    )

    uninstall_packageage("guest", "ai.test.demo@1")
    install_packageage_from_archive("guest", archive_bytes)
    rebuilt = json.loads((installed / "integrity.json").read_text(encoding="utf-8"))
    assert "manifest.json" in rebuilt["sha256"]
    # The map describes the files actually on disk, so every hashed path exists.
    for rel in rebuilt["sha256"]:
        assert (installed / rel).is_file(), f"integrity names a missing file: {rel}"


def _rewrite_archive_package_id(archive: bytes, new_id: str) -> bytes:
    """Copy *archive*, replacing only ``manifest.json``'s ``id``."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(archive)) as src:
        with zipfile.ZipFile(out, mode="w", compression=zipfile.ZIP_DEFLATED) as dst:
            for item in src.infolist():
                body = src.read(item.filename)
                if item.filename == "manifest.json":
                    manifest = json.loads(body.decode("utf-8"))
                    manifest["id"] = new_id
                    body = json.dumps(manifest, indent=2).encode("utf-8")
                dst.writestr(item.filename, body)
    return out.getvalue()


def test_renamed_archive_installs_alongside_original(tmp_curio, make_archive):
    """Editing the manifest id forks a package rather than colliding with it.

    ``dir_name`` is derived purely from the manifest (``<id>@<major>``), and
    nothing verifies integrity on install - so retitling an exported archive
    yields an independent package. This is what makes an export -> edit ->
    re-import round trip usable without ``replace=True``.
    """
    original = make_archive()
    install_packageage_from_archive("guest", original)

    forked = _rewrite_archive_package_id(original, "ai.test.forked")
    result = install_packageage_from_archive("guest", forked)

    assert result.manifest.package_id == "ai.test.forked"
    assert result.replaced_existing is False, "a new coordinate must not replace anything"

    original_dir = package_dir("guest", "ai.test.demo@1")
    forked_dir = package_dir("guest", "ai.test.forked@1")
    assert original_dir.is_dir() and forked_dir.is_dir()
    assert original_dir != forked_dir
    # Both remain independently loadable, each with its own integrity map.
    for d in (original_dir, forked_dir):
        assert (d / "manifest.json").is_file()
        assert (d / "integrity.json").is_file()


def test_reinstalling_the_same_coordinate_still_needs_replace(tmp_curio, make_archive):
    """The fork above works *because* the coordinate changed, not because
    re-import is permissive: the unmodified archive is still refused."""
    archive = make_archive()
    install_packageage_from_archive("guest", archive)
    with pytest.raises(InstallerError, match="already installed"):
        install_packageage_from_archive("guest", archive)


def test_install_packageage_from_directory_uses_committed_fixture(tmp_curio):
    """The catalog install path turns a fixture dir into an installed package."""
    from pathlib import Path

    fixtures_root = (
        Path(__file__).resolve().parents[2] / "fixtures" / "packages"
    )
    fixture = fixtures_root / "ai.urbanlab.uhvi@1"
    if not fixture.is_dir():
        pytest.skip("UHVI fixture missing")
    result = install_packageage_from_directory("guest", fixture)
    assert result.manifest.package_id == "ai.urbanlab.uhvi"
    target = package_dir("guest", "ai.urbanlab.uhvi@1")
    assert (target / "starters" / "uhvi-load").is_dir()


# ---------------------------------------------------------------------------
# Orphan staging directory cleanup
# ---------------------------------------------------------------------------

def test_install_purges_orphan_staging_dirs(tmp_curio, make_archive):
    """A previous install that was SIGKILL'd / lost power leaves a
    ``stage-XXXX`` directory in ``<user>/.package-staging/``. The next
    install must sweep it so the orphans don't accumulate forever."""
    from utk_curio.backend.app.packages.storage import (
        user_packageage_staging_dir,
        user_packageages_dir,
    )

    staging_base = user_packageage_staging_dir("guest")
    staging_base.mkdir(parents=True, exist_ok=True)
    orphan_a = staging_base / "stage-abcd"
    orphan_b = staging_base / "stage-zzzz"
    orphan_a.mkdir()
    orphan_b.mkdir()
    (orphan_a / "leftover.txt").write_text("junk")

    # And a legacy orphan from older builds that staged inside the
    # package store — the sweep also has to clear that out so the watchdog
    # reloader doesn't keep tripping over its ``.py`` files.
    legacy_base = user_packageages_dir("guest")
    legacy_base.mkdir(parents=True, exist_ok=True)
    legacy_orphan = legacy_base / ".staging-legacy"
    legacy_orphan.mkdir()
    (legacy_orphan / "leftover.py").write_text("# old")

    install_packageage_from_archive("guest", make_archive())

    assert not orphan_a.exists(), "stale staging dir should have been swept"
    assert not orphan_b.exists()
    assert not legacy_orphan.exists(), "legacy in-store staging dir must also be swept"
    # And the new install is intact.
    target = package_dir("guest", "ai.test.demo@1")
    assert target.is_dir()


def test_install_stages_outside_packageage_store(tmp_curio, make_archive):
    """Installs must write ``.py`` template files outside the user's
    package store. Staging inside ``<user>/packages/`` triggers Werkzeug's
    watchdog reloader mid-install and kills the response — which is
    exactly the "Failed to fetch" bug the new staging layout fixes."""
    from utk_curio.backend.app.packages.storage import (
        user_packageage_staging_dir,
        user_packageages_dir,
    )

    install_packageage_from_archive("guest", make_archive())

    staging_base = user_packageage_staging_dir("guest")
    legacy_base = user_packageages_dir("guest")

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
        "install must not leave .staging-/stage- dirs inside the package store "
        "— the dev-server watchdog reloader would fire on the .py files"
    )


def test_seeder_purges_orphan_staging_dirs(tmp_curio):
    """The dev seeder runs on cold startup; it also has to sweep orphan
    staging dirs so a user who has not yet hit an install endpoint can
    still recover from a previously crashed install cycle."""
    from utk_curio.backend.app.packages.seed import seed_dev_packageages
    from utk_curio.backend.app.packages.storage import (
        user_packageage_staging_dir,
        user_packageages_dir,
    )

    staging_base = user_packageage_staging_dir("guest")
    staging_base.mkdir(parents=True, exist_ok=True)
    new_orphan = staging_base / "stage-deadbeef"
    new_orphan.mkdir()

    legacy_base = user_packageages_dir("guest")
    legacy_base.mkdir(parents=True, exist_ok=True)
    legacy_orphan = legacy_base / ".staging-legacy"
    legacy_orphan.mkdir()

    seed_dev_packageages(user_key="guest")
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
        "/abs/repo/.curio/users/guest/packages/foo@1/templates/x.py",
        "/abs/repo/.curio/users/guest/.package-staging/stage-abcd/templates/y.py",
        "/abs/repo/.curio/users/guest/packages/.staging-zzzz/templates/z.py",
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
        "/abs/repo/utk_curio/backend/app/packages/installer.py",
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
        "/abs/repo/.curio/users/guest/packages/pkg@1/templates/sub/foo.py"
    )
    assert not deep.match("**/.curio/**"), (
        "expected pathlib to miss deep .curio trees (Watchdog ignore bug)"
    )
    assert _matches_exclude(str(deep), list(RELOADER_EXCLUDE_PATTERNS))


def test_purge_stale_staging_keeps_the_in_flight_dir(tmp_curio):
    """A concurrent install must not delete a staging tree still being extracted.

    The sweep is indiscriminate by design (a crashed install leaves no marker to
    distinguish it from a live one), so the only safe discriminator is the
    caller's own directory. Without ``keep`` this races: Flask serves requests
    concurrently, and the victim fails much later - as a WinError 2 from the
    manifest-validation copytree on a file it had just written.
    """
    from utk_curio.backend.app.packages.installer import _purge_stale_staging
    from utk_curio.backend.app.packages.storage import user_packageage_staging_dir

    base = user_packageage_staging_dir("guest")
    base.mkdir(parents=True, exist_ok=True)
    orphan = base / "stage-orphaned"
    in_flight = base / "stage-in-flight"
    for d in (orphan, in_flight):
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "behaviors.js.map").write_text("{}", encoding="utf-8")

    _purge_stale_staging("guest", keep=in_flight)

    assert not orphan.exists(), "a genuine orphan should still be swept"
    assert (in_flight / "scripts" / "behaviors.js.map").is_file(), (
        "the in-flight staging tree must survive the sweep"
    )


def test_purge_stale_staging_sweeps_everything_when_nothing_is_kept(tmp_curio):
    from utk_curio.backend.app.packages.installer import _purge_stale_staging
    from utk_curio.backend.app.packages.storage import user_packageage_staging_dir

    base = user_packageage_staging_dir("guest")
    (base / "stage-a").mkdir(parents=True)
    (base / "stage-b").mkdir(parents=True)

    _purge_stale_staging("guest")

    assert list(base.iterdir()) == []


def test_purge_stale_staging_only_sweeps_its_own_prefix(tmp_curio):
    """The sweep must not touch directories this module did not create.

    A concurrent install's manifest-validation copy lives in the same parent
    (``load_packageage_manifest_from_dir`` stages it there to stay on one
    filesystem). Deleting it mid-copy surfaces as a shutil.Error with WinError 3
    on every destination path at once, from a request that looks unrelated.
    """
    from utk_curio.backend.app.packages.installer import _purge_stale_staging
    from utk_curio.backend.app.packages.storage import user_packageage_staging_dir

    base = user_packageage_staging_dir("guest")
    base.mkdir(parents=True, exist_ok=True)
    ours = base / "stage-orphaned"
    theirs = base / ".validate-inflight"
    for d in (ours, theirs):
        d.mkdir(parents=True)
        (d / "manifest.json").write_text("{}", encoding="utf-8")

    _purge_stale_staging("guest")

    assert not ours.exists(), "a stale stage- dir should still be swept"
    assert (theirs / "manifest.json").is_file(), (
        "a concurrent validate copy must survive the sweep"
    )


def test_validate_copy_lands_beside_the_tree_it_validates(tmp_curio, make_archive):
    """The validate copy stays on the same filesystem, not in the system temp dir.

    Asserted by observing where it appears during the load: the system temp dir
    is exposed to OS cleaners and scanners, which was deleting it mid-copy.
    """
    import tempfile
    from utk_curio.backend.app.packages import installer as inst

    seen: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def spy(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        if str(kwargs.get("prefix", "")).startswith(".validate-"):
            seen.append(str(kwargs.get("dir")))
        return path

    original = inst.tempfile.mkdtemp
    inst.tempfile.mkdtemp = spy
    try:
        install_packageage_from_archive("guest", make_archive())
    finally:
        inst.tempfile.mkdtemp = original

    assert seen, "the validate copy should declare an explicit parent dir"
    assert all(d and "package-staging" in d for d in seen), seen

