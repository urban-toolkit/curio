"""Street View Fetcher endpoints and session-scoped image proxy."""

from io import BytesIO
import secrets
from threading import Lock
from time import monotonic

import requests
from flask import jsonify, request, send_file, url_for

from . import bp
from .services import streetview


# Only opaque URLs enter workflow output. Provider URLs and keys stay in memory.
# This cache is intentionally scoped to the current server session.
_image_lock = Lock()
_image_urls: dict[str, tuple[float, str, bytes | None]] = {}
_IMAGE_TTL_SECONDS = 2 * 60 * 60
_IMAGE_LIMIT = 512


def _register_image_url(provider_url: str) -> str:
    token = secrets.token_urlsafe(32)
    now = monotonic()
    with _image_lock:
        expired = [key for key, (created, _, _) in _image_urls.items()
                   if now - created > _IMAGE_TTL_SECONDS]
        for key in expired:
            _image_urls.pop(key, None)
        while len(_image_urls) >= _IMAGE_LIMIT:
            _image_urls.pop(next(iter(_image_urls)))
        _image_urls[token] = (now, provider_url, None)
    return url_for("streetvision.streetview_image", token=token, _external=True)


@bp.get("/data/streetview/image/<token>")
def streetview_image(token: str):
    """Serve a Fetcher image without exposing its provider key in the URL."""
    with _image_lock:
        entry = _image_urls.get(token)
    if entry is None or monotonic() - entry[0] > _IMAGE_TTL_SECONDS:
        return jsonify({"error": "Street View image link expired; run Fetcher again"}), 404
    _, provider_url, image_bytes = entry
    if image_bytes is None:
        try:
            fetched = requests.get(provider_url, timeout=20)
            fetched.raise_for_status()
            image_bytes = fetched.content
        except requests.RequestException:
            # Provider exceptions may include the credential-bearing URL.
            return jsonify({"error": "Street View image could not be loaded"}), 502
        with _image_lock:
            if token in _image_urls:
                _image_urls[token] = (entry[0], provider_url, image_bytes)
    response = send_file(BytesIO(image_bytes), mimetype="image/jpeg")
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@bp.get("/health")
def health():
    return jsonify({"status": "healthy"})


# ── Street View geocoding + coverage + fetch ────────────────────────

@bp.get("/data/streetview/search_place")
def streetview_search_place():
    """Geocode a place name (Nominatim) and return a bbox suitable for
    Street View querying."""
    query = (request.args.get("query") or "").strip()
    if not query:
        return jsonify({"error": "missing required query parameter"}), 400
    try:
        return jsonify(streetview.search_place(query))
    except LookupError:
        return jsonify({"error": "Place not found"}), 404
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@bp.post("/data/streetview/coverage")
def streetview_coverage():
    """Estimate Street View coverage inside a bbox using the metadata API
    (which does not consume image quota). The Google Maps API key is
    supplied per-request from the Street View Fetcher node's UI."""
    body = request.get_json(silent=True) or {}
    bbox = body.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return jsonify({"error": "body must be { bbox: [west, south, east, north], api_key }"}), 400
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "error": "Google Maps API key required",
            "hint": "Enter your Google Maps API key in the Street View Fetcher node",
        }), 400
    try:
        estimated = streetview.estimate_coverage(bbox=bbox, api_key=api_key)
        return jsonify({"bbox": bbox, "estimated_count": estimated})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}".replace(api_key, "[redacted]")}), 500


@bp.post("/data/streetview/fetch")
def streetview_fetch():
    """Fetch unique Street View panorama metadata inside a bbox.

    Returns a GeoJSON-flavored payload the Street View Fetcher node feeds
    to downstream nodes: a FeatureCollection of point features
    keyed by ``pano_id`` with ``image_url`` + ``latitude`` + ``longitude``
    in each feature's properties. The Google Maps API key is supplied
    per-request from the Street View Fetcher node's UI.
    """
    body = request.get_json(silent=True) or {}
    bbox = body.get("bbox")
    limit = int(body.get("limit") or 20)
    if not isinstance(bbox, list) or len(bbox) != 4:
        return jsonify({"error": "body must be { bbox: [west, south, east, north], api_key, limit? }"}), 400
    api_key = (body.get("api_key") or "").strip()
    if not api_key:
        return jsonify({
            "error": "Google Maps API key required",
            "hint": "Enter your Google Maps API key in the Street View Fetcher node",
        }), 400
    try:
        images = streetview.fetch_images_in_bbox(bbox=bbox, limit=limit, api_key=api_key)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}".replace(api_key, "[redacted]")}), 500

    # Shape as a GEODATAFRAME-compatible FeatureCollection so the downstream
    # Spatial Join and display nodes can consume it without a transformation.
    features = []
    for img in images:
        url = _register_image_url(streetview.get_image_url_by_pano(img["pano_id"], api_key, heading=0))
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [img["longitude"], img["latitude"]]},
            "properties": {
                "image_id": img["pano_id"],
                "pano_id": img["pano_id"],
                "image_url": url,
                "latitude": img["latitude"],
                "longitude": img["longitude"],
                "date": img.get("date", ""),
            },
        })
    return jsonify({
        "type": "FeatureCollection",
        "features": features,
        "metadata": {"name": "streetview_points", "count": len(features)},
    })
