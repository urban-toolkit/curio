# Example Agent Packages

Hand-testable packages for the **upload-import** feature (memo `dev/36`,
`BL-P3-20260727-10`). Each package is a folder shaped exactly like a real agent
definition: a `manifest.json` plus the `prompts/*.txt` assets it references.

## `agent.dataflow-scribe@1.0.0`

A documentation assistant (canvas + node targets, report-only): ask it to draft a
README-style summary of your dataflow. Two prompt assets (system preamble +
instruction), so it exercises multi-file digest stamping.

## How to test upload-import in the app

1. Open a project, then **Data → Agents Catalog**.
2. Click the footer's **Import package** button.
3. In the picker, select **all three files** from the package folder:
   `manifest.json`, `prompts/instruction.txt`, `prompts/preamble.txt`
   (pick the `.txt` files themselves — the modal maps each to `prompts/<name>`,
   which is exactly how the manifest references them).
4. Click **Import**. The drawer jumps to **My Imports**, where *Dataflow Scribe*
   appears as your own definition with **Install**, **Delete**, and a live
   **Publish** pill (upload-import creates `imported`-trust definitions — the
   only kind Publish accepts).
5. **Install** it, drag it from the AGENTS palette onto the canvas (or a node),
   and chat: *"Document this dataflow: it loads census tracts, joins heat-index
   rasters, and renders a vulnerability map."*
6. Optional: **Publish** it, then check the Global Catalog lists it as published.

## What the server enforces (try to break it)

- Re-importing the same folder → **409** "definitions are immutable; bump the
  version" (edit `version` in the manifest to `1.0.1` to import again).
- Removing a `.txt` file from your selection → **400** (a manifest-referenced
  prompt is missing); adding an unreferenced `.txt` → **400**.
- The manifest's `provenance.trust` is ignored — the server forces `imported`.
- Prompt `sha256` digests are computed server-side from the uploaded bytes; you
  never maintain them by hand (this package's manifest omits them on purpose).

Verified against the real backend service (upload → stamped digests → duplicate
409 → publish) on 2026-07-27.
