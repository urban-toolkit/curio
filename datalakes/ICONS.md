# Source icons

Each source folder may hold an `icon.png`, named by its manifest's `icon` field.
A source without one renders the shared lake glyph instead, on the same
`--curio-kind-lake-*` tokens every other catalog uses for an item with no
imagery. `lake.curio.direct-url@1` deliberately ships without one, so the
fallback is exercised by the shipped set rather than only by a test.

## What ships, and where it came from

Each mark is the portal's own, fetched from the portal, and used to identify
that portal in a list of portals.

| Source | Mark | Fetched from | Date |
|---|---|---|---|
| `lake.cityofchicago.data-portal@1` | City of Chicago seal | `data.cityofchicago.org/api/assets/FF6A8E2F-9E44-4A23-AB53-60E5E4D14E7A` (`city-seal-small.png`, the portal's own header asset) | 2026-09-23 |
| `lake.uk.data-gov@1` | data.gov.uk mark | `data.gov.uk/assets/images/favicon.<hash>.png`, 48×48 | 2026-09-23 |
| `lake.esri.hub-opendata@1` | ArcGIS mark | `www.arcgis.com/favicon.ico`, 48×48 frame | 2026-09-23 |
| `lake.saopaulo.geosampa@1` | São Paulo coat of arms | cropped from `geosampa.prefeitura.sp.gov.br/css/img/cabecalhoProdam.png`, the site header banner; there is no standalone asset | 2026-09-23 |
| `lake.curio.direct-url@1` | none - renders the glyph | — | — |

Normalised to PNG at 256px on the long edge, transparent margin trimmed, aspect
preserved. The card renders them at 48px and the drawer at 112px, both with
`object-fit: contain` on a neutral panel - `contain` rather than `cover`
because cropping a square out of a wordmark cuts somebody's name in half.

## On using the marks

These are trademarks of the organisations that own them. They are used here
**nominatively**: to identify the portal a card refers to, in a catalog whose
entire purpose is to point at those portals. Nothing here claims affiliation,
sponsorship or endorsement, the marks are unmodified apart from scaling and
trimming, and each appears only beside the name of the thing it identifies.
The project maintainers have made this call; it is recorded here so it is a
decision on the record rather than an assumption.

Two consequences worth knowing:

- **A rights holder who objects should be accommodated, not argued with.**
  Removing a mark is deleting one PNG and the manifest's `icon` line; the card
  then renders the glyph and nothing else changes.
- **A fork or a rebrand inherits the question, not the answer.** If you ship
  Curio under another name or in another jurisdiction, this is yours to
  re-decide.

## Adding one

1. Put a PNG in the source folder. Keep the mark's own aspect ratio; it is
   rendered at 48px on a card and 112px in the detail drawer.
2. Point the manifest's `icon` at it (any single `.png` filename; the default
   is `icon.png`, so naming it that needs no manifest edit).
3. Add a row above with where it came from and when. A row with an empty source
   column is a row that should not ship.

Constraints the loader enforces, so a mistake fails visibly rather than
silently: a single `.png` filename with no path separators, resolved inside the
source folder, at most 256 KiB. Anything else is treated as "no icon" and the
glyph is served, because a broken icon should cost a logo, not a page.

PNG only. An SVG served from the app's own origin can carry script, and the
icon is the one file in this feature whose bytes are rendered rather than
parsed.
