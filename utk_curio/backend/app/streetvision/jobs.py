"""In-memory inference job store + worker thread.

Replaces the FastAPI service's ``asyncio.create_task`` + per-job dict with a
plain ``threading.Thread`` + a module-level dict guarded by a lock. The job
state is process-local; if the user restarts Curio mid-job, the job is lost.
That tradeoff is fine for the typical interactive workflow (jobs complete in
seconds to a few minutes) and avoids pulling in Celery / Redis.

Job state schema::

    {
      "job_id":       str,
      "status":       "queued" | "running" | "completed" | "failed",
      "total_images": int,
      "processed":    int,
      "results":      list[dict],
      "error":        Optional[str],
    }
"""

import os
import threading
import traceback
import uuid
from typing import Dict, List, Optional

_jobs: Dict[str, dict] = {}
_lock = threading.Lock()


#: A generic image URL is fetched through the egress policy under this cap.
MAX_IMAGE_BYTES = 32 * 1024 * 1024


def create_job(total_images: int, owner: str = "guest") -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            # Whose job this is. ``get_job`` answers only its owner, so a job
            # id seen in one account's traffic reads nothing from another.
            "owner": owner,
            "status": "queued",
            "total_images": total_images,
            "processed": 0,
            "results": [],
            "error": None,
            # ``stage_message`` lets the worker tell the UI what slow thing
            # it's currently waiting on (image downloads, HF model fetch,
            # …) so the frontend can show "Downloading model - first run
            # takes a few minutes" instead of a static 0/N progress bar.
            "stage_message": None,
        }
    return job_id


