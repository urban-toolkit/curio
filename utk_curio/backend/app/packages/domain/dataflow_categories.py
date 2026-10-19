"""The ``dataflowCategories`` a manifest declares (pure; the standard library only).

A package, one of its templates, or a dataset names the tags and data types a
dataflow that uses it shows on the Projects page's rail and in the canvas's
title chips::

    "dataflowCategories": {"tags": ["SCOUT"], "dataTypes": ["Rasters"]}

Both manifest parsers read the field here, the package's (``manifest.py``) and
the dataset's (``datasets/domain/manifest.py``), so they clean it alike and as
the rail's hand-set categories are cleaned (``projects/categories.py``
``normalize_hand``): each value trimmed, its spaces collapsed, cut to
``MAX_VALUE_LENGTH`` characters, a repeat of an earlier value in another case
dropped (the first spelling stays), and at most ``MAX_VALUES`` values in a
list. A value of the wrong type is refused. The dataset parser imports this
module, so it imports nothing of Curio's.
"""

from __future__ import annotations

#: The manifest key.
FIELD = "dataflowCategories"
#: Its lists, in the order a cleaned declaration holds them.
SECTIONS = ("tags", "dataTypes")
#: The most characters a value keeps.
MAX_VALUE_LENGTH = 40
#: The most values a list keeps.
MAX_VALUES = 20


class DataflowCategoriesError(ValueError):
    """A ``dataflowCategories`` value of the wrong type."""


def clean_dataflow_categories(raw: object, *, where: str) -> dict[str, list[str]] | None:
    """The tags and data types *raw* declares, cleaned; None when it declares none.

    *raw* is a manifest's ``dataflowCategories`` value, None when the manifest
    has no such key. The result holds each list that keeps a value, in
    ``SECTIONS`` order. *where* names the value in a refusal.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise DataflowCategoriesError(
            f"{where} must be an object with 'tags' and 'dataTypes' lists, got {type(raw).__name__}"
        )
    unknown = sorted(str(key) for key in raw if key not in SECTIONS)
    if unknown:
        raise DataflowCategoriesError(f"{where} holds only 'tags' and 'dataTypes', not {unknown}")
    cleaned: dict[str, list[str]] = {}
    for section in SECTIONS:
        if section in raw:
            values = _clean_list(raw[section], where=f"{where}.{section}")
            if values:
                cleaned[section] = values
    return cleaned or None


def _clean_list(raw: object, *, where: str) -> list[str]:
    if not isinstance(raw, list):
        raise DataflowCategoriesError(f"{where} must be a list of strings, got {type(raw).__name__}")
    out: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, str):
            raise DataflowCategoriesError(f"{where}[{index}] must be a string, got {type(value).__name__}")
        text = " ".join(value.split())[:MAX_VALUE_LENGTH].strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        out.append(text)
    return out[:MAX_VALUES]
