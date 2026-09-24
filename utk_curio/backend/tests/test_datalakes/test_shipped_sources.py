"""Every committed source loads, serialises, and declares only what it can do.

Parametrized over whatever is in ``datalakes/``, so a new source is covered the
moment it lands. The emptiness guard is the important one: a glob that matches
nothing makes a parametrized suite pass vacuously, which is how a broken path
looks exactly like a clean run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from utk_curio.backend.app.datalakes.domain import manifest as M
from utk_curio.backend.app.datalakes.domain.source_id import SourceId
from utk_curio.backend.app.datalakes.schemas.payloads import source_row
from utk_curio.backend.tests.test_datalakes.conftest import SHIPPED_ROOT

SHIPPED = sorted(p for p in SHIPPED_ROOT.iterdir() if p.is_dir()) if SHIPPED_ROOT.is_dir() else []
IDS = [p.name for p in SHIPPED]

MAX_ICON_BYTES = 256 * 1024
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_the_catalog_is_not_empty():
    """Guards every other test in this file against passing vacuously."""
    assert SHIPPED, f"no source directories under {SHIPPED_ROOT}"


@pytest.mark.parametrize("path", SHIPPED, ids=IDS)
class TestEveryShippedSource:
    def test_it_loads(self, path: Path):
        M.load_source_manifest(path)

    def test_the_directory_name_is_the_coordinate(self, path: Path):
        manifest = M.load_source_manifest(path)
        assert manifest.dir_name == path.name
        assert SourceId.parse_dir(path.name).source_id == manifest.id

    def test_it_serialises_to_a_wire_row(self, path: Path):
        row = source_row(M.load_source_manifest(path))
        assert row["sourceId"] and row["name"] and row["provider"]

    def test_the_wire_row_carries_exactly_the_allowlisted_keys(self, path: Path):
        """The payload builder is the structural defence against leaking a
        credential, so the assertion is an exact key set rather than a search
        for suspicious substrings - ``usesToken`` contains "token" and is
        perfectly safe, while a field called ``extra`` might not be. An exact
        set means a new manifest field stays invisible to clients until
        someone adds it here on purpose.
        """
        row = source_row(M.load_source_manifest(path))
        assert set(row) == {
            "sourceId", "dirName", "name", "version", "description", "publisher",
            "homepage", "license", "tags", "iconUrl", "provider", "baseUrl",
            "auth", "capabilities", "createdAt", "updatedAt",
        }
        assert set(row["auth"]) == {
            "mode", "required", "usesToken", "secretId", "present", "helpUrl",
        }
        assert set(row["capabilities"]) == {
            "search", "describe", "download", "formats", "maxDownloadBytes",
        }

    def test_provider_options_never_reach_a_client(self, path: Path):
        """Provider wiring is not information. Keeping it server-side means a
        provider can gain an option without anyone auditing whether it was
        safe to publish - which is where a credential would end up."""
        row = source_row(M.load_source_manifest(path))
        assert "options" not in json.dumps(row)

    def test_the_auth_block_is_booleans_a_slot_name_and_a_link(self, path: Path):
        """Never a value. ``secretId`` names WHICH credential is wanted; it is
        a slot, matched against the same grammar the manifest validates."""
        auth = source_row(M.load_source_manifest(path))["auth"]
        assert isinstance(auth["required"], bool)
        assert isinstance(auth["usesToken"], bool)
        assert isinstance(auth["present"], bool)
        if auth["secretId"] is not None:
            assert M._SECRET_ID_RE.match(auth["secretId"])

    def test_its_provider_is_one_we_implement(self, path: Path):
        assert M.load_source_manifest(path).provider.type in M.PROVIDER_TYPES

    def test_it_declares_only_acquirable_formats(self, path: Path):
        formats = M.load_source_manifest(path).capabilities.formats
        assert formats, "a source that can deliver nothing is not useful"
        assert set(formats) <= set(M.LAKE_ACQUIRABLE_FORMATS)

    def test_a_searchable_source_has_a_base_to_search(self, path: Path):
        manifest = M.load_source_manifest(path)
        if manifest.capabilities.search:
            assert manifest.provider.base_url.startswith("https://")

    def test_a_token_source_names_its_slot_and_header(self, path: Path):
        auth = M.load_source_manifest(path).auth
        if auth.uses_token:
            assert auth.secret_id and auth.header_name
            assert auth.scheme == "header"
            assert auth.help_url, "tell the user where to get the token"

    def test_its_icon_is_a_real_png_within_the_cap(self, path: Path):
        """Or there is no icon, which is fine - the glyph covers it."""
        manifest = M.load_source_manifest(path)
        if manifest.icon is None:
            return
        icon = path / manifest.icon
        assert icon.is_file(), f"{path.name} names {manifest.icon} but the file is missing"
        assert icon.resolve().parent == path.resolve(), "an icon must live in its own source folder"
        blob = icon.read_bytes()
        assert blob.startswith(PNG_MAGIC), "declared .png but the bytes are not a PNG"
        assert len(blob) <= MAX_ICON_BYTES


def test_the_shipped_set_exercises_the_glyph_fallback():
    """At least one source ships without an icon.

    Not pedantry: the fallback is what every source without a logo renders,
    and a shipped set where all five have icons would leave it untested in the
    one place a human actually looks.
    """
    without = [p.name for p in SHIPPED if M.load_source_manifest(p).icon is None]
    assert without, "no shipped source exercises the no-icon path"


def test_every_provider_we_implement_has_a_shipped_example():
    """A provider with no source is a provider nobody will notice breaking."""
    shipped = {M.load_source_manifest(p).provider.type for p in SHIPPED}
    assert shipped == set(M.PROVIDER_TYPES), (
        f"providers without a shipped source: {sorted(set(M.PROVIDER_TYPES) - shipped)}"
    )


def _packaging_file(name: str) -> str:
    """Read a packaging file from the checkout, or skip.

    These checks only mean anything where the source tree is: a built image
    does not ship its own Dockerfile, and asserting against a file that is
    legitimately absent tests the environment rather than the packaging. This
    is the second thing this pair caught, the first being the bug itself.
    """
    path = SHIPPED_ROOT.parent / name
    if not path.is_file():
        pytest.skip(f"no {name} here - a packaging check needs a source checkout")
    return path.read_text(encoding="utf-8")


def test_the_image_ships_the_catalog():
    """The Dockerfile copies ``datalakes/`` into the image.

    It did not, and nothing local noticed: every test here reads the catalog
    from the working tree, so the suite was green while the built image had no
    sources at all and every portal 404'd. CI caught it, 112 failures deep and
    an image build later.

    ``MANIFEST.in`` is not the same question and does not cover this: that
    governs the sdist and the wheel, while the container copies named
    directories one at a time. A new shipped root has to be added to both, and
    forgetting either is invisible until something is built.
    """
    assert "COPY datalakes/" in _packaging_file("Dockerfile"), (
        "Dockerfile does not copy datalakes/ - the built image would serve an "
        "empty Data Lake Catalog"
    )


def test_the_wheel_ships_the_catalog():
    """And ``MANIFEST.in`` covers it for a pip install.

    The twin of the above, and the reason both exist: these are two separate
    packaging paths, and a source that reaches one does not reach the other.
    """
    assert "recursive-include datalakes" in _packaging_file("MANIFEST.in")


@pytest.mark.parametrize(
    "compose", ["docker-compose.ci.yml", "docker-compose.ci-isolated.yml"]
)
def test_the_ci_container_is_pointed_at_the_recorded_corpus(compose: str):
    """CI's container gets ``CURIO_DATALAKE_FIXTURES``, at the path it really has.

    The third packaging path, and the one the other two do not cover. CI runs
    the browser specs with ``--use-existing`` against the container, so it is
    the CONTAINER that decides whether a lake search is a recording or a live
    call to a municipal portal - setting the variable for the pytest process
    does nothing for it.

    The path is derived rather than written down twice: moving the corpus
    inside the tree would otherwise leave the compose files pointing at a
    directory that no longer exists, which degrades silently to real HTTP.
    """
    repo_root = SHIPPED_ROOT.parent
    fixtures = Path(__file__).resolve().parent / "fixtures"
    in_image = "/app/" + fixtures.relative_to(repo_root).as_posix()

    text = _packaging_file(compose)
    assert f"CURIO_DATALAKE_FIXTURES={in_image}" in text, (
        f"{compose} does not point the container at {in_image} - the lake e2e "
        "specs there would reach live portals (they skip instead, so the only "
        "symptom is lost coverage)"
    )
