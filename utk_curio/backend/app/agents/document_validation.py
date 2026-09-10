"""Validating the content the sandbox cannot run.

Memo dev/129, from the owner's instruction: *"it should never put failing code
inside a node."*

``DEC-075`` (dev/118) made Solve honest about node kinds the sandbox cannot
execute — a Vega-Lite chart, an AUTK map grammar — by writing their content and
saying plainly that it was not executed. Honest, and too permissive: those
kinds carry a **document**, and "cannot be run" is not "cannot be checked". The
field proof is dataflow ``00708324``, where the Vega spec Solve wrote and
called *solved* is invalid — ``altair`` (already a dependency, its Vega-Lite
schema bundled) reports ``additional property 'else' is not allowed`` inside
``encoding.color.condition`` — and the node renders red while the chat says
solved.

So a document is validated before it is written, and the answer is one of three
things, never a guess:

- ``valid``    — write it, and say it was validated as a document, not executed;
- ``invalid``  — a failed ROUND: the validator's message is the correction, and
                 the loop's existing budget and trail carry it;
- ``unchecked``— nothing here can check this kind: write NOTHING and say so.

Kind routing is by canonical template id (``DEC-076``'s rule: the roster, not a
name list). Pure: no I/O, no network, no spec.
"""

from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

STATUS_VALID = "valid"
STATUS_INVALID = "invalid"
STATUS_UNCHECKED = "unchecked"

#: The marker a passive node's content carries — nothing was authored, so there
#: is nothing to validate and nothing to write.
NOT_CONTROLLABLE = "not controllable"

_DETAIL_CHARS = 600
#: Placeholder data for validation only: Curio supplies a Vega node's data at
#: render time from its input, so a spec without ``data`` is CORRECT here and
#: the schema's "data is required" must not be reported as the author's error.
_DATA_STUB = {"values": [{}]}


def _detail(text: object) -> str:
    return str(text or "").strip()[:_DETAIL_CHARS]


def _parse_json(content: str) -> tuple[object | None, str | None]:
    try:
        return json.loads(content), None
    except ValueError as exc:
        return None, f"the document is not valid JSON: {exc}"


def validate_vega_lite(content: str) -> dict:
    """A Vega-Lite document, against the schema ``altair`` bundles offline."""
    payload, error = _parse_json(content)
    if error:
        return {"status": STATUS_INVALID, "detail": _detail(error)}
    if not isinstance(payload, dict):
        return {"status": STATUS_INVALID,
                "detail": "a Vega-Lite document must be a JSON object"}
    try:
        import altair as alt
    except Exception as exc:  # noqa: BLE001
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"altair is unavailable, so the Vega-Lite schema "
                               f"could not be read: {exc}")}
    spec = dict(payload)
    if "data" not in spec:
        # Never overwrite an author's own data block; only stand in for the one
        # the runtime injects.
        spec["data"] = _DATA_STUB
    try:
        alt.Chart.from_dict(spec, validate=True)
    except Exception as exc:  # noqa: BLE001  (altair raises SchemaValidationError)
        return {"status": STATUS_INVALID, "detail": _vega_message(exc)}
    return {"status": STATUS_VALID}


def _vega_message(exc: Exception) -> str:
    """The offending property and where it sits, from a schema error.

    ``altair``'s message is a full schema dump; the first line carries the
    complaint and the ``$.…`` path line carries the location. Both are worth
    keeping, nothing after them is.
    """
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return _detail(f"{type(exc).__name__}: the document does not match the Vega-Lite schema")
    head = lines[0]
    # A JSON path (``$.encoding.color.condition``) is the useful location when
    # altair emits one; the bare "On instance:" label and the schema dump that
    # follows are not, so they are dropped rather than truncated into noise.
    path = next((line for line in lines if line.startswith("$.")), "")
    rule = next(
        (line for line in lines if line.startswith("Failed validating")), ""
    )
    parts = [head]
    if path:
        parts.append(f"at {path}")
    elif rule:
        parts.append(rule.rstrip(":"))
    return _detail(" — ".join(parts))


