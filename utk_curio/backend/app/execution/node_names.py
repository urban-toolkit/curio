"""What a node is called: the name its canvas header shows (#775).

The twin of ``utils/nodeDisplayLabel.ts``, which ``resolveNodeDisplayLabel``
calls for the header; ``utils/nodeDisplayLabel.cases.json`` beside it holds the
cases both sides run. The name titles the node's computed dataset whichever
path saves it (a save, a node's play, a run on the server), and is what a run
on the server calls the node in its steps and skip reasons.

- :func:`display_label`: the node's renamed header, else its template's label,
  else its type in words without the version. A purely numeric type is a node
  id rather than a template: the renamed header names it, else the id itself.
- :func:`saved_node_label`: the same, for a node as a saved dataflow holds it.
- :func:`template_labels`: each template's label by unversioned id, for the
  templates a project can use (what the canvas's registry holds).
"""
from __future__ import annotations

import logging
import re
from typing import Mapping, Optional

log = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"@[0-9]+$")
_WORD_BREAK_RE = re.compile(r"[-_\s]+")
_NUMERIC_RE = re.compile(r"^[0-9]+$")


def _as_text(value) -> str:
    return "" if value is None else str(value).strip()


def _label_text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def humanize_node_type(node_type) -> str:
    """A node type in words, without its package or version:
    ``curio.builtin/data-loading@1`` is "Data Loading"."""
    text = _as_text(node_type)
    base = _VERSION_RE.sub("", text.rsplit("/", 1)[-1])
    words = [word for word in _WORD_BREAK_RE.split(base) if word]
    return " ".join(word[:1].upper() + word[1:].lower() for word in words)


def display_label(node_type, custom_label=None, template_label=None) -> str:
    """The name of a node of *node_type*: *custom_label* (its renamed header),
    else *template_label* (its template's label), else the type in words."""
    custom = _label_text(custom_label)
    if custom:
        return custom
    type_text = _as_text(node_type)
    if _NUMERIC_RE.match(type_text):
        return type_text
    return _label_text(template_label) or humanize_node_type(type_text)


def saved_node_label(node: Mapping, labels: Optional[Mapping[str, str]] = None) -> str:
    """:func:`display_label` of a node as a saved dataflow holds it: the renamed
    header at ``metadata.packageTemplateLabel`` (or the older
    ``data.packageTemplateLabel``), the type at ``type`` (or ``data.nodeType``),
    and the template's label looked up in *labels* by unversioned id."""
    from utk_curio.backend.app.packages.service import canonical_template_id

    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    metadata = node.get("metadata") if isinstance(node.get("metadata"), dict) else {}
    custom = _label_text(metadata.get("packageTemplateLabel")) or _label_text(
        data.get("packageTemplateLabel")
    )
    node_type = node.get("type") or data.get("nodeType")
    template = (labels or {}).get(canonical_template_id(node_type)) if node_type else None
    return display_label(node_type, custom, template)


def template_labels(user_key: str, project_id: str) -> dict:
    """``{unversioned template id: label}`` for the templates *project_id* may
    use. Empty when the package store cannot be read: names then fall back to
    the type in words, as the canvas's do before its registry loads."""
    try:
        from utk_curio.backend.app.packages.service import available_templates

        return {
            row["id"]: row.get("label") or ""
            for row in available_templates(user_key, project_id)
            if isinstance(row, dict) and row.get("id")
        }
    except Exception:  # noqa: BLE001 - a name is never worth failing a save or a run
        log.warning("template labels for project %s could not be read", project_id, exc_info=True)
        return {}
