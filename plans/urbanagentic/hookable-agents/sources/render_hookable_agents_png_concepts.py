from __future__ import annotations

import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Sequence

from PIL import Image, ImageDraw, ImageFont
from fontTools.svgLib.path.parser import parse_path

MPL_CACHE = Path("/private/tmp/curio-hookable-agents-matplotlib")
XDG_CACHE = Path("/private/tmp/curio-hookable-agents-cache")
MPL_CACHE.mkdir(parents=True, exist_ok=True)
XDG_CACHE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE))
os.environ.setdefault("XDG_CACHE_HOME", str(XDG_CACHE))

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
from matplotlib.transforms import Affine2D


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[2]
OUT = ROOT / "png-concepts"
CURIO_LOGO = REPO_ROOT / "utk_curio/frontend/urban-workflows/src/assets/curio-2.png"
FA_SOLID = REPO_ROOT / "utk_curio/frontend/urban-workflows/node_modules/@fortawesome/free-solid-svg-icons"
FA_BRANDS = REPO_ROOT / "utk_curio/frontend/urban-workflows/node_modules/@fortawesome/free-brands-svg-icons"
W, H = 1672, 941
RENDER_SCALE = 3
DRAWER_W = 560
TOP_H = 65
CANVAS_X = 0
CANVAS_Y = TOP_H
CANVAS_W = W - DRAWER_W
CANVAS_H = H - CANVAS_Y

# ── Curio design tokens (styles/curioTokens.css + live UI reference) ──────
DARK = "#1e1f23"          # top bar, palette, primary buttons/chrome
NAV = DARK
PANEL = "#ffffff"
CANVAS = "#f0f0f0"        # react-flow canvas background
DOT = "#c9cacd"           # faint dot grid (a0a0a0 @ low opacity)
BORDER = "#e5e5e7"
BORDER_STRONG = "#d0d0d5"
TEXT = "#1e1f23"          # text-primary
SECONDARY = "#6b6b76"     # text-secondary
MUTED = "#9e9e9e"         # text-muted
ON_DARK = "#fbfcf6"
PEACH = "#fbaa69"         # node play button / unsaved / hover accent
SAVE_GREEN = "#5cb85c"    # saved floppy icon / active AI toggle

# Accent pairs (fg / soft bg) — the four Curio thumbnail accents
ORANGE = "#e86a3c"; ORANGE_SOFT = "#ffe3da"
BLUE = "#3567c7"; BLUE_SOFT = "#dce8ff"
GREEN = "#2f8f4a"; GREEN_SOFT = "#dff2e1"
PURPLE = "#7a4bd1"; PURPLE_SOFT = "#eadcfb"

# Node-type left-accent bar colors (styles.tsx nodeTypeBorderColor)
BAR_DATA = "#3498db"; BAR_COMPUTE = "#8e44ad"; BAR_VIS = "#1abc9c"; BAR_FALLBACK = "#95a5a6"

# Code syntax colours for node body previews
CODE_KW = "#a626a4"; CODE_STR = "#c18401"; CODE_FN = "#4078f2"; CODE_TXT = "#383a42"; CODE_NUM = "#b9bcc4"


FONTS_DIR = Path(__file__).resolve().parent / "fonts"
RUBIK = FONTS_DIR / "Rubik.ttf"
ROBOTO_MONO = FONTS_DIR / "RobotoMono.ttf"


def font(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    """Curio ships Rubik (Google Fonts). Load the variable file and pin the
    named weight axis so the mockups use the app's real typeface."""
    try:
        f = ImageFont.truetype(str(RUBIK), size * RENDER_SCALE)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    except OSError:
        pass
    for candidate in [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size * RENDER_SCALE)
        except OSError:
            pass
    return ImageFont.load_default()


def mono(size: int) -> ImageFont.FreeTypeFont:
    # Roboto Mono (bundled) keeps the PNG node code matching the SVG's declared
    # monospace family; fall back to a system mono if the file is missing.
    try:
        return ImageFont.truetype(str(ROBOTO_MONO), size * RENDER_SCALE)
    except OSError:
        pass
    for candidate in [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/Monaco.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ]:
        try:
            return ImageFont.truetype(candidate, size * RENDER_SCALE)
        except OSError:
            pass
    return ImageFont.load_default()


FONT_META: dict[int, tuple[int, str, str]] = {}


def _rk(size: int, weight: str = "Regular") -> ImageFont.FreeTypeFont:
    fobj = font(size, weight)
    FONT_META[id(fobj)] = (size, weight, "Rubik")
    return fobj


def _mn(size: int) -> ImageFont.FreeTypeFont:
    fobj = mono(size)
    FONT_META[id(fobj)] = (size, "Regular", "Roboto Mono")
    return fobj


F = {
    "tiny": _rk(10),
    "micro": _rk(11),
    "small": _rk(12),
    "body": _rk(13),
    "body_bold": _rk(13, "SemiBold"),
    "label": _rk(14, "SemiBold"),
    "title": _rk(18, "SemiBold"),
    "nav": _rk(15, "Bold"),
    "brand": _rk(25, "Bold"),
    "screen": _rk(12, "SemiBold"),
    "h1": _rk(30, "Bold"),
    "badge": _rk(9, "Bold"),
    "mono": _mn(11),
    "mono_sm": _mn(10),
    "num": _mn(10),
}


def new_canvas() -> Image.Image:
    return Image.new("RGB", (W * RENDER_SCALE, H * RENDER_SCALE), CANVAS)


def rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i : i + 2], 16) for i in (0, 2, 4)) + (alpha,)


def sc(value):
    if isinstance(value, (int, float)):
        return int(round(value * RENDER_SCALE))
    if isinstance(value, tuple):
        return tuple(sc(v) for v in value)
    if isinstance(value, list):
        return [sc(v) for v in value]
    return value


class ScaledDraw:
    def __init__(self, image: Image.Image):
        self._image = image
        self._draw = ImageDraw.Draw(image)

    def rectangle(self, xy, *args, **kwargs):
        if "width" in kwargs:
            kwargs["width"] = max(1, sc(kwargs["width"]))
        return self._draw.rectangle(sc(xy), *args, **kwargs)

    def rounded_rectangle(self, xy, radius=0, *args, **kwargs):
        if "width" in kwargs:
            kwargs["width"] = max(1, sc(kwargs["width"]))
        return self._draw.rounded_rectangle(sc(xy), radius=sc(radius), *args, **kwargs)

    def line(self, xy, *args, **kwargs):
        if "width" in kwargs:
            kwargs["width"] = max(1, sc(kwargs["width"]))
        return self._draw.line(sc(xy), *args, **kwargs)

    def ellipse(self, xy, *args, **kwargs):
        if "width" in kwargs:
            kwargs["width"] = max(1, sc(kwargs["width"]))
        return self._draw.ellipse(sc(xy), *args, **kwargs)

    def arc(self, xy, start, end, *args, **kwargs):
        if "width" in kwargs:
            kwargs["width"] = max(1, sc(kwargs["width"]))
        return self._draw.arc(sc(xy), start, end, *args, **kwargs)

    def polygon(self, xy, *args, **kwargs):
        return self._draw.polygon(sc(xy), *args, **kwargs)

    def dim(self, box, color=(18, 19, 23), alpha=120):
        x1, y1, x2, y2 = sc(box)
        layer = Image.new("RGBA", self._image.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle((x1, y1, x2, y2), fill=tuple(color) + (alpha,))
        self._image.paste(Image.alpha_composite(self._image.convert("RGBA"), layer).convert("RGB"), (0, 0))

    def text(self, xy, *args, **kwargs):
        return self._draw.text(sc(xy), *args, **kwargs)

    def textbbox(self, xy, *args, **kwargs):
        bbox = self._draw.textbbox(sc(xy), *args, **kwargs)
        return tuple(v / RENDER_SCALE for v in bbox)


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _colspec(c) -> tuple[str, float]:
    """Return (svg-color, opacity) supporting #rrggbb, #rrggbbaa and names."""
    if c is None:
        return ("none", 1.0)
    if isinstance(c, str) and c.startswith("#") and len(c) == 9:
        return (c[:7], int(c[7:9], 16) / 255)
    return (c, 1.0)


_WEIGHTS = {"Light": 300, "Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700}
_MEASURE = None
_METRICS: dict[int, tuple[float, float]] = {}


def _measure_draw() -> ImageDraw.ImageDraw:
    global _MEASURE
    if _MEASURE is None:
        _MEASURE = ImageDraw.Draw(Image.new("RGB", (4, 4)))
    return _MEASURE


def _font_metrics(fobj) -> tuple[float, float]:
    if id(fobj) not in _METRICS:
        a, d = fobj.getmetrics()
        _METRICS[id(fobj)] = (a / RENDER_SCALE, d / RENDER_SCALE)
    return _METRICS[id(fobj)]


class SvgDraw:
    """A drawing surface mirroring ScaledDraw's API but emitting editable,
    Figma-ready SVG. Text stays as <text> (Rubik), icons as <path>, shapes as
    primitives. Text metrics are delegated to the real PIL fonts so every
    coordinate matches the PNG renders exactly."""

    def __init__(self):
        self.elems: list[str] = []
        self.defs: list[str] = []
        self._image = self  # so isinstance-unaware helpers can pass draw._image

    # ── geometry ──────────────────────────────────────────────────────────
    def _paint(self, fill, outline, width) -> str:
        fc, fo = _colspec(fill)
        parts = [f'fill="{fc}"']
        if fo != 1.0:
            parts.append(f'fill-opacity="{fo:.3f}"')
        if outline is not None:
            sc_, so = _colspec(outline)
            parts.append(f'stroke="{sc_}" stroke-width="{width}"')
            if so != 1.0:
                parts.append(f'stroke-opacity="{so:.3f}"')
        return " ".join(parts)

    @staticmethod
    def _points(xy):
        if xy and isinstance(xy[0], (int, float)):
            return [(xy[i], xy[i + 1]) for i in range(0, len(xy), 2)]
        return list(xy)

    def rectangle(self, xy, fill=None, outline=None, width=1):
        x1, y1, x2, y2 = xy
        self.elems.append(f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" {self._paint(fill, outline, width)}/>')

    def dim(self, box, color=(18, 19, 23), alpha=120):
        x1, y1, x2, y2 = box
        r, g, b = color
        self.elems.append(f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" fill="rgb({r},{g},{b})" fill-opacity="{alpha / 255:.3f}"/>')

    def rounded_rectangle(self, xy, radius=0, fill=None, outline=None, width=1, shadow=False):
        x1, y1, x2, y2 = xy
        if shadow:
            for dy, op in ((5, 0.14), (2, 0.10)):
                self.elems.append(f'<rect x="{x1}" y="{y1 + dy}" width="{x2 - x1}" height="{y2 - y1}" rx="{radius}" fill="#1f222b" fill-opacity="{op}"/>')
        self.elems.append(f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" rx="{radius}" {self._paint(fill, outline, width)}/>')

    def line(self, xy, fill=None, width=1, joint=None):
        pts = self._points(xy)
        col, op = _colspec(fill)
        extra = f' stroke-opacity="{op:.3f}"' if op != 1.0 else ""
        if len(pts) == 2:
            (x1, y1), (x2, y2) = pts
            self.elems.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{col}" stroke-width="{width}" stroke-linecap="round"{extra}/>')
        else:
            p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
            self.elems.append(f'<polyline points="{p}" fill="none" stroke="{col}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"{extra}/>')

    def ellipse(self, xy, fill=None, outline=None, width=1):
        x1, y1, x2, y2 = xy
        self.elems.append(f'<ellipse cx="{(x1 + x2) / 2}" cy="{(y1 + y2) / 2}" rx="{(x2 - x1) / 2}" ry="{(y2 - y1) / 2}" {self._paint(fill, outline, width)}/>')

    def polygon(self, points, fill=None, outline=None, width=1):
        p = " ".join(f"{x:.2f},{y:.2f}" for x, y in self._points(points))
        self.elems.append(f'<polygon points="{p}" {self._paint(fill, outline, width)}/>')

    def arc(self, xy, start, end, fill=None, width=1):
        x1, y1, x2, y2 = xy
        cx, cy, rx, ry = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) / 2, (y2 - y1) / 2
        sa, ea = math.radians(start), math.radians(end)
        sx, sy = cx + rx * math.cos(sa), cy + ry * math.sin(sa)
        ex, ey = cx + rx * math.cos(ea), cy + ry * math.sin(ea)
        large = 1 if (end - start) % 360 > 180 else 0
        col, _ = _colspec(fill)
        self.elems.append(f'<path d="M {sx:.2f} {sy:.2f} A {rx} {ry} 0 {large} 1 {ex:.2f} {ey:.2f}" fill="none" stroke="{col}" stroke-width="{width}"/>')

    def text(self, xy, value, fill=None, font=None, anchor=None):
        x, y = xy
        size, weight, family = FONT_META.get(id(font), (13, "Regular", "Rubik"))
        ascent, descent = _font_metrics(font) if font is not None else (size * 0.8, size * 0.2)
        h = (anchor or "la")[0]
        v = (anchor or "la")[1] if len(anchor or "la") > 1 else "a"
        ta = {"l": "start", "m": "middle", "r": "end"}[h]
        if v == "a":
            by = y + ascent
        elif v == "m":
            by = y + (ascent - descent) / 2
        elif v == "d":
            by = y - descent
        else:
            by = y
        col, op = _colspec(fill)
        extra = f' fill-opacity="{op:.3f}"' if op != 1.0 else ""
        self.elems.append(
            f'<text x="{x:.2f}" y="{by:.2f}" font-family="{family}" font-size="{size}" '
            f'font-weight="{_WEIGHTS.get(weight, 400)}" fill="{col}"{extra} text-anchor="{ta}">{_xml_escape(value)}</text>'
        )

    def textbbox(self, xy, value, font=None, **kwargs):
        b = _measure_draw().textbbox((0, 0), value, font=font)
        x, y = xy
        return (x + b[0] / RENDER_SCALE, y + b[1] / RENDER_SCALE, x + b[2] / RENDER_SCALE, y + b[3] / RENDER_SCALE)

    # ── vector Font Awesome glyph + raster logo embed ──────────────────────
    def fa(self, x, y, icon_ref, color, size):
        w, h, path = _load_fa_path(icon_ref)
        inset = max(1, size * 0.07)
        scale = min((size - inset * 2) / w, (size - inset * 2) / h)
        tx = x + (size - w * scale) / 2
        ty = y + (size - h * scale) / 2
        col, _ = _colspec(color)
        self.elems.append(f'<path d="{path}" fill="{col}" transform="translate({tx:.2f},{ty:.2f}) scale({scale:.4f})"/>')

    def image_embed(self, x, y, w, h, png_bytes):
        import base64
        data = base64.b64encode(png_bytes).decode("ascii")
        self.elems.append(f'<image x="{x}" y="{y}" width="{w:.2f}" height="{h:.2f}" href="data:image/png;base64,{data}"/>')

    def dot_pattern(self, top):
        self.defs.append(
            f'<pattern id="dots" x="6" y="{top + 8}" width="20" height="20" patternUnits="userSpaceOnUse">'
            f'<circle cx="0" cy="0" r="1" fill="{DOT}"/></pattern>'
        )
        self.elems.append(f'<rect x="0" y="{top}" width="{W}" height="{H - top}" fill="url(#dots)"/>')

    def to_svg(self) -> str:
        defs = f'<defs>{"".join(self.defs)}</defs>' if self.defs else ""
        body = "\n".join(self.elems)
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Rubik">\n'
            f'{defs}\n{body}\n</svg>\n'
        )


class _MplPathPen:
    def __init__(self):
        self.vertices: list[tuple[float, float]] = []
        self.codes: list[int] = []
        self._current: tuple[float, float] | None = None
        self._start: tuple[float, float] | None = None

    def moveTo(self, p0):
        point = (float(p0[0]), float(p0[1]))
        self.vertices.append(point)
        self.codes.append(MplPath.MOVETO)
        self._current = point
        self._start = point

    def lineTo(self, p1):
        point = (float(p1[0]), float(p1[1]))
        self.vertices.append(point)
        self.codes.append(MplPath.LINETO)
        self._current = point

    def curveTo(self, *points):
        for point in points:
            self.vertices.append((float(point[0]), float(point[1])))
            self.codes.append(MplPath.CURVE4)
        if points:
            self._current = (float(points[-1][0]), float(points[-1][1]))

    def qCurveTo(self, *points):
        clean_points = [point for point in points if point is not None]
        if len(clean_points) == 1:
            self.lineTo(clean_points[0])
            return
        for i in range(0, len(clean_points) - 1, 2):
            control, end = clean_points[i], clean_points[i + 1]
            self.vertices.append((float(control[0]), float(control[1])))
            self.codes.append(MplPath.CURVE3)
            self.vertices.append((float(end[0]), float(end[1])))
            self.codes.append(MplPath.CURVE3)
            self._current = (float(end[0]), float(end[1]))

    def closePath(self):
        if self._start is None:
            return
        self.vertices.append(self._start)
        self.codes.append(MplPath.CLOSEPOLY)
        self._current = self._start


def _fa_ref_to_module(icon_ref: str) -> tuple[Path, str]:
    style, raw_name = icon_ref.split(":", 1)
    module_dir = FA_BRANDS if style == "fa-brands" else FA_SOLID
    const_name = "fa" + "".join(part[:1].upper() + part[1:] for part in raw_name.split("-"))
    return module_dir / f"{const_name}.js", const_name


@lru_cache(maxsize=None)
def _load_fa_path(icon_ref: str) -> tuple[int, int, str]:
    module_path, const_name = _fa_ref_to_module(icon_ref)
    if not module_path.exists():
        raise FileNotFoundError(f"Missing Font Awesome icon module for {icon_ref}: {module_path}")
    source = module_path.read_text()
    width_match = re.search(r"var width = (\d+);", source)
    height_match = re.search(r"var height = (\d+);", source)
    path_match = re.search(r"var svgPathData = '([^']+)';", source, flags=re.S)
    if not width_match or not height_match or not path_match:
        raise ValueError(f"Could not parse Font Awesome icon module {const_name}")
    path_data = path_match.group(1).replace("\\'", "'")
    return int(width_match.group(1)), int(height_match.group(1)), path_data


@lru_cache(maxsize=None)
def _render_fa_icon(icon_ref: str, color: str, px: int) -> Image.Image:
    width, height, path_data = _load_fa_path(icon_ref)
    pen = _MplPathPen()
    parse_path(path_data, pen)
    mpl_path = MplPath(pen.vertices, pen.codes)
    dpi = 96
    fig = Figure(figsize=(px / dpi, px / dpi), dpi=dpi)
    fig.patch.set_alpha(0)
    canvas = FigureCanvasAgg(fig)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, px)
    ax.set_ylim(px, 0)
    ax.axis("off")
    inset = max(1, int(px * 0.07))
    scale = min((px - inset * 2) / width, (px - inset * 2) / height)
    tx = (px - width * scale) / 2
    ty = (px - height * scale) / 2
    patch = PathPatch(
        mpl_path,
        facecolor=color,
        edgecolor="none",
        transform=Affine2D().scale(scale).translate(tx, ty) + ax.transData,
    )
    ax.add_patch(patch)
    canvas.draw()
    return Image.frombuffer("RGBA", (px, px), canvas.buffer_rgba(), "raw", "RGBA", 0, 1).copy()


def repo_icon(draw, x: int, y: int, icon_ref: str, color: str, size: int = 28) -> None:
    if isinstance(draw, SvgDraw):
        draw.fa(x, y, icon_ref, color, size)
        return
    px = max(1, sc(size))
    icon = _render_fa_icon(icon_ref, color, px)
    draw._image.paste(icon, sc((x, y)), icon)


def shadowed_round(
    draw,
    box: tuple[int, int, int, int],
    radius: int,
    fill: str,
    outline: str | None = None,
    width: int = 1,
    shadow: bool = True,
) -> None:
    if isinstance(draw, SvgDraw):
        draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width, shadow=shadow)
        return
    img = draw._image
    d = ImageDraw.Draw(img)
    x1, y1, x2, y2 = sc(box)
    if shadow:
        for off, alpha in [(3, 42), (6, 18)]:
            d.rounded_rectangle((x1, y1 + sc(off), x2, y2 + sc(off)), radius=sc(radius), fill=rgba("#1f222b", alpha))
    d.rounded_rectangle((x1, y1, x2, y2), radius=sc(radius), fill=fill, outline=outline, width=max(1, sc(width)))


def text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, fill: str = TEXT, f=None, anchor=None) -> None:
    draw.text(xy, value, fill=fill, font=f or F["body"], anchor=anchor)


