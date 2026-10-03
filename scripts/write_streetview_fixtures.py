#!/usr/bin/env python
"""Write the Google Street View test fixtures, without a key.

WHY
    Curio is built and tested with no Google key: none is shared, and none
    belongs in a repository. So these answers are written, not recorded. They
    follow the shapes Google documents for the Street View metadata endpoint
    (https://developers.google.com/maps/documentation/streetview/metadata)
    and its image endpoint, and their panorama IDs and images are made up.

HOW
    The real provider is driven through a transport that answers each request
    from the scenario below, in the order the provider asks, and writes each
    answer to the corpus. So the corpus holds exactly the URLs the provider
    builds; a provider that changes a URL is re-written against the new one.

USAGE
    conda run -n curio python scripts/write_streetview_fixtures.py

    Idempotent: the same scenario writes the same corpus.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from utk_curio.backend.app.discovery.domain import parameters as P  # noqa: E402
from utk_curio.backend.app.discovery.domain.manifest import load_source_manifest  # noqa: E402
from utk_curio.backend.app.discovery.providers import build_service  # noqa: E402

FIXTURES = REPO / "utk_curio" / "backend" / "tests" / "test_discovery" / "fixtures"
FOLDER = "google-streetview"
SOURCE = "source.google.street-view@1"

LINCOLN_PARK = [-87.642, 41.918, -87.639, 41.92]
DENIED_BOX = [-87.632, 41.91, -87.631, 41.911]

#: What each metadata request is answered, in the order the provider asks.
#: ``ok:N`` is panorama N (a second ``ok:1`` finds the same panorama again).
SCENARIO = ["ok:1", "zero", "ok:2", "ok:1", "zero", "ok:3", "ok:4", "zero", "ok:5"]

#: Panorama 3 has no image to the south: Google answers its grey placeholder.
PLACEHOLDERS = {("3", "180")}

ASKS = {
    "lincoln-park": {"area": {"box": LINCOLN_PARK, "label": "Lincoln Park"}, "spacing": 60, "maxImages": 20},
    "denied": {"area": {"box": DENIED_BOX, "label": "Old Town"}, "spacing": 60, "maxImages": 4},
}


def _jpeg(noise: bool) -> bytes:
    """A synthetic image: noise (a real image's size) or flat grey (the
    placeholder's)."""
    import random

    from PIL import Image

    rng = random.Random(7)
    if noise:
        image = Image.new("RGB", (96, 96))
        image.putdata([(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(96 * 96)])
    else:
        image = Image.new("RGB", (64, 64), (228, 227, 223))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


class ScenarioTransport:
    def __init__(self, index: dict, answers: list[dict], name: str) -> None:
        self.index = index
        self.answers = answers
        self.name = name
        self.asked = 0

    def _write(self, name: str, data: bytes | str, url: str, content_type: str) -> None:
        path = FIXTURES / FOLDER / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
            size = len(data.encode("utf-8"))
        else:
            path.write_bytes(data)
            size = len(data)
        self.index[url] = {
            "file": f"{FOLDER}/{name}",
            "status": 200,
            "headers": {"Content-Type": content_type, "Content-Length": str(size)},
        }

    def json_get(self, url, *, credential=None, headers=None):
        assert "key=" not in url, "a fixture URL holds no key"
        answer = self.answers[self.asked % len(self.answers)]
        self.asked += 1
        name = f"metadata-{self.name}-{self.asked:02d}.json"
        body = json.dumps(answer, indent=2) + "\n"
        self._write(name, body, url, "application/json")
        return body

    def download(self, url, sink, *, max_bytes, credential=None, headers=None, progress=None, ceiling=None):
        from utk_curio.backend.app.agents.infrastructure import egress

        query = parse_qs(urlsplit(url).query)
        pano = query["pano"][0].removeprefix("CurioFixturePano")
        heading = query["heading"][0]
        placeholder = (pano.lstrip("0"), heading) in PLACEHOLDERS
        name = "placeholder.jpg" if placeholder else "image.jpg"
        blob = (FIXTURES / FOLDER / name).read_bytes()
        self.index[url] = {
            "file": f"{FOLDER}/{name}",
            "status": 200,
            "headers": {"Content-Type": "image/jpeg", "Content-Length": str(len(blob))},
        }
        sink(blob)
        return egress.DownloadResult(url=url, final_url=url, status=200, content_type="image/jpeg",
                                     bytes_written=len(blob), sha256="", headers={})


def _metadata(entry: str) -> dict:
    if entry == "zero":
        return {"status": "ZERO_RESULTS"}
    number = int(entry.split(":")[1])
    return {
        "copyright": "© Google",
        "date": f"2019-{number:02d}",
        "location": {"lat": round(41.9185 + number * 0.0002, 7), "lng": round(-87.6415 + number * 0.0004, 7)},
        "pano_id": f"CurioFixturePano{number:02d}",
        "status": "OK",
    }


def main() -> None:
    index_path = FIXTURES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    # This folder is written whole each time.
    index = {url: e for url, e in index.items() if not str(e.get("file", "")).startswith(f"{FOLDER}/")}
    folder = FIXTURES / FOLDER
    for old in folder.glob("metadata-*.json"):
        old.unlink()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "image.jpg").write_bytes(_jpeg(noise=True))
    (folder / "placeholder.jpg").write_bytes(_jpeg(noise=False))
    assert (folder / "image.jpg").stat().st_size >= 5000 > (folder / "placeholder.jpg").stat().st_size

    manifest = load_source_manifest(REPO / "discovery" / SOURCE)
    spec = manifest.resource("images")
    lincoln = [_metadata(entry) for entry in SCENARIO]
    denied = [{"error_message": "The provided API key is invalid. ", "status": "REQUEST_DENIED"}]
    for name, answers in (("lincoln-park", lincoln), ("denied", denied)):
        service = build_service(manifest, ScenarioTransport(index, answers, name))
        values = P.validate_values(manifest.declared_parameters("images"), ASKS[name])
        with tempfile.TemporaryDirectory() as tmp:
            try:
                answer = service.load(spec, values, Path(tmp))
                print(f"{name}: {len(answer.images)} images from {answer.found} panoramas")
            except Exception as exc:  # noqa: BLE001 - the denied scenario raises
                print(f"{name}: {type(exc).__name__}: {exc}")

    index_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {index_path} ({len(index)} entries)")


if __name__ == "__main__":
    main()
