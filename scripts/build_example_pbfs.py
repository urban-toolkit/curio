#!/usr/bin/env python3
"""Generate the pre-clipped OSM ``.pbf`` extracts used by the Autark examples.

WHY
---
The Autark examples (``docs/examples/06|07|08``) load OSM through the
``autk-grammar`` node's ``data`` block. Loading from a committed ``.pbf``
(``pbfFileUrl``) instead of the live Overpass API makes them deterministic and
offline — Overpass is heavily rate-limited (see the throttle workarounds in
``utk_curio/backend/tests/test_frontend/test_workflows.py``).

``autk-db``'s PBF loader (``loadOsmFromPbf`` → ``collectBoundaryContext``) clips
each layer to an **administrative boundary relation whose ``name`` tag equals the
``queryArea.areas`` entry** — so that boundary relation (and its member ways) MUST
be present in the PBF, or loading fails with "No administrative boundary found in
PBF". Each example therefore needs a PBF covering its area *and* carrying that
named boundary relation. This script builds those, once, at authoring time.

HOW
---
For each area we resolve a bounding box via Nominatim, then fetch a tag-filtered
Overpass extract containing only the OSM feature classes ``autk-db`` turns into
layers (roads=``highway``, buildings=``building``, parks=``leisure``/``landuse``/
``natural``, water=``natural``/``waterway``) — a superset of autk-db's own
queries, kept small by omitting unrelated POIs. pyosmium then converts the OSM
XML to ``.pbf``. ``buildings`` are only fetched for examples whose
``autoLoadLayers`` request them (08/Niterói does not), which keeps that extract
small.

This is AUTHORING-ONLY tooling. It is not imported at runtime and ``osmium``
(pyosmium) is not a Curio runtime dependency.

USAGE
-----
    conda run -n curio pip install osmium     # one-time
    conda run -n curio python scripts/build_example_pbfs.py
    # then commit the resulting docs/examples/data/*.osm.pbf

Requires network access to nominatim.openstreetmap.org and overpass-api.de.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

import requests

try:
    import osmium
except ImportError:
    sys.exit("pyosmium is required: conda run -n curio pip install osmium")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
# overpass-api.de sits behind a mod_security WAF that intermittently 406-rejects;
# fall through to mirrors on 406/429/5xx.
OVERPASS_ENDPOINTS = [
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
UA = {"User-Agent": "curio-example-pbf-builder/1.0 (https://github.com/urban-toolkit/curio)"}

OUT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "docs", "examples", "data")
)

# area key -> (Nominatim query, include_buildings, boundary_area_names).
# include_buildings mirrors each example's autoLoadLayers: 08/Niterói loads only
# surface/parks/water/roads, so skipping buildings there keeps the PBF small.
# boundary_area_names MUST match each example's grammar ``queryArea.areas`` exactly:
# autk-db's PBF clip looks for a relation whose ``name`` tag equals each entry, so
# that boundary relation has to be in the PBF.
AREAS = {
    "back_bay": ("Back Bay, Boston, Massachusetts, USA", True, ["Back Bay"]),       # ex 06
    "chicago_loop": ("Loop, Chicago, Illinois, USA", True, ["Loop"]),              # ex 07
    "niteroi": ("Niterói, Rio de Janeiro, Brazil", False, ["Niterói"]),            # ex 08
}


def bbox_for(query: str):
    """Return (south, west, north, east) for the first Nominatim match."""
    r = requests.get(
        NOMINATIM,
        params={"q": query, "format": "json", "limit": 1},
        headers=UA,
        timeout=60,
    )
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise SystemExit(f"Nominatim found nothing for {query!r}")
    s, n, w, e = (float(x) for x in hits[0]["boundingbox"])  # [S, N, W, E]
    return s, w, n, e


def overpass_query(bbox, include_buildings: bool, area_names: list[str]) -> str:
    s, w, n, e = bbox
    b = f"{s},{w},{n},{e}"
    # Use the combined node/way/relation selector ``nwr[...]``. NOTE: overpass-api.de
    # sits behind an Apache/mod_security WAF that 406-rejects requests containing the
    # ``way[`` / ``relation[`` keywords; ``nwr[`` is accepted (and is more correct
    # anyway, covering all three element types per tag).
    selectors = [
        "highway",    # roads
        "leisure",    # parks
        "landuse",    # parks / surface
        "natural",    # parks / water
        "waterway",   # water
    ]
    parts = [f"nwr[{k}]({b});" for k in selectors]
    if include_buildings:
        parts += [f"nwr[building]({b});", f'nwr["building:part"]({b});']
    # Boundary relations autk-db's PBF clip requires: a relation whose ``name`` tag
    # equals each ``queryArea.areas`` entry. Fetch every element named that within the
    # bbox (autk-db picks the relation); the ``(._;>;)`` recursion below then pulls the
    # relation's member ways and their nodes so the boundary geometry is complete.
    # Bbox-scoped (not area-scoped) to avoid geocodeArea ambiguity (e.g. the
    # "Rio de Janeiro" city vs. state areas both contain a relation, but only Niterói's
    # own bbox unambiguously yields the Niterói municipality relation).
    for nm in area_names:
        parts.append(f'nwr["name"="{nm}"]({b});')
    body = "\n  ".join(parts)
    # recurse down (>;) to pull in member nodes/ways so geometry is complete.
    return f"[out:xml][timeout:300];\n(\n  {body}\n);\n(._;>;);\nout body;"


def fetch_osm_xml(query: str) -> bytes:
    last = "no attempt"
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(3):
            try:
                r = requests.post(endpoint, data={"data": query}, headers=UA, timeout=600)
            except requests.RequestException as exc:
                last = f"{endpoint}: {exc}"
                time.sleep(3 * (attempt + 1))
                continue
            if r.status_code == 200 and r.content.lstrip().startswith(b"<?xml"):
                return r.content
            last = f"{endpoint}: HTTP {r.status_code} {r.text[:120]!r}"
            print(f"    retry ({last})", flush=True)
            time.sleep(5 * (attempt + 1))  # back off on 406/429/5xx
    raise SystemExit(f"All Overpass endpoints failed. Last: {last}")


def xml_to_pbf(xml_bytes: bytes, out_path: str) -> tuple[int, int, int]:
    """Convert OSM XML bytes to a .pbf at out_path. Returns (nodes, ways, rels)."""
    with tempfile.NamedTemporaryFile(suffix=".osm", delete=False) as tmp:
        tmp.write(xml_bytes)
        xml_path = tmp.name
    counts = [0, 0, 0]
    try:
        if os.path.exists(out_path):
            os.unlink(out_path)
        writer = osmium.SimpleWriter(out_path)
        try:
            for obj in osmium.FileProcessor(xml_path):
                if obj.is_node():
                    writer.add_node(obj); counts[0] += 1
                elif obj.is_way():
                    writer.add_way(obj); counts[1] += 1
                elif obj.is_relation():
                    writer.add_relation(obj); counts[2] += 1
        finally:
            writer.close()
    finally:
        os.unlink(xml_path)
    return tuple(counts)


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    for key, (query, include_buildings, area_names) in AREAS.items():
        out_path = os.path.join(OUT_DIR, f"{key}.osm.pbf")
        print(f"\n=== {key}  ({query})  buildings={include_buildings}  "
              f"boundaries={area_names} ===", flush=True)
        bbox = bbox_for(query)
        print(f"  bbox (S,W,N,E): {bbox}", flush=True)
        time.sleep(1)  # be polite to Nominatim/Overpass
        xml = fetch_osm_xml(overpass_query(bbox, include_buildings, area_names))
        print(f"  overpass XML bytes: {len(xml):,}", flush=True)
        n, w, r = xml_to_pbf(xml, out_path)
        size = os.path.getsize(out_path)
        print(f"  wrote {out_path}  ({size:,} bytes)  nodes={n:,} ways={w:,} rels={r:,}",
              flush=True)
        time.sleep(1)
    print("\nDone. Review sizes, then commit docs/examples/data/*.osm.pbf")


if __name__ == "__main__":
    main()
