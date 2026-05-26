"""Google Street View Static + Metadata API client.

Sync port of the upstream FastAPI service (which used aiohttp). Uses `requests`
since we're running inside Flask's sync request handlers. The metadata API does
not consume image quota, so coverage estimation is cheap; the static image API
is paid past Google's free tier.

API docs: https://developers.google.com/maps/documentation/streetview
"""

import hashlib
import os
import random
from typing import List, Optional, Tuple

import requests

STREETVIEW_BASE = "https://maps.googleapis.com/maps/api/streetview"
METADATA_BASE = f"{STREETVIEW_BASE}/metadata"

DEFAULT_SIZE = "640x480"
DEFAULT_FOV = 90


def check_coverage(lat: float, lon: float, api_key: str, radius: int = 50) -> Optional[dict]:
    """Probe a single coordinate for Street View imagery via the metadata API."""
    params = {
        "location": f"{lat},{lon}",
        "radius": radius,
        "source": "outdoor",
        "key": api_key,
    }
    try:
        r = requests.get(METADATA_BASE, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        return None
    if data.get("status") != "OK":
        return None
    return {
        "pano_id": data.get("pano_id", ""),
        "latitude": data["location"]["lat"],
        "longitude": data["location"]["lng"],
        "date": data.get("date", ""),
        "status": "OK",
    }


def fetch_images_in_bbox(
    bbox: List[float],
    limit: int,
    api_key: str,
    grid_density: int = 0,
) -> List[dict]:
    """Sample a grid inside the bbox and return unique panoramas with coverage.

    bbox: [west, south, east, north] (lon_min, lat_min, lon_max, lat_max)
    """
    if not api_key:
        raise ValueError("Google Maps API key required.")

    west, south, east, north = bbox
    if grid_density <= 0:
        grid_density = max(int((limit * 4) ** 0.5), 4)

    lat_step = (north - south) / grid_density
    lon_step = (east - west) / grid_density

    candidates: List[Tuple[float, float]] = []
    for i in range(grid_density):
        for j in range(grid_density):
            lat = south + lat_step * (i + 0.5)
            lon = west + lon_step * (j + 0.5)
            candidates.append((lat, lon))

    # Random shuffle so hitting `limit` doesn't bias toward one corner.
    random.shuffle(candidates)

    results: List[dict] = []
    seen = set()
    for lat, lon in candidates:
        if len(results) >= limit:
            break
        params = {
            "location": f"{lat},{lon}",
            "radius": 100,
            "source": "outdoor",
            "key": api_key,
        }
        try:
            r = requests.get(METADATA_BASE, params=params, timeout=10)
            data = r.json()
        except requests.RequestException:
            continue
        if data.get("status") != "OK":
            continue
        pano_id = data.get("pano_id", "")
        if not pano_id or pano_id in seen:
            continue
        seen.add(pano_id)
        results.append({
            "pano_id": pano_id,
            "latitude": data["location"]["lat"],
            "longitude": data["location"]["lng"],
            "date": data.get("date", ""),
        })
    return results


def get_image_url(
    lat: float, lon: float, api_key: str,
    heading: int = 0, size: str = DEFAULT_SIZE, fov: int = DEFAULT_FOV, pitch: int = 0,
) -> str:
    return (
        f"{STREETVIEW_BASE}"
        f"?size={size}&location={lat},{lon}"
        f"&heading={heading}&fov={fov}&pitch={pitch}&key={api_key}"
    )


def get_image_url_by_pano(
    pano_id: str, api_key: str,
    heading: int = 0, size: str = DEFAULT_SIZE, fov: int = DEFAULT_FOV, pitch: int = 0,
) -> str:
    return (
        f"{STREETVIEW_BASE}"
        f"?size={size}&pano={pano_id}"
        f"&heading={heading}&fov={fov}&pitch={pitch}&key={api_key}"
    )


def download_image(
    pano_id: str,
    api_key: str,
    cache_dir: str,
    heading: int = 0,
    size: str = DEFAULT_SIZE,
    fov: int = DEFAULT_FOV,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> str:
    """Fetch a Street View JPEG and cache it locally; returns the on-disk path."""
    os.makedirs(cache_dir, exist_ok=True)

    key = f"{pano_id}_{heading}_{size}"
    file_hash = hashlib.md5(key.encode()).hexdigest()[:12]
    local_path = os.path.join(cache_dir, f"gsv_{file_hash}.jpg")
    if os.path.exists(local_path):
        return local_path

    if pano_id:
        url = get_image_url_by_pano(pano_id, api_key, heading=heading, size=size, fov=fov)
    elif lat is not None and lon is not None:
        url = get_image_url(lat, lon, api_key, heading=heading, size=size, fov=fov)
    else:
        raise ValueError("Either pano_id or lat/lon required")

    r = requests.get(url, timeout=30)
    if r.status_code != 200:
        raise ValueError(f"Street View API returned status {r.status_code}")
    # Google returns a small gray placeholder when no image is available.
    if len(r.content) < 5000:
        raise ValueError(f"No Street View image available for {pano_id}")

    with open(local_path, "wb") as f:
        f.write(r.content)
    return local_path


def estimate_coverage(bbox: List[float], api_key: str, sample_count: int = 16) -> int:
    """Estimate how many Street View panoramas exist in a bbox using a small grid sample."""
    west, south, east, north = bbox
    grid_size = max(int(sample_count ** 0.5), 2)
    lat_step = (north - south) / grid_size
    lon_step = (east - west) / grid_size

    hits = 0
    total = 0
    for i in range(grid_size):
        for j in range(grid_size):
            lat = south + lat_step * (i + 0.5)
            lon = west + lon_step * (j + 0.5)
            total += 1
            params = {
                "location": f"{lat},{lon}",
                "radius": 100,
                "source": "outdoor",
                "key": api_key,
            }
            try:
                r = requests.get(METADATA_BASE, params=params, timeout=10)
                if r.json().get("status") == "OK":
                    hits += 1
            except requests.RequestException:
                continue
    if total == 0:
        return 0
    # Extrapolate to a denser practical grid (5× per axis).
    full_grid = grid_size * 5
    return int((hits / total) * full_grid * full_grid)


def search_place(query: str) -> dict:
    """Geocode a place name via Nominatim. Returns name + bbox + lat/lon."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": query, "format": "json", "limit": 1},
        headers={"User-Agent": "Curio-StreetVision/1.0"},
        timeout=10,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise LookupError("Place not found")
    place = results[0]
    # Nominatim's boundingbox is [south, north, west, east]; reshape to
    # [west, south, east, north] which is what the rest of the service expects.
    bb = place["boundingbox"]
    bbox = [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])]
    return {
        "name": place.get("display_name", query),
        "bbox": bbox,
        "lat": float(place["lat"]),
        "lon": float(place["lon"]),
    }
