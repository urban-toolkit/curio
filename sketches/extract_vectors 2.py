#!/usr/bin/env python3
"""
extract_brand_svgs.py

Identify and extract individual visual identity / branding components from:
- PDF files (vector-first when feasible, plus raster fallback)
- Image files (PNG/JPG/WebP/TIFF...)

Exports each detected component as a standalone SVG.
Also writes a manifest.json with metadata.

Dependencies:
  pip install pymupdf pillow opencv-python numpy
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

# Optional at runtime if PDFs are used
try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None  # type: ignore

import cv2


IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp"}
PDF_EXTS = {".pdf"}


# -----------------------------
# Data structures
# -----------------------------
@dataclass
class ComponentRecord:
    source_file: str
    page_index: Optional[int]  # for PDFs
    method: str                # "pdf_vector" | "pdf_raster" | "image_raster"
    bbox: Tuple[float, float, float, float]  # (x0,y0,x1,y1) in source coordinate space
    output_svg: str
    notes: Optional[str] = None


@dataclass
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def w(self) -> float:
        return max(0.0, self.x1 - self.x0)

    def h(self) -> float:
        return max(0.0, self.y1 - self.y0)

    def area(self) -> float:
        return self.w() * self.h()

    def expand(self, pad: float) -> "Rect":
        return Rect(self.x0 - pad, self.y0 - pad, self.x1 + pad, self.y1 + pad)

    def intersect(self, other: "Rect") -> bool:
        return not (self.x1 < other.x0 or self.x0 > other.x1 or self.y1 < other.y0 or self.y0 > other.y1)

    def distance_to(self, other: "Rect") -> float:
        """Minimum edge-to-edge distance between rectangles (0 if overlapping)."""
        if self.intersect(other):
            return 0.0
        dx = max(other.x0 - self.x1, self.x0 - other.x1, 0.0)
        dy = max(other.y0 - self.y1, self.y0 - other.y1, 0.0)
        return math.hypot(dx, dy)

    def to_tuple(self) -> Tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


# -----------------------------
# Utility
# -----------------------------
def iter_inputs(paths: Sequence[str]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        pp = Path(p)
        if pp.is_dir():
            for root, _, names in os.walk(pp):
                for n in names:
                    fp = Path(root) / n
                    ext = fp.suffix.lower()
                    if ext in IMG_EXTS or ext in PDF_EXTS:
                        files.append(fp)
        elif pp.is_file():
            ext = pp.suffix.lower()
            if ext in IMG_EXTS or ext in PDF_EXTS:
                files.append(pp)
        else:
            # Allow glob-ish patterns via manual expansion
            for gp in Path(".").glob(p):
                if gp.is_file():
                    ext = gp.suffix.lower()
                    if ext in IMG_EXTS or ext in PDF_EXTS:
                        files.append(gp)
    return sorted(set(files))


def safe_stem(path: Path) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", path.stem)
    return s[:120] if len(s) > 120 else s


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def pil_to_bgra(img: Image.Image) -> np.ndarray:
    """Return BGRA uint8 array."""
    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)  # RGBA
    bgra = arr[:, :, [2, 1, 0, 3]]        # BGRA for OpenCV
    return bgra


def bg_estimate_from_border(bgra: np.ndarray, border: int = 8) -> Tuple[int, int, int]:
    """Estimate background color as median of border pixels (ignores alpha)."""
    h, w = bgra.shape[:2]
    b = min(border, h // 2, w // 2)
    if b <= 0:
        px = bgra.reshape(-1, 4)
    else:
        top = bgra[:b, :, :3].reshape(-1, 3)
        bot = bgra[h - b :, :, :3].reshape(-1, 3)
        left = bgra[:, :b, :3].reshape(-1, 3)
        right = bgra[:, w - b :, :3].reshape(-1, 3)
        px = np.vstack([top, bot, left, right])
    med = np.median(px, axis=0).astype(np.int32)
    return int(med[2]), int(med[1]), int(med[0])  # return RGB


# -----------------------------
# Raster component extraction
# -----------------------------
def foreground_mask(bgra: np.ndarray, bg_rgb: Optional[Tuple[int, int, int]] = None) -> np.ndarray:
    """
    Build a foreground mask.
    - Uses alpha if present
    - Otherwise uses color distance from estimated background
    """
    h, w = bgra.shape[:2]
    alpha = bgra[:, :, 3]

    if np.max(alpha) > 0 and np.min(alpha) < 255:
        # True alpha image
        mask = (alpha > 0).astype(np.uint8) * 255
        return mask

    if bg_rgb is None:
        bg_rgb = bg_estimate_from_border(bgra)

    # Compute distance from background in RGB space
    bgr = bgra[:, :, :3].astype(np.int16)
    bg_bgr = np.array([bg_rgb[2], bg_rgb[1], bg_rgb[0]], dtype=np.int16)  # BGR
    diff = bgr - bg_bgr
    dist = np.sqrt(np.sum(diff * diff, axis=2))

    # Threshold: forgiving default
    mask = (dist > 18.0).astype(np.uint8) * 255

    # Clean up
    k = max(3, int(min(h, w) * 0.004) | 1)  # odd kernel
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    return mask


def connected_components(mask: np.ndarray, min_area: int, max_components: int) -> List[Rect]:
    """Return bounding rects for connected components in a binary mask."""
    num, labels, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), connectivity=8)
    rects: List[Rect] = []
    # stats: [label, x, y, w, h, area]
    for i in range(1, num):  # skip background
        x, y, w, h, area = stats[i]
        if area < min_area:
            continue
        rects.append(Rect(float(x), float(y), float(x + w), float(y + h)))

    rects.sort(key=lambda r: r.area(), reverse=True)
    return rects[:max_components]


def quantize_palette_rgba(rgba: Image.Image, k: int) -> Tuple[np.ndarray, List[Tuple[int, int, int]]]:
    """
    Quantize image to k colors, return:
      idx_map: HxW uint8 indices
      palette: list of RGB tuples
    """
    rgb = rgba.convert("RGB")
    q = rgb.quantize(colors=k, method=Image.MEDIANCUT)  # mode 'P'
    idx = np.array(q, dtype=np.uint8)

    pal = q.getpalette() or []
    palette: List[Tuple[int, int, int]] = []
    for i in range(k):
        base = 3 * i
        if base + 2 < len(pal):
            palette.append((pal[base], pal[base + 1], pal[base + 2]))
        else:
            palette.append((0, 0, 0))
    return idx, palette


def dominant_border_index(idx_map: np.ndarray, border: int = 6) -> int:
    h, w = idx_map.shape[:2]
    b = min(border, h // 2, w // 2)
    if b <= 0:
        vals = idx_map.reshape(-1)
    else:
        vals = np.concatenate(
            [
                idx_map[:b, :].reshape(-1),
                idx_map[h - b :, :].reshape(-1),
                idx_map[:, :b].reshape(-1),
                idx_map[:, w - b :].reshape(-1),
            ]
        )
    # mode
    binc = np.bincount(vals, minlength=256)
    return int(np.argmax(binc))


def contour_to_svg_path(contour: np.ndarray) -> str:
    """
    contour: Nx1x2 int array.
    Returns SVG path string with absolute coordinates.
    """
    pts = contour.reshape(-1, 2)
    if len(pts) < 3:
        return ""
    d = [f"M {pts[0,0]} {pts[0,1]}"]
    for p in pts[1:]:
        d.append(f"L {p[0]} {p[1]}")
    d.append("Z")
    return " ".join(d)


def vectorize_crop_to_svg(
    crop_rgba: Image.Image,
    out_svg: Path,
    color_k: int,
    simplify: float,
    min_contour_area: float,
) -> None:
    """
    Vectorize a cropped RGBA image into a multi-path SVG using:
      - palette quantization (k colors)
      - contour tracing per color
      - polygon simplification via approxPolyDP

    This produces filled shapes; no gradients.
    """
    w, h = crop_rgba.size

    idx_map, palette = quantize_palette_rgba(crop_rgba, k=max(2, color_k))
    bg_idx = dominant_border_index(idx_map)

    # Convert crop to BGRA for alpha gating
    bgra = pil_to_bgra(crop_rgba)
    alpha = bgra[:, :, 3]
    alpha_gate = (alpha > 0).astype(np.uint8) * 255 if (np.min(alpha) < 255) else None

    svg_parts: List[str] = []
    svg_parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}">')

    # For each palette entry (skip background)
    unique_idxs = np.unique(idx_map)
    for idx in unique_idxs:
        idx_int = int(idx)
        if idx_int == bg_idx:
            continue

        mask = (idx_map == idx_int).astype(np.uint8) * 255
        if alpha_gate is not None:
            mask = cv2.bitwise_and(mask, alpha_gate)

        if np.count_nonzero(mask) == 0:
            continue

        # Clean mask
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if not contours:
            continue

        fill = rgb_to_hex(palette[idx_int] if idx_int < len(palette) else (0, 0, 0))

        for c in contours:
            area = cv2.contourArea(c)
            if area < min_contour_area:
                continue

            # Simplify contour
            peri = cv2.arcLength(c, True)
            eps = max(0.5, float(simplify) * peri)
            approx = cv2.approxPolyDP(c, eps, True)

            d = contour_to_svg_path(approx)
            if not d:
                continue
            svg_parts.append(f'<path d="{d}" fill="{fill}" stroke="none"/>')

    svg_parts.append("</svg>")
    out_svg.write_text("\n".join(svg_parts), encoding="utf-8")


def extract_components_from_image_file(
    img_path: Path,
    out_dir: Path,
    min_area: int,
    max_components: int,
    color_k: int,
    simplify: float,
    min_contour_area: float,
) -> List[ComponentRecord]:
    img = Image.open(img_path)
    rgba = img.convert("RGBA")
    bgra = pil_to_bgra(rgba)

    mask = foreground_mask(bgra)
    rects = connected_components(mask, min_area=min_area, max_components=max_components)

    records: List[ComponentRecord] = []
    stem = safe_stem(img_path)

    for i, r in enumerate(rects):
        # Crop (pad a bit to keep antialiased edges)
        pad = 2
        x0 = max(0, int(r.x0) - pad)
        y0 = max(0, int(r.y0) - pad)
        x1 = min(rgba.size[0], int(r.x1) + pad)
        y1 = min(rgba.size[1], int(r.y1) + pad)
        crop = rgba.crop((x0, y0, x1, y1))

        out_svg = out_dir / f"{stem}_c{i:03d}.svg"
        vectorize_crop_to_svg(
            crop_rgba=crop,
            out_svg=out_svg,
            color_k=color_k,
            simplify=simplify,
            min_contour_area=min_contour_area,
        )

        records.append(
            ComponentRecord(
                source_file=str(img_path),
                page_index=None,
                method="image_raster",
                bbox=(float(x0), float(y0), float(x1), float(y1)),
                output_svg=str(out_svg),
            )
        )

    return records


# -----------------------------
# PDF vector extraction (best-effort)
# -----------------------------
def color_from_pymupdf(c: Any) -> Optional[str]:
    """
    PyMuPDF drawing colors may be:
      - None
      - tuple of floats 0..1 (r,g,b)
      - int or other
    """
    if c is None:
        return None
    if isinstance(c, (list, tuple)) and len(c) >= 3:
        r = int(max(0, min(255, round(float(c[0]) * 255))))
        g = int(max(0, min(255, round(float(c[1]) * 255))))
        b = int(max(0, min(255, round(float(c[2]) * 255))))
        return rgb_to_hex((r, g, b))
    return None


def drawings_to_svg_paths(drawings: List[Dict[str, Any]]) -> List[Tuple[Rect, str]]:
    """
    Convert PyMuPDF page.get_drawings() output into a list of (bbox, svg_path_element_string).

    This is "best-effort": PDFs vary; if a drawing op is unknown, we skip it.
    """
    out: List[Tuple[Rect, str]] = []

    for d in drawings:
        rect = d.get("rect", None)
        if rect is None:
            continue
        # rect is fitz.Rect-like
        r = Rect(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1))

        stroke = color_from_pymupdf(d.get("color", None))
        fill = color_from_pymupdf(d.get("fill", None))
        width = d.get("width", 1.0)
        opacity = d.get("opacity", None)

        items = d.get("items", [])
        if not items:
            continue

        path_cmds: List[str] = []
        started = False

        for it in items:
            if not it:
                continue
            op = it[0]
            try:
                if op == "m":
                    # move to
                    p = it[1]
                    path_cmds.append(f"M {p.x} {p.y}")
                    started = True
                elif op == "l":
                    # line: sometimes ("l", p1, p2) or ("l", p2)
                    p = it[-1]
                    if not started:
                        p0 = it[1]
                        path_cmds.append(f"M {p0.x} {p0.y}")
                        started = True
                    path_cmds.append(f"L {p.x} {p.y}")
                elif op == "c":
                    # cubic: ("c", p1, p2, p3, p4) (start + 2 ctrl + end) OR other variants
                    # We'll take last 3 points as (c1,c2,end)
                    pts = it[1:]
                    if len(pts) >= 3:
                        c1, c2, pe = pts[-3], pts[-2], pts[-1]
                        if not started and len(pts) >= 4:
                            ps = pts[0]
                            path_cmds.append(f"M {ps.x} {ps.y}")
                            started = True
                        path_cmds.append(f"C {c1.x} {c1.y} {c2.x} {c2.y} {pe.x} {pe.y}")
                elif op == "re":
                    # rectangle: ("re", rect)
                    rr = it[1]
                    x0, y0, x1, y1 = float(rr.x0), float(rr.y0), float(rr.x1), float(rr.y1)
                    path_cmds.append(f"M {x0} {y0} L {x1} {y0} L {x1} {y1} L {x0} {y1} Z")
                    started = True
                elif op in ("h", "z"):
                    path_cmds.append("Z")
                else:
                    # Unknown op; ignore
                    continue
            except Exception:
                continue

        if not path_cmds:
            continue

        # Style
        style_parts: List[str] = []
        if fill:
            style_parts.append(f'fill="{fill}"')
        else:
            style_parts.append('fill="none"')
        if stroke:
            style_parts.append(f'stroke="{stroke}"')
            style_parts.append(f'stroke-width="{float(width):.4g}"')
        else:
            style_parts.append('stroke="none"')
        if opacity is not None:
            try:
                style_parts.append(f'opacity="{float(opacity):.4g}"')
            except Exception:
                pass

        path = " ".join(path_cmds)
        out.append((r, f'<path d="{path}" {" ".join(style_parts)}/>' ))

    return out


def cluster_rects(rects: List[Rect], gap: float) -> List[List[int]]:
    """
    Cluster rectangles by overlap/proximity using union-find.
    gap: maximum distance between rects to be considered in the same cluster.
    """
    n = len(rects)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i in range(n):
        for j in range(i + 1, n):
            if rects[i].distance_to(rects[j]) <= gap:
                union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        r = find(i)
        clusters.setdefault(r, []).append(i)

    # Sort clusters by total area desc
    def cluster_area(ixs: List[int]) -> float:
        return sum(rects[i].area() for i in ixs)

    out = list(clusters.values())
    out.sort(key=cluster_area, reverse=True)
    return out


def union_bbox(rects: List[Rect]) -> Rect:
    x0 = min(r.x0 for r in rects)
    y0 = min(r.y0 for r in rects)
    x1 = max(r.x1 for r in rects)
    y1 = max(r.y1 for r in rects)
    return Rect(x0, y0, x1, y1)


def write_svg_group_from_paths(
    out_svg: Path,
    bbox: Rect,
    path_elements: List[str],
) -> None:
    w = bbox.w()
    h = bbox.h()
    x0, y0 = bbox.x0, bbox.y0

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg"',
        f' viewBox="0 0 {w:.6g} {h:.6g}">',
        f'<g transform="translate({-x0:.6g},{-y0:.6g})">',
    ]
    parts.extend(path_elements)
    parts.append("</g></svg>")
    out_svg.write_text("\n".join(parts), encoding="utf-8")


def process_pdf(
    pdf_path: Path,
    out_dir: Path,
    pdf_mode: str,
    zoom: float,
    min_area: int,
    max_components: int,
    color_k: int,
    simplify: float,
    min_contour_area: float,
    vector_gap: float,
) -> List[ComponentRecord]:
    if fitz is None:
        raise RuntimeError("PyMuPDF is not available. Install with: pip install pymupdf")

    records: List[ComponentRecord] = []
    stem = safe_stem(pdf_path)

    doc = fitz.open(pdf_path)

    for pno in range(len(doc)):
        page = doc[pno]

        # 1) Vector attempt
        if pdf_mode in ("vector", "hybrid"):
            try:
                drawings = page.get_drawings()
                paths = drawings_to_svg_paths(drawings)
                if paths:
                    rects = [r for (r, _) in paths]
                    clusters = cluster_rects(rects, gap=vector_gap)

                    for gi, idxs in enumerate(clusters):
                        group_rects = [rects[i] for i in idxs]
                        bbox = union_bbox(group_rects).expand(0.0)
                        elems = [paths[i][1] for i in idxs]

                        out_svg = out_dir / f"{stem}_p{pno:03d}_v{gi:03d}.svg"
                        write_svg_group_from_paths(out_svg, bbox, elems)

                        records.append(
                            ComponentRecord(
                                source_file=str(pdf_path),
                                page_index=pno,
                                method="pdf_vector",
                                bbox=bbox.to_tuple(),
                                output_svg=str(out_svg),
                            )
                        )
            except Exception as e:
                # Continue to raster path
                records.append(
                    ComponentRecord(
                        source_file=str(pdf_path),
                        page_index=pno,
                        method="pdf_vector",
                        bbox=(0, 0, 0, 0),
                        output_svg="",
                        notes=f"Vector extraction skipped/failure: {type(e).__name__}: {e}",
                    )
                )

        # 2) Raster component extraction
        if pdf_mode in ("raster", "hybrid"):
            # Render page
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=True)
            img = Image.frombytes("RGBA", (pix.width, pix.height), pix.samples)

            # Run the same pipeline as for raster images
            tmp_img_path = out_dir / f"{stem}_p{pno:03d}_render.png"
            # Save render for debugging/repro (optional; comment out if unwanted)
            img.save(tmp_img_path)

            page_records = extract_components_from_image_file(
                tmp_img_path,
                out_dir=out_dir,
                min_area=min_area,
                max_components=max_components,
                color_k=color_k,
                simplify=simplify,
                min_contour_area=min_contour_area,
            )
            # Rewrite source_file/page_index/method and adjust bbox back to page pixel-space (already)
            for r in page_records:
                r.source_file = str(pdf_path)
                r.page_index = pno
                r.method = "pdf_raster"
            records.extend(page_records)

    return records


# -----------------------------
# Main
# -----------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extract individual branding/visual identity components from PDF + image files into SVGs."
    )
    ap.add_argument("inputs", nargs="+", help="Input file(s) and/or folder(s).")
    ap.add_argument("--out", default="out_svgs", help="Output directory.")
    ap.add_argument("--pdf-mode", choices=["hybrid", "vector", "raster"], default="hybrid",
                    help="PDF extraction strategy.")
    ap.add_argument("--zoom", type=float, default=4.0,
                    help="PDF raster render zoom (higher = sharper, bigger). 4.0 ~ 288dpi.")
    ap.add_argument("--min-area", type=int, default=2500,
                    help="Minimum connected-component area (pixels) for raster extraction.")
    ap.add_argument("--max-components", type=int, default=150,
                    help="Max components per raster image/page.")
    ap.add_argument("--color-k", type=int, default=8,
                    help="Palette size for raster vectorization (higher = more detail).")
    ap.add_argument("--simplify", type=float, default=0.002,
                    help="Contour simplification factor (approxPolyDP epsilon = simplify * perimeter).")
    ap.add_argument("--min-contour-area", type=float, default=12.0,
                    help="Minimum contour area (pixels) when building SVG paths.")
    ap.add_argument("--vector-gap", type=float, default=2.0,
                    help="Max distance (PDF units) to cluster nearby vector drawings into one component.")
    args = ap.parse_args()

    out_dir = Path(args.out)
    ensure_dir(out_dir)

    files = iter_inputs(args.inputs)
    if not files:
        print("No supported files found (PDF or images).", file=sys.stderr)
        return 2

    manifest: List[ComponentRecord] = []

    for fp in files:
        ext = fp.suffix.lower()
        try:
            if ext in PDF_EXTS:
                recs = process_pdf(
                    pdf_path=fp,
                    out_dir=out_dir,
                    pdf_mode=args.pdf_mode,
                    zoom=args.zoom,
                    min_area=args.min_area,
                    max_components=args.max_components,
                    color_k=args.color_k,
                    simplify=args.simplify,
                    min_contour_area=args.min_contour_area,
                    vector_gap=args.vector_gap,
                )
                manifest.extend(recs)
            elif ext in IMG_EXTS:
                recs = extract_components_from_image_file(
                    img_path=fp,
                    out_dir=out_dir,
                    min_area=args.min_area,
                    max_components=args.max_components,
                    color_k=args.color_k,
                    simplify=args.simplify,
                    min_contour_area=args.min_contour_area,
                )
                manifest.extend(recs)
        except Exception as e:
            manifest.append(
                ComponentRecord(
                    source_file=str(fp),
                    page_index=None,
                    method="error",
                    bbox=(0, 0, 0, 0),
                    output_svg="",
                    notes=f"{type(e).__name__}: {e}",
                )
            )

    # Write manifest.json
    man_path = out_dir / "manifest.json"
    man_path.write_text(json.dumps([asdict(r) for r in manifest], indent=2), encoding="utf-8")

    # Summary
    n_svgs = sum(1 for r in manifest if r.output_svg and r.output_svg.endswith(".svg"))
    print(f"Done. Wrote {n_svgs} SVGs.")
    print(f"Manifest: {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())