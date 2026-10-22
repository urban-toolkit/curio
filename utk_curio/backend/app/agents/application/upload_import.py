"""Upload-import of user-authored definitions (memo dev/36).

Application layer of the agents package (memo dev/142, B2; re-derived on enh/agent-catalog): cut from
``services.py`` by responsibility; every function keeps its name and body. Sibling modules are reached
module-qualified (``agents_<module>.name``) so a test that patches the owner is seen by every caller,
and import order between siblings cannot matter.
"""

from __future__ import annotations

import hashlib

from utk_curio.backend.app.agents.application.errors import AgentServiceError
from utk_curio.backend.app.agents.repositories import imports
from utk_curio.backend.app.agents.repositories import publications
from utk_curio.backend.app.agents.repositories import storage
from utk_curio.backend.app.agents.application import catalog as agents_catalog
from utk_curio.backend.app.agents.domain import manifest as agents_manifest


# ── upload-import (user-authored definitions, memo dev/36) ───────────────────
_UPLOAD_MAX_FILES = 16


_UPLOAD_MAX_FILE_BYTES = 256 * 1024


_UPLOAD_MAX_TOTAL_BYTES = 1024 * 1024


def upload_import(user_key: str, manifest_raw: object, prompt_files: object) -> dict:
    """Create a user-owned definition from an uploaded manifest + prompt texts.

    Fail-closed rules (memo dev/36): the manifest must pass the package
    contract; ``provenance.trust`` is forced to ``"imported"`` server-side;
    ``catalog``, which only the agents Curio ships set, is refused;
    prompt digests are computed from the uploaded bytes (client digests are
    ignored); the provided files must correspond exactly to the manifest's
    referenced prompt paths, except a page of Curio's agent text
    (``curio:<path>``), which has no file and no digest; a manifest of kind
    ``base`` is no agent and is refused; size limits apply. The coordinate is
    ``<id>@<major>``: a newer version of a major the store holds replaces it,
    as a node package's Update does, while the same or an older version is a
    409 (a version is immutable), and so is a store copy of an agent Curio
    ships; the write is atomic. Success registers the coordinate in My Imports
    (upload IS an explicit account import) and returns the My Imports card,
    publishable.
    """

    from utk_curio.backend.app.common.safe_paths import PathTraversalError

    if not isinstance(manifest_raw, dict):
        raise AgentServiceError("'manifest' must be an object", 400)
    if not isinstance(prompt_files, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in prompt_files.items()
    ):
        raise AgentServiceError("'prompts' must map file paths to text", 400)
    if len(prompt_files) > _UPLOAD_MAX_FILES:
        raise AgentServiceError(f"at most {_UPLOAD_MAX_FILES} prompt files", 413)
    total = 0
    for rel, text in prompt_files.items():
        size = len(text.encode("utf-8"))
        total += size
        if size > _UPLOAD_MAX_FILE_BYTES:
            raise AgentServiceError(f"prompt file {rel!r} exceeds 256 KB", 413)
    if total > _UPLOAD_MAX_TOTAL_BYTES:
        raise AgentServiceError("prompt files exceed 1 MB total", 413)

    manifest = dict(manifest_raw)
    if "catalog" in manifest:
        # Where an agent stands in the catalog (a card or a helper) is set by
        # the agents Curio ships; a helper's LLM routes through its caller's.
        raise AgentServiceError(
            "manifest.catalog is set only by the agents Curio ships; remove it to upload", 400
        )
    prov = manifest.get("provenance")
    if not isinstance(prov, dict):
        raise AgentServiceError("manifest.provenance must be an object", 400)
    # Forced provenance: an upload can never claim built-in/global trust —
    # that would corrupt publish gating and roster-first resolution.
    manifest["provenance"] = {**prov, "trust": "imported"}

    # Digests from bytes: stamp each referenced prompt's sha256 from the
    # uploaded text, and require exact file<->manifest correspondence.
    prompts_sect = manifest.get("prompts") or {}
    if not isinstance(prompts_sect, dict):
        raise AgentServiceError("manifest.prompts must be an object", 400)
    referenced: set[str] = set()
    stamped = {}
    for name, asset in prompts_sect.items():
        if not isinstance(asset, dict) or not isinstance(asset.get("path"), str):
            raise AgentServiceError(f"manifest.prompts.{name} must declare a path", 400)
        rel = asset["path"]
        if rel.startswith(agents_manifest.SHARED_PROMPT_PREFIX):
            # Curio's own prompt, read where Curio keeps it: no file, no digest.
            stamped[name] = {key: value for key, value in asset.items() if key != "sha256"}
            continue
        if rel not in prompt_files:
            raise AgentServiceError(f"prompt file {rel!r} referenced by the manifest is missing", 400)
        referenced.add(rel)
        stamped[name] = {
            **asset,
            "sha256": hashlib.sha256(prompt_files[rel].encode("utf-8")).hexdigest(),
        }
    if stamped:
        manifest["prompts"] = stamped
    extra = set(prompt_files) - referenced
    if extra:
        raise AgentServiceError(
            f"prompt files not referenced by the manifest: {sorted(extra)}", 400
        )

    try:
        m = agents_manifest.parse_agent_manifest(manifest, where="upload")
    except agents_manifest.AgentManifestError as exc:
        raise AgentServiceError(str(exc), 400) from exc

    coord = m.dir_name
    existing = storage.load_installed_agent_definition(user_key, coord)
    if existing is not None:
        if existing.provenance.trust == "built-in":
            raise AgentServiceError(f"{coord!r} is an agent Curio ships; give yours an id of its own", 409)
        if agents_manifest.version_order(m.version) <= agents_manifest.version_order(existing.version):
            raise AgentServiceError(
                f"{coord!r} holds version {existing.version} in your store, and a version is "
                f"immutable: upload a version of major {m.major} newer than {existing.version} to replace it",
                409,
            )
    try:
        storage.write_definition_atomic(
            user_key, coord, manifest, prompt_files, replace=existing is not None,
        )
    except FileExistsError as exc:
        raise AgentServiceError(
            f"{coord!r} was written by another upload at the same time; upload it again",
            409,
        ) from exc
    except PathTraversalError as exc:
        raise AgentServiceError(str(exc), 400) from exc

    imports.add_imported_agent(user_key, coord)
    return agents_catalog._manifest_to_card(
        m,
        scope="imports",
        imported=True,
        installed_in_project=False,
        published=publications.is_published(coord),
        publishable=True,
        requires_agents=agents_catalog._requires_agents_rows(user_key, m, set()),
    )
