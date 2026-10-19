"""The restored Fetcher retains GeoDataFrame shape without persisting its key."""

from flask import Flask

from utk_curio.backend.app.streetvision import bp, routes
from utk_curio.backend.app.streetvision.services import streetview


def test_fetcher_emits_geodataframe_compatible_points(monkeypatch):
    monkeypatch.setattr(streetview, "fetch_images_in_bbox", lambda **kwargs: [
        {"pano_id": "fixture-pano", "longitude": -34.9, "latitude": -8.1, "date": "2026-01"}
    ])
    monkeypatch.setattr(streetview, "get_image_url_by_pano", lambda *args, **kwargs:
                        "https://maps.example.test/image?key=fixture-only")
    app = Flask(__name__)
    app.register_blueprint(bp, url_prefix="/api/streetvision")
    client = app.test_client()
    response = client.post("/api/streetvision/data/streetview/fetch", json={
        "bbox": [-35, -9, -34, -8], "limit": 1, "api_key": "fixture-only",
    })
    assert response.status_code == 200
    result = response.get_json()
    assert result["type"] == "FeatureCollection"
    assert result["metadata"] == {"name": "streetview_points", "count": 1}
    image_url = result["features"][0]["properties"]["image_url"]
    assert image_url.startswith("http://localhost/api/streetvision/data/streetview/image/")
    assert "fixture-only" not in str(result)
    assert result["features"] == [{
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [-34.9, -8.1]},
        "properties": {"image_id": "fixture-pano", "pano_id": "fixture-pano",
                       "image_url": image_url, "latitude": -8.1,
                       "longitude": -34.9, "date": "2026-01"},
    }]
    calls = []

    class ImageResponse:
        content = b"fixture-jpeg"

        def raise_for_status(self):
            pass

    def fake_get(url, timeout):
        calls.append((url, timeout))
        return ImageResponse()

    monkeypatch.setattr(routes.requests, "get", fake_get)
    image_path = image_url.removeprefix("http://localhost")
    assert client.get(image_path).data == b"fixture-jpeg"
    assert client.get(image_path).data == b"fixture-jpeg"
    assert calls == [("https://maps.example.test/image?key=fixture-only", 20)]
