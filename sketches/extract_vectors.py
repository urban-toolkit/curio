"""
Shared helpers for extract_single_svg.py — color quantization, SVG paths, paths.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def safe_stem(path: Path, max_len: int = 180) -> str:
    raw = path.stem
    s = re.sub(r"[^\w\-.]+", "_", raw).strip("_")
    if not s:
        s = "out"
    return s[:max_len]


def rgb_to_hex(rgb: Tuple[int, int, int]) -> str:
    r, g, b = (int(max(0, min(255, x))) for x in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def dominant_border_index(idx_map: np.ndarray) -> int:
    """Most common palette index along the image border (background guess)."""
    h, w = idx_map.shape
    if h < 2 or w < 2:
        return int(idx_map.flat[0])
    border = np.concatenate(
        [
            idx_map[0, :].ravel(),
            idx_map[-1, :].ravel(),
            idx_map[1:-1, 0].ravel(),
            idx_map[1:-1, -1].ravel(),
        ]
    )
    vals, counts = np.unique(border, return_counts=True)
    return int(vals[int(np.argmax(counts))])


def quantize_palette_rgba(img: Image.Image, k: int) -> Tuple[np.ndarray, List[Tuple[int, int, int]]]:
    """
    K-means quantize RGB (with alpha weighting) into k labels per pixel.
    Returns idx_map (H, W) int32 and palette list of (r,g,b) uint8 tuples.
    """
    arr = np.array(img.convert("RGBA"))
    h, w, _ = arr.shape
    rgb = arr[:, :, :3].astype(np.float32)
    alpha = arr[:, :, 3:4].astype(np.float32) / 255.0
    weighted = rgb * (0.25 + 0.75 * alpha)
    data = weighted.reshape(-1, 3)
    data = np.ascontiguousarray(data, dtype=np.float32)
    k = max(2, min(k, 256))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 1.0)
    _compactness, labels, centers = cv2.kmeans(
        data,
        k,
        None,
        criteria,
        attempts=3,
        flags=cv2.KMEANS_PP_CENTERS,
    )
    labels = labels.flatten().astype(np.int32)
    centers_u8 = np.clip(centers, 0, 255).astype(np.uint8)
    idx_map = labels.reshape(h, w)
    palette = [tuple(int(x) for x in row) for row in centers_u8]
    return idx_map, palette


def contour_to_svg_path(contour: np.ndarray) -> str:
    """OpenCV contour (N, 1, 2) or (N, 2) to closed SVG path."""
    if contour is None or len(contour) < 2:
        return ""
    pts = contour.reshape(-1, 2)
    x0, y0 = float(pts[0][0]), float(pts[0][1])
    parts: List[str] = [f"M {x0:.2f} {y0:.2f}"]
    for i in range(1, len(pts)):
        x, y = float(pts[i][0]), float(pts[i][1])
        parts.append(f"L {x:.2f} {y:.2f}")
    parts.append("Z")
    return " ".join(parts)
