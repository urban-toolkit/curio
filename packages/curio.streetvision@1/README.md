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

1. **Install the package**: open `/catalog` in Curio and install Street Vision. The first install pip-installs the package's Python deps (`torch`, `transformers`, `ultralytics`, `huggingface_hub`) declared in `manifest.dependencies.python` — about 3 GB on a cold conda env, possibly minutes on a slow connection. The Install button stays in its busy state until pip finishes. Re-installs of the same package are near-instant because the deps are already satisfied.

2. **Have a Google Maps API key handy.** You paste it directly into the Street View Fetcher node — it lives in the node's UI for the current session, never written to the backend env or saved with the dataflow, so a shared dataflow won't leak your key.

   The Street View Static API is paid past Google's free tier — the Fetcher node defaults to a 20-image limit per run; raise it with care.

3. **(Optional) HuggingFace token** — only needed for gated models:

   ```bash
   export HUGGINGFACE_TOKEN=hf_...
   ```

A GPU is *not* required, but with one you'll see roughly 10× faster inference.

## Limitations

- **Jobs don't survive backend restart.** Inference state lives in-process; restarting Curio mid-job loses progress. Re-run.
- **Chicago is not bundled.** Earlier versions of this work included a hardcoded Chicago neighborhoods basemap for spatial enrichment. That feature now lives in the generic **Spatial Join** node (in `curio.builtin@1`) and accepts any polygons FeatureCollection the user provides.
- **Demo cap.** The frontend's Fetcher node caps panorama requests at 200; the default is 20 to keep Google API costs bounded on first try.

## Origin

The original CV pipeline + node design was contributed by [@ManeeshJupalle](https://github.com/ManeeshJupalle) in [PR #120](https://github.com/urban-toolkit/curio/pull/120) as a CS 524 university project. The merged version decomposes the two original monolithic nodes (`STREET_VISION`, `CV_ANALYSIS`) into the three reusable nodes here plus a generic `Spatial Join` node in `curio.builtin@1`, and ports the FastAPI service to a Flask blueprint inside Curio so users don't need a separate companion service.
