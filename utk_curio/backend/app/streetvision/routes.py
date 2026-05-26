"""Street Vision HTTP endpoints (registered under ``/api/streetvision/*``).

Three frontend nodes share this blueprint:

- **Street View Fetcher** uses ``/data/streetview/search_place``,
  ``/data/streetview/coverage``, and ``/data/streetview/fetch``.
- **HuggingFace CV Inference** uses ``/models/search``, ``/inference/run``,
  ``/inference/results/<job_id>``, and ``/inference/overlay/<image_id>``.
- **CV Gallery** just consumes the inference results plus
  ``/inference/overlay/<image_id>`` for the inspect view; no extra endpoints.

All heavy ML dependencies (``torch``, ``transformers``, ``ultralytics``)
are lazy-imported deep in the call stack so route handlers only fail with
``503 streetvision extras not installed`` when the user actually triggers
inference — searching models or fetching imagery works on a base install.
"""

import os

from flask import jsonify, request, send_file

from . import bp, jobs
from .services import cache, streetview


def _missing_extras_response(err: ImportError):
    return jsonify({
        "error": "streetvision extras not installed",
        "hint": "pip install curio[streetvision]",
        "detail": str(err),
    }), 503


# ── Health ──────────────────────────────────────────────────────────

@bp.get("/health")
def health():
    """Lightweight liveness check. Reports whether the Google Maps API key
    is configured so the frontend can show a "key required" banner without
    waiting for the first failed request."""
    has_key = bool(os.environ.get("GOOGLE_MAPS_API_KEY"))
    return jsonify({
        "status": "healthy",
        "demo_mode": not has_key,
        "has_google_api_key": has_key,
        "has_huggingface_token": bool(os.environ.get("HUGGINGFACE_TOKEN")),
    })


# ── HuggingFace model search ────────────────────────────────────────

@bp.get("/models/search")
def models_search():
    """Search HuggingFace Hub for CV models. Used by the Inference node's
    model picker; no heavy ML deps needed."""
    task = request.args.get("task", "segmentation")
    query = request.args.get("query", "cityscapes")
    try:
        from .services import huggingface as hf  # huggingface_hub is light
    except ImportError as e:
        return _missing_extras_response(e)
    try:
        results = hf.search_models(task, query)
        return jsonify({"models": results})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


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
    (which does not consume image quota)."""
    body = request.get_json(silent=True) or {}
    bbox = body.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return jsonify({"error": "body must be { bbox: [west, south, east, north] }"}), 400
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return jsonify({
            "error": "Google Maps API key required",
            "hint": "Set GOOGLE_MAPS_API_KEY in your environment",
        }), 400
    try:
        estimated = streetview.estimate_coverage(bbox=bbox, api_key=api_key)
        return jsonify({"bbox": bbox, "estimated_count": estimated})
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500


@bp.post("/data/streetview/fetch")
def streetview_fetch():
    """Fetch unique Street View panorama metadata inside a bbox.

    Returns a GeoJSON-flavored payload the Street View Fetcher node feeds
    to the downstream Inference node: a FeatureCollection of point features
    keyed by ``pano_id`` with ``image_url`` + ``latitude`` + ``longitude``
    in each feature's properties.
    """
    body = request.get_json(silent=True) or {}
    bbox = body.get("bbox")
    limit = int(body.get("limit") or 20)
    if not isinstance(bbox, list) or len(bbox) != 4:
        return jsonify({"error": "body must be { bbox: [west, south, east, north], limit? }"}), 400
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return jsonify({
            "error": "Google Maps API key required",
            "hint": "Set GOOGLE_MAPS_API_KEY in your environment",
        }), 400
    try:
        images = streetview.fetch_images_in_bbox(bbox=bbox, limit=limit, api_key=api_key)
    except Exception as e:
        return jsonify({"error": f"{type(e).__name__}: {e}"}), 500

    # Shape as a GEODATAFRAME-compatible FeatureCollection so the downstream
    # Inference / Spatial Join nodes can consume it without a transformation.
    features = []
    for img in images:
        url = streetview.get_image_url_by_pano(img["pano_id"], api_key, heading=0)
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


# ── Inference job lifecycle ─────────────────────────────────────────

@bp.post("/inference/run")
def inference_run():
    """Start an inference job. Accepts either:

    1. A list of image entries: ``{ images: [{image_id, image_url, pano_id?,
       latitude?, longitude?}, ...], model: {...}, classes: [...] }`` — used
       by the wired-up Inference node when fed by Street View Fetcher.

    2. A GEODATAFRAME FeatureCollection (as ``input``) with per-feature
       ``image_url`` properties — used by the Inference node when fed by
       any node emitting GEODATAFRAME shape (Data Loading, Spatial Join, etc).
    """
    body = request.get_json(silent=True) or {}

    # Accept either explicit `images` list or a FeatureCollection-shaped `input`.
    images = body.get("images")
    if not images and isinstance(body.get("input"), dict):
        fc = body["input"]
        feats = fc.get("features") if isinstance(fc, dict) else None
        if isinstance(feats, list):
            images = []
            for f in feats:
                props = f.get("properties") or {}
                geom = f.get("geometry") or {}
                coords = geom.get("coordinates") if isinstance(geom, dict) else None
                lat = props.get("latitude")
                lon = props.get("longitude")
                if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
                images.append({
                    "image_id": props.get("image_id") or props.get("pano_id"),
                    "pano_id": props.get("pano_id"),
                    "image_url": props.get("image_url"),
                    "latitude": lat,
                    "longitude": lon,
                })

    if not isinstance(images, list) or not images:
        return jsonify({"error": "body must include `images` (list) or `input` (FeatureCollection)"}), 400

    model = body.get("model") or {}
    model_id = model.get("model_id")
    model_type = model.get("model_type")
    if not model_id or model_type not in ("segmentation", "detection"):
        return jsonify({"error": "model.model_id and model.model_type (segmentation|detection) required"}), 400

    classes_field = body.get("classes")
    if isinstance(classes_field, dict):
        classes = classes_field.get("classes") or []
    elif isinstance(classes_field, list):
        classes = classes_field
    else:
        classes = []

    # Cap the batch at 200 to keep memory + Google API costs bounded.
    images = images[:200]

    job_id = jobs.create_job(total_images=len(images))
    jobs.start_inference(
        job_id=job_id,
        images=images,
        model_id=model_id,
        model_type=model_type,
        classes=classes,
        api_key=os.environ.get("GOOGLE_MAPS_API_KEY", ""),
    )
    return jsonify({"job_id": job_id, "status": "queued", "total_images": len(images)})


@bp.get("/inference/results/<job_id>")
def inference_results(job_id: str):
    """Poll for inference progress + results. Frontend hits this every ~2s."""
    job = jobs.get_job(job_id)
    if job is None:
        return jsonify({"error": "job not found"}), 404
    return jsonify(job)


@bp.get("/inference/overlay/<path:image_id>")
def inference_overlay(image_id: str):
    """Serve the segmentation overlay PNG for a single image (used by the
    CV Gallery's inspect view)."""
    path = cache.overlay_path(image_id)
    if not path:
        return jsonify({"error": "overlay not found"}), 404
    return send_file(path, mimetype="image/png")