def get_job(job_id: str, owner: Optional[str] = None) -> Optional[dict]:
    """The job, or None when it does not exist or belongs to someone else.

    ``owner`` is left out only by in-process callers that already know whose
    job it is; every route passes the caller's key.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None or (owner is not None and job.get("owner") != owner):
            return None
        # Return a shallow copy so callers don't observe mid-update mutations.
        out = dict(job)
    out.pop("owner", None)
    return out


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job.update(fields)


def start_inference(
    job_id: str,
    images: List[dict],
    model_id: str,
    model_type: str,
    classes: List[str],
    api_key: Optional[str] = None,
    hf_token: Optional[str] = None,
    user_key: str = "guest",
) -> None:
    """Spawn a daemon worker thread that runs inference and updates the job store.

    Args:
        job_id: id returned by ``create_job``.
        images: list of ``{image_id, image_url, latitude?, longitude?}`` dicts.
            If ``image_url`` is a remote URL, the worker will download it via
            the Street View service first. Local paths are used as-is.
        model_id, model_type, classes: forwarded to ``services.inference.run_batch``.
        api_key: Google Maps key needed only when fetching Street View URLs.
        hf_token: the caller's HuggingFace token, resolved in the request and
            handed over because this worker has no request context.
        user_key: whose ``.curio/users/<key>/streetvision/`` caches the
            downloaded panoramas, overlays and model weights. Resolved in the
            request for the same reason.
    """

    def _worker():
        # Lazy-import the heavy services here so the import doesn't run on
        # every Curio startup - only when a user actually starts an inference.
        try:
            from .services import inference as inference_svc
            from .services import streetview as streetview_svc
            from .services import cache as cache_svc
        except ImportError as e:
            _update(job_id, status="failed",
                    error=f"streetvision dependency unavailable: {e}")
            return

        _update(job_id, status="running", stage_message="Downloading source images…")

        # First pass: materialize every image to a local path. For Street View
        # URLs we need to download. A local path is accepted only inside this
        # user's own image cache: the request body names it, so anything else
        # would let a caller point the model at any file the server can read.
        prepared: List[dict] = []
        download_dir = cache_svc.images_dir(user_key)
        for img in images:
            url_or_path = img.get("image_url") or ""
            local_path: Optional[str] = img.get("local_path")
            try:
                if local_path and _cached_image(local_path, download_dir):
                    pass  # an image this user's earlier runs cached
                elif (
                    url_or_path.startswith(("http://", "https://"))
                    and "googleapis.com" in url_or_path
                    and api_key
                ):
                    # Street View URL with a key supplied by the caller -
                    # use the pano_id-aware downloader so we reuse the
                    # existing cache layout. Without a key we fall through
                    # to the generic HTTP path: the URL itself embeds the
                    # key, so a plain GET still works (just with a
                    # different on-disk cache key).
                    pano_id = img.get("pano_id") or img.get("image_id") or ""
                    local_path = streetview_svc.download_image(
                        pano_id=pano_id,
                        api_key=api_key,
                        cache_dir=download_dir,
                        lat=img.get("latitude"),
                        lon=img.get("longitude"),
                    )
                elif url_or_path.startswith(("http://", "https://")):
                    # Generic HTTP URL, so this node works for any image
                    # source, not just Street View. It goes through the egress
                    # policy: the URL comes from the request body, and a plain
                    # GET would reach private and link-local addresses.
                    import hashlib
                    h = hashlib.md5(url_or_path.encode()).hexdigest()[:12]
                    local_path = os.path.join(download_dir, f"img_{h}.jpg")
                    if not os.path.exists(local_path):
                        _download_image(url_or_path, local_path)
                elif url_or_path and _cached_image(url_or_path, download_dir):
                    local_path = url_or_path
                else:
                    raise ValueError(f"unreadable image_url: {url_or_path}")
            except Exception as e:
                _update_results_append(job_id, {
                    "image_id": img.get("image_id", ""),
                    "error": f"{type(e).__name__}: {e}",
                })
                continue
            prepared.append({**img, "local_path": local_path})

        # Update total_images to the count we actually prepared.
        # Switch the stage to "model loading" - the next thing run_batch
        # does is fetch the HF model (potentially hundreds of MB on a
        # cold cache). The first ``progress_cb`` call clears this once
        # actual inference starts.
        _update(
            job_id,
            total_images=len(prepared),
            stage_message="Loading model - first run can take a few minutes for HuggingFace download…",
        )

        def _progress(processed: int, _total: int) -> None:
            # First progress tick means model load is done; clear the
            # stage banner so the UI shows the per-image counter.
            _update(job_id, processed=processed, stage_message=None)

        try:
            for result in inference_svc.run_batch(
                prepared, model_id, model_type, classes, progress_cb=_progress,
                hf_token=hf_token, user_key=user_key,
            ):
                _update_results_append(job_id, result)
            _update(job_id, status="completed", stage_message=None)
        except Exception as e:
            traceback.print_exc()  # Surface to backend logs for debugging.
            _update(job_id, status="failed", stage_message=None,
                    error=f"{type(e).__name__}: {e}")

    t = threading.Thread(target=_worker, name=f"streetvision-{job_id[:8]}", daemon=True)
    t.start()


def _cached_image(path: str, cache_dir: str) -> bool:
    """True when *path* is an existing file inside *cache_dir*."""
    from pathlib import Path

    from utk_curio.backend.app.common.safe_paths import is_within

    candidate = Path(path)
    return candidate.is_file() and is_within(candidate, Path(cache_dir))


def _download_image(url: str, dest: str) -> None:
    """Fetch *url* into *dest* under the egress policy and a size cap."""
    from utk_curio.backend.app.agents.infrastructure import egress

    part = f"{dest}.part"
    try:
        with open(part, "wb") as handle:
            result = egress.download(url, sink=handle.write, max_bytes=MAX_IMAGE_BYTES)
        if not 200 <= result.status < 300:
            raise ValueError(f"image download answered HTTP {result.status}")
        os.replace(part, dest)
    finally:
        if os.path.exists(part):
            os.remove(part)


def _update_results_append(job_id: str, result: dict) -> None:
    """Append a single result dict to the job's results list (thread-safe)."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["results"].append(result)
