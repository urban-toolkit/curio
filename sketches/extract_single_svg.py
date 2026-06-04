#!/usr/bin/env python3
"""
extract_single_svg.py

Produce a single SVG per input image that mirrors the picture pixel-for-pixel
at the vector level, while keeping every design component as an isolated,
independently editable <g> group.

Strategy (color-layer segmentation):
  1. Load image as RGBA.
  2. Quantize the full image into K palette colors.
  3. Optionally emit a background rectangle for the dominant border color.
  4. For each non-background palette color, find every connected region of
     that color (connected-components on the color's mask).
  5. Each sufficiently large region becomes one <g id="cNNN_kKK">...<path/></g>
     whose <path> is the traced (and optionally simplified) contour of that
     region, filled with the region's color.
  6. Groups are ordered largest-first so larger shapes sit behind smaller
     ones, mirroring what you see in the source image.

Every visible colored shape in the source becomes its own selectable group
in Figma / the browser. Nothing is merged into a single big blob.

Dependencies (reuse the extract-vectors conda env):
  pip install -r requirements.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, List, Tuple
from xml.sax.saxutils import escape as xml_escape

import cv2
import numpy as np
from PIL import Image

from extract_vectors import (
    contour_to_svg_path,
    dominant_border_index,
    ensure_dir,
    quantize_palette_rgba,
    rgb_to_hex,
    safe_stem,
)


IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}


def _simplify_contour(c: np.ndarray, simplify: float) -> np.ndarray:
    """Apply approxPolyDP with a perimeter-relative epsilon.

    simplify == 0 disables simplification (returns the contour unchanged).
    """
    if simplify <= 0:
        return c
    peri = cv2.arcLength(c, True)
    eps = max(0.5, float(simplify) * peri)
    return cv2.approxPolyDP(c, eps, True)


def _contours_with_holes_to_path(
    contours: List[np.ndarray],
    hierarchy: np.ndarray,
    outer_idx: int,
    simplify: float,
) -> str:
    """Build an evenodd SVG path: outer contour + any direct holes.

    Holes are immediate children of `outer_idx` in the RETR_CCOMP hierarchy.
    """
    parts: List[str] = []

    outer = _simplify_contour(contours[outer_idx], simplify)
    d = contour_to_svg_path(outer)
    if not d:
        return ""
    parts.append(d)

    if hierarchy is not None and len(hierarchy.shape) == 3:
        h = hierarchy[0]
        child = h[outer_idx][2]
        while child != -1:
            hole = _simplify_contour(contours[child], simplify)
            hd = contour_to_svg_path(hole)
            if hd:
                parts.append(hd)
            child = h[child][0]

    return " ".join(parts)


def _iter_color_regions(
    idx_map: np.ndarray,
    palette: List[Tuple[int, int, int]],
    bg_idx: int,
    min_area: int,
    simplify: float,
) -> Iterable[Tuple[int, int, int, str, float]]:
    """Yield (color_idx, comp_label, area, svg_path_d, _sort_key).

    Holes inside a region are captured via RETR_CCOMP + evenodd so fills stay
    accurate even for nested shapes.
    """
    for color_idx in np.unique(idx_map):
        color_idx = int(color_idx)
        if color_idx == bg_idx:
            continue

        color_mask = (idx_map == color_idx).astype(np.uint8) * 255
        if np.count_nonzero(color_mask) == 0:
            continue

        num, labels, stats, _ = cv2.connectedComponentsWithStats(
            color_mask, connectivity=8
        )

        for comp_label in range(1, num):
            area = int(stats[comp_label, cv2.CC_STAT_AREA])
            if area < min_area:
                continue

            comp_mask = (labels == comp_label).astype(np.uint8) * 255
            contours, hierarchy = cv2.findContours(
                comp_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE
            )
            if not contours:
                continue

            path_parts: List[str] = []
            h = hierarchy[0] if hierarchy is not None else None
            for outer_idx, c in enumerate(contours):
                if h is not None and h[outer_idx][3] != -1:
                    continue
                d = _contours_with_holes_to_path(
                    list(contours), hierarchy, outer_idx, simplify
                )
                if d:
                    path_parts.append(d)

            if not path_parts:
                continue

            yield color_idx, comp_label, area, " ".join(path_parts), float(area)


def build_single_svg(
    img_path: Path,
    out_svg: Path,
    color_k: int,
    min_area: int,
    simplify: float,
    include_background: bool,
    max_components: int,
) -> Tuple[Path, int]:
    img = Image.open(img_path).convert("RGBA")
    W, H = img.size

    idx_map, palette = quantize_palette_rgba(img, k=max(2, color_k))
    bg_idx = dominant_border_index(idx_map) if include_background else -1

    regions = list(
        _iter_color_regions(
            idx_map=idx_map,
            palette=palette,
            bg_idx=bg_idx,
            min_area=min_area,
            simplify=simplify,
        )
    )

    regions.sort(key=lambda r: r[4], reverse=True)
    if max_components > 0:
        regions = regions[:max_components]

    svg: List[str] = []
    svg.append(
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'shape-rendering="geometricPrecision">'
    )
    title = xml_escape(img_path.name)
    svg.append(f"<title>{title}</title>")
    svg.append(
        f"<desc>Vectorized mirror of {title}. Every visible shape is an "
        "isolated &lt;g&gt; group at its original pixel coordinates.</desc>"
    )

    if include_background and 0 <= bg_idx < len(palette):
        bg_hex = rgb_to_hex(palette[bg_idx])
        svg.append(
            f'<g id="background" data-role="background">'
            f'<rect x="0" y="0" width="{W}" height="{H}" fill="{bg_hex}"/>'
            f"</g>"
        )

    for n, (color_idx, comp_label, area, d, _k) in enumerate(regions):
        color = palette[color_idx] if 0 <= color_idx < len(palette) else (0, 0, 0)
        fill = rgb_to_hex(color)
        svg.append(
            f'<g id="c{n:04d}_k{color_idx:02d}" '
            f'data-area="{area}" data-color="{fill}">'
            f'<path d="{d}" fill="{fill}" stroke="none" fill-rule="evenodd"/>'
            f"</g>"
        )

    svg.append("</svg>")

    ensure_dir(out_svg.parent)
    out_svg.write_text("\n".join(svg), encoding="utf-8")
    return out_svg, len(regions)


def iter_image_inputs(paths: List[str]) -> List[Path]:
    out: List[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for fp in sorted(pp.rglob("*")):
                if fp.is_file() and fp.suffix.lower() in IMG_EXTS:
                    out.append(fp)
        elif pp.is_file() and pp.suffix.lower() in IMG_EXTS:
            out.append(pp)
        else:
            for gp in Path(".").glob(p):
                if gp.is_file() and gp.suffix.lower() in IMG_EXTS:
                    out.append(gp)
    seen = set()
    unique: List[Path] = []
    for fp in out:
        key = fp.resolve()
        if key not in seen:
            seen.add(key)
            unique.append(fp)
    return unique


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Produce a single SVG per input image, mirroring its layout with "
            "every design element as an isolated, positioned vector group."
        )
    )
    ap.add_argument("inputs", nargs="+", help="Input image file(s) or folder(s).")
    ap.add_argument("--out", default="svg_single", help="Output directory.")
    ap.add_argument("--color-k", type=int, default=16,
                    help="Palette size for quantization (higher = more color fidelity).")
    ap.add_argument("--min-area", type=int, default=4,
                    help="Minimum region area (pixels) to keep as its own group.")
    ap.add_argument("--simplify", type=float, default=0.0,
                    help="Contour simplification factor (0 disables; try 0.001 for lighter files).")
    ap.add_argument("--max-components", type=int, default=0,
                    help="Cap on emitted groups (0 = no cap).")
    ap.add_argument("--no-background", action="store_true",
                    help="Do not emit a background rectangle for the dominant border color.")
    args = ap.parse_args()

    files = iter_image_inputs(args.inputs)
    if not files:
        print("No supported image files found.", file=sys.stderr)
        return 2

    out_dir = Path(args.out)
    ensure_dir(out_dir)

    for fp in files:
        out_svg = out_dir / f"{safe_stem(fp)}.svg"
        try:
            _, n = build_single_svg(
                img_path=fp,
                out_svg=out_svg,
                color_k=args.color_k,
                min_area=args.min_area,
                simplify=args.simplify,
                include_background=not args.no_background,
                max_components=args.max_components,
            )
            print(f"{fp}  ->  {out_svg}  ({n} groups)")
        except Exception as e:
            print(f"{fp}: ERROR {type(e).__name__}: {e}", file=sys.stderr)

    print(f"Done. Wrote {len(files)} SVG file(s) to {out_dir}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
