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


def create_job(total_images: int) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {
            "job_id": job_id,
            "status": "queued",
            "total_images": total_images,
            "processed": 0,
            "results": [],
            "error": None,
        }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        # Return a shallow copy so callers don't observe mid-update mutations.
        return dict(job) if job is not None else None


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
) -> None:
    """Spawn a daemon worker thread that runs inference and updates the job store.

    Args:
        job_id: id returned by ``create_job``.
        images: list of ``{image_id, image_url, latitude?, longitude?}`` dicts.
            If ``image_url`` is a remote URL, the worker will download it via
            the Street View service first. Local paths are used as-is.
        model_id, model_type, classes: forwarded to ``services.inference.run_batch``.
        api_key: Google Maps key needed only when fetching Street View URLs.
    """

    def _worker():
        # Lazy-import the heavy services here so the import doesn't run on
        # every Curio startup — only when a user actually starts an inference.
        try:
            from .services import inference as inference_svc
            from .services import streetview as streetview_svc
            from .services import cache as cache_svc
        except ImportError as e:
            _update(job_id, status="failed",
                    error=f"streetvision extras not installed: {e}")
            return

        _update(job_id, status="running")

        # First pass: materialize every image to a local path. For Street View
        # URLs we need to download; for already-local paths we trust the caller.
        prepared: List[dict] = []
        download_dir = cache_svc.images_dir()
        for img in images:
            url_or_path = img.get("image_url") or ""
            local_path: Optional[str] = img.get("local_path")
            try:
                if local_path and os.path.exists(local_path):
                    pass  # caller pre-staged it
                elif url_or_path.startswith(("http://", "https://")) and "googleapis.com" in url_or_path:
                    # Street View URL — use the pano_id-aware downloader so
                    # we reuse the existing cache layout.
                    pano_id = img.get("pano_id") or img.get("image_id") or ""
                    local_path = streetview_svc.download_image(
                        pano_id=pano_id,
                        api_key=api_key or "",
                        cache_dir=download_dir,
                        lat=img.get("latitude"),
                        lon=img.get("longitude"),
                    )
                elif url_or_path.startswith(("http://", "https://")):
                    # Generic HTTP URL — fetch via requests so this node works
                    # for any image source, not just Street View.
                    import hashlib
                    import requests as _rq
                    h = hashlib.md5(url_or_path.encode()).hexdigest()[:12]
                    local_path = os.path.join(download_dir, f"img_{h}.jpg")
                    if not os.path.exists(local_path):
                        r = _rq.get(url_or_path, timeout=30)
                        r.raise_for_status()
                        with open(local_path, "wb") as f:
                            f.write(r.content)
                elif os.path.exists(url_or_path):
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
        _update(job_id, total_images=len(prepared))

        def _progress(processed: int, _total: int) -> None:
            _update(job_id, processed=processed)

        try:
            for result in inference_svc.run_batch(
                prepared, model_id, model_type, classes, progress_cb=_progress,
            ):
                _update_results_append(job_id, result)
            _update(job_id, status="completed")
        except Exception as e:
            traceback.print_exc()  # Surface to backend logs for debugging.
            _update(job_id, status="failed",
                    error=f"{type(e).__name__}: {e}")

    t = threading.Thread(target=_worker, name=f"streetvision-{job_id[:8]}", daemon=True)
    t.start()


def _update_results_append(job_id: str, result: dict) -> None:
    """Append a single result dict to the job's results list (thread-safe)."""
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["results"].append(result)
