# Source icons

Each source folder may hold an `icon.png`, named by its manifest's `icon` field.
A source without one renders the shared lake glyph instead, on the same
`--curio-kind-lake-*` tokens every other catalog uses for an item with no
imagery. `lake.curio.direct-url@1` deliberately ships without one, so the
fallback is exercised by the shipped set rather than only by a test.

## The shipped icons are placeholders, not the portals' logos

| Source | Icon | Origin | Licence |
|---|---|---|---|
| `lake.cityofchicago.data-portal@1` | `CHI` lettermark | Generated for this repo | Same as Curio |
| `lake.us.data-gov@1` | `GOV` lettermark | Generated for this repo | Same as Curio |
| `lake.esri.hub-opendata@1` | `ARC` lettermark | Generated for this repo | Same as Curio |
| `lake.saopaulo.geosampa@1` | `SP` lettermark | Generated for this repo | Same as Curio |
| `lake.curio.direct-url@1` | none | — | — |

**A portal's logo is that portal's trademark.** Using the City of Chicago's or
Esri's mark here would mean redistributing it under Curio's licence, which this
repo has no right to do and no way to verify. So the shipped marks are neutral
lettermarks on the provider palette: enough to tell five cards apart at a
glance, and unmistakably not a claim to be anyone's brand.

An operator running their own deployment is in a different position - they may
well have permission, or be the publisher - so replacing any of these is a
matter of dropping a PNG in. It is not a code change.

## Adding one

1. Put a PNG in the source folder. Keep it square; it is rendered at 48px on a
   card and 112px in the detail drawer.
2. Point the manifest's `icon` at it (any single `.png` filename; the default
   is `icon.png`, so naming it that needs no manifest edit).
3. Record it in the table above, with where it came from and under what
   licence. A row with an empty licence column is a row that should not ship.

Constraints the loader enforces, so a mistake fails visibly rather than
silently: a single `.png` filename with no path separators, resolved inside the
source folder, at most 256 KiB. Anything else is treated as "no icon" and the
glyph is served, because a broken icon should cost a logo, not a page.

PNG only. An SVG served from the app's own origin can carry script, and the
icon is the one file in this feature whose bytes are rendered rather than
parsed.
