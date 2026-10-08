"""OpenStreetMap through Autark: autk-db's own ``loadOsm``, in a Node child.

Curio writes no Overpass client. ``autark_osm.mjs`` calls the loader an Autark
map node runs, with the same autk-db build (the repo-root ``node_modules``, as
the sandbox's JS nodes use), so a download and a map get the same features.
Its requests go to autk-db's fixed Overpass endpoint, with the retries, slot
waits and tiling autk-db does; no value a person types becomes a URL.

The child runs from the backend's process tree, not in the sandbox, so it has
the network under ``--deploy`` as every Discovery download does. Two ceilings
bound it, each refused with a message that names it: how long it may run, and
how much GeoJSON it may write. Before it starts, named areas are held to the
area's ``maxAreaKm2`` as a box is: their box comes from the place search.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from utk_curio.backend.app.discovery.domain import parameters as P
from utk_curio.backend.app.discovery.domain.errors import DiscoveryError, ProviderError
from utk_curio.backend.app.discovery.domain.manifest import (
    DiscoverySourceManifest,
    ResourceSpec,
)
from utk_curio.backend.app.discovery.domain.resource import DiscoveryResource

PARAMETER_IDS = ("area", "tags")

#: A tag resource asks autk-db for one tag set per geometry, ``tags_<geometry>``,
#: each with the same tags; the layers come back as these geometries, one group.
TAG_SET = "tags"
TAG_GEOMETRIES = ("points", "polylines", "polygons")

SCRIPT = Path(__file__).with_suffix(".mjs")

#: How long one download may take, Overpass waits and retries included.
MAX_SECONDS = 15 * 60

#: How much GeoJSON one download may write, all layers together.
MAX_OUTPUT_BYTES = 512 * 1024 * 1024

_STAGE = "__CURIO_OSM_STAGE__ "
_RESULT = "__CURIO_OSM_RESULT__ "

#: autk-db's progress phases, as a person reads them.
STAGE_MESSAGES = {
    "querying-osm-server": "Asking OpenStreetMap…",
    "downloading-osm-data": "Downloading from OpenStreetMap…",
    "processing-osm-data": "Building the layers…",
    "processing-boundaries": "Building the area's boundary…",
}


class Cancelled(Exception):
    """The person stopped the download; the Node child was killed."""


@dataclass(frozen=True)
class LoadedLayer:
    layer: str
    path: Path
    features: int


class AutarkOsmService:
    """The ``autark-osm`` provider: declared resources in, GeoJSON layers out."""

    type = "autark-osm"

    def __init__(self, manifest: DiscoverySourceManifest, *, fixtures: Path | None = None,
                 transport=None) -> None:
        self.manifest = manifest
        #: Recorded Overpass answers (tests only, behind the transport's gate).
        self.fixtures = fixtures
        #: For the place search that measures named areas; the process's own when None.
        self.transport = transport

    def rows(self) -> tuple[DiscoveryResource, ...]:
        """One row per declared resource. Nothing to scan, nothing to fetch."""
        return tuple(self.row(spec) for spec in self.manifest.resources)

    def row(self, spec: ResourceSpec) -> DiscoveryResource:
        return DiscoveryResource(
            source_id=self.manifest.id,
            resource_id=spec.id,
            name=spec.name,
            description=spec.description,
            publisher=self.manifest.publisher,
            formats=(spec.dataset_format,),
            kind=spec.kind,
        )

    def load(
        self,
        spec: ResourceSpec,
        values: dict[str, Any],
        out_dir: Path,
        *,
        stage: Callable[[str], None] | None = None,
        cancelled: Callable[[], bool] | None = None,
        node: str = "node",
    ) -> list[LoadedLayer]:
        """Run autk-db's ``loadOsm`` for *spec*'s layers, or its tags, over the area in *values*."""
        from utk_curio.sandbox.util.node_runtime import (
            OVERPASS_USER_AGENT,
            ROOT_NODE_MODULES,
            node_env,
            resolve_pkg_entry_url,
        )

        area = values.get("area") or {}
        if "names" in area:
            query_area: dict[str, Any] = {
                "geocodeArea": area["names"]["geocodeArea"],
                "areas": list(area["names"]["areas"]),
            }
        elif "box" in area:
            query_area = {"bbox": [float(v) for v in area["box"]]}
        else:
            raise DiscoveryError("OpenStreetMap needs an area: named areas inside a place, or a box")
        tags = spec.tag_entries(values)
        tag_sets: list[dict[str, Any]] = []
        if tags is not None:
            # Checked again here, whatever the manifest or the request said:
            # each entry becomes an Overpass selector inside autk-db.
            filters = []
            for entry in tags:
                key, value = P.parse_tag_entry(entry)
                filters.append({"key": key} if value is None else {"key": key, "value": value})
            if not filters:
                raise DiscoveryError("OpenStreetMap needs one or more tags, as key=value or key=*")
            tag_sets = [{"name": f"{TAG_SET}_{geometry}", "type": geometry, "tags": filters}
                        for geometry in TAG_GEOMETRIES]
        if "names" in area:
            self._check_named_areas_size(spec, area["names"])
        autk_db = resolve_pkg_entry_url("@urban-toolkit/autk-db", ROOT_NODE_MODULES)
        if autk_db is None:
            raise ProviderError(
                "autk-db is not installed at the repository root; run npm install there"
            )
        request = {
            "autkDbUrl": autk_db,
            "queryArea": query_area,
            "layers": list(spec.options.get("layers") or []),
            "tagSets": tag_sets,
            "outDir": str(out_dir),
            "userAgent": OVERPASS_USER_AGENT,
            "fixtures": str(self.fixtures) if self.fixtures else None,
        }
        try:
            proc = subprocess.Popen(
                [node, str(SCRIPT)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=str(out_dir),
                env=node_env(),
                # Its own process group, so a stop takes everything it started
                # with it, and no child keeps its pipes open after it.
                start_new_session=True,
            )
        except OSError as exc:
            raise ProviderError(f"Node.js could not be started: {exc}") from exc

        result: dict[str, Any] = {}
        stderr: list[str] = []

        def _read_stdout() -> None:
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line.startswith(_STAGE):
                    message = STAGE_MESSAGES.get(line[len(_STAGE):].strip())
                    if message and stage is not None:
                        stage(message)
                elif line.startswith(_RESULT):
                    try:
                        result.update(json.loads(line[len(_RESULT):]))
                    except ValueError:
                        pass

        def _read_stderr() -> None:
            for line in proc.stderr:
                stderr.append(line.rstrip("\n"))
                del stderr[:-40]

        readers = [threading.Thread(target=_read_stdout, daemon=True),
                   threading.Thread(target=_read_stderr, daemon=True)]
        for reader in readers:
            reader.start()
        try:
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
        except BrokenPipeError:
            pass

        started = time.monotonic()
        try:
            while proc.poll() is None:
                if cancelled is not None and cancelled():
                    raise Cancelled()
                if time.monotonic() - started > MAX_SECONDS:
                    raise DiscoveryError(
                        f"OpenStreetMap took longer than {MAX_SECONDS // 60} minutes for this "
                        "area and was stopped; choose a smaller area or fewer layers"
                    )
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                _kill_group(proc)
            for reader in readers:
                reader.join(timeout=5)

        if not result:
            tail = "\n".join(stderr[-5:]).strip()
            raise ProviderError(
                "the OpenStreetMap loader ended without an answer"
                + (f": {tail[:300]}" if tail else f" (exit {proc.returncode})")
            )
        if not result.get("ok"):
            # autk-db's own refusal, as it words it: a name with no boundary
            # in OSM says which name.
            raise DiscoveryError(str(result.get("error") or "the OpenStreetMap loader failed")[:500])

        layers = [
            LoadedLayer(layer=str(entry["layer"]), path=Path(entry["file"]), features=int(entry["features"]))
            for entry in result.get("layers") or []
        ]
        asked = TAG_GEOMETRIES if tags is not None else tuple(spec.options.get("layers") or ())
        unasked = sorted({layer.layer for layer in layers} - set(asked))
        if unasked:
            raise ProviderError(f"the OpenStreetMap loader returned layers it was not asked for: {', '.join(unasked)}")
        written = sum(layer.path.stat().st_size for layer in layers if layer.path.is_file())
        if written > MAX_OUTPUT_BYTES:
            raise DiscoveryError(
                f"these layers come to more than {MAX_OUTPUT_BYTES // (1024 * 1024)} MB of GeoJSON; "
                "choose a smaller area or fewer layers"
            )
        out = out_dir.resolve()
        for layer in layers:
            if out not in layer.path.resolve().parents:
                raise ProviderError("the OpenStreetMap loader wrote outside its folder")
        return layers

    def _check_named_areas_size(self, spec: ResourceSpec, names: dict[str, Any]) -> None:
        """Refuse named areas whose box is over the area's ``maxAreaKm2``, with
        the words a drawn box over it gets."""
        from utk_curio.backend.app.discovery.application import places
        from utk_curio.backend.app.discovery.infrastructure.transport import build_transport

        declared = next((p for p in self.manifest.declared_parameters(spec.id) if p.id == "area"), None)
        if declared is None or declared.max_area_km2 is None:
            return
        box = places.named_areas_box(self.transport or build_transport(), names)
        if box is not None:
            P.check_area_size(declared, box)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        proc.kill()
    proc.wait()


def fixtures_for(root: str | None) -> Path | None:
    """Where the recorded Overpass answers live under a fixture corpus."""
    return Path(root) / "overpass" if root else None
