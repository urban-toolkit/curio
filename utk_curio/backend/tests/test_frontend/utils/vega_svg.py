"""Vega-Lite SVG helpers: rows from a ``.data`` dict and structural SVG compares."""

import os

from .environment import state_root


PLAYWRIGHT_EXPECTED_DIR = os.path.join(state_root(), "playwright", "expected")


# ---------------------------------------------------------------------------
# Vega-Lite SVG helpers
# ---------------------------------------------------------------------------

def dot_data_to_vega_values(data: dict) -> list[dict]:
    """Convert a ``.data`` dict to the row-oriented list that Vega expects.

    Mirrors the frontend ``parseDataframe`` / ``parseGeoDataframe`` functions
    in ``src/utils/parsing.ts``.

    The ``dataframe`` format can be either dict-of-dicts (``to_dict()``)
    or dict-of-lists (``to_dict(orient='list')``); both are handled.
    """
    dtype = data.get("dataType")
    raw = data.get("data", {})
    if dtype == "dataframe":
        columns = list(raw.keys())
        first_col = raw[columns[0]]
        if isinstance(first_col, dict):
            keys = list(first_col.keys())
        else:
            keys = list(range(len(first_col)))
        return [
            {col: raw[col][k] for col in columns}
            for k in keys
        ]
    elif dtype == "geodataframe":
        return [f["properties"] for f in raw.get("features", [])]
    return []


def save_expected_svg(dataflow_name: str, node_id: str, svg_content: str) -> str:
    """Save a programmatically generated expected SVG to
    ``.curio/playwright/expected/<dataflow_name>/<node_id>.svg``.

    Returns the absolute path of the saved file.
    """
    dest_dir = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name)
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{node_id}.svg")
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg_content)
    return path


def load_expected_svg(dataflow_name: str, node_id: str) -> str | None:
    """Load a previously saved expected SVG, or return ``None``."""
    path = os.path.join(PLAYWRIGHT_EXPECTED_DIR, dataflow_name, f"{node_id}.svg")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def compare_svg_structure(
    actual_svg: str,
    expected_svg: str,
) -> list[str]:
    """Structurally compare two Vega-rendered SVG strings.

    Returns an empty list when the two SVGs are structurally equivalent.

    The comparison walks the ``<g>`` element tree and checks that both
    SVGs share the same hierarchy of ``class``, ``role``, and
    ``aria-roledescription`` attributes at every level.
    """
    import xml.etree.ElementTree as ET

    SVG_NS = "http://www.w3.org/2000/svg"

    _STRUCTURAL_ATTRS = ("class", "role", "aria-roledescription")

    def _parse(svg_str: str, label: str):
        try:
            return ET.fromstring(svg_str), []
        except ET.ParseError as e:
            return None, [f"{label} SVG is not valid XML: {e}"]

    def _sig(el) -> str:
        """Structural signature of an element: tag + key attributes."""
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        parts = [tag]
        for attr in _STRUCTURAL_ATTRS:
            val = el.get(attr)
            if val:
                parts.append(f"{attr}={val}")
        return "|".join(parts)

    def _g_children(el):
        """Return direct ``<g>`` children of *el*."""
        return [
            ch for ch in el
            if ch.tag == f"{{{SVG_NS}}}g" or ch.tag == "g"
        ]

    def _compare_g_tree(actual_el, expected_el, path: str, diffs: list):
        """Recursively compare ``<g>`` sub-trees by structural signature."""
        actual_gs = _g_children(actual_el)
        expected_gs = _g_children(expected_el)

        if len(actual_gs) != len(expected_gs):
            diffs.append(
                f"At {path}: <g> child count differs — "
                f"actual={len(actual_gs)}, expected={len(expected_gs)}"
            )
            return

        for i, (a_g, e_g) in enumerate(zip(actual_gs, expected_gs)):
            a_sig = _sig(a_g)
            e_sig = _sig(e_g)
            child_path = f"{path}/g[{i}]"
            if a_sig != e_sig:
                diffs.append(
                    f"At {child_path}: signature mismatch — "
                    f"actual=({a_sig}), expected=({e_sig})"
                )
            else:
                _compare_g_tree(a_g, e_g, child_path, diffs)

    diffs: list[str] = []

    actual_root, errs = _parse(actual_svg, "Actual")
    if errs:
        return errs
    expected_root, errs = _parse(expected_svg, "Expected")
    if errs:
        return errs

    _compare_g_tree(actual_root, expected_root, "svg", diffs)

    return diffs
