"""The data lake source manifest: reader, validator and serialiser.

A source manifest describes a *portal*, not a dataset. It says who publishes
it, what software it runs, whether it needs a token, and what it is allowed to
hand us. The datasets themselves are discovered live.

Hand-rolled validation rather than pydantic, matching
``datasets/domain/manifest.py`` - the two manifests should be read and
extended the same way. Unlike that one there IS a JSON Schema
(``docs/schemas/data-lake-source.v1.json``), because these are authored by a
human: the Node and Agent catalogs ship schemas for the same reason, and
``tests/test_datalakes/test_schema_matches_validator.py`` keeps the two from
drifting apart.

The formats a manifest declares are an upper bound that is intersected with
the Data Catalog's own ``SUPPORTED_FORMATS`` at acquire time, so a manifest
can narrow what may be ingested but never widen it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utk_curio.backend.app.datalakes.domain.source_id import SourceId

#: Provider implementations that exist. Kept here rather than imported from
#: ``providers`` so that reading a manifest never drags in a transport.
#: ``providers/__init__.py`` asserts the two agree.
PROVIDER_TYPES = ("socrata", "ckan", "arcgis", "wfs", "direct")

AUTH_MODES = ("public", "optional-token", "required-token")

#: v1 is header-only, and that single constraint is load-bearing: it means no
#: secret ever enters a URL, which is what makes the egress audit record, every
#: refusal message and every job record safe to store verbatim.
AUTH_SCHEMES = ("header",)

#: The credential slots that exist, as a SERVER-owned allowlist. A manifest may
#: name one; it may not invent one. Each maps to a column on the user's row -
#: see ``datalakes/infrastructure/credentials.py`` - so a manifest inventing a
#: slot would be a manifest inventing somewhere for a secret to live. Declared
#: here rather than imported from that module because a manifest must be
#: readable without the ORM; ``test_credentials.py`` asserts the two agree.
KNOWN_SECRET_SLOTS = ("socrata.app-token",)

#: The formats this catalog can hand to the Data Catalog's importer. A subset
#: of the Data Catalog's own SUPPORTED_FORMATS: multi-file and archive formats
#: (shp, bundle) are not acquirable remotely in v1 - a .shp is meaningless
#: without its sibling .dbf/.shx, and unpacking a remote archive is a
#: decompression-bomb surface that deserves its own design.
LAKE_ACQUIRABLE_FORMATS = ("csv", "geojson", "json", "parquet", "geotiff")

DEFAULT_ICON_FILE = "icon.png"
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_REQUESTS_PER_MINUTE = 30

_SECRET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){0,2}$")
_ICON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.png$")


class ManifestError(ValueError):
    """Raised when a source manifest is malformed."""


@dataclass(frozen=True)
class ProviderSpec:
    type: str
    base_url: str
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AuthSpec:
    mode: str = "public"
    secret_id: str | None = None
    scheme: str = "header"
    header_name: str | None = None
    help_url: str | None = None

    @property
    def needs_token(self) -> bool:
        return self.mode == "required-token"

    @property
    def uses_token(self) -> bool:
        return self.mode in ("optional-token", "required-token")


@dataclass(frozen=True)
class CapabilitySpec:
    search: bool = True
    describe: bool = True
    download: bool = True
    formats: tuple[str, ...] = LAKE_ACQUIRABLE_FORMATS
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    #: CKAN distributions legitimately live off-portal (a package on
    #: catalog.data.gov points at an agency's own host), so that one provider
    #: needs to follow a URL off its base. It is opt-in per manifest rather
    #: than per provider, because it widens what a hostile search response can
    #: steer a request at, and that should be an operator's decision.
    allow_off_base_distributions: bool = False


@dataclass(frozen=True)
class LakeSourceManifest:
    id: str
    name: str
    version: str
    major: int
    provider: ProviderSpec
    auth: AuthSpec
    capabilities: CapabilitySpec
    description: str = ""
    publisher: str = ""
    homepage: str | None = None
    license: str = ""
    tags: tuple[str, ...] = ()
    icon: str | None = None
    requests_per_minute: int = DEFAULT_REQUESTS_PER_MINUTE
    created_at: str | None = None
    updated_at: str | None = None

    @property
    def dir_name(self) -> str:
        return f"{self.id}@{self.major}"


def _require_str(raw: object, field_name: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"manifest.{field_name} must be a non-empty string")
    return raw.strip()


def _bool(raw: object, default: bool, field_name: str) -> bool:
    if raw is None:
        return default
    if not isinstance(raw, bool):
        raise ManifestError(f"manifest.{field_name} must be a boolean")
    return raw


def _parse_provider(raw: object) -> ProviderSpec:
    if not isinstance(raw, dict):
        raise ManifestError("manifest.provider must be an object")
    kind = _require_str(raw.get("type"), "provider.type").lower()
    if kind not in PROVIDER_TYPES:
        raise ManifestError(
            f"manifest.provider.type must be one of {sorted(PROVIDER_TYPES)}"
        )
    base_url = raw.get("baseUrl")
    if base_url is None:
        base_url = ""
    if not isinstance(base_url, str):
        raise ManifestError("manifest.provider.baseUrl must be a string")
    base_url = base_url.strip().rstrip("/")
    # ``direct`` has no portal of its own - a resource id IS a URL - so it is
    # the one type permitted an empty base. Every other provider builds its
    # URLs by joining onto this, and an empty base would make that join
    # meaningless rather than merely unvalidated.
    if kind == "direct":
        if base_url and not base_url.startswith("https://"):
            raise ManifestError("manifest.provider.baseUrl must be https when set")
    else:
        if not base_url:
            raise ManifestError(
                f"manifest.provider.baseUrl is required for provider type {kind!r}"
            )
        if not base_url.startswith("https://"):
            raise ManifestError("manifest.provider.baseUrl must be https")
    options = raw.get("options") or {}
    if not isinstance(options, dict):
        raise ManifestError("manifest.provider.options must be an object")
    return ProviderSpec(type=kind, base_url=base_url, options=dict(options))


def _parse_auth(raw: object) -> AuthSpec:
    if raw is None:
        return AuthSpec()
    if not isinstance(raw, dict):
        raise ManifestError("manifest.auth must be an object")
    mode = str(raw.get("mode") or "public").strip().lower()
    if mode not in AUTH_MODES:
        raise ManifestError(f"manifest.auth.mode must be one of {sorted(AUTH_MODES)}")
    scheme = str(raw.get("scheme") or "header").strip().lower()
    if scheme not in AUTH_SCHEMES:
        raise ManifestError(
            f"manifest.auth.scheme must be one of {sorted(AUTH_SCHEMES)} "
            "(v1 is header-only so no secret can enter a URL)"
        )
    secret_id = raw.get("secretId")
    if secret_id is not None:
        secret_id = _require_str(secret_id, "auth.secretId")
        if not _SECRET_ID_RE.match(secret_id):
            raise ManifestError(f"manifest.auth.secretId is not a valid slot: {secret_id!r}")
        if secret_id not in KNOWN_SECRET_SLOTS:
            raise ManifestError(
                f"manifest.auth.secretId names an unknown credential slot "
                f"{secret_id!r}; this deployment holds {sorted(KNOWN_SECRET_SLOTS)}. "
                "Adding one is a column on the user row, a migration, and an "
                "entry in datalakes/infrastructure/credentials.py."
            )
    if mode != "public" and not secret_id:
        raise ManifestError(f"manifest.auth.secretId is required when mode is {mode!r}")
    header_name = raw.get("headerName")
    if header_name is not None:
        header_name = _require_str(header_name, "auth.headerName")
    if mode != "public" and not header_name:
        raise ManifestError("manifest.auth.headerName is required when a token is used")
    help_url = raw.get("helpUrl")
    if help_url is not None:
        help_url = _require_str(help_url, "auth.helpUrl")
    return AuthSpec(
        mode=mode,
        secret_id=secret_id,
        scheme=scheme,
        header_name=header_name,
        help_url=help_url,
    )


def _parse_capabilities(raw: object) -> CapabilitySpec:
    if raw is None:
        return CapabilitySpec()
    if not isinstance(raw, dict):
        raise ManifestError("manifest.capabilities must be an object")
    formats_raw = raw.get("formats")
    if formats_raw is None:
        formats = tuple(LAKE_ACQUIRABLE_FORMATS)
    else:
        if not isinstance(formats_raw, list):
            raise ManifestError("manifest.capabilities.formats must be an array")
        formats = tuple(str(f).strip().lower() for f in formats_raw)
        unknown = [f for f in formats if f not in LAKE_ACQUIRABLE_FORMATS]
        if unknown:
            raise ManifestError(
                f"manifest.capabilities.formats has unacquirable entries {unknown}; "
                f"allowed: {sorted(LAKE_ACQUIRABLE_FORMATS)}"
            )
    max_bytes = raw.get("maxDownloadBytes", DEFAULT_MAX_DOWNLOAD_BYTES)
    try:
        max_bytes = int(max_bytes)
    except (TypeError, ValueError) as exc:
        raise ManifestError("manifest.capabilities.maxDownloadBytes must be an integer") from exc
    if max_bytes <= 0:
        raise ManifestError("manifest.capabilities.maxDownloadBytes must be positive")
    # A manifest may lower the ceiling, never raise it: the hard bound is the
    # server's to set, and an operator editing a JSON file should not be able
    # to talk the server into a 10 GB download.
    max_bytes = min(max_bytes, DEFAULT_MAX_DOWNLOAD_BYTES)
    return CapabilitySpec(
        search=_bool(raw.get("search"), True, "capabilities.search"),
        describe=_bool(raw.get("describe"), True, "capabilities.describe"),
        download=_bool(raw.get("download"), True, "capabilities.download"),
        formats=formats,
        max_download_bytes=max_bytes,
        allow_off_base_distributions=_bool(
            raw.get("allowOffBaseDistributions"),
            False,
            "capabilities.allowOffBaseDistributions",
        ),
    )


def _parse_icon(raw: object) -> str | None:
    """Validate the icon filename. A single ``.png`` component, never a path.

    Operator-authored, but still a path, and it is the one value in this
    feature whose bytes get rendered rather than parsed. PNG-only rather than
    allowing SVG: an SVG served from the app's own origin can carry script.
    """
    if raw is None:
        return None
    name = _require_str(raw, "icon")
    if not _ICON_RE.match(name):
        raise ManifestError(
            f"manifest.icon must be a single .png filename, got {name!r}"
        )
    return name


def _parse_manifest(raw: dict[str, Any], *, where: str) -> LakeSourceManifest:
    source_id = _require_str(raw.get("id"), "id")

    compatibility = raw.get("compatibility") or {}
    if not isinstance(compatibility, dict):
        raise ManifestError(f"{where}.compatibility must be an object")
    major_raw = compatibility.get("major", 1)
    try:
        major = int(major_raw)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{where}.compatibility.major must be an integer") from exc

    try:
        SourceId.parse_dir(f"{source_id}@{major}")
    except Exception as exc:
        raise ManifestError(f"{where}.id is not a valid source id: {source_id!r}") from exc

    tags_raw = raw.get("tags") or []
    if not isinstance(tags_raw, list):
        raise ManifestError(f"{where}.tags must be an array")

    limits = raw.get("limits") or {}
    if not isinstance(limits, dict):
        raise ManifestError(f"{where}.limits must be an object")
    rpm = limits.get("requestsPerMinute", DEFAULT_REQUESTS_PER_MINUTE)
    try:
        rpm = int(rpm)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{where}.limits.requestsPerMinute must be an integer") from exc
    if rpm <= 0:
        raise ManifestError(f"{where}.limits.requestsPerMinute must be positive")

    homepage = raw.get("homepage")
    if homepage is not None:
        homepage = _require_str(homepage, "homepage")

    return LakeSourceManifest(
        id=source_id,
        name=_require_str(raw.get("name"), "name"),
        version=_require_str(raw.get("version"), "version"),
        major=major,
        provider=_parse_provider(raw.get("provider")),
        auth=_parse_auth(raw.get("auth")),
        capabilities=_parse_capabilities(raw.get("capabilities")),
        description=str(raw.get("description") or ""),
        publisher=str(raw.get("publisher") or ""),
        homepage=homepage,
        license=str(raw.get("license") or ""),
        tags=tuple(str(tag) for tag in tags_raw),
        icon=_parse_icon(raw.get("icon")),
        requests_per_minute=rpm,
        created_at=str(raw.get("createdAt") or "") or None,
        updated_at=str(raw.get("updatedAt") or "") or None,
    )


def build_manifest_dict(manifest: LakeSourceManifest) -> dict[str, Any]:
    """Serialise to a complete JSON-ready dict; every known key is present."""
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "compatibility": {"major": manifest.major},
        "description": manifest.description or "",
        "publisher": manifest.publisher or "",
        "homepage": manifest.homepage or None,
        "license": manifest.license or "",
        "tags": list(manifest.tags),
        "icon": manifest.icon or None,
        "provider": {
            "type": manifest.provider.type,
            "baseUrl": manifest.provider.base_url,
            "options": dict(manifest.provider.options),
        },
        "auth": {
            "mode": manifest.auth.mode,
            "secretId": manifest.auth.secret_id or None,
            "scheme": manifest.auth.scheme,
            "headerName": manifest.auth.header_name or None,
            "helpUrl": manifest.auth.help_url or None,
        },
        "capabilities": {
            "search": manifest.capabilities.search,
            "describe": manifest.capabilities.describe,
            "download": manifest.capabilities.download,
            "formats": list(manifest.capabilities.formats),
            "maxDownloadBytes": manifest.capabilities.max_download_bytes,
            "allowOffBaseDistributions": manifest.capabilities.allow_off_base_distributions,
        },
        "limits": {"requestsPerMinute": manifest.requests_per_minute},
        "createdAt": manifest.created_at or None,
        "updatedAt": manifest.updated_at or None,
    }


def load_source_manifest(source_root: Path) -> LakeSourceManifest:
    """Read and validate, enforcing that the directory name matches the id."""
    manifest = load_source_manifest_from_dir(source_root)
    expected = manifest.dir_name
    if source_root.name != expected:
        raise ManifestError(
            f"directory name {source_root.name!r} does not match manifest id {expected!r}"
        )
    return manifest


def load_source_manifest_from_dir(source_root: Path) -> LakeSourceManifest:
    """Read and validate without the directory-name check."""
    manifest_path = source_root / "manifest.json"
    if not manifest_path.is_file():
        raise ManifestError(f"missing manifest.json in {source_root}")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"manifest.json is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise ManifestError("manifest.json must be a JSON object")
    return _parse_manifest(raw, where="manifest.json")