#: AUTK map grammar: what the renderer requires of any document (memo dev/129).
#: Deliberately structural — the parts a document cannot render without — and
#: honest that it is not the whole grammar.
def validate_autk_grammar(content: str) -> dict:
    payload, error = _parse_json(content)
    if error:
        return {"status": STATUS_INVALID, "detail": _detail(error)}
    if not isinstance(payload, dict):
        return {"status": STATUS_INVALID,
                "detail": "an AUTK grammar document must be a JSON object"}
    grammar = payload.get("map")
    if not isinstance(grammar, dict):
        return {"status": STATUS_INVALID,
                "detail": 'the document has no "map" object — an AUTK grammar '
                          'is {"map": {"layerRefs": [...], ...}}'}
    layers = grammar.get("layerRefs")
    if not isinstance(layers, list) or not layers:
        return {"status": STATUS_INVALID,
                "detail": '"map.layerRefs" must be a non-empty list — a map with no '
                          "layer renders nothing"}
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            return {"status": STATUS_INVALID,
                    "detail": f'"map.layerRefs[{index}]" must be an object'}
        if not str(layer.get("dataRef") or "").strip():
            return {"status": STATUS_INVALID,
                    "detail": f'"map.layerRefs[{index}].dataRef" is missing — a layer '
                              "must name the data it draws (the metadata name the "
                              "upstream node set)"}
    view = grammar.get("initialView")
    if view is not None:
        if not isinstance(view, dict):
            return {"status": STATUS_INVALID, "detail": '"map.initialView" must be an object'}
        center = view.get("center")
        if center is not None and not (
            isinstance(center, list) and len(center) == 2
            and all(isinstance(v, (int, float)) for v in center)
        ):
            return {"status": STATUS_INVALID,
                    "detail": '"map.initialView.center" must be [longitude, latitude]'}
    return {"status": STATUS_VALID}


#: canonical template id suffix → validator. Read by ``validate`` only, so a new
#: grammar kind is one entry rather than a branch somewhere.
_VALIDATORS = {
    "vis-vega": validate_vega_lite,
    "autk-grammar": validate_autk_grammar,
}

#: Kinds whose content is never authored (the preamble's "uncontrollable"
#: boxes): nothing to validate, and nothing to write.
_PASSIVE = ("merge-flow", "data-pool", "vis-simple", "spatial-join")


def canonical_suffix(node_type: object) -> str:
    """``"curio.builtin/vis-vega@2"`` → ``"vis-vega"`` (versioned and legacy
    enum spellings tolerated, as everywhere else)."""
    return str(node_type or "").rsplit("/", 1)[-1].split("@", 1)[0].lower().replace("_", "-")


def validate(node_type: object, content: object) -> dict:
    """Validate a non-executable node's content. See the module docstring."""
    text = content if isinstance(content, str) else ""
    suffix = canonical_suffix(node_type)
    if not text.strip() or text.strip().lower() == NOT_CONTROLLABLE:
        # A passive box's marker, or nothing at all: there is no document.
        return {"status": STATUS_UNCHECKED,
                "why": "there is no authored document to validate",
                "passive": suffix in _PASSIVE}
    validator = _VALIDATORS.get(suffix)
    if validator is None:
        return {"status": STATUS_UNCHECKED,
                "why": f"no document validator exists for {suffix or 'this kind'}",
                "passive": suffix in _PASSIVE}
    try:
        return validator(text)
    except Exception as exc:  # noqa: BLE001
        log.warning("Document validation failed for %s", suffix, exc_info=True)
        return {"status": STATUS_UNCHECKED,
                "why": _detail(f"the validator for {suffix} could not run: {exc}")}


def refusal_text(node_type: object, verdict: dict) -> str:
    """What the model is told, and what a human reads in the trail."""
    suffix = canonical_suffix(node_type)
    what = "Vega-Lite" if suffix == "vis-vega" else (
        "AUTK map grammar" if suffix == "autk-grammar" else suffix or "document"
    )
    return (
        f"document refused — this node's content is a {what} document and it does not "
        f"validate: {_detail(verdict.get('detail'))}. Fix exactly that and return the "
        "whole document; nothing is written to the node until it validates."
    )
