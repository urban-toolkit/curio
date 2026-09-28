"""The data lake source manifest: reader, validator and serialiser.

A source manifest describes a *portal* or a *storage* location, not a dataset.
It says who publishes it, what software it runs, whether it needs a token, and
what it is allowed to hand us. A portal's datasets are discovered live. A
storage source (a folder, an S3 bucket, a Hugging Face repo) declares how its
files are organized in ``resources``, the way a portal manifest declares its
endpoints: each resource is a path template whose captures become columns.

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
from utk_curio.backend.app.datalakes.domain.templates import (
    CAPTURE_NAME_RE,
    RESERVED_NAMES,
    TABLE_RESERVED_NAMES,
    Template,
    TemplateError,
    compile_template,
)

#: Portals: a query API whose datasets are discovered live.
PORTAL_PROVIDER_TYPES = ("socrata", "ckan", "arcgis", "wfs", "direct")

#: Storage: files listed and read in place, organized by ``resources``.
STORAGE_PROVIDER_TYPES = ("folder", "s3", "huggingface")

#: Provider implementations that exist. Kept here rather than imported from
#: ``providers`` so that reading a manifest never drags in a transport.
#: ``providers/__init__.py`` asserts the two agree.
PROVIDER_TYPES = PORTAL_PROVIDER_TYPES + STORAGE_PROVIDER_TYPES

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
KNOWN_SECRET_SLOTS = ("socrata.app-token", "huggingface.token")

#: The formats this catalog can hand to the Data Catalog's importer. A subset
#: of the Data Catalog's own SUPPORTED_FORMATS: multi-file and archive formats
#: (shp, bundle) are not acquirable remotely in v1 - a .shp is meaningless
#: without its sibling .dbf/.shx, and unpacking a remote archive is a
#: decompression-bomb surface that deserves its own design.
LAKE_ACQUIRABLE_FORMATS = ("csv", "geojson", "json", "parquet", "geotiff")

#: What a storage resource can be. ``table`` files are copied into the Data
#: Catalog as the other lakes' downloads are; every other kind becomes one
#: ``collection`` dataset, an index with one row per file, referenced in place.
RESOURCE_KINDS = ("table", "rasters", "frames", "images", "videos", "media", "audio")
COLLECTION_KINDS = tuple(kind for kind in RESOURCE_KINDS if kind != "table")

#: The file formats a ``table`` resource may name. gpkg, pbf and shp are
#: converted to Parquet layers on the way in, as an upload of one is.
TABLE_FORMATS = ("csv", "json", "geojson", "parquet", "gpkg", "shp", "pbf")

#: Formats a storage source can hand the Data Catalog.
STORAGE_FORMATS = TABLE_FORMATS + ("collection",)

_IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff")
_VIDEO_EXTENSIONS = ("mp4", "mov", "m4v", "webm", "mkv", "avi")
_AUDIO_EXTENSIONS = ("wav", "flac", "mp3", "ogg", "opus", "m4a", "aiff", "aif")

#: The files a resource's template sees when it names no ``extensions``.
DEFAULT_EXTENSIONS = {
    "rasters": ("tif", "tiff", "jp2"),
    "frames": _IMAGE_EXTENSIONS,
    "images": _IMAGE_EXTENSIONS,
    "videos": _VIDEO_EXTENSIONS,
    "media": _IMAGE_EXTENSIONS + _VIDEO_EXTENSIONS,
    "audio": _AUDIO_EXTENSIONS,
}
TABLE_EXTENSIONS = {
    "csv": ("csv",),
    "json": ("json",),
    "geojson": ("geojson", "json"),
    "parquet": ("parquet",),
    "gpkg": ("gpkg",),
    "shp": ("shp",),
    "pbf": ("pbf",),
}

#: How many files one source may hold. A manifest may lower it.
DEFAULT_MAX_FILES = 200_000
MAX_RESOURCES = 64

DEFAULT_ICON_FILE = "icon.png"
DEFAULT_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_REQUESTS_PER_MINUTE = 30

_SECRET_ID_RE = re.compile(r"^[a-z][a-z0-9-]*(\.[a-z][a-z0-9-]*){0,2}$")
_ICON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.png$")
_RESOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_VALUE_PREFIX_RE = re.compile(r"^[A-Za-z]{1,16} $")
_EXTENSION_RE = re.compile(r"^[a-z0-9]{1,8}$")
_HF_REPO_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,95}/[A-Za-z0-9][\w.-]{0,95}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][\w.-]{0,63}$")


class ManifestError(ValueError):
    """Raised when a source manifest is malformed."""


@dataclass(frozen=True)
class ProviderSpec:
    type: str
    base_url: str
    options: dict[str, Any] = field(default_factory=dict)
    #: A ``folder`` source's root, as written in the manifest. Resolved by
    #: ``infrastructure.storage.storage_root``, never served to a client.
    root: str | None = None

    @property
    def is_storage(self) -> bool:
        return self.type in STORAGE_PROVIDER_TYPES


@dataclass(frozen=True)
class AuthSpec:
    mode: str = "public"
    secret_id: str | None = None
    scheme: str = "header"
    header_name: str | None = None
    help_url: str | None = None
    #: Put before the token in the header's value, e.g. ``"Bearer "``.
    value_prefix: str | None = None

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
class ResourceSpec:
    """One declared resource of a storage source."""

    id: str
    name: str
    kind: str
    path: str
    template: Template
    description: str = ""
    #: ``one``, ``per-file``, or ``per:<field>[,<field>]``.
    datasets: str = "one"
    split_by: tuple[str, ...] = ()
    #: ``table`` resources only.
    format: str | None = None
    extensions: tuple[str, ...] = ()
    options: dict[str, Any] = field(default_factory=dict)
    #: ``frames``: frames per second, so ``t_s`` can be filled in.
    fps: float | None = None
    #: The capture holding each file's timestamp.
    time: str | None = None
    #: A table joined onto a collection's rows: ``{"path", "on"}``.
    metadata: dict[str, str] | None = None

    @property
    def is_collection(self) -> bool:
        return self.kind != "table"

    @property
    def dataset_format(self) -> str:
        return "collection" if self.is_collection else str(self.format)


@dataclass(frozen=True)
class LakeSourceManifest:
    id: str
    name: str
    version: str
    major: int
    provider: ProviderSpec
    auth: AuthSpec
    capabilities: CapabilitySpec
    resources: tuple[ResourceSpec, ...] = ()
    max_files: int = DEFAULT_MAX_FILES
    #: Which root the manifest was read from: ``shipped`` or ``instance``. Set
    #: by the roster, never read from the file.
    origin: str = "shipped"
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

    @property
    def is_storage(self) -> bool:
        return self.provider.is_storage

    def resource(self, resource_id: str) -> ResourceSpec | None:
        for spec in self.resources:
            if spec.id == resource_id:
                return spec
        return None


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
    options = raw.get("options") or {}
    if not isinstance(options, dict):
        raise ManifestError("manifest.provider.options must be an object")
    root = raw.get("root")
    # ``direct`` has no portal of its own - a resource id IS a URL - so it is
    # the one portal type permitted an empty base. Every other provider builds
    # its URLs by joining onto this, and an empty base would make that join
    # meaningless rather than merely unvalidated. A ``folder`` has a root on
    # disk in place of a base URL.
    if kind == "folder":
        if base_url:
            raise ManifestError("manifest.provider.baseUrl does not apply to a folder; set root")
        root = _parse_root(root)
    else:
        if root is not None:
            raise ManifestError(f"manifest.provider.root only applies to a folder, not {kind!r}")
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
    if kind == "s3":
        prefix = options.get("prefix", "")
        if not isinstance(prefix, str) or prefix.startswith("/") or ".." in prefix.split("/"):
            raise ManifestError("manifest.provider.options.prefix must be a relative key prefix")
    if kind == "huggingface":
        repo = options.get("repo")
        if not isinstance(repo, str) or not _HF_REPO_RE.match(repo):
            raise ManifestError("manifest.provider.options.repo must name a repo as owner/name")
        revision = options.get("revision", "main")
        if not isinstance(revision, str) or not _REVISION_RE.match(revision):
            raise ManifestError("manifest.provider.options.revision is not a valid revision")
    return ProviderSpec(type=kind, base_url=base_url, options=dict(options), root=root)


def _parse_root(raw: object) -> str:
    """A folder root: an absolute path, or one relative to the shipped catalog.

    Which of the two a manifest may use depends on where it was found, and is
    decided when it is resolved (``infrastructure.storage.storage_root``). Here
    only the shape is checked: no ``..``, no NUL, not empty.
    """
    root = _require_str(raw, "provider.root")
    if "\x00" in root:
        raise ManifestError("manifest.provider.root is not a path")
    parts = root.replace("\\", "/").split("/")
    if ".." in parts:
        raise ManifestError("manifest.provider.root must not contain '..'")
    return root


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
    value_prefix = raw.get("valuePrefix")
    if value_prefix is not None:
        if not isinstance(value_prefix, str) or not _VALUE_PREFIX_RE.match(value_prefix):
            raise ManifestError("manifest.auth.valuePrefix must be a word and a space, e.g. 'Bearer '")
    return AuthSpec(
        mode=mode,
        secret_id=secret_id,
        scheme=scheme,
        header_name=header_name,
        help_url=help_url,
        value_prefix=value_prefix,
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


def _parse_resources(raw: object, *, provider: ProviderSpec) -> tuple[ResourceSpec, ...]:
    """The ``resources`` block: required for storage, refused for a portal."""
    if not provider.is_storage:
        if raw not in (None, []):
            raise ManifestError(
                f"manifest.resources only applies to a storage source; "
                f"a {provider.type} portal's datasets are discovered live"
            )
        return ()
    if not isinstance(raw, list) or not raw:
        raise ManifestError(
            "manifest.resources must list at least one resource: a storage source "
            "declares how its files are organized"
        )
    if len(raw) > MAX_RESOURCES:
        raise ManifestError(f"manifest.resources is limited to {MAX_RESOURCES} entries")
    seen: set[str] = set()
    out = []
    for index, entry in enumerate(raw):
        where = f"resources[{index}]"
        spec = _parse_resource(entry, where=where)
        if spec.id in seen:
            raise ManifestError(f"manifest.{where}.id {spec.id!r} is used twice")
        seen.add(spec.id)
        out.append(spec)
    return tuple(out)


def _parse_resource(raw: object, *, where: str) -> ResourceSpec:
    if not isinstance(raw, dict):
        raise ManifestError(f"manifest.{where} must be an object")
    resource_id = _require_str(raw.get("id"), f"{where}.id")
    if not _RESOURCE_ID_RE.match(resource_id):
        raise ManifestError(
            f"manifest.{where}.id must be lowercase letters, digits and dashes, got {resource_id!r}"
        )
    kind = _require_str(raw.get("kind"), f"{where}.kind").lower()
    if kind not in RESOURCE_KINDS:
        raise ManifestError(f"manifest.{where}.kind must be one of {sorted(RESOURCE_KINDS)}")
    path = _require_str(raw.get("path"), f"{where}.path")
    try:
        template = compile_template(
            path, reserved=TABLE_RESERVED_NAMES if kind == "table" else RESERVED_NAMES
        )
    except TemplateError as exc:
        raise ManifestError(f"manifest.{where}.path: {exc}") from exc
    names = set(template.names)

    fmt = raw.get("format")
    if kind == "table":
        fmt = _require_str(fmt, f"{where}.format").lower()
        if fmt not in TABLE_FORMATS:
            raise ManifestError(f"manifest.{where}.format must be one of {sorted(TABLE_FORMATS)}")
    elif fmt is not None:
        raise ManifestError(f"manifest.{where}.format only applies to a table resource")

    extensions_raw = raw.get("extensions")
    if extensions_raw is None:
        extensions = TABLE_EXTENSIONS[fmt] if kind == "table" else DEFAULT_EXTENSIONS[kind]
    else:
        if not isinstance(extensions_raw, list) or not extensions_raw:
            raise ManifestError(f"manifest.{where}.extensions must be a non-empty array")
        extensions = tuple(str(e).strip().lower().lstrip(".") for e in extensions_raw)
        bad = [e for e in extensions if not _EXTENSION_RE.match(e)]
        if bad:
            raise ManifestError(f"manifest.{where}.extensions has invalid entries {bad}")

    datasets = str(raw.get("datasets") or "one").strip()
    split_by: tuple[str, ...] = ()
    if datasets.startswith("per:"):
        split_by = tuple(part.strip() for part in datasets[4:].split(",") if part.strip())
        if not split_by:
            raise ManifestError(f"manifest.{where}.datasets 'per:' needs a field name")
        missing = [name for name in split_by if name not in names]
        if missing:
            raise ManifestError(
                f"manifest.{where}.datasets splits on {missing}, which {path!r} does not capture"
            )
        datasets = "per:" + ",".join(split_by)
    elif datasets == "per-file":
        if kind not in ("table", "rasters"):
            raise ManifestError(
                f"manifest.{where}.datasets 'per-file' applies to tables and rasters; "
                f"a single {kind} file is a row of a collection, not a dataset"
            )
    elif datasets != "one":
        raise ManifestError(
            f"manifest.{where}.datasets must be 'one', 'per-file' or 'per:<field>'"
        )

    if kind == "frames":
        frame_capture = next((c for c in template.captures if c.name == "frame"), None)
        if frame_capture is not None and frame_capture.type != "int":
            raise ManifestError(f"manifest.{where}.path captures frame as a number: {{frame:int}}")

    fps = raw.get("fps")
    if fps is not None:
        if kind != "frames":
            raise ManifestError(f"manifest.{where}.fps only applies to a frames resource")
        if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 0 < fps <= 1000:
            raise ManifestError(f"manifest.{where}.fps must be a number between 0 and 1000")
        fps = float(fps)

    time_field = raw.get("time")
    if time_field is not None:
        if kind == "table":
            raise ManifestError(f"manifest.{where}.time only applies to a collection")
        time_field = _require_str(time_field, f"{where}.time")
        capture = next((c for c in template.captures if c.name == time_field), None)
        if capture is None or capture.type not in ("date", "datetime"):
            raise ManifestError(
                f"manifest.{where}.time must name a date or strftime capture of {path!r}"
            )

    metadata = raw.get("metadata")
    if metadata is not None:
        if kind == "table":
            raise ManifestError(f"manifest.{where}.metadata only applies to a collection")
        if not isinstance(metadata, dict):
            raise ManifestError(f"manifest.{where}.metadata must be an object")
        meta_path = _require_str(metadata.get("path"), f"{where}.metadata.path")
        try:
            compile_template(meta_path, reserved=frozenset())
        except TemplateError as exc:
            raise ManifestError(f"manifest.{where}.metadata.path: {exc}") from exc
        on = str(metadata.get("on") or "file_name").strip()
        if on not in ("file_name", "frame") and on not in names:
            raise ManifestError(
                f"manifest.{where}.metadata.on must be file_name, frame or a capture of {path!r}"
            )
        if not CAPTURE_NAME_RE.match(on):
            raise ManifestError(f"manifest.{where}.metadata.on is not a column name")
        metadata = {"path": meta_path, "on": on}

    options = raw.get("options") or {}
    if not isinstance(options, dict):
        raise ManifestError(f"manifest.{where}.options must be an object")

    return ResourceSpec(
        id=resource_id,
        name=_require_str(raw.get("name"), f"{where}.name"),
        kind=kind,
        path=path,
        template=template,
        description=str(raw.get("description") or ""),
        datasets=datasets,
        split_by=split_by,
        format=fmt,
        extensions=extensions,
        options=dict(options),
        fps=fps,
        time=time_field,
        metadata=metadata,
    )


def _storage_capabilities(raw: object, resources: tuple[ResourceSpec, ...]) -> CapabilitySpec:
    """A storage source's capabilities follow from what it declares.

    Its formats are the formats of its resources, so a manifest does not list
    them a second time. Search filters the declared resources and needs no
    network, and every declared resource can be added.
    """
    if raw is not None and not isinstance(raw, dict):
        raise ManifestError("manifest.capabilities must be an object")
    raw = raw or {}
    if "formats" in raw:
        raise ManifestError(
            "manifest.capabilities.formats is derived from resources for a storage source"
        )
    base = _parse_capabilities({k: v for k, v in raw.items() if k != "formats"})
    formats = tuple(dict.fromkeys(spec.dataset_format for spec in resources))
    return CapabilitySpec(
        search=base.search,
        describe=base.describe,
        download=base.download,
        formats=formats,
        max_download_bytes=base.max_download_bytes,
        allow_off_base_distributions=False,
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

    max_files = limits.get("maxFiles", DEFAULT_MAX_FILES)
    try:
        max_files = int(max_files)
    except (TypeError, ValueError) as exc:
        raise ManifestError(f"{where}.limits.maxFiles must be an integer") from exc
    if max_files <= 0:
        raise ManifestError(f"{where}.limits.maxFiles must be positive")
    # Lowered, never raised: the ceiling is the server's.
    max_files = min(max_files, DEFAULT_MAX_FILES)

    homepage = raw.get("homepage")
    if homepage is not None:
        homepage = _require_str(homepage, "homepage")

    provider = _parse_provider(raw.get("provider"))
    resources = _parse_resources(raw.get("resources"), provider=provider)
    if provider.is_storage:
        capabilities = _storage_capabilities(raw.get("capabilities"), resources)
    else:
        capabilities = _parse_capabilities(raw.get("capabilities"))

    return LakeSourceManifest(
        id=source_id,
        name=_require_str(raw.get("name"), "name"),
        version=_require_str(raw.get("version"), "version"),
        major=major,
        provider=provider,
        auth=_parse_auth(raw.get("auth")),
        capabilities=capabilities,
        resources=resources,
        max_files=max_files,
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
            **({"root": manifest.provider.root} if manifest.provider.root else {}),
        },
        "auth": {
            "mode": manifest.auth.mode,
            "secretId": manifest.auth.secret_id or None,
            "scheme": manifest.auth.scheme,
            "headerName": manifest.auth.header_name or None,
            "helpUrl": manifest.auth.help_url or None,
            "valuePrefix": manifest.auth.value_prefix or None,
        },
        "resources": [_resource_dict(spec) for spec in manifest.resources],
        "capabilities": {
            "search": manifest.capabilities.search,
            "describe": manifest.capabilities.describe,
            "download": manifest.capabilities.download,
            # A storage source's formats follow from its resources.
            **({} if manifest.is_storage else {"formats": list(manifest.capabilities.formats)}),
            "maxDownloadBytes": manifest.capabilities.max_download_bytes,
            "allowOffBaseDistributions": manifest.capabilities.allow_off_base_distributions,
        },
        "limits": {
            "requestsPerMinute": manifest.requests_per_minute,
            "maxFiles": manifest.max_files,
        },
        "createdAt": manifest.created_at or None,
        "updatedAt": manifest.updated_at or None,
    }


def _resource_dict(spec: ResourceSpec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": spec.id,
        "name": spec.name,
        "description": spec.description,
        "kind": spec.kind,
        "path": spec.path,
        "datasets": spec.datasets,
        "extensions": list(spec.extensions),
    }
    if spec.format:
        out["format"] = spec.format
    if spec.options:
        out["options"] = dict(spec.options)
    if spec.fps is not None:
        out["fps"] = spec.fps
    if spec.time:
        out["time"] = spec.time
    if spec.metadata:
        out["metadata"] = dict(spec.metadata)
    return out


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
