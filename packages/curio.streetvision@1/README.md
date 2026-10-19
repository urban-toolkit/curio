# Street View inspection

Street View Fetcher emits a GeoJSON FeatureCollection of image points. Panorama inspects a requested WGS84 longitude/latitude and emits correlated actual camera positions and headings. Each node accepts its own Google Maps credential through its UI; keys remain in memory and must be entered again after reload.

Fetcher requires backend Street View routes. Opaque image-proxy links expire after two hours, backend restart, or cache eviction (512 entries); run Fetcher again to restore expired images. Saved outputs do not contain provider keys. Static and JavaScript API credentials have different restrictions.

Panorama retains the latest pending request without a key. It issues a lookup when configured, rejects stale responses, and confirms only actual camera events. Manual coordinates require View location. Navigation does not request a new editing tile. Open camera tile explicitly adopts an already loaded camera context. Fixtures cover these contracts; fixture success does not establish live provider access.

This focused package contains Fetcher and Panorama only. No model inference nodes or training support are included.

Open [review follow-ups](../../docs/sidewalk/phase1-review-followups.md) include server-enforced Fetcher limits, bounds validation/authentication and provider failures currently reported as successful empty results. These remain unfixed in this draft and are distinct from Panorama camera-confirmation safeguards.