def wrap(draw: ImageDraw.ImageDraw, value: str, max_width: int, f: ImageFont.FreeTypeFont) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if draw.textbbox((0, 0), trial, font=f)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, fill: str, fg: str, w: int | None = None) -> int:
    bbox = draw.textbbox((0, 0), label, font=F["tiny"])
    width = w or max(34, bbox[2] - bbox[0] + 16)
    draw.rounded_rectangle((x, y, x + width, y + 19), radius=9, fill=fill)
    draw.text((x + width // 2, y + 9), label, fill=fg, font=F["tiny"], anchor="mm")
    return width


def bot(draw: ImageDraw.ImageDraw, x: int, y: int, color: str, scale: float = 1.0) -> None:
    w, h = int(22 * scale), int(18 * scale)
    r = int(6 * scale)
    draw.rounded_rectangle((x, y + 4, x + w, y + 4 + h), radius=r, fill=color)
    eye = max(2, int(3 * scale))
    draw.ellipse((x + int(6 * scale), y + int(10 * scale), x + int(6 * scale) + eye, y + int(10 * scale) + eye), fill="white")
    draw.ellipse((x + w - int(8 * scale), y + int(10 * scale), x + w - int(8 * scale) + eye, y + int(10 * scale) + eye), fill="white")
    draw.line((x + w // 2, y + 4, x + w // 2, y), fill=color, width=max(1, int(2 * scale)))
    draw.ellipse((x + w // 2 - 2, y - 3, x + w // 2 + 2, y + 1), fill=color)


def curio_icon(draw: ImageDraw.ImageDraw, x: int, y: int, name: str, color: str, size: int = 28) -> None:
    s = size
    cx, cy = x + s / 2, y + s / 2
    lw = max(2, int(size / 13))

    if name == "upload":
        draw.arc((x + 3, y + 8, x + s - 3, y + s - 3), 200, 345, fill=color, width=lw)
        draw.line((cx, y + 6, cx, y + s - 7), fill=color, width=lw)
        draw.line((cx, y + 6, cx - 6, y + 13), fill=color, width=lw)
        draw.line((cx, y + 6, cx + 6, y + 13), fill=color, width=lw)
        draw.line((x + 5, y + s - 5, x + s - 5, y + s - 5), fill=color, width=lw)
    elif name == "download":
        draw.arc((x + 3, y + 5, x + s - 3, y + s - 6), 200, 345, fill=color, width=lw)
        draw.line((cx, y + 6, cx, y + s - 8), fill=color, width=lw)
        draw.line((cx, y + s - 8, cx - 6, y + s - 15), fill=color, width=lw)
        draw.line((cx, y + s - 8, cx + 6, y + s - 15), fill=color, width=lw)
        draw.line((x + 5, y + s - 5, x + s - 5, y + s - 5), fill=color, width=lw)
    elif name == "search":
        draw.ellipse((x + 4, y + 4, x + s - 9, y + s - 9), outline=color, width=lw)
        draw.line((x + s - 10, y + s - 10, x + s - 3, y + s - 3), fill=color, width=lw)
    elif name == "database":
        draw.ellipse((x + 4, y + 4, x + s - 4, y + 12), outline=color, width=lw)
        draw.line((x + 4, y + 8, x + 4, y + s - 8), fill=color, width=lw)
        draw.line((x + s - 4, y + 8, x + s - 4, y + s - 8), fill=color, width=lw)
        draw.ellipse((x + 4, y + s - 12, x + s - 4, y + s - 4), outline=color, width=lw)
        draw.arc((x + 4, y + 11, x + s - 4, y + 19), 0, 180, fill=color, width=lw)
    elif name == "server":
        for yy in [y + 4, y + 12, y + 20]:
            draw.rounded_rectangle((x + 4, yy, x + s - 4, yy + 6), radius=2, outline=color, width=lw)
            draw.ellipse((x + s - 10, yy + 2, x + s - 7, yy + 5), fill=color)
    elif name == "cube":
        pts_top = [(cx, y + 3), (x + s - 5, y + 10), (cx, y + 17), (x + 5, y + 10)]
        pts_left = [(x + 5, y + 10), (cx, y + 17), (cx, y + s - 4), (x + 5, y + s - 11)]
        pts_right = [(x + s - 5, y + 10), (cx, y + 17), (cx, y + s - 4), (x + s - 5, y + s - 11)]
        draw.polygon(pts_top, outline=color)
        draw.line(pts_top + [pts_top[0]], fill=color, width=lw)
        draw.line(pts_left + [pts_left[0]], fill=color, width=lw)
        draw.line(pts_right + [pts_right[0]], fill=color, width=lw)
    elif name == "layout":
        draw.rounded_rectangle((x + 4, y + 5, x + s - 4, y + s - 5), radius=3, outline=color, width=lw)
        draw.rectangle((x + 8, y + 9, x + 15, y + 16), outline=color, width=lw)
        draw.rectangle((x + s - 15, y + 9, x + s - 8, y + 16), outline=color, width=lw)
        draw.rectangle((x + 8, y + s - 16, x + s - 8, y + s - 9), outline=color, width=lw)
    elif name == "python":
        draw.rounded_rectangle((x + 5, y + 4, x + 17, y + 17), radius=5, outline=color, width=lw)
        draw.rounded_rectangle((x + 11, y + 11, x + s - 5, y + s - 4), radius=5, outline=color, width=lw)
        draw.ellipse((x + 9, y + 8, x + 12, y + 11), fill=color)
        draw.ellipse((x + s - 12, y + s - 11, x + s - 9, y + s - 8), fill=color)
    elif name == "javascript":
        draw.line((x + 8, y + 8, x + 4, cy, x + 8, y + s - 8), fill=color, width=lw)
        draw.line((x + s - 8, y + 8, x + s - 4, cy, x + s - 8, y + s - 8), fill=color, width=lw)
        draw.line((x + 13, y + s - 7, x + s - 13, y + 7), fill=color, width=lw)
    elif name == "city":
        draw.rectangle((x + 5, y + 10, x + 12, y + s - 5), outline=color, width=lw)
        draw.rectangle((x + 13, y + 5, x + 21, y + s - 5), outline=color, width=lw)
        draw.rectangle((x + 22, y + 13, x + s - 5, y + s - 5), outline=color, width=lw)
        for wx in [x + 8, x + 16, x + 25]:
            draw.line((wx, y + 17, wx, y + 19), fill=color, width=lw)
        draw.line((x + 3, y + s - 5, x + s - 3, y + s - 5), fill=color, width=lw)
    elif name == "chart":
        draw.line((x + 5, y + s - 5, x + 5, y + 5), fill=color, width=lw)
        draw.line((x + 5, y + s - 5, x + s - 4, y + s - 5), fill=color, width=lw)
        pts = [(x + 7, y + s - 9), (x + 13, y + 16), (x + 19, y + 20), (x + s - 5, y + 8)]
        draw.line(pts, fill=color, width=lw)
    elif name == "table":
        draw.rounded_rectangle((x + 4, y + 5, x + s - 4, y + s - 5), radius=2, outline=color, width=lw)
        draw.line((x + 4, y + 13, x + s - 4, y + 13), fill=color, width=lw)
        draw.line((x + 4, y + 21, x + s - 4, y + 21), fill=color, width=lw)
        draw.line((x + 13, y + 5, x + 13, y + s - 5), fill=color, width=lw)
        draw.line((x + 22, y + 5, x + 22, y + s - 5), fill=color, width=lw)
    elif name == "save":
        draw.rounded_rectangle((x + 5, y + 4, x + s - 5, y + s - 4), radius=2, outline=color, width=lw)
        draw.rectangle((x + 9, y + 5, x + s - 10, y + 12), outline=color, width=lw)
        draw.rectangle((x + 10, y + s - 13, x + s - 10, y + s - 4), outline=color, width=lw)
    elif name == "share":
        nodes = [(x + 8, cy), (x + s - 8, y + 8), (x + s - 8, y + s - 8)]
        draw.line((nodes[0], nodes[1]), fill=color, width=lw)
        draw.line((nodes[0], nodes[2]), fill=color, width=lw)
        for nx, ny in nodes:
            draw.ellipse((nx - 4, ny - 4, nx + 4, ny + 4), outline=color, width=lw)
    elif name == "run":
        triangle(draw, [(x + 8, y + 5), (x + 8, y + s - 5), (x + s - 6, cy)], color)
    elif name == "refresh":
        draw.arc((x + 5, y + 5, x + s - 5, y + s - 5), 35, 315, fill=color, width=lw)
        triangle(draw, [(x + s - 8, y + 8), (x + s - 4, y + 17), (x + s - 14, y + 15)], color)
    elif name == "bell":
        draw.arc((x + 7, y + 6, x + s - 7, y + 22), 180, 360, fill=color, width=lw)
        draw.line((x + 7, y + 15, x + 7, y + 22), fill=color, width=lw)
        draw.line((x + s - 7, y + 15, x + s - 7, y + 22), fill=color, width=lw)
        draw.line((x + 5, y + 22, x + s - 5, y + 22), fill=color, width=lw)
        draw.ellipse((cx - 2, y + 24, cx + 2, y + 28), fill=color)
    elif name == "help":
        draw.ellipse((x + 5, y + 5, x + s - 5, y + s - 5), outline=color, width=lw)
        text(draw, (int(cx), int(cy + 1)), "?", color, F["small"], anchor="mm")
    elif name == "gear":
        draw.ellipse((x + 8, y + 8, x + s - 8, y + s - 8), outline=color, width=lw)
        for ang in range(0, 360, 45):
            dx = math.cos(math.radians(ang))
            dy = math.sin(math.radians(ang))
            draw.line((cx + dx * 9, cy + dy * 9, cx + dx * 13, cy + dy * 13), fill=color, width=lw)
        draw.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), outline=color, width=lw)
    elif name == "menu":
        for yy in [y + 8, y + 14, y + 20]:
            draw.line((x + 6, yy, x + s - 6, yy), fill=color, width=lw)


def triangle(draw: ImageDraw.ImageDraw, points: Sequence[tuple[float, float]], fill: str) -> None:
    draw.polygon(points, fill=fill)


def arrow(draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str = "#1d1f25", width: int = 2, dash: bool = False) -> None:
    x1, y1 = start
    x2, y2 = end
    if dash:
        dx, dy = x2 - x1, y2 - y1
        length = max(1, math.hypot(dx, dy))
        ux, uy = dx / length, dy / length
        step, gap = 12, 8
        pos = 0
        while pos < length - 14:
            a = pos
            b = min(pos + step, length - 14)
            draw.line((x1 + ux * a, y1 + uy * a, x1 + ux * b, y1 + uy * b), fill=color, width=width)
            pos += step + gap
    else:
        draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    size = 10
    pts = [
        (x2, y2),
        (x2 - size * math.cos(angle - 0.45), y2 - size * math.sin(angle - 0.45)),
        (x2 - size * math.cos(angle + 0.45), y2 - size * math.sin(angle + 0.45)),
    ]
    triangle(draw, pts, color)


def draw_grid(draw) -> None:
    # Flat #f0f0f0 canvas with react-flow's faint dot background (gap 20).
    # Full width — any right drawer is painted over it afterwards.
    draw.rectangle((0, CANVAS_Y, W, H), fill=CANVAS)
    if isinstance(draw, SvgDraw):
        draw.dot_pattern(CANVAS_Y)
        return
    for x in range(6, W, 20):
        for y in range(CANVAS_Y + 8, H, 20):
            draw.ellipse((x, y, x + 1, y + 1), fill=DOT)


def draw_dropdown_label(draw: ImageDraw.ImageDraw, x: int, y: int, label: str) -> int:
    text(draw, (x, y), label, ON_DARK, F["nav"], anchor="lm")
    label_width = draw.textbbox((0, 0), label, font=F["nav"])[2]
    tx = x + int(label_width) + 8
    triangle(draw, [(tx, y - 4), (tx + 8, y - 4), (tx + 4, y + 3)], ON_DARK)
    return tx + 24


def draw_curio_logo_asset(draw, x: int, y: int, height: int) -> None:
    logo = Image.open(CURIO_LOGO).convert("RGBA")
    alpha_bbox = logo.getchannel("A").getbbox()
    if alpha_bbox:
        logo = logo.crop(alpha_bbox)
    if isinstance(draw, SvgDraw):
        import io
        buf = io.BytesIO()
        logo.save(buf, format="PNG")
        draw.image_embed(x, y, height * logo.width / logo.height, height, buf.getvalue())
        return
    target_h = sc(height)
    target_w = max(1, int(round(logo.width * target_h / logo.height)))
    logo = logo.resize((target_w, target_h), Image.Resampling.LANCZOS)
    draw._image.paste(logo, sc((x, y)), logo)


def draw_curio_bird_logo(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    # Compact redraw of the current Curio bird mark used in the app top bar.
    text(draw, (x + 3, y + 8), "Curio", "white", F["small"], anchor="lm")
    draw.ellipse((x + 24, y + 18, x + 62, y + 45), outline="white", width=2)
    draw.ellipse((x + 52, y + 13, x + 72, y + 31), outline="white", width=2)
    draw.ellipse((x + 59, y + 18, x + 63, y + 22), fill="white")
    draw.line((x + 71, y + 22, x + 84, y + 17), fill="white", width=2)
    draw.line((x + 72, y + 25, x + 84, y + 30), fill="white", width=2)
    draw.arc((x + 31, y + 24, x + 57, y + 48), 205, 350, fill="white", width=2)
    draw.line((x + 39, y + 44, x + 32, y + 55), fill="white", width=2)
    draw.line((x + 52, y + 44, x + 48, y + 56), fill="white", width=2)
    draw.line((x + 28, y + 56, x + 39, y + 52), fill="white", width=2)
    draw.line((x + 45, y + 57, x + 57, y + 56), fill="white", width=2)
    draw.arc((x + 13, y + 37, x + 37, y + 59), 210, 330, fill="white", width=2)
    draw.line((x + 13, y + 54, x + 4, y + 61), fill="white", width=2)


def draw_robot_icon(draw: ImageDraw.ImageDraw, x: int, y: int, color: str) -> None:
    draw.rounded_rectangle((x + 5, y + 9, x + 25, y + 25), radius=4, outline=color, width=2)
    draw.line((x + 15, y + 9, x + 15, y + 3), fill=color, width=2)
    draw.ellipse((x + 12, y, x + 18, y + 6), outline=color, width=2)
    draw.ellipse((x + 11, y + 15, x + 14, y + 18), fill=color)
    draw.ellipse((x + 18, y + 15, x + 21, y + 18), fill=color)
    draw.line((x + 2, y + 16, x + 5, y + 16), fill=color, width=2)
    draw.line((x + 25, y + 16, x + 28, y + 16), fill=color, width=2)


def draw_topbar(draw: ImageDraw.ImageDraw, avatar: bool = True) -> None:
    # UpMenu.tsx: #1E1F23 bar, 65px, Rubik bold menus, robot + floppy status icons.
    draw.rectangle((0, 0, W, TOP_H), fill=DARK)
    draw.line((0, TOP_H - 1, W, TOP_H - 1), fill="#0c0d0f", width=1)
    draw_curio_logo_asset(draw, 15, 8, 50)
    x = 150
    for item, gap in [("File", 58), ("View", 62), ("Data", 82), ("Provenance", 112), ("Help", 70)]:
        x = draw_dropdown_label(draw, x, 33, item) + gap - 24
    repo_icon(draw, 826, 19, "fa-solid:robot", ON_DARK, 27)
    repo_icon(draw, 906, 20, "fa-solid:floppy-disk", SAVE_GREEN, 24)
    if avatar:
        draw.ellipse((1512, 15, 1548, 51), fill="white", outline="#2a2a2e", width=1)
        text(draw, (1530, 33), "SG", "#0f0f11", F["micro"], anchor="mm")
        text(draw, (1560, 33), "Shared Guest", "white", F["small"], anchor="lm")


def draw_zoom_controls(draw: ImageDraw.ImageDraw) -> None:
    # react-flow default <Controls>: white stacked zoom/fit/lock, bottom-left.
    bx, by, bw, bh = 20, H - 208, 38, 38
    icons = ["fa-solid:plus", "fa-solid:minus", "fa-solid:expand", "fa-solid:lock"]
    shadowed_round(draw, (bx, by, bx + bw, by + bh * len(icons)), 4, "white", BORDER)
    for i, ic in enumerate(icons):
        top = by + i * bh
        if i:
            draw.line((bx + 6, top, bx + bw - 6, top), fill=BORDER, width=1)
        repo_icon(draw, bx + 11, top + 11, ic, "#4b4b52", 16)


PAL_X, PAL_Y, PAL_W = 70, 150, 150
PAL_ROW_H = 52


def draw_palette_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, icon_ref: str, badge: str | None = None) -> None:
    repo_icon(draw, cx - 15, cy - 15, icon_ref, ON_DARK, 30)
    if badge:
        bw = max(26, int(draw.textbbox((0, 0), badge, font=F["badge"])[2]) + 8)
        draw.rounded_rectangle((cx - bw // 2, cy + 12, cx + bw // 2, cy + 25), radius=3, fill="#2a6df4")
        text(draw, (cx, cy + 18), badge, "white", F["badge"], anchor="mm")


def draw_palette_dropdown(draw: ImageDraw.ImageDraw, x: int, y: int, icon: str, label: str, count: str, hot: bool, open_: bool = False) -> None:
    w, h = 74, 96
    border = PEACH if open_ else "#34363c"
    fg = PEACH if open_ else ON_DARK
    shadowed_round(draw, (x, y, x + w, y + h), 6, DARK, border, width=2 if open_ else 1)
    repo_icon(draw, x + w // 2 - 13, y + 14, icon, fg, 26)
    text(draw, (x + w // 2, y + 50), label, fg, F["badge"], anchor="mm")
    cw = max(24, int(draw.textbbox((0, 0), count, font=F["badge"])[2]) + 14)
    draw.rounded_rectangle((x + w // 2 - cw // 2, y + 58, x + w // 2 + cw // 2, y + 74), radius=8,
                           fill=PEACH if open_ else ("#4a3a2c" if hot else "#34363c"))
    text(draw, (x + w // 2, y + 66), count, DARK if open_ else ON_DARK, F["badge"], anchor="mm")
    cx = x + w // 2
    if open_:
        triangle(draw, [(cx - 5, y + 88), (cx + 5, y + 88), (cx, y + 82)], fg)
    else:
        triangle(draw, [(cx - 5, y + 82), (cx + 5, y + 82), (cx, y + 88)], "#8b8c93")


def draw_left_palette(draw: ImageDraw.ImageDraw) -> None:
    rx, ry, rw = PAL_X, PAL_Y, PAL_W
    header_h = 30
    top = [
        ("fa-solid:upload", None), ("fa-solid:download", None),
        ("fa-solid:database", None), ("fa-solid:object-group", None),
        ("fa-solid:code-merge", None), ("fa-solid:server", None),
        ("fa-brands:python", None), ("fa-solid:rectangle-list", None),
        ("fa-brands:js", None),
    ]
    vis = [("fa-solid:city", "AUTK"), ("fa-solid:chart-line", "VEGA"), ("fa-solid:table", None)]
    top_rows = (len(top) + 1) // 2
    vis_rows = (len(vis) + 1) // 2
    rail_h = header_h + top_rows * PAL_ROW_H + 16 + vis_rows * PAL_ROW_H + 8
    shadowed_round(draw, (rx, ry, rx + rw, ry + rail_h), 6, DARK, "#34363c")
    text(draw, (rx + rw // 2, ry + 16), "BUILT-IN", "#8b8c93", F["badge"], anchor="mm")
    c0, c1 = rx + 50, rx + 100
    y = ry + header_h + 4
    for i, (ic, bd) in enumerate(top):
        cx = c0 if i % 2 == 0 else c1
        draw_palette_icon(draw, cx, y + (i // 2) * PAL_ROW_H + 18, ic, bd)
    dy = y + top_rows * PAL_ROW_H + 6
    draw.line((rx + 14, dy, rx + rw - 14, dy), fill="#34363c", width=1)
    y2 = dy + 12
    for i, (ic, bd) in enumerate(vis):
        cx = c0 if i % 2 == 0 else c1
        draw_palette_icon(draw, cx, y2 + (i // 2) * PAL_ROW_H + 18, ic, bd)
    # Run-all-nodes button under the rail.
    py = ry + rail_h + 12
    shadowed_round(draw, (rx, py, rx + rw, py + 50), 5, DARK, "#34363c")
    repo_icon(draw, rx + rw // 2 - 14, py + 13, "fa-solid:forward-step", ON_DARK, 26)
    # DATA + PACKAGES + AGENTS dropdown triggers, to the right of the rail.
    # Agents follow the same palette model as datasets and packages.
    draw_palette_dropdown(draw, rx + rw + 14, ry, "fa-solid:database", "DATA", "10", True)
    draw_palette_dropdown(draw, rx + rw + 96, ry, "fa-solid:cube", "PACKAGES", "0", False)
    draw_palette_dropdown(draw, rx + rw + 178, ry, "fa-solid:robot", "AGENTS", "5", False)


def draw_canvas_base(
    draw: ImageDraw.ImageDraw,
    label: str | None = None,
    title: str = "Heat_Vulnerability",
    banner: bool = True,
) -> None:
    draw_topbar(draw, avatar=False)
    draw_grid(draw)
    draw_left_palette(draw)
    draw_zoom_controls(draw)
    text(draw, (70, 103), title, TEXT, F["h1"], anchor="lm")
    if banner:
        # Curio's centred shared-view / status banner style (#FFF4D6 / #7A5A00).
        bw = 500
        bx = CANVAS_W - bw - 40
        shadowed_round(draw, (bx, 80, bx + bw, 116), 6, "#fff4d6", "#e6cd7a", width=1, shadow=False)
        text(draw, (bx + bw // 2, 98),
             "Composed from reusable agents  —  review connections before running.",
             "#7a5a00", F["small"], anchor="mm")
    text(draw, (CANVAS_W - 12, H - 14), "React Flow", "#b6b6ba", F["tiny"], anchor="rm")
    if label:
        lw = int(draw.textbbox((0, 0), label, font=F["screen"])[2])
        shadowed_round(draw, (70, 128, 70 + lw + 24, 154), 13, DARK, None, shadow=False)
        text(draw, (82, 141), label, "white", F["screen"], anchor="lm")


_KW = {"import", "from", "as", "return", "def", "for", "in", "if", "else",
       "with", "and", "or", "not", "None", "True", "False", "lambda", "class"}
_tok_re = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|#.*|[A-Za-z_][A-Za-z0-9_]*|\d+\.?\d*|\s+|.')


def _tok_color(tok: str, nxt: str) -> str:
    if tok[:1] in ('"', "'"):
        return CODE_STR
    if tok.startswith("#"):
        return "#a0a1a7"
    if tok in _KW:
        return CODE_KW
    if tok[:1].isdigit():
        return CODE_NUM
    if tok[:1].isalpha() and nxt[:1] == "(":
        return CODE_FN
    return CODE_TXT


def draw_code_line(draw: ImageDraw.ImageDraw, x: int, y: int, line: str) -> None:
    f = F["mono"]
    charw = f.getlength("m") / RENDER_SCALE
    toks = _tok_re.findall(line)
    cx = x
    for i, tok in enumerate(toks):
        if tok.strip():
            col = _tok_color(tok, toks[i + 1] if i + 1 < len(toks) else "")
            text(draw, (cx, y), tok, col, f, anchor="lm")
        cx += len(tok) * charw


def draw_port(draw: ImageDraw.ImageDraw, edge_x: int, cy: int, side: str) -> None:
    bw, bh = 13, 20
    bx = edge_x - bw + 1 if side == "in" else edge_x - 1
    draw.rounded_rectangle((bx, cy - bh // 2, bx + bw, cy + bh // 2), radius=3, fill="white", outline="#1e1f23", width=1)
    offs = [0] if side == "out" else [-4, 4]
    for o in offs:
        draw.ellipse((bx + bw // 2 - 1, cy + o - 1, bx + bw // 2 + 2, cy + o + 2), fill="#1e1f23")


TYPE_META = {
    "data": (BAR_DATA, [("DATA", ORANGE_SOFT, ORANGE), ("OUTPUT", GREEN_SOFT, GREEN)]),
    "compute": (BAR_COMPUTE, [("PACKAGE", BLUE_SOFT, BLUE), ("OUTPUT", GREEN_SOFT, GREEN)]),
    "vis": (BAR_VIS, [("OUTPUT", GREEN_SOFT, GREEN)]),
}


def truncate(draw: ImageDraw.ImageDraw, s: str, maxw: int, f) -> str:
    if maxw <= 0 or draw.textbbox((0, 0), s, font=f)[2] <= maxw:
        return s
    while s and draw.textbbox((0, 0), s + "…", font=f)[2] > maxw:
        s = s[:-1]
    return s + "…"


def draw_node(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    w: int,
    title: str,
    node_type: str,
    code: list[str],
    selected: str | None = None,
) -> tuple[int, int, int, int]:
    bar_color, pills = TYPE_META.get(node_type, (BAR_FALLBACK, []))
    accent = {"green": GREEN, "blue": BLUE, "orange": ORANGE, "purple": PURPLE}.get(selected)
    head_h, foot_h, line_h = 28, 30, 17
    n = len(code)
    body_h = 12 + n * line_h + 22
    h = head_h + body_h + foot_h
    compact = w < 240

    shadowed_round(draw, (x, y, x + w, y + h), 8, "white",
                   accent or BORDER_STRONG, width=3 if accent else 1)
    # colored left accent bar (node-type)
    draw.rounded_rectangle((x + 1, y + 3, x + 5, y + h - 3), radius=2, fill=bar_color)
    # header band
    draw.rectangle((x + 2, y + 1, x + w - 1, y + head_h), fill="#fbfbfb")
    draw.line((x + 6, y + head_h, x + w - 1, y + head_h), fill="#c3c3c6", width=1)
    repo_icon(draw, x + 10, y + 9, "fa-solid:minus", "#888787", 12)
    # right-aligned icon cluster
    ix = x + w - 6
    for ic in ["fa-solid:xmark", "fa-solid:circle", "fa-solid:comments"]:
        ix -= 15
        repo_icon(draw, ix, y + 9, ic, "#888787", 12)
        ix -= 2
    # header pills, laid right-to-left, then a gear
    px = ix - 6
    if not compact:
        for label, bg, fg in reversed(pills):
            pw = int(draw.textbbox((0, 0), label, font=F["badge"])[2]) + 14
            px -= pw
            draw.rounded_rectangle((px, y + 7, px + pw, y + 21), radius=7, fill=bg)
            text(draw, (px + pw // 2, y + 14), label, fg, F["badge"], anchor="mm")
            px -= 5
    title_max = px - 12 - (x + 30)
    text(draw, (x + 30, y + 14), truncate(draw, title, title_max, F["screen"]), SECONDARY, F["screen"], anchor="lm")
    # body: line numbers + syntax-highlighted code
    by = y + head_h + 14
    for i, line in enumerate(code):
        ly = by + i * line_h
        text(draw, (x + 24, ly), str(i + 1), CODE_NUM, F["num"], anchor="rm")
        draw_code_line(draw, x + 32, ly, line)
    oy = by + n * line_h + 8
    draw.line((x + 8, oy - 4, x + w - 8, oy - 4), fill="#eeeeef", width=1)
    text(draw, (x + 14, oy + 6), "[ ]: No output yet", "#9a9aa2", F["mono_sm"], anchor="lm")
    # footer toolbar
    fy = y + h - foot_h
    draw.rectangle((x + 2, fy + 1, x + w - 1, y + h - 1), fill="#fbfbfb")
    draw.line((x + 6, fy, x + w - 1, fy), fill="#e2e2e4", width=1)
    fcy = fy + foot_h // 2
    repo_icon(draw, x + 11, fcy - 9, "fa-solid:circle-play", PEACH, 18)
    if not compact:
        repo_icon(draw, x + 34, fcy - 7, "fa-solid:database", "#a6a6ac", 14)
        draw.rounded_rectangle((x + 54, fcy - 6, x + 74, fcy + 6), radius=6, fill=PEACH)
        draw.ellipse((x + 64, fcy - 5, x + 74, fcy + 5), fill="white")
    cw = 42
    ccx = x + w // 2 + (12 if compact else 0)
    draw.rounded_rectangle((ccx - cw // 2, fcy - 11, ccx + cw // 2, fcy + 11), radius=6, fill=DARK)
    repo_icon(draw, ccx - 9, fcy - 8, "fa-solid:code", ON_DARK, 15)
    if not compact:
        repo_icon(draw, x + w - 56, fcy - 7, "fa-solid:box-archive", "#a6a6ac", 14)
        repo_icon(draw, x + w - 36, fcy - 7, "fa-solid:list", "#a6a6ac", 14)
        repo_icon(draw, x + w - 18, fcy - 7, "fa-solid:rotate-right", "#a6a6ac", 14)
    # ports
    pcy = y + head_h + body_h // 2
    draw_port(draw, x, pcy, "in")
    draw_port(draw, x + w, pcy, "out")
    return (x, y, x + w, y + h)


# macOS-Dock-style attached-agent dock: compact square, icon-only tiles that
# magnify on hover (with neighbour falloff), a running dot beneath active
# agents, and the agent name in a hover tooltip above the magnified tile.
DOCK_BASE = 40      # resting tile size
DOCK_PAD = 9        # shelf padding
DOCK_GAP = 12       # gap between tiles
DOCK_SHELF_H = DOCK_BASE + 2 * DOCK_PAD
DOCK_MAG = {0: 66, 1: 52, 2: 44}  # magnification by distance from hovered tile


def draw_agent_dock(draw: ImageDraw.ImageDraw, edge: int, cy: int, items, hovered=None, align="right"):
    """Floating macOS-style dock (no shelf): free-floating square tiles whose
    row is aligned to `edge` (right edge when align="right", left edge when
    align="left") and vertically centred on `cy`. Tiles magnify on hover with
    neighbour falloff. Returns per-tile (centre_x, top_y)."""
    def size_for(i):
        return DOCK_BASE if hovered is None else DOCK_MAG.get(abs(i - hovered), DOCK_BASE)

    sizes = [size_for(i) for i in range(len(items))]
    total_w = sum(sizes) + DOCK_GAP * (len(items) - 1)
    x = edge if align == "left" else edge - total_w
    anchors, tip = [], None
    for i, it in enumerate(items):
        s = sizes[i]
        iy = int(cy - s / 2)
        shadowed_round(draw, (x, iy, x + s, iy + s), max(6, int(s * 0.26)),
                       it["soft"], it["accent"], width=1 if s == DOCK_BASE else 2, shadow=True)
        bs = s / 38.0
        bot(draw, int(x + s / 2 - 11 * bs), int(iy + s * 0.24), it["accent"], bs)
        if it.get("running"):
            dcx = x + s // 2
            draw.ellipse((dcx - 3, iy + s + 4, dcx + 3, iy + s + 10), fill="#9a9aa0")
        anchors.append((x + s // 2, iy))
        if i == hovered:
            tip = (x + s // 2, iy, it["name"])
        x += s + DOCK_GAP
    if tip:
        tcx, tiy, name = tip
        tw = int(draw.textbbox((0, 0), name, font=F["small"])[2]) + 26
        ty = tiy - 10
        shadowed_round(draw, (tcx - tw // 2, ty - 26, tcx + tw // 2, ty), 7, DARK, DARK, shadow=True)
        text(draw, (tcx, ty - 13), name, ON_DARK, F["small"], anchor="mm")
        triangle(draw, [(tcx - 6, ty), (tcx + 6, ty), (tcx, ty + 7)], DARK)
    return anchors


def bezier(draw: ImageDraw.ImageDraw, p0, p1, color: str = "#b1b1b7", width: int = 2, head: bool = True) -> None:
    x0, y0 = p0
    x1, y1 = p1
    dx = max(50, abs(x1 - x0) * 0.6)
    c0 = (x0 + dx, y0)
    c1 = (x1 - dx, y1)
    pts = []
    for i in range(41):
        t = i / 40
        mt = 1 - t
        bx = mt ** 3 * x0 + 3 * mt ** 2 * t * c0[0] + 3 * mt * t ** 2 * c1[0] + t ** 3 * x1
        by = mt ** 3 * y0 + 3 * mt ** 2 * t * c0[1] + 3 * mt * t ** 2 * c1[1] + t ** 3 * y1
        pts.append((bx, by))
    draw.line(pts, fill=color, width=width, joint="curve")
    if head:
        triangle(draw, [(x1 + 5, y1), (x1 - 5, y1 - 5), (x1 - 5, y1 + 5)], color)


def _node_h(code: list[str]) -> int:
    return len(code) * 17 + 92


NODE_LAYOUT = [
    ("data", "Data Loading", "data", 250, 300, 286,
     ["import geopandas as gpd", "", "gdf = gpd.read_file(\"data/tracts.geojson\")", "return gdf"]),
    ("clean", "Python Computation", "compute", 576, 300, 286,
     ["import pandas as pd", "", "df = arg.dropna()", "df = df.rename(columns=cols)", "return df"]),
    ("map", "Autark", "vis", 902, 300, 185,
     ["const m = new AutarkMap(data)", "m.render()"]),
    ("compute", "Python Computation", "compute", 430, 560, 286,
     ["import numpy as np", "", "expo = normalize(df.heat)", "score = expo*0.6 + sens*0.4", "return score"]),
    ("explain", "Data Summary", "data", 756, 560, 286,
     ["import pandas as pd", "", "summary = df.describe()", "return summary"]),
]

EDGES = [("data", "clean"), ("clean", "map"), ("data", "compute"), ("compute", "explain")]


def draw_nodes(
    draw: ImageDraw.ImageDraw,
    tabs: bool = False,
    selected: str | None = None,
    source_selected: bool = False,
    open_agent: str | None = None,
) -> dict[str, tuple[int, int, int, int]]:
    geo = {}
    for key, _t, _ty, x, y, w, code in NODE_LAYOUT:
        h = _node_h(code)
        geo[key] = (x, y, x + w, y + h)
    # edges behind nodes (react-flow grey bezier)
    for a, b in EDGES:
        ax = geo[a][2] + 2
        ay = (geo[a][1] + geo[a][3]) // 2
        bx = geo[b][0] - 4
        by = (geo[b][1] + geo[b][3]) // 2
        bezier(draw, (ax, ay), (bx, by))
    hl = {"data": "green", "compute": "blue"}
    boxes = {}
    for key, title, ntype, x, y, w, code in NODE_LAYOUT:
        acc = hl.get(key) if selected == key else None
        boxes[key] = draw_node(draw, x, y, w, title, ntype, code, acc)
    if tabs:
        d = boxes["data"]
        c = boxes["compute"]
        da = draw_agent_dock(draw, d[0], d[3] + 40,
                             [{"name": "Dataset Finder", "accent": GREEN, "soft": GREEN_SOFT, "running": True}],
                             hovered=0 if open_agent == "dataset" else None, align="left")
        ca = draw_agent_dock(draw, c[0], c[3] + 40,
                             [{"name": "Node Explainer", "accent": BLUE, "soft": BLUE_SOFT, "running": True},
                              {"name": "Validation", "accent": PURPLE, "soft": PURPLE_SOFT, "running": False}],
                             hovered=0 if open_agent == "explainer" else None, align="left")
        if open_agent == "dataset":
            boxes["open_anchor"] = da[0]
        elif open_agent == "explainer":
            boxes["open_anchor"] = ca[0]
    return boxes


def draw_dock(draw: ImageDraw.ImageDraw, hovered=0) -> None:
    # Canvas-level agents as a floating macOS-style dock, right-aligned near the top.
    draw_agent_dock(draw, 980, 206, [
        {"name": "Dataflow Builder", "accent": ORANGE, "soft": ORANGE_SOFT, "running": True},
        {"name": "Validation", "accent": PURPLE, "soft": PURPLE_SOFT, "running": False},
        {"name": "Optimization", "accent": ORANGE, "soft": ORANGE_SOFT, "running": False},
    ], hovered=hovered)


def _drawer_edge_shadow(draw, x0: int) -> None:
    """Soft leftward shadow along a full-height right drawer's edge, so the
    flush drawer reads as an overlay above the canvas (matches the app's
    `-8px 0 24px` drawer shadow)."""
    for i in range(12):
        draw.dim((x0 - 12 + i, 0, x0 - 11 + i, H), alpha=2 + i * 2)


def draw_panel_frame(draw: ImageDraw.ImageDraw, title: str, subtitle: str, icon_color: str) -> int:
    """Right drawer with the Agents Roster's dark header (pin · icon · title),
    flush against the top bar like Curio's Data Catalog panel.

    DEC-042 (dev/21): this static catalog-style bar is exclusive to the Agents
    Roster drawer and keeps the **Pin button only** — no Close, no master-agent
    identity, no agent-cycling controls. The opened agent view draws its own
    identity header instead (see _chat_header)."""
    x0 = W - DRAWER_W
    _drawer_edge_shadow(draw, x0)
    draw.rectangle((x0, 0, W, H), fill="white", outline=BORDER_STRONG)
    draw.rectangle((x0, 0, W, TOP_H), fill=DARK)
    repo_icon(draw, x0 + 20, 22, "fa-solid:thumbtack", ON_DARK, 20)
    bot(draw, x0 + 56, 22, icon_color, 0.95)
    text(draw, (x0 + 94, 33), title, "white", F["title"], anchor="lm")
    if subtitle:
        text(draw, (x0 + 24, 94), subtitle, SECONDARY, F["small"], anchor="lm")
    return x0


def publish_pill(draw, rx: int, y: int, published: bool) -> int:
    """Shared CatalogPublishPill — the SAME control datasets and node packages use, and it
    lives ONLY in the catalog drawer (never in the palette). 'Publish' (sky accent) toggles
    to a neutral 'Published' badge. Right-anchored at rx."""
    label = "Published" if published else "Publish"
    w = int(draw.textbbox((0, 0), label, font=F["badge"])[2]) + 20
    x = rx - w
    if published:
        # Published → neutral badge (muted text · page bg · hairline border), like CatalogPublishPill.
        draw.rounded_rectangle((x, y, rx, y + 20), radius=10, fill="#f4f4f6", outline=CHAT_BORDER, width=1)
        text(draw, ((x + rx) // 2, y + 10), label, MUTED, F["badge"], anchor="mm")
    else:
        # Publish → sky pill (sky-fg text · sky-bg fill · sky border), like CatalogPublishPill.
        draw.rounded_rectangle((x, y, rx, y + 20), radius=10, fill=BLUE_SOFT, outline="#a9c2ee", width=1)
        text(draw, ((x + rx) // 2, y + 10), label, BLUE, F["badge"], anchor="mm")
    return w


# Agents lifecycle drawer scopes (reconciled project-scoped model, docs 03/11):
#   Global Catalog          → Install in project (no user Publish/Share)
#   My Imports              → owned private definitions: Publish + Install in project
#   Installed in this project → ProjectAgentTemplate: Project agent settings + Uninstall
_CATALOG_CARDS = [
    ("builder", "Dataflow Builder", "Canvas", ORANGE, ORANGE_SOFT, "master orchestrator · plans + coordinates agents", "hook: Canvas", "orchestrates", True),
    ("dataset", "Dataset Finder", "Data", GREEN, GREEN_SOFT, "sources internal + external datasets", "hook: Data Load", "~600 tok", True),
    ("nodebuilder", "Node Builder", "Node", BLUE, BLUE_SOFT, "creates computation / transform / viz nodes", "hook: Canvas / conn", "review", True),
    ("connection", "Connection Builder", "Node", BLUE, BLUE_SOFT, "suggests + creates valid connections", "hook: Canvas / nodes", "review", False),
    ("package", "Package Recommendation", "Package", PURPLE, PURPLE_SOFT, "recommends packages that fit the task", "hook: Node / canvas", "~500 tok", False),
    ("validation", "Validation", "Evaluate", PURPLE, PURPLE_SOFT, "checks coherence, data types, outputs", "hook: Node / canvas", "~900 tok", True),
    ("optimize", "Optimization", "Canvas", ORANGE, ORANGE_SOFT, "improves performance + structure", "hook: Canvas", "~800 tok", False),
    ("explainer", "Node Explainer", "Node", BLUE, BLUE_SOFT, "explains what a node / flow does", "hook: Node", "~450 tok", True),
]


def _scope_tabs(draw, x0, cx1, ty, active) -> int:
    """Tab strip matching the app's DrawerTabs (Data / Node Catalog): a dark-filled active tab
    (small radius), plain secondary-text inactive tabs (no fill/border), 4px gap, 6×14 padding,
    and a hairline bottom border across the drawer. Returns the border y."""
    tx = cx1
    h = 28
    for sc in ["Global Catalog", "My Imports", "Installed in this project"]:
        on = sc == active
        tw = int(draw.textbbox((0, 0), sc, font=F["small"])[2]) + 28
        if on:
            draw.rounded_rectangle((tx, ty, tx + tw, ty + h), radius=6, fill=DARK)
            text(draw, (tx + tw // 2, ty + h // 2), sc, ON_DARK, F["small"], anchor="mm")
        else:
            text(draw, (tx + tw // 2, ty + h // 2), sc, SECONDARY, F["small"], anchor="mm")
        tx += tw + 4
    by = ty + h + 8
    draw.line((x0, by, W, by), fill=BORDER)
    return by


def _catalog_card(draw, cx1, cx2, y, ch, card, sel, scope) -> None:
    key, title, cat, fg, soft, meta, hook, tok, inst = card
    shadowed_round(draw, (cx1, y, cx2, y + ch - 10), 11, "white", fg if sel else CHAT_BORDER, width=2 if sel else 1, shadow=False)
    draw.rounded_rectangle((cx1 + 2, y + 3, cx1 + 6, y + ch - 13), radius=2, fill=fg)
    shadowed_round(draw, (cx1 + 14, y + 11, cx1 + 50, y + 47), 9, soft, None, shadow=False)
    bot(draw, cx1 + 23, y + 20, fg, 0.74)
    tx0 = cx1 + 62
    text(draw, (tx0, y + 18), title, TEXT, F["body_bold"], anchor="lm")
    px = tx0 + int(draw.textbbox((0, 0), title, font=F["body_bold"])[2]) + 8
    cw = pill(draw, px, y + 9, cat, soft, fg)
    pill(draw, px + cw + 6, y + 9, "v1", "#f0f0f2", SECONDARY, 26)
    if scope == "My Imports":
        pill(draw, px + cw + 38, y + 9, "Private", "#efe7fb", PURPLE, 52)
    text(draw, (tx0, y + 35), meta, SECONDARY, F["tiny"], anchor="lm")
    gx = tx0
    for tag in [hook, tok]:
        gw = int(draw.textbbox((0, 0), tag, font=F["tiny"])[2]) + 14
        draw.rounded_rectangle((gx, y + 46, gx + gw, y + 61), radius=8, fill="#f2f2f4", outline=CHAT_BORDER, width=1)
        text(draw, (gx + gw // 2, y + 53), tag, "#555555", F["tiny"], anchor="mm")
        gx += gw + 6
    # Right-side action column — the SAME controls the Data / Node Catalog cards use:
    # a dark primary Install / Update, neutral white-outline secondary (Uninstall / Delete /
    # Unpublish), and the shared CatalogPublishPill (Publish → Published). No bespoke labels,
    # colors, or per-card "settings" button.
    aw = 96
    ax, ax1 = cx2 - 12, cx2 - 12 - aw

    def _primary(top, label):  # .btnInstall — dark fill, white text
        draw.rounded_rectangle((ax1, top, ax, top + 24), radius=8, fill=DARK)
        text(draw, ((ax1 + ax) // 2, top + 12), label, ON_DARK, F["small"], anchor="mm")

    def _secondary(top, label):  # .btnSecondary — white, border-strong, text-primary
        draw.rounded_rectangle((ax1, top, ax, top + 22), radius=8, fill="white", outline=BORDER_STRONG, width=1)
        text(draw, ((ax1 + ax) // 2, top + 11), label, TEXT, F["small"], anchor="mm")

    if scope == "Global Catalog":
        # available → Install (primary); already installed → Uninstall (secondary). No publish.
        cyt = y + (ch - 10 - 24) // 2
        if inst:
            _secondary(cyt + 1, "Uninstall")
        else:
            _primary(cyt, "Install")
    elif scope == "My Imports":
        # owned private definition: Install + shared Publish pill + Delete (all real primitives).
        _primary(y + 7, "Install")
        publish_pill(draw, ax, y + 35, published=(key in ("dataset", "validation")))
        _secondary(y + 59, "Delete")
    else:  # Installed in this project → Uninstall (secondary), matching the real Installed cards.
        cyt = y + (ch - 10 - 22) // 2
        _secondary(cyt, "Uninstall")


def draw_catalog(draw: ImageDraw.ImageDraw, selected: str = "dataset", scope: str = "Global Catalog") -> None:
    subtitle = {
        "Global Catalog": "Global Catalog · install agents into this project.",
        "My Imports": "My Imports · private account definitions — publish to the Catalog Hub or install.",
        "Installed in this project": "Installed in this project · templates available in this project's palette.",
    }[scope]
    x0 = draw_panel_frame(draw, "Agents Catalog", subtitle, ORANGE)
    cx1, cx2 = x0 + 24, W - 24
    sy = 108
    shadowed_round(draw, (cx1, sy, cx1 + 358, sy + 38), 8, "white", BORDER, shadow=False)
    repo_icon(draw, cx1 + 12, sy + 10, "fa-solid:magnifying-glass", "#9296a0", 18)
    text(draw, (cx1 + 40, sy + 19), "Search agents, hooks, keywords...", "#9296a0", F["small"], anchor="lm")
    shadowed_round(draw, (cx2 - 118, sy, cx2, sy + 38), 8, "white", BORDER, shadow=False)
    text(draw, (cx2 - 59, sy + 19), "Sort: New  ▾", TEXT, F["small"], anchor="mm")
    _scope_tabs(draw, x0, cx1, sy + 48, scope)
    # category filters (below the tab strip's bottom border)
    ty2 = sy + 96
    cxp = cx1
    for i, label in enumerate(["All", "Data", "Node", "Canvas", "Package", "Evaluate"]):
        on = i == 0
        tw = int(draw.textbbox((0, 0), label, font=F["tiny"])[2]) + 18
        draw.rounded_rectangle((cxp, ty2, cxp + tw, ty2 + 24), radius=12, fill=ORANGE_SOFT if on else "white", outline=ORANGE if on else BORDER, width=1)
        text(draw, (cxp + tw // 2, ty2 + 12), label, ORANGE if on else SECONDARY, F["tiny"], anchor="mm")
        cxp += tw + 6
    hy = ty2 + 36
    text(draw, (cx1, hy), scope.upper(), CHAT_META, F["badge"], anchor="lm")
    action_hint = {"Global Catalog": "install / uninstall",
                   "My Imports": "install · publish · delete",
                   "Installed in this project": "uninstall"}[scope]
    text(draw, (cx2, hy), action_hint, CHAT_META, F["tiny"], anchor="rm")
    y = hy + 14
    # My Imports shows the account's OWN imported definitions (a subset, not the full global
    # catalog) and needs a taller card to fit the three-action column (Install · Publish/Published
    # pill · Delete), matching the real Data / Node Catalog owned-item cards.
    if scope == "My Imports":
        cards = [c for c in _CATALOG_CARDS if c[0] in ("builder", "dataset", "nodebuilder", "validation", "explainer")]
        ch = 92
    else:
        cards = _CATALOG_CARDS
        ch = 72
    for card in cards:
        _catalog_card(draw, cx1, cx2, y, ch, card, card[0] == selected, scope)
        y += ch
    draw.rectangle((x0, H - 70, W, H), fill="white", outline=BORDER)
    shadowed_round(draw, (cx1, H - 56, cx2, H - 16), 7, DARK, DARK, shadow=False)
    cxm = (cx1 + cx2) // 2
    repo_icon(draw, cxm - 64, H - 45, "fa-solid:file-import", ON_DARK, 16)
    text(draw, (cxm + 4, H - 36), "Import package", ON_DARK, F["body_bold"], anchor="mm")


# ── Shared agent settings modal (six screens over the current surface) ───────
_SETTINGS_TABS = [
    ("Cost", "fa-solid:coins"),
    ("Quotas", "fa-solid:gauge-high"),
    ("Resource policies", "fa-solid:server"),
    ("Prompt quality", "fa-solid:clipboard-check"),
    ("Prompt editor", "fa-solid:pen-to-square"),
    ("Prompt audit", "fa-solid:shield-halved"),
]


def _srow(draw, x, y, w, label, value, tone=SECONDARY, h=34):
    shadowed_round(draw, (x, y, x + w, y + h), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
    text(draw, (x + 14, y + h // 2 + 1), label, TEXT, F["small"], anchor="lm")
    text(draw, (x + w - 14, y + h // 2 + 1), value, tone, F["small"], anchor="rm")
    return y + h + 8


def _slock(draw, rx, y, label="inherited"):
    w = int(draw.textbbox((0, 0), label, font=F["tiny"])[2]) + 28
    draw.rounded_rectangle((rx - w, y, rx, y + 20), radius=8, fill="#eef0f2")
    repo_icon(draw, rx - w + 6, y + 3, "fa-solid:lock", "#9a9ba3", 12)
    text(draw, (rx - w // 2 + 6, y + 10), label, "#7c7d85", F["tiny"], anchor="mm")
    return w


def _smeter(draw, x, y, w, frac, accent):
    draw.rounded_rectangle((x, y, x + w, y + 8), radius=4, fill="#eceef1")
    draw.rounded_rectangle((x, y, x + int(w * frac), y + 8), radius=4, fill=accent)


def _shead(draw, x, y, w, title, meta=None):
    text(draw, (x, y), title, CHAT_TITLE, F["body_bold"], anchor="lm")
    if meta:
        text(draw, (x + w, y), meta, CHAT_META, F["tiny"], anchor="rm")
    return y + 26


def _body_cost(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Budget & spend", "pricing effective 2026-07-01")
    y = _srow(draw, x, y, w, "Per-run budget", "$0.50")
    y = _srow(draw, x, y, w, "Rolling budget · 30 days", "$40.00")
    shadowed_round(draw, (x, y, x + w, y + 58), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
    text(draw, (x + 14, y + 16), "Current usage", TEXT, F["small"], anchor="lm")
    text(draw, (x + w - 14, y + 16), "$24.80 / $40.00", SECONDARY, F["small"], anchor="rm")
    _smeter(draw, x + 14, y + 32, w - 28, 0.62, accent)
    text(draw, (x + 14, y + 48), "62% of rolling budget used", CHAT_META, F["tiny"], anchor="lm")
    y += 66
    y = _srow(draw, x, y, w, "Alert thresholds", "80% · 100%")
    _chip(draw, x, y + 2, "Estimated", "#eef2fb", BLUE, closable=False, border="#d4e0f6")
    _chip(draw, x + 96, y + 2, "Actual (provider-reported)", "#eef6f0", GREEN, closable=False, border="#cfe6d6")


def _body_quotas(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Quotas", "resets Aug 1 · 00:00 UTC")
    for label, val, locked in [("Executions", "500 / month", True), ("Tokens", "2.0M / month", True),
                               ("Tool calls", "5,000 / month", False), ("Concurrency", "3 parallel", False),
                               ("Rate window", "60 / minute", False)]:
        shadowed_round(draw, (x, y, x + w, y + 34), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
        text(draw, (x + 14, y + 18), label, TEXT, F["small"], anchor="lm")
        vx = x + w - 14
        if locked:
            vx -= _slock(draw, x + w - 14, y + 7) + 10
        text(draw, (vx, y + 18), val, SECONDARY, F["small"], anchor="rm")
        y += 42
    y = _srow(draw, x, y, w, "Reservations", "1 execution held for retries")


def _body_resource(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Resource policies", "secrets never shown")
    y = _srow(draw, x, y, w, "Provider profile", "Anthropic · profile #2")
    y = _srow(draw, x, y, w, "Model", "claude · policy-selected")
    shadowed_round(draw, (x, y, x + w, y + 34), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
    text(draw, (x + 14, y + 18), "Processing locality", TEXT, F["small"], anchor="lm")
    for i, opt in enumerate(["Local", "Remote"]):
        on = opt == "Remote"
        bw2 = 66
        bx = x + w - 14 - (2 - i) * (bw2 + 6) + bw2
        draw.rounded_rectangle((bx - bw2, y + 6, bx, y + 28), radius=8, fill=accent if on else "white", outline=accent if on else BORDER_STRONG, width=1)
        text(draw, (bx - bw2 // 2, y + 17), opt, "white" if on else SECONDARY, F["tiny"], anchor="mm")
    y += 42
    y = _srow(draw, x, y, w, "Context / output limits", "128k in · 4k out")
    y = _srow(draw, x, y, w, "Time limit", "60s / run")
    y = _srow(draw, x, y, w, "Egress", "allowlist only")
    y = _srow(draw, x, y, w, "Tools / network", "restricted · no raw fetch")


def _body_quality(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Prompt quality", "pinned suite")
    y = _srow(draw, x, y, w, "Validation suite", "heat-vuln-v3")
    y = _srow(draw, x, y, w, "Rubric · threshold", "R2 · 0.85 pass")
    shadowed_round(draw, (x, y, x + w, y + 92), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
    text(draw, (x + 14, y + 16), "Recent evaluations", TEXT, F["small"], anchor="lm")
    rows = [("Groundedness", "passed", GREEN, "0.91"), ("Coverage", "passed", GREEN, "0.88"),
            ("Toxicity", "running", BLUE, "—")]
    ry = y + 34
    for name, st, col, score in rows:
        text(draw, (x + 20, ry + 9), name, SECONDARY, F["small"], anchor="lm")
        text(draw, (x + w - 70, ry + 9), score, MUTED, F["tiny"], anchor="rm")
        pw = int(draw.textbbox((0, 0), st, font=F["tiny"])[2]) + 22
        draw.rounded_rectangle((x + w - 20 - pw, ry, x + w - 20, ry + 18), radius=9, fill=_TONE[col][0])
        text(draw, (x + w - 20 - pw // 2, ry + 9), st, col, F["tiny"], anchor="mm")
        ry += 24
    y += 100
    y = _srow(draw, x, y, w, "Evaluation usage", "312k tokens · $1.90")


def _body_editor(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Prompt editor", "owned import · draft")
    shadowed_round(draw, (x, y, x + w, y + 118), 9, "#1e1f23", "#1e1f23", shadow=False)
    for i, ln in enumerate(["SYSTEM  You are Dataset Finder for Curio.",
                            "Rank {catalog} + external sources for",
                            "the mission {mission}. Never fetch;",
                            "propose candidates for review.",
                            "Vars: {mission} {catalog} {geography}"]):
        text(draw, (x + 16, y + 18 + i * 18), ln, "#d7d8dd", F["mono_sm"], anchor="lm")
    y += 128
    _chip(draw, x, y, "variables valid", "#eef6f0", GREEN, closable=False, border="#cfe6d6")
    _chip(draw, x + 116, y, "schema valid", "#eef6f0", GREEN, closable=False, border="#cfe6d6")
    _chip(draw, x + 220, y, "diff +3 / -1 lines", "#eef2fb", BLUE, closable=False, border="#d4e0f6")
    y += 32
    text(draw, (x, y + 6), "Saving a draft never mutates the immutable imported definition.", CHAT_META, F["tiny"], anchor="lm")
    draw.rounded_rectangle((x + w - 96, y, x + w, y + 26), radius=8, fill=DARK)
    text(draw, (x + w - 48, y + 13), "Save draft", ON_DARK, F["tiny"], anchor="mm")


def _body_audit(draw, x, y, w, accent):
    y = _shead(draw, x, y, w, "Prompt audit", "append-only governance")
    for label, val, col in [("Privacy rules", "v4 · 0 findings", GREEN),
                            ("Security rules", "v4 · 1 finding", ORANGE),
                            ("Compliance rules", "v3 · 0 findings", GREEN)]:
        shadowed_round(draw, (x, y, x + w, y + 34), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
        text(draw, (x + 14, y + 18), label, TEXT, F["small"], anchor="lm")
        pw = int(draw.textbbox((0, 0), val, font=F["tiny"])[2]) + 22
        draw.rounded_rectangle((x + w - 14 - pw, y + 8, x + w - 14, y + 26), radius=9, fill=_TONE[col][0])
        text(draw, (x + w - 14 - pw // 2, y + 17), val, col, F["tiny"], anchor="mm")
        y += 42
    shadowed_round(draw, (x, y, x + w, y + 86), 9, CHAT_INNER, CHAT_BORDER, shadow=False)
    text(draw, (x + 14, y + 16), "Audit history", TEXT, F["small"], anchor="lm")
    for i, (when, who, what) in enumerate([("2026-07-14", "karlas", "release v4 · security review"),
                                           ("2026-07-02", "karlas", "release v3 · rubric update")]):
        ry = y + 34 + i * 24
        text(draw, (x + 20, ry), when, MUTED, F["tiny"], anchor="lm")
        text(draw, (x + 116, ry), who, SECONDARY, F["tiny"], anchor="lm")
        text(draw, (x + 196, ry), what, "#3a3a42", F["tiny"], anchor="lm")
    text(draw, (x, y + 96), "Distinct from the chat transcript / execution history.", CHAT_META, F["tiny"], anchor="lm")


_SETTINGS_BODY = {
    "Cost": _body_cost, "Quotas": _body_quotas, "Resource policies": _body_resource,
    "Prompt quality": _body_quality, "Prompt editor": _body_editor, "Prompt audit": _body_audit,
}


def draw_settings_modal(draw, active, agent_name, accent, scope_label="Project agent settings") -> None:
    mx1, my1, mx2, my2 = 286, 122, 1386, 818
    shadowed_round(draw, (mx1, my1, mx2, my2), 16, "white", BORDER_STRONG, shadow=True)
    bot(draw, mx1 + 22, my1 + 18, accent, 0.95)
    text(draw, (mx1 + 56, my1 + 29), agent_name, TEXT, F["title"], anchor="lm")
    nw = int(draw.textbbox((0, 0), agent_name, font=F["title"])[2])
    text(draw, (mx1 + 56 + nw + 12, my1 + 31), "· " + scope_label, SECONDARY, F["small"], anchor="lm")
    repo_icon(draw, mx2 - 42, my1 + 18, "fa-solid:xmark", "#b8b9bf", 22)
    draw.line((mx1 + 18, my1 + 56, mx2 - 18, my1 + 56), fill=CHAT_BORDER)
    # left tab rail
    rail_x, rail_w = mx1 + 18, 228
    ty = my1 + 72
    for name, icon in _SETTINGS_TABS:
        on = name == active
        if on:
            draw.rounded_rectangle((rail_x, ty, rail_x + rail_w, ty + 40), radius=9, fill=_OPT_SEL.get(accent, "#f0f1f4"))
            draw.rounded_rectangle((rail_x + 3, ty + 9, rail_x + 7, ty + 31), radius=2, fill=accent)
        repo_icon(draw, rail_x + 16, ty + 12, icon, accent if on else "#8a8b93", 16)
        text(draw, (rail_x + 42, ty + 20), name, TEXT if on else SECONDARY, F["small"], anchor="lm")
        ty += 46
    draw.line((rail_x + rail_w + 18, my1 + 66, rail_x + rail_w + 18, my2 - 18), fill=CHAT_BORDER)
    text(draw, (rail_x + 6, my2 - 44), "Account policy sets ceilings;", CHAT_META, F["tiny"], anchor="lm")
    text(draw, (rail_x + 6, my2 - 28), "this scope can only tighten them.", CHAT_META, F["tiny"], anchor="lm")
    # body
    bx1 = rail_x + rail_w + 44
    bx2 = mx2 - 28
    _SETTINGS_BODY[active](draw, bx1, my1 + 84, bx2 - bx1, accent)


def draw_lifecycle_drawer(draw) -> None:
    # Scene 18: the three-scope lifecycle as a vertical flow (import → publish / install → attach).
    x0 = draw_panel_frame(draw, "Agents Catalog", "Lifecycle · import · publish / install · attach", ORANGE)
    cx1, cx2 = x0 + 24, W - 24
    stages = [
        ("My Imports · private", "Import package · private account definition", "fa-solid:file-import", PURPLE,
         [("Install", DARK, ON_DARK, None), ("Publish", BLUE_SOFT, BLUE, "#a9c2ee"), ("Delete", "white", TEXT, BORDER_STRONG)]),
        ("Global Catalog", "Built-in + published, reusable across projects", "fa-solid:box-open", ORANGE,
         [("Install", DARK, ON_DARK, None)]),
        ("Installed in this project", "ProjectAgentTemplate · shows in this project's palette", "fa-solid:cube", GREEN,
         [("Uninstall", "white", TEXT, BORDER_STRONG)]),
        ("Attached instance", "Drag to a target · private, no Publish / Share", "fa-solid:link", BLUE,
         [("Attach", "white", SECONDARY, BORDER_STRONG)]),
    ]
    conn = ["Publish to Global Catalog", "Install in project", "Attach to a target"]
    y = 118
    ch = 118
    for i, (title, sub, icon, acc, actions) in enumerate(stages):
        shadowed_round(draw, (cx1, y, cx2, y + ch), 12, CHAT_SURFACE, CHAT_BORDER, shadow=False)
        draw.ellipse((cx1 + 16, y + 20, cx1 + 24, y + 28), fill=acc)
        repo_icon(draw, cx1 + 34, y + 15, icon, acc, 18)
        text(draw, (cx1 + 62, y + 24), title, CHAT_TITLE, F["body_bold"], anchor="lm")
        text(draw, (cx1 + 18, y + 52), sub, SECONDARY, F["small"], anchor="lm")
        ax = cx1 + 18
        for label, fill, fg, outline in actions:
            aw = int(draw.textbbox((0, 0), label, font=F["tiny"])[2]) + 24
            draw.rounded_rectangle((ax, y + 78, ax + aw, y + 100), radius=8, fill=fill, outline=outline, width=1 if outline else 0)
            text(draw, (ax + aw // 2, y + 89), label, fg, F["tiny"], anchor="mm")
            ax += aw + 8
        y += ch
        if i < len(stages) - 1:
            midx = (cx1 + cx2) // 2
            draw.line((midx, y + 2, midx, y + 20), fill=BORDER_STRONG, width=2)
            lbl = conn[i]
            lw = int(draw.textbbox((0, 0), lbl, font=F["tiny"])[2]) + 18
            draw.rounded_rectangle((midx + 12, y + 2, midx + 12 + lw, y + 22), radius=9, fill="white", outline=CHAT_BORDER, width=1)
            repo_icon(draw, midx + 18, y + 5, "fa-solid:arrow-down", "#9a9ba3", 12)
            text(draw, (midx + 12 + (lw + 14) // 2, y + 12), lbl, SECONDARY, F["tiny"], anchor="mm")
            y += 28


def draw_scope_matrix(draw) -> None:
    # Scene 19: which settings each ownership scope can edit / inherits / reads.
    mx1, my1, mx2, my2 = 286, 132, 1386, 812
    shadowed_round(draw, (mx1, my1, mx2, my2), 16, "white", BORDER_STRONG, shadow=True)
    text(draw, (mx1 + 26, my1 + 30), "Settings applicability by scope", TEXT, F["title"], anchor="lm")
    text(draw, (mx1 + 26, my1 + 56), "One six-screen shell; each scope owns, inherits, or reads a screen.", SECONDARY, F["small"], anchor="lm")
    cols = ["Account policy", "Imported definition", "Project agent", "Attached instance"]
    rows = ["Cost", "Quotas", "Resource policies", "Prompt quality", "Prompt editor", "Prompt audit"]
    cells = {
        "Cost": ["Ceiling", "—", "Default", "Tighten"], "Quotas": ["Ceiling", "—", "Default", "Tighten"],
        "Resource policies": ["Ceiling", "—", "Default", "Tighten"],
        "Prompt quality": ["—", "Owns", "Read-only", "Read-only"], "Prompt editor": ["—", "Owns", "Read-only", "Read-only"],
        "Prompt audit": ["—", "Owns", "Read-only", "Read-only"],
    }
    tone = {"Ceiling": ("#eef2fb", BLUE), "Default": ("#eef6f0", GREEN), "Owns": ("#eef6f0", GREEN),
            "Tighten": ("#fdeee7", "#b5651d"), "Read-only": ("#eef0f2", "#7c7d85")}
    lx = mx1 + 26
    labw = 210
    colx = lx + labw
    colw = (mx2 - 26 - colx) // 4
    hy = my1 + 92
    for j, c in enumerate(cols):
        cxm = colx + j * colw + colw // 2
        text(draw, (cxm, hy), c, CHAT_META, F["badge"], anchor="mm")
    ry = hy + 22
    rh = 52
    for r in rows:
        shadowed_round(draw, (lx, ry, mx2 - 26, ry + rh - 8), 9, CHAT_SURFACE, CHAT_BORDER, shadow=False)
        text(draw, (lx + 14, ry + (rh - 8) // 2), r, TEXT, F["small"], anchor="lm")
        for j, val in enumerate(cells[r]):
            cxm = colx + j * colw + colw // 2
            cy = ry + (rh - 8) // 2
            if val == "—":
                text(draw, (cxm, cy), "—", "#c7c8cf", F["small"], anchor="mm")
            else:
                bg, fg = tone[val]
                pw = int(draw.textbbox((0, 0), val, font=F["tiny"])[2]) + 22
                draw.rounded_rectangle((cxm - pw // 2, cy - 10, cxm + pw // 2, cy + 10), radius=9, fill=bg)
                text(draw, (cxm, cy), val, fg, F["tiny"], anchor="mm")
        ry += rh
    text(draw, (lx, ry + 8), "Account ceilings bound everything; attachments can only tighten; prompt screens are read-only evidence outside their owning import.", CHAT_META, F["tiny"], anchor="lm")


def draw_callout(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], title: str, body: str, color: str, fill: str) -> None:
    shadowed_round(draw, box, 8, "white", color, width=2, shadow=True)
    draw.rounded_rectangle((box[0] + 2, box[1] + 3, box[0] + 6, box[3] - 3), radius=2, fill=color)
    text(draw, (box[0] + 16, box[1] + 19), title, color, F["body_bold"], anchor="lm")
    text(draw, (box[0] + 16, box[1] + 42), body, SECONDARY, F["small"], anchor="lm")


# ── Unified attached-agent chat drawer ────────────────────────────────────
# Every attached agent uses this SAME drawer. Instances are visually
# indistinguishable and differ only by agent type (name + icon colour),
# configuration, and chat/execution history. A session is keyed by the tuple
# (node id + agent type + project id) and is reachable via prev/next in the
# header. Refinement, suggestions, and behaviour config all happen in chat.

CHAT_HEADER_H = 96  # the opened agent view's two-line identity header


def _chat_header(draw, name, accent, target, session, idx, total):
    # DEC-042 (dev/21): the opened agent view has ONE top header carrying the
    # master agent identity, the ‹ › cycling arrows, the identification details
    # (session chip + attached target), and Close (✕). There is NO Pin here,
    # and the static "Agents Catalog" bar does not appear — that chrome is
    # exclusive to the Agents Roster drawer (draw_panel_frame).
    # Flush full-height overlay drawer: viewport-top to bottom, with a soft
    # left shadow over the canvas (the implementation is a fixed <body> portal).
    x0 = W - DRAWER_W
    _drawer_edge_shadow(draw, x0)
    draw.rectangle((x0, 0, W, H), fill="white", outline=BORDER_STRONG)
    draw.rectangle((x0, 0, W, CHAT_HEADER_H), fill=DARK)
    # line 1 — ‹ 🤖 <name> <idx>/<total> ›                                   ✕
    prev_c = "#5c5d66" if idx <= 1 else "#cfd0d3"
    next_c = "#5c5d66" if idx >= total else "#cfd0d3"
    repo_icon(draw, x0 + 20, 24, "fa-solid:chevron-left", prev_c, 16)
    bot(draw, x0 + 46, 24, accent, 0.85)
    text(draw, (x0 + 78, 33), name, "white", F["title"], anchor="lm")
    nw = int(draw.textbbox((0, 0), name, font=F["title"])[2])
    cxt = x0 + 78 + nw + 12
    label = f"{idx} / {total}"
    text(draw, (cxt, 34), label, "#9a9ba2", F["small"], anchor="lm")
    lw = int(draw.textbbox((0, 0), label, font=F["small"])[2])
    repo_icon(draw, cxt + lw + 6, 24, "fa-solid:chevron-right", next_c, 16)
    # Close is preserved in this header (dismisses the agent view, never detaches).
    repo_icon(draw, W - 46, 22, "fa-solid:xmark", "#cfd0d3", 24)
    # line 2 — attached target (left) + session chip (right), still in the header
    text(draw, (x0 + 24, 72), "Attached to " + target, "#b9bac1", F["small"], anchor="lm")
    st = "session " + session
    sw = int(draw.textbbox((0, 0), st, font=F["mono_sm"])[2]) + 16
    draw.rounded_rectangle((W - 24 - sw, 62, W - 24, 82), radius=6, fill="#2c2d33")
    text(draw, (W - 24 - sw + 8, 72), st, "#b6b7bf", F["mono_sm"], anchor="lm")
    # The opening intent is not a standalone field — it renders as the first
    # user message in the conversation (see draw_agent_chat).
    return x0, CHAT_HEADER_H + 16


def _chat_system(draw, lx, rx, y, s) -> int:
    tw = int(draw.textbbox((0, 0), s, font=F["tiny"])[2]) + 28
    cx = (lx + rx) // 2
    draw.rounded_rectangle((cx - tw // 2, y, cx + tw // 2, y + 22), radius=11, fill="#f2f2f4", outline=CHAT_BORDER, width=1)
    text(draw, (cx, y + 11), s, "#8a8b93", F["tiny"], anchor="mm")
    return y + 34


def _chat_user(draw, lx, rx, y, s) -> int:
    lines = wrap(draw, s, 300, F["small"])
    bw = min(360, max(int(draw.textbbox((0, 0), ln, font=F["small"])[2]) for ln in lines) + 32)
    bh = len(lines) * 18 + 20
    draw.rounded_rectangle((rx - bw, y, rx, y + bh), radius=12, fill=DARK)
    for i, ln in enumerate(lines):
        text(draw, (rx - bw + 16, y + 16 + i * 18), ln, ON_DARK, F["small"], anchor="lm")
    return y + bh + 14


def _chat_agent_text(draw, lx, rx, y, accent, s) -> int:
    bot(draw, lx, y, accent, 0.9)
    tx = lx + 34
    lines = wrap(draw, s, rx - 30 - tx, F["small"])
    for i, ln in enumerate(lines):
        text(draw, (tx, y + 8 + i * 18), ln, "#2c2d33", F["small"], anchor="lm")
    return y + max(24, len(lines) * 18 + 8) + 8


# ── Chat-feedback visual system ───────────────────────────────────────────
# Claude-like agent-chat feel — subtle surfaces, hairline borders, grouped options,
# soft selection states, polished spacing — expressed with Curio's tokens/accents.
CHAT_SURFACE = "#f7f7f8"   # subtle grouped card surface
CHAT_INNER = "#ffffff"     # raised inner panels (code, table, option group)
CHAT_BORDER = "#ececee"    # hairline border
CHAT_RADIUS = 12
CHAT_TITLE = "#33353c"     # card title
CHAT_META = "#9a9ba3"      # card meta / section labels
OPT_BORDER = "#e6e6ea"     # option / control resting border
# soft, low-saturation selection tints per accent (lighter than the *_SOFT pastels)
_OPT_SEL = {ORANGE: "#fdeee7", BLUE: "#eaf1fd", GREEN: "#eef6f0", PURPLE: "#f3ecfb"}
# soft result/status surfaces + borders per accent
_TONE = {
    GREEN: ("#eef6f0", "#cfe6d6"),
    ORANGE: ("#fdeee7", "#f4dbcb"),
    BLUE: ("#eaf1fd", "#d4e0f6"),
    PURPLE: ("#f3ecfb", "#e0d0f4"),
}


def _card_shell(draw, lx, rx, y, hh, title, meta=None, accent=None, tone=None) -> None:
    """Grouped chat-feedback surface with a header row: subtle fill, hairline border,
    optional soft tone (result/status) and a small leading accent dot for identity."""
    if tone:
        fill, border = _TONE.get(accent, (CHAT_SURFACE, CHAT_BORDER))
    else:
        fill, border = CHAT_SURFACE, CHAT_BORDER
    shadowed_round(draw, (lx, y, rx, y + hh), CHAT_RADIUS, fill, border, shadow=False)
    hx = lx + 16
    if accent is not None and not tone:
        draw.ellipse((hx, y + 15, hx + 8, y + 23), fill=accent)
        hx += 16
    text(draw, (hx, y + 19), title, CHAT_TITLE, F["body_bold"], anchor="lm")
    if meta:
        text(draw, (rx - 16, y + 19), meta, CHAT_META, F["tiny"], anchor="rm")


def _radio(draw, x, y, checked, accent=GREEN) -> None:
    if checked:
        draw.ellipse((x, y, x + 16, y + 16), outline=accent, width=2, fill="white")
        draw.ellipse((x + 4, y + 4, x + 12, y + 12), fill=accent)
    else:
        draw.ellipse((x, y, x + 16, y + 16), outline="#c7c7cf", width=1, fill="white")


def _lane_hint(draw, rx, ymid, label, accent) -> None:
    """Right-anchored routing hint (arrow icon + label) for a suggestion lane."""
    text(draw, (rx, ymid), label, accent, F["badge"], anchor="rm")
    lw = int(draw.textbbox((0, 0), label, font=F["badge"])[2])
    repo_icon(draw, rx - lw - 16, ymid - 6, "fa-solid:arrow-right", accent, 11)


def _card_sources(draw, lx, rx, y, accent) -> int:
    # ONE discovery step, TWO lanes:
    #  · External sources    → selecting hands off to Node Builder (builds a fetch node)
    #  · From the Data Catalog → selecting auto-installs (if needed) via the existing flow
    # The card carries NO action button — the confirm action is offered as a suggested
    # prompt in the chat input box (see draw_agent_chat `suggested`).
    external = [("NOAA Climate Data API", "API", "94%", True),
                ("City Open Data Portal", "Portal", "81%", False)]
    catalog = [("Census ACS 5-year", "Parquet", "installed", False),
               ("Heat Advisory Days", "GeoJSON", "not installed", True)]
    row_h, seclbl = 34, 24
    sel = _OPT_SEL.get(accent, "#f0f1f4")
    hh = 42 + seclbl + len(external) * row_h + 14 + seclbl + len(catalog) * row_h + 8
    _card_shell(draw, lx, rx, y, hh, "Suggested datasets", meta="external + catalog", accent=accent)
    ry = y + 42
    # ── External sources lane → Node Builder ──
    text(draw, (lx + 16, ry + 8), "EXTERNAL SOURCES", CHAT_META, F["badge"], anchor="lm")
    _lane_hint(draw, rx - 16, ry + 8, "Node Builder", BLUE)
    ry += seclbl
    for title, typ, conf, checked in external:
        if checked:
            draw.rounded_rectangle((lx + 10, ry - 3, rx - 10, ry + 27), radius=8, fill=sel)
        _checkbox(draw, lx + 18, ry + 4, checked, accent)
        text(draw, (lx + 46, ry + 12), title, TEXT, F["small"], anchor="lm")
        tw = int(draw.textbbox((0, 0), title, font=F["small"])[2])
        pill(draw, lx + 46 + tw + 8, ry + 3, typ, "#eef0f2", SECONDARY)
        # No inline preview link — details are reviewed later via the Data Catalog drawer.
        text(draw, (rx - 18, ry + 12), conf, CHAT_META, F["tiny"], anchor="rm")
        ry += row_h
    # ── Data Catalog lane → existing install flow ──
    ry += 14
    text(draw, (lx + 16, ry + 8), "FROM YOUR DATA CATALOG", CHAT_META, F["badge"], anchor="lm")
    _lane_hint(draw, rx - 16, ry + 8, "install", ORANGE)
    ry += seclbl
    for title, fmt, state, checked in catalog:
        if checked:
            draw.rounded_rectangle((lx + 10, ry - 3, rx - 10, ry + 27), radius=8, fill=sel)
        _checkbox(draw, lx + 18, ry + 4, checked, accent)
        text(draw, (lx + 46, ry + 12), title, TEXT, F["small"], anchor="lm")
        tw = int(draw.textbbox((0, 0), title, font=F["small"])[2])
        pill(draw, lx + 46 + tw + 8, ry + 3, fmt, PURPLE_SOFT, PURPLE)
        installed = state == "installed"
        sfg, sbg = (GREEN, "#e6f2ea") if installed else ("#b26a2c", "#f7ece2")
        sw = int(draw.textbbox((0, 0), state, font=F["tiny"])[2]) + 16
        # No inline preview link — details are reviewed later via the Data Catalog drawer.
        draw.rounded_rectangle((rx - 18 - sw, ry + 3, rx - 18, ry + 22), radius=9, fill=sbg)
        text(draw, (rx - 18 - sw // 2, ry + 12), state, sfg, F["tiny"], anchor="mm")
        ry += row_h
    return y + hh + 12


def _card_handoff(draw, lx, rx, y, accent) -> int:
    # Dataset Finder delegates external-source implementation to the Node Builder agent.
    hh = 62
    fill, border = _TONE[BLUE]
    shadowed_round(draw, (lx, y, rx, y + hh), CHAT_RADIUS, fill, border, shadow=False)
    bot(draw, lx + 16, y + 12, BLUE, 0.7)
    text(draw, (lx + 46, y + 18), "Handing off to Node Builder", CHAT_TITLE, F["body_bold"], anchor="lm")
    text(draw, (lx + 46, y + 38), "Installed in project (reviewed) · builds the fetch node for NOAA Climate Data API", SECONDARY, F["tiny"], anchor="lm")
    lbl = "running"
    pw = int(draw.textbbox((0, 0), lbl, font=F["tiny"])[2]) + 26
    draw.rounded_rectangle((rx - pw - 14, y + 12, rx - 14, y + 30), radius=9, fill="white", outline=border, width=1)
    repo_icon(draw, rx - pw - 8, y + 14, "fa-solid:spinner", BLUE, 13)
    text(draw, (rx - pw + 12, y + 21), lbl, BLUE, F["tiny"], anchor="lm")
    return y + hh + 12


def _card_install(draw, lx, rx, y, msg, chips) -> int:
    # Data Catalog selection → reuse the EXISTING dataset install flow (no fetch code).
    hh = 66
    fill, border = _TONE[ORANGE]
    shadowed_round(draw, (lx, y, rx, y + hh), CHAT_RADIUS, fill, border, shadow=False)
    repo_icon(draw, lx + 16, y + 13, "fa-solid:download", ORANGE, 18)
    text(draw, (lx + 44, y + 20), msg, CHAT_TITLE, F["body_bold"], anchor="lm")
    cx = lx + 44
    for c in chips:
        cx += _chip(draw, cx, y + 34, c, "#b5651d", "#f5e5d8", closable=False) + 8
    return y + hh + 12


def _card_preview(draw, lx, rx, y, accent) -> int:
    # The Node Builder-generated dataset node — reviewed before it is added to the dataflow.
    # No action button on the card; the add / dismiss actions are offered as suggested prompts
    # in the chat input box (see draw_agent_chat `suggested`).
    hh = 334
    _card_shell(draw, lx, rx, y, hh, "Node Builder · Will create · Data Loading node", accent=BLUE)
    pill(draw, rx - 62, y + 11, "JSON", PURPLE_SOFT, PURPLE, 48)
    # generated request code in a raised inner panel
    code = ["params = {'datasetid':'GHCND','stationid':ST,",
            "  'startdate':START,'enddate':END,'units':'metric'}",
            "r = requests.get(URL, params=params,",
            "  headers={'token': KEY}); r.raise_for_status()",
            "return pd.DataFrame(r.json()['results'])"]
    cyc = y + 40
    chh = len(code) * 16 + 16
    shadowed_round(draw, (lx + 14, cyc, rx - 14, cyc + chh), 8, CHAT_INNER, CHAT_BORDER, shadow=False)
    for i, ln in enumerate(code):
        text(draw, (lx + 26, cyc + 14 + i * 16), ln, CODE_TXT, F["mono_sm"], anchor="lm")
    ky = cyc + chh + 12
    draw.rounded_rectangle((lx + 14, ky, lx + 150, ky + 22), radius=6, fill="#fdf1e7", outline="#f0cba6", width=1)
    repo_icon(draw, lx + 20, ky + 4, "fa-solid:key", "#b26a2c", 14)
    text(draw, (lx + 40, ky + 11), "API key required", "#b26a2c", F["tiny"], anchor="lm")
    text(draw, (lx + 160, ky + 11), "NOAA_TOKEN", MUTED, F["mono_sm"], anchor="lm")
    py = ky + 30
    text(draw, (lx + 14, py + 8), "Params", CHAT_META, F["badge"], anchor="lm")
    text(draw, (lx + 60, py + 8), "datasetid · stationid · startdate · enddate · units", TEXT, F["tiny"], anchor="lm")
    cy = py + 26
    cxp = lx + 14
    for c in ["Response parsing", "Error handling", "Output format"]:
        repo_icon(draw, cxp, cy, "fa-solid:circle-check", GREEN, 13)
        text(draw, (cxp + 18, cy + 7), c, SECONDARY, F["tiny"], anchor="lm")
        cxp += 26 + int(draw.textbbox((0, 0), c, font=F["tiny"])[2])
    _preview_table(draw, lx + 14, cy + 24, rx - 14)
    return y + hh + 12


def _card_behavior(draw, lx, rx, y, options, sel, accent) -> int:
    # Single-select presented as grouped radio option rows with a soft selected state.
    row_h = 30
    hh = 40 + len(options) * row_h + 8
    _card_shell(draw, lx, rx, y, hh, "Behavior", meta="suggestions only", accent=accent)
    tint = _OPT_SEL.get(accent, "#f0f1f4")
    ry = y + 40
    for i, opt in enumerate(options):
        on = i == sel
        if on:
            draw.rounded_rectangle((lx + 10, ry, rx - 10, ry + row_h - 4), radius=8, fill=tint, outline=accent, width=1)
        _radio(draw, lx + 18, ry + 5, on, accent)
        text(draw, (lx + 46, ry + 13), opt, TEXT if on else "#54565e", F["small"], anchor="lm")
        ry += row_h
    return y + hh + 12


def _card_result(draw, lx, rx, y, msg, chips, accent) -> int:
    hh = 66
    fill, border = _TONE[GREEN]
    shadowed_round(draw, (lx, y, rx, y + hh), CHAT_RADIUS, fill, border, shadow=False)
    repo_icon(draw, lx + 16, y + 13, "fa-solid:circle-check", GREEN, 18)
    text(draw, (lx + 44, y + 20), msg, CHAT_TITLE, F["body_bold"], anchor="lm")
    cx = lx + 44
    for c in chips:
        cx += _chip(draw, cx, y + 34, c, GREEN, "#e2efe6", closable=False) + 8
    return y + hh + 12


def _card_plan(draw, lx, rx, y, steps, accent) -> int:
    # Execution plan: the orchestrator's decomposed subtasks.
    hh = 42 + len(steps) * 24 + 8
    _card_shell(draw, lx, rx, y, hh, "Execution plan", meta=f"{len(steps)} subtasks", accent=accent)
    for i, step in enumerate(steps):
        sy = y + 52 + i * 24
        draw.ellipse((lx + 16, sy - 8, lx + 32, sy + 8), outline=accent, width=1, fill="white")
        text(draw, (lx + 24, sy), str(i + 1), accent, F["tiny"], anchor="mm")
        text(draw, (lx + 44, sy), step, "#3a3a42", F["small"], anchor="lm")
    return y + hh + 12


_AGENT_STATUS = {
    "done": (GREEN, "#e2efe6", "done"),
    "running": (BLUE, "#e6eefb", "running"),
    "queued": ("#8b8c93", "#eef0f2", "queued"),
    "install": (ORANGE, "#fbe8dc", "install in project"),
}


def _card_agents(draw, lx, rx, y, agents) -> int:
    # Spawned specialized agents with live status (background execution).
    row_h = 34
    hh = 42 + len(agents) * row_h + 8
    _card_shell(draw, lx, rx, y, hh, "Specialized agents", meta="coordinated in this project")
    for i, (name, acc, status) in enumerate(agents):
        ry = y + 46 + i * row_h
        bot(draw, lx + 16, ry + 4, acc, 0.7)
        text(draw, (lx + 44, ry + 13), name, TEXT, F["small"], anchor="lm")
        fg, tone_bg, lbl = _AGENT_STATUS[status]
        pw = int(draw.textbbox((0, 0), lbl, font=F["tiny"])[2]) + 26
        draw.rounded_rectangle((rx - pw - 16, ry + 3, rx - 16, ry + 21), radius=9, fill=tone_bg)
        dot = ("fa-solid:circle-check" if status == "done"
               else "fa-solid:spinner" if status == "running"
               else "fa-solid:download" if status == "install"
               else "fa-solid:clock")
        repo_icon(draw, rx - pw - 10, ry + 5, dot, fg, 13)
        text(draw, (rx - pw + 10, ry + 12), lbl, fg, F["tiny"], anchor="lm")
    return y + hh + 12


def _chat_card(draw, lx, rx, y, accent, card) -> int:
    kind = card[0]
    if kind == "sources":
        return _card_sources(draw, lx, rx, y, accent)
    if kind == "behavior":
        return _card_behavior(draw, lx, rx, y, card[1], card[2], accent)
    if kind == "preview":
        return _card_preview(draw, lx, rx, y, accent)
    if kind == "result":
        return _card_result(draw, lx, rx, y, card[1], card[2], accent)
    if kind == "install":
        return _card_install(draw, lx, rx, y, card[1], card[2])
    if kind == "handoff":
        return _card_handoff(draw, lx, rx, y, accent)
    if kind == "plan":
        return _card_plan(draw, lx, rx, y, card[1], accent)
    if kind == "agents":
        return _card_agents(draw, lx, rx, y, card[1])
    return y


def draw_agent_chat(draw, name, accent, target, session, idx, total, transcript, quick=None, intent=None, suggested=None) -> None:
    # Generic, reusable pattern: agents never render bespoke action buttons in the chat.
    # Confirmations / next steps are offered as SUGGESTED PROMPTS the user can review, edit,
    # and submit — the primary one prefilled (editable) in the input box (`suggested`), with
    # alternatives as chips above it (`quick`).
    x0, y = _chat_header(draw, name, accent, target, session, idx, total)
    lx, rx = x0 + 20, W - 24
    # The opening intent reads as the first user prompt — same chat-message styling,
    # spacing, and hierarchy as the rest of the conversation.
    if intent:
        y = _chat_user(draw, lx, rx, y, intent)
    for msg in transcript:
        if "sys" in msg:
            y = _chat_system(draw, lx, rx, y, msg["sys"])
        elif "user" in msg:
            y = _chat_user(draw, lx, rx, y, msg["user"])
        elif "agent" in msg:
            y = _chat_agent_text(draw, lx, rx, y, accent, msg["agent"])
            if msg.get("card"):
                y = _chat_card(draw, x0 + 54, rx, y, accent, msg["card"])
    iy = H - 56
    if quick:
        text(draw, (lx, H - 108), "SUGGESTED PROMPTS", CHAT_META, F["badge"], anchor="lm")
        qx = lx
        for q in quick:
            qx += _chip(draw, qx, H - 88, q, SECONDARY, "#f5f5f7", closable=False, border=OPT_BORDER) + 8
    draw.rounded_rectangle((lx, iy, rx, H - 16), radius=10, fill=DARK)
    if suggested:
        # Primary confirmation, prefilled as editable suggested text with an active send button.
        text(draw, (lx + 16, iy + 20), suggested, ON_DARK, F["small"], anchor="lm")
        sw = int(draw.textbbox((0, 0), suggested, font=F["small"])[2])
        draw.line((lx + 20 + sw, iy + 11, lx + 20 + sw, iy + 29), fill="#8b8c93", width=1)
        draw.ellipse((rx - 40, iy + 4, rx - 8, iy + 36), fill=accent)
        repo_icon(draw, rx - 33, iy + 11, "fa-solid:arrow-up", "white", 16)
    else:
        text(draw, (lx + 16, iy + 20), "Ask or refine this agent…", "#8b8c93", F["small"], anchor="lm")
        draw.ellipse((rx - 40, iy + 4, rx - 8, iy + 36), fill=ON_DARK)
        repo_icon(draw, rx - 33, iy + 11, "fa-solid:arrow-up", DARK, 16)


# ── shared helpers for chat cards + the DATA palette dropdown ──────────────
def _chip(draw, x, y, label, fg, bg, closable=True, border=None):
    # Soft token/chip: filled surface, optional hairline, rounded — no heavy outline.
    w = int(draw.textbbox((0, 0), label, font=F["tiny"])[2]) + (30 if closable else 22)
    draw.rounded_rectangle((x, y, x + w, y + 22), radius=8, fill=bg,
                           outline=border, width=1 if border else 0)
    text(draw, (x + 11, y + 11), label, fg, F["tiny"], anchor="lm")
    if closable:
        text(draw, (x + w - 13, y + 10), "×", fg, F["small"], anchor="mm")
    return w


def _checkbox(draw, x, y, checked, accent=GREEN):
    if checked:
        draw.rounded_rectangle((x, y, x + 16, y + 16), radius=5, fill=accent, outline=accent, width=1)
        repo_icon(draw, x, y, "fa-solid:check", "white", 16)
    else:
        draw.rounded_rectangle((x, y, x + 16, y + 16), radius=5, fill="white", outline="#c7c7cf", width=1)


def _preview_table(draw, x, y, right) -> int:
    """Compact data-preview table used inside the chat preview card. Returns height."""
    cols = [("station", 120), ("date", 88), ("tmax", 60)]
    rows = [
        ("USW00094728", "2023-07-18", "36.1"),
        ("USW00094728", "2023-07-19", "35.4"),
        ("USW00023174", "2023-07-18", "33.9"),
    ]
    rh = 24
    draw.rounded_rectangle((x, y, right, y + rh), radius=6, fill="#f4f4f6")
    cxp = x + 12
    for name, w in cols:
        text(draw, (cxp, y + rh // 2), name, SECONDARY, F["badge"], anchor="lm")
        cxp += w
    for i, row in enumerate(rows):
        ry = y + rh + i * rh
        if i % 2:
            draw.rectangle((x + 1, ry, right - 1, ry + rh), fill="#fafafa")
        cxp = x + 12
        for (name, w), val in zip(cols, row):
            text(draw, (cxp, ry + rh // 2), val, TEXT, F["mono_sm"], anchor="lm")
            cxp += w
    h = rh * (len(rows) + 1)
    draw.rounded_rectangle((x, y, right, y + h), radius=6, outline=BORDER, width=1)
    return h


# status-pill colors on the dark palette, keyed by provenance accent
_ROW_STATUS_DARK = {
    GREEN: ("#22331f", "#7bbf8a"),
    BLUE: ("#1e2a3f", "#8fb3f0"),
    ORANGE: ("#3a2a1e", "#d8996a"),
    PURPLE: ("#2a1e3f", "#b79ae0"),
}


def _dataset_row(draw, x1, x2, ry, fmt, fmt_color, title, cid, when, up, down, prov) -> None:
    """One row of the dark DATA dropdown. `prov` is None for a plain computed dataset (shows
    a COMPUTED pill + up/down connection counts), or a (author_label, accent, status) tuple
    for an agent-authored external node or a catalog-installed dataset (accent bar + status
    pill + author chip)."""
    # rounded icon tile with a format label at the bottom-left
    draw.rounded_rectangle((x1 + 18, ry + 14, x1 + 64, ry + 60), radius=8, fill="#26272c", outline="#3a3b41", width=1)
    repo_icon(draw, x1 + 31, ry + 18, "fa-solid:database", "#c9cacd", 20)
    text(draw, (x1 + 23, ry + 52), fmt, fmt_color, F["badge"], anchor="lm")
    tx = x1 + 80
    text(draw, (tx, ry + 24), title, ON_DARK, F["body_bold"], anchor="lm")
    text(draw, (tx, ry + 44), cid, "#8b8c93", F["mono_sm"], anchor="lm")
    if prov:
        label, acc, status = prov
        draw.rounded_rectangle((x1 + 2, ry + 10, x1 + 6, ry + 74), radius=2, fill=acc)
        sbg, sfg = _ROW_STATUS_DARK.get(acc, ("#2a2b30", "#9a9aa0"))
        cpw = int(draw.textbbox((0, 0), status, font=F["badge"])[2]) + 14
        draw.rounded_rectangle((tx, ry + 58, tx + cpw, ry + 74), radius=4, fill=sbg)
        text(draw, (tx + cpw // 2, ry + 66), status, sfg, F["badge"], anchor="mm")
        text(draw, (tx + cpw + 12, ry + 66), when, "#8b8c93", F["tiny"], anchor="lm")
        soft = _AGENT_CAT_SOFT.get(acc, GREEN_SOFT)
        cw = int(draw.textbbox((0, 0), label, font=F["badge"])[2]) + 32
        cx = x2 - 16 - cw
        draw.rounded_rectangle((cx, ry + 16, x2 - 16, ry + 36), radius=10, fill=soft)
        bot(draw, cx + 5, ry + 17, acc, 0.5)
        text(draw, (cx + 24, ry + 26), label, acc, F["badge"], anchor="lm")
    else:
        cpw = int(draw.textbbox((0, 0), "COMPUTED", font=F["badge"])[2]) + 14
        draw.rounded_rectangle((tx, ry + 58, tx + cpw, ry + 74), radius=4, fill="#2a2b30")
        text(draw, (tx + cpw // 2, ry + 66), "COMPUTED", "#9a9aa0", F["badge"], anchor="mm")
        text(draw, (tx + cpw + 12, ry + 66), when, "#8b8c93", F["tiny"], anchor="lm")
        ux = x2 - 76
        text(draw, (ux, ry + 26), str(up), "#9a9aa0", F["tiny"], anchor="lm")
        repo_icon(draw, ux + 10, ry + 19, "fa-solid:arrow-up", "#9a9aa0", 12)
        if down is not None:
            text(draw, (ux + 34, ry + 26), str(down), "#9a9aa0", F["tiny"], anchor="lm")
            repo_icon(draw, ux + 44, ry + 19, "fa-solid:arrow-down", "#9a9aa0", 12)


def _data_dropdown(draw) -> None:
    # Dark DATA palette dropdown matching png-ideas/datasets_palette_dropdown.
    x1, y1, x2, y2 = 234, 252, 668, 906
    shadowed_round(draw, (x1, y1, x2, y2), 10, DARK, "#3a3b41", shadow=True)
    text(draw, ((x1 + x2) // 2, y1 + 22), "DATASETS", "#c9cacd", F["screen"], anchor="mm")
    draw.line((x1 + 12, y1 + 44, x2 - 12, y1 + 44), fill="#34363c", width=1)
    text(draw, (x1 + 20, y1 + 62), "Installed datasets", ON_DARK, F["body_bold"], anchor="lm")
    text(draw, (x2 - 20, y1 + 62), "10", "#8b8c93", F["small"], anchor="rm")
    rows = [
        ("JSON", PURPLE, "NOAA Climate Data API", "agent.noaa-climate@1", "just now", 1, None, ("Node Builder", BLUE, "EXTERNAL")),
        ("PARQUET", ORANGE, "Census ACS 5-year", "catalog.census-acs5@1", "just now", 1, None, ("Data Catalog", ORANGE, "IMPORTED")),
        ("JSON", PURPLE, "Autark", "computed.n86a5886f-112e-4567-95f3-…", "9d ago", 1, 1, None),
        ("PARQUET", ORANGE, "Data Loading", "computed.node2@1", "9d ago", 1, 1, None),
        ("PARQUET", ORANGE, "Data Transformation", "computed.node5@1", "9d ago", 1, 1, None),
        ("PARQUET", ORANGE, "Python Computation", "computed.n1a815d0b-2298-…", "9d ago", 1, None, None),
    ]
    ry = y1 + 88
    for i, (fmt, fc, title, cid, when, up, down, prov) in enumerate(rows):
        if i:
            draw.line((x1 + 18, ry, x2 - 18, ry), fill="#2a2b30", width=1)
        _dataset_row(draw, x1, x2, ry, fmt, fc, title, cid, when, up, down, prov)
        ry += 84
    shadowed_round(draw, (x1 + 14, y2 - 56, x2 - 14, y2 - 14), 8, PEACH, PEACH, shadow=False)
    text(draw, ((x1 + x2) // 2, y2 - 35), "Browse Data Catalog  +", DARK, F["body_bold"], anchor="mm")
    # DATA trigger in its open (active) state, layered above the panel
    draw_palette_dropdown(draw, 234, 150, "fa-solid:database", "DATA", "10", True, open_=True)


def _toast(draw, message, icon="fa-solid:circle-check", color=GREEN) -> None:
    tw = 460
    tx = (CANVAS_W - tw) // 2
    ty = 84
    shadowed_round(draw, (tx, ty, tx + tw, ty + 42), 8, "white", color, width=2, shadow=True)
    draw.rounded_rectangle((tx + 2, ty + 3, tx + 6, ty + 39), radius=2, fill=color)
    repo_icon(draw, tx + 14, ty + 12, icon, color, 18)
    text(draw, (tx + 44, ty + 21), message, TEXT, F["small"], anchor="lm")


# Agents follow the SAME palette model as datasets/packages. Like the DATA palette row,
# a palette row has NO per-row publish/install action — publish lives solely in the
# Agents Catalog drawer. The row shows the agent reference and a category chip (the
# analog of the dataset provenance chip) and is dragged onto the dataflow to attach.
_AGENT_CAT_SOFT = {ORANGE: ORANGE_SOFT, BLUE: BLUE_SOFT, GREEN: GREEN_SOFT, PURPLE: PURPLE_SOFT}


def _agent_row(draw, x1, x2, ry, name, ref, category, accent) -> None:
    # Matches the real DATA / node-package palette row exactly: icon tile + name + reference
    # + provenance/category chip. No accent border strip and no drag handle on the right.
    draw.rounded_rectangle((x1 + 18, ry + 14, x1 + 64, ry + 60), radius=8, fill="#26272c", outline="#3a3b41", width=1)
    bot(draw, x1 + 30, ry + 22, accent, 0.85)
    tx = x1 + 80
    text(draw, (tx, ry + 24), name, ON_DARK, F["body_bold"], anchor="lm")
    text(draw, (tx, ry + 44), ref, "#8b8c93", F["mono_sm"], anchor="lm")
    # category chip (accent-tinted, like the dataset provenance chip) — no publish/install
    # action in the palette; those live in the Agents Catalog drawer.
    soft = _AGENT_CAT_SOFT.get(accent, GREEN_SOFT)
    cpw = int(draw.textbbox((0, 0), category, font=F["badge"])[2]) + 16
    draw.rounded_rectangle((tx, ry + 58, tx + cpw, ry + 74), radius=8, fill=soft)
    text(draw, (tx + cpw // 2, ry + 66), category, accent, F["badge"], anchor="mm")


def _agents_dropdown(draw) -> None:
    # Dark AGENTS palette dropdown — same layout as the DATA / PACKAGES dropdowns. The
    # palette lists ONLY agents installed in the project; global agents are installed from
    # the right-sidebar Agents Catalog. Rows have NO publish/install action (publish lives
    # in the drawer) and are dragged onto the dataflow to attach.
    tx0 = PAL_X + PAL_W + 178
    x1, y1, x2, y2 = tx0, 252, tx0 + 436, 906
    pitch = 84
    installed = [
        ("Dataflow Builder", "agent.dataflow-builder@1", "Canvas", ORANGE),
        ("Dataset Finder", "agent.dataset-finder@1", "Data", GREEN),
        ("Node Builder", "agent.node-builder@1", "Node", BLUE),
        ("Validation", "agent.validation@1", "Evaluate", PURPLE),
        ("Node Explainer", "agent.node-explainer@1", "Node", BLUE),
    ]
    shadowed_round(draw, (x1, y1, x2, y2), 10, DARK, "#3a3b41", shadow=True)
    text(draw, ((x1 + x2) // 2, y1 + 22), "AGENTS", "#c9cacd", F["screen"], anchor="mm")
    draw.line((x1 + 12, y1 + 44, x2 - 12, y1 + 44), fill="#34363c", width=1)
    text(draw, (x1 + 20, y1 + 62), "Installed in this project", ON_DARK, F["body_bold"], anchor="lm")
    text(draw, (x2 - 20, y1 + 62), str(len(installed)), "#8b8c93", F["small"], anchor="rm")
    ry = y1 + 84
    for i, (name, ref, category, acc) in enumerate(installed):
        if i:
            draw.line((x1 + 18, ry, x2 - 18, ry), fill="#2a2b30", width=1)
        _agent_row(draw, x1, x2, ry, name, ref, category, acc)
        ry += pitch
    text(draw, (x1 + 20, ry + 4), "Drag an agent onto a node or the canvas to attach it.", "#8b8c93", F["tiny"], anchor="lm")
    shadowed_round(draw, (x1 + 14, y2 - 56, x2 - 14, y2 - 14), 8, PEACH, PEACH, shadow=False)
    text(draw, ((x1 + x2) // 2, y2 - 35), "Browse Agents Catalog  +", DARK, F["body_bold"], anchor="mm")
    draw_palette_dropdown(draw, tx0, 150, "fa-solid:robot", "AGENTS", "5", False, open_=True)


_ACCENT_SOFT = {ORANGE: ORANGE_SOFT, BLUE: BLUE_SOFT, GREEN: GREEN_SOFT, PURPLE: PURPLE_SOFT}


def _drag_ghost(draw, cx, cy, name, accent) -> None:
    # A picked-up agent tile being dragged from the palette onto the dataflow.
    s = 50
    x, y = cx - s // 2, cy - s // 2
    shadowed_round(draw, (x, y, x + s, y + s), 13, _ACCENT_SOFT.get(accent, GREEN_SOFT), accent, width=2, shadow=True)
    bs = s / 38.0
    bot(draw, int(cx - 11 * bs), int(y + s * 0.24), accent, bs)
    tw = int(draw.textbbox((0, 0), name, font=F["tiny"])[2]) + 20
    draw.rounded_rectangle((cx - tw // 2, y + s + 6, cx + tw // 2, y + s + 26), radius=6, fill=DARK)
    text(draw, (cx, y + s + 16), name, ON_DARK, F["tiny"], anchor="mm")


MODE = "png"
SVG_OUT = ROOT / "svg-concepts"


def new_draw():
    return SvgDraw() if MODE == "svg" else ScaledDraw(new_canvas())


def emit(draw, base: str) -> None:
    if MODE == "svg":
        SVG_OUT.mkdir(parents=True, exist_ok=True)
        (SVG_OUT / f"{base}.svg").write_text(draw.to_svg(), encoding="utf-8")
    else:
        img = draw._image
        OUT.mkdir(parents=True, exist_ok=True)
        if img.size != (W, H):
            img = img.resize((W, H), Image.Resampling.LANCZOS)
        img.save(OUT / f"{base}.png", optimize=True)


def screen_base(label: str, catalog_selected: str = "dataset"):
    draw = new_draw()
    draw_canvas_base(draw, label)
    draw_nodes(draw)
    draw_catalog(draw, selected=catalog_selected)
    return draw


def render_all() -> None:
    draw = screen_base("01 · Agents Catalog — browse & install", "connection")
    emit(draw, "01-agents-catalog-drawer")

    draw = screen_base("02 · Dataflow with attached agents", "dataset")
    draw_nodes(draw, tabs=True, selected="dataset")
    draw_dock(draw)
    draw_catalog(draw, selected="dataset")
    emit(draw, "02-main-dataflow-attached-agents")

    draw = new_draw()
    draw_canvas_base(draw, "03 · Attach Dataset Finder — chat opens", banner=False)
    draw_nodes(draw, tabs=True, selected="data", open_agent="dataset")
    draw_agent_chat(draw, "Dataset Finder", GREEN, "Data Loading node", "n1·dataset-finder·heat-vuln", 1, 4, [
        {"sys": "dataset.discover + dataset.select · reads mission, node, catalog, geography, lineage"},
        {"agent": "Relevant external sources and Data Catalog matches. Review the suggested prompt below, edit it, and send to confirm.", "card": ("sources",)},
    ], quick=["Only build NOAA", "Catalog only", "Explain ranking"],
        suggested="Build the NOAA node and install Heat Advisory Days",
        intent="Find heat, demographic, and tract-level datasets for the Data Loading node.")
    arrow(draw, (1112, 250), (300, 500), GREEN, 3, dash=True)
    draw_callout(draw, (250, 214, 604, 268), "One chat per attachment",
                 "Clicking the agent's dock item under the node opens its chat session.", GREEN, GREEN_SOFT)
    emit(draw, "03-attachment-dataset-finder-to-data-load")

    draw = new_draw()
    draw_canvas_base(draw, "04 · Attach Node Explainer — drag from palette", banner=False)
    draw_nodes(draw, tabs=False, selected="compute")
    arrow(draw, (435, 246), (573, 526), BLUE, 3, dash=True)
    _drag_ghost(draw, 573, 556, "Node Explainer", BLUE)
    draw_callout(draw, (250, 464, 604, 524), "Drag from the Agents palette",
                 "Attach an installed agent by dragging it onto this node.", BLUE, BLUE_SOFT)
    emit(draw, "04-attachment-node-explainer-to-node")

    draw = new_draw()
    draw_canvas_base(draw, "05 · Attach Dataflow Builder — drag to canvas", banner=False)
    bx1, by1, bx2, by2 = 228, 150, 1096, 762
    for x in range(bx1, bx2, 18):
        draw.line((x, by1, min(x + 10, bx2), by1), fill=ORANGE, width=3)
        draw.line((x, by2, min(x + 10, bx2), by2), fill=ORANGE, width=3)
    for y in range(by1, by2, 18):
        draw.line((bx1, y, bx1, min(y + 10, by2)), fill=ORANGE, width=3)
        draw.line((bx2, y, bx2, min(y + 10, by2)), fill=ORANGE, width=3)
    draw_nodes(draw)
    arrow(draw, (435, 246), (655, 405), ORANGE, 3, dash=True)
    _drag_ghost(draw, 655, 435, "Dataflow Builder", ORANGE)
    draw_callout(draw, (252, 250, 620, 318), "Drag from the Agents palette",
                 "Canvas hook · dataflow.orchestrate — drag onto the canvas to attach.", ORANGE, ORANGE_SOFT)
    emit(draw, "05-attachment-dataflow-builder-to-canvas")

    draw = new_draw()
    draw_canvas_base(draw, "06 · Unified agent chat — refine in chat", banner=False)
    boxes = draw_nodes(draw, tabs=True, selected="compute", open_agent="explainer")
    draw_dock(draw, hovered=None)
    draw_agent_chat(draw, "Node Explainer", BLUE, "Python Computation", "n4·node-explainer·heat-vuln", 2, 4, [
        {"sys": "Reads code, output, and lineage · suggestions only"},
        {"agent": "It scores exposure × 0.6 + sensitivity × 0.4, then normalises per tract. Assumptions: equal indicator weight; tracts missing ACS fields are dropped."},
        {"agent": "Pick an explanation style:", "card": ("behavior", ["Planner-friendly", "Technical", "Public"], 0)},
    ], quick=["List assumptions", "Suggest fixes"],
        suggested="Explain in the technical style",
        intent="Explain how the vulnerability index is computed, and flag key assumptions.")
    ax, ay = boxes.get("open_anchor", (566, 760))
    arrow(draw, (ax, ay - 4), (1112, 470), BLUE, 2, dash=True)
    emit(draw, "06-agent-refinement-sidebar-open")

    draw = new_draw()
    draw_canvas_base(draw, "07 · Agent session — chat history", banner=False)
    draw_nodes(draw, tabs=True, selected="data", open_agent="dataset")
    draw_agent_chat(draw, "Dataset Finder", GREEN, "Data Loading node", "n1·dataset-finder·heat-vuln", 1, 4, [
        {"sys": "Two lanes · External sources → Node Builder · From your Data Catalog → install flow"},
        {"agent": "Ranked external sources and Data Catalog matches.", "card": ("sources",)},
        {"user": "Build the NOAA node and install Census ACS."},
        {"agent": "NOAA is external — delegating to Node Builder. Census ACS is in the catalog — installing.", "card": ("handoff",)},
        {"agent": "Census ACS installed from the Data Catalog and attached.", "card": ("install", "Installed from the Data Catalog", ["Census ACS · CATALOG"])},
    ], quick=["Open Census ACS in the Data Catalog", "Attach to another node"],
        suggested="Find a tract-level tree-canopy dataset too",
        intent="Find heat, demographic, and tract-level datasets for the Data Loading node.")
    emit(draw, "07-dataset-finder-overview")

    draw = new_draw()
    draw_canvas_base(draw, "08 · Node Builder — generated dataset node", banner=False)
    draw_nodes(draw, tabs=True, selected="data", open_agent="dataset")
    draw_agent_chat(draw, "Node Builder", BLUE, "Data Loading node", "n1·node-builder·heat-vuln", 2, 4, [
        {"sys": "dataset.fetch.author · spawned by Dataset Finder for NOAA Climate Data API · review-before-apply"},
        {"agent": "I built the dataset node for the selected external source — request code, key, params, parsing, error handling, and output. It needs the requests + pandas packages (reviewed install). Review, then send a prompt to add it:", "card": ("preview",)},
    ], quick=["Add NOAA_TOKEN", "Install requests + pandas", "Not now"],
        suggested="Add the NOAA dataset node to Data Loading",
        intent="Implement a fetch node for the NOAA Climate Data API selected in Dataset Finder.")
    emit(draw, "08-dataset-review-modal")

    draw = new_draw()
    draw_canvas_base(draw, "09 · Datasets created in palette", banner=False)
    draw_nodes(draw, tabs=True, selected="data", open_agent="dataset")
    draw_agent_chat(draw, "Dataset Finder", GREEN, "Data Loading node", "n1·dataset-finder·heat-vuln", 1, 4, [
        {"agent": "NOAA dataset node built by Node Builder and attached. Logged to run history.", "card": ("result", "Dataset node created (Node Builder)", ["NOAA · EXTERNAL"])},
        {"agent": "Census ACS installed from the Data Catalog and attached.", "card": ("install", "Installed from the Data Catalog", ["Census ACS · CATALOG"])},
    ], intent="Find heat, demographic, and tract-level datasets for the Data Loading node.")
    _data_dropdown(draw)
    _toast(draw, "NOAA node created (Node Builder) · Census ACS installed from the catalog")
    emit(draw, "09-datasets-created-in-palette")

    draw = new_draw()
    draw_canvas_base(draw, "10 · Dataflow Builder — orchestration", banner=False)
    draw_nodes(draw, tabs=True)
    draw_dock(draw, hovered=0)
    draw_agent_chat(draw, "Dataflow Builder", ORANGE, "Canvas (whole dataflow)", "canvas·dataflow-builder·heat-vuln", 4, 4, [
        {"sys": "dataflow.orchestrate · reads mission, graph, run state · coordinates installed specialists"},
        {"agent": "Plan to reach your outcome:", "card": ("plan", [
            "Find datasets", "Build load + transform nodes", "Connect nodes",
            "Recommend packages", "Validate coherence", "Optimize + explain"])},
        {"sys": "Any missing specialist is added with a reviewed Install in project · never auto-installed"},
        {"agent": "Delegating to the specialists installed in this project (running in the background):", "card": ("agents", [
            ("Dataset Finder", GREEN, "done"),
            ("Node Builder", BLUE, "running"),
            ("Package Recommendation", PURPLE, "running"),
            ("Connection Builder", PURPLE, "queued"),
            ("Dataflow Explainer", BLUE, "queued"),
            ("Validation", PURPLE, "install")])},
    ], quick=["Pause", "Run in background", "Show the plan"],
        suggested="Approve the plan and update the graph",
        intent="Build a dataflow that finds high heat-vulnerability tracts and explains the evidence.")
    arrow(draw, (827, 242), (1112, 300), ORANGE, 2, dash=True)
    emit(draw, "10-dataflow-builder-orchestration")

    draw = new_draw()
    draw_canvas_base(draw, "11 · Agents palette — installed agents", banner=False)
    draw_nodes(draw, tabs=True)
    _agents_dropdown(draw)
    _toast(draw, "Install into this project from the Agents Catalog; drag installed agents to attach", icon="fa-solid:robot", color=ORANGE)
    emit(draw, "11-agents-palette")

    # ── Shared agent settings modal — six screens (12–17) over the canvas ──
    for _sid, _tab, _base in [
        ("12", "Cost", "12-agent-settings-cost"),
        ("13", "Quotas", "13-agent-settings-quotas"),
        ("14", "Resource policies", "14-agent-settings-resource-policies"),
        ("15", "Prompt quality", "15-agent-settings-prompt-quality"),
        ("16", "Prompt editor", "16-agent-settings-prompt-editor"),
        ("17", "Prompt audit", "17-agent-settings-prompt-audit"),
    ]:
        draw = new_draw()
        draw_canvas_base(draw, f"{_sid} · Agent settings — {_tab}", banner=False)
        draw_nodes(draw, tabs=True)
        draw_settings_modal(draw, _tab, "Dataset Finder", GREEN)
        emit(draw, _base)

    draw = new_draw()
    draw_canvas_base(draw, "18 · Agents drawer — lifecycle", banner=False)
    draw_lifecycle_drawer(draw)
    emit(draw, "18-agents-drawer-lifecycle")

    draw = new_draw()
    draw_canvas_base(draw, "19 · Settings — scope applicability", banner=False)
    draw_nodes(draw, tabs=True)
    draw_scope_matrix(draw)
    emit(draw, "19-settings-scope-applicability")

    draw = new_draw()
    draw_canvas_base(draw, "20 · Node Explainer — no node tab", banner=False)
    draw_nodes(draw, tabs=True, selected="compute")
    # a small context popover on the compute node header: the ONLY explanation affordance
    px1, py1 = 560, 556
    shadowed_round(draw, (px1, py1, px1 + 250, py1 + 84), 10, "white", CHAT_BORDER, shadow=True)
    text(draw, (px1 + 14, py1 + 18), "No Explanation tab", CHAT_TITLE, F["small"], anchor="lm")
    draw.rounded_rectangle((px1 + 12, py1 + 34, px1 + 238, py1 + 68), radius=8, fill=BLUE_SOFT)
    bot(draw, px1 + 22, py1 + 40, BLUE, 0.6)
    text(draw, (px1 + 48, py1 + 51), "Explain with Node Explainer", BLUE, F["tiny"], anchor="lm")
    arrow(draw, (px1 + 125, py1), (620, 470), BLUE, 2, dash=True)
    draw_callout(draw, (250, 250, 620, 320), "Explanation is an agent, not a node tab",
                 "'Explain with Node Explainer' opens the normal install · attach · chat workflow.", BLUE, BLUE_SOFT)
    emit(draw, "20-node-explainer-only-workflow")

    # My Imports scope of the Agents Catalog drawer — the owned imported definitions with the
    # SAME catalog publishing controls as datasets / node packs: Install · Publish → Published
    # pill (to the global Catalog Hub) · Delete. Publishing is imported-only and lives here.
    draw = new_draw()
    draw_canvas_base(draw, "21 · Agents Catalog — My Imports · publish to the Catalog Hub")
    draw_nodes(draw)
    draw_catalog(draw, selected="builder", scope="My Imports")
    emit(draw, "21-agents-catalog-my-imports-publish")


if __name__ == "__main__":
    import sys
    targets = sys.argv[1:] or ["png", "svg"]
    for _m in targets:
        MODE = _m
        render_all()
    print("rendered:", ", ".join(targets))
