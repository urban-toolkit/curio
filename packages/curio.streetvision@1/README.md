# Street Vision (curio.streetvision@1)

Three nodes for street-level computer vision pipelines in Curio:

- **Street View Fetcher** — geocode a place name, sample Google Street View imagery in its bounding box, emit a GEODATAFRAME of image points (each feature carrying `image_url`, `pano_id`, `latitude`, `longitude`).
- **HF CV Inference** — run HuggingFace segmentation or detection models on the image points. Pluggable input: works with the Street View Fetcher *or* any node that emits a GEODATAFRAME with an `image_url` property. Emits per-image inference results as JSON.
- **CV Gallery** — inspect results in a gallery + per-image overlay view + aggregate stats, then re-emit as a GEODATAFRAME for downstream nodes (Spatial Join, Vega-Lite, AUTK Map).

A typical pipeline:

```
Street View Fetcher → HF CV Inference → CV Gallery → Spatial Join → Vega-Lite
                                                       ↑
                                       Data Loading (neighborhood polygons)
```

See [`docs/examples/10-street-vision-cv-analysis.md`](../../docs/examples/10-street-vision-cv-analysis.md) for a worked walkthrough.

## Setup

1. **Install the package**: open `/catalog` in Curio and install Street Vision. *(Not auto-installed — the ML stack is heavy.)*

2. **Install the Python extras** in your Curio Python environment:

   ```bash
   pip install "utk-curio[streetvision]"
   ```

   This pulls in `torch`, `transformers`, `ultralytics`, and `huggingface_hub`. About 3 GB of disk; a GPU is *not* required but speeds inference up roughly 10×.

3. **Set a Google Maps API key** before starting the backend, so the Fetcher can pull Street View imagery:

   ```bash
   export GOOGLE_MAPS_API_KEY=your-key-here
   ```

   The Street View Static API is paid past Google's free tier — the Fetcher node defaults to a 20-image limit per run; raise it with care.

4. **(Optional) HuggingFace token** — only needed for gated models:

   ```bash
   export HUGGINGFACE_TOKEN=hf_...
   ```

## How dependencies are resolved

Endpoints in `utk_curio/backend/app/streetvision/` lazy-import the ML libraries at call time. With the base install (no `[streetvision]` extras), the Fetcher node still works (it only needs the lightweight Google API client) but the Inference node returns HTTP 503 with a `pip install curio[streetvision]` hint. The frontend shows that hint inline so the user knows what to do.

## Limitations

- **Jobs don't survive backend restart.** Inference state lives in-process; restarting Curio mid-job loses progress. Re-run.
- **Chicago is not bundled.** Earlier versions of this work included a hardcoded Chicago neighborhoods basemap for spatial enrichment. That feature now lives in the generic **Spatial Join** node (in `curio.builtin@1`) and accepts any polygons FeatureCollection the user provides.
- **Demo cap.** The frontend's Fetcher node caps panorama requests at 200; the default is 20 to keep Google API costs bounded on first try.

## Origin

The original CV pipeline + node design was contributed by [@ManeeshJupalle](https://github.com/ManeeshJupalle) in [PR #120](https://github.com/urban-toolkit/curio/pull/120) as a CS 524 university project. The merged version decomposes the two original monolithic nodes (`STREET_VISION`, `CV_ANALYSIS`) into the three reusable nodes here plus a generic `Spatial Join` node in `curio.builtin@1`, and ports the FastAPI service to a Flask blueprint inside Curio so users don't need a separate companion service.
