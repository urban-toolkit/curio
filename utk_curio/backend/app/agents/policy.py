"""Effective agent policy: resolution + downward-only validation.

Resolution per field is ``attachment ?? project ?? account ?? deployment``,
**clamped downward at read**: a stored value looser than its parent scope's
effective value can never leak through, even if it was legal when written.
``validate_patch`` additionally rejects loosening at write time with
field-specific messages.

**One field remains.** ``quotas.runsPerDay`` and the whole ``cost`` section
(``dailyBudgetUsd``, ``estimatedCostPerRunUsd``) are gone with the metering
they served: Curio does not cap or price agent runs. ``maxOutputTokens`` stays
because it is not a quota at all - it is passed to the provider as
``max_tokens`` on every completion, so it shapes one reply rather than
rationing a day's worth.

Fields (optional per scope):
  resources.maxOutputTokens      int > 0    account + project + attachment
"""

from __future__ import annotations

import numbers

DEPLOYMENT_MAX_OUTPUT_TOKENS = 4096

# section -> {key: (numeric_kind, account_allowed, project_allowed, attachment_allowed)}
_FIELDS: dict[str, dict[str, tuple[str, bool, bool, bool]]] = {
    "resources": {"maxOutputTokens": ("int", True, True, True)},
}


class PolicyValidationError(ValueError):
    """A settings patch violates the field contract or the tighten-only rule."""


class StaleRevisionError(Exception):
    """A settings PATCH carried an outdated revision (→ 409)."""


def _value(settings: dict | None, section: str, key: str):
    if not isinstance(settings, dict):
        return None
    sect = settings.get(section)
    if not isinstance(sect, dict):
        return None
    v = sect.get(key)
    return v if isinstance(v, numbers.Real) and not isinstance(v, bool) else None


def deployment_defaults() -> dict:
    """The deployment scope: env-derived defaults that double as ceilings."""
    return {
        "resources": {"maxOutputTokens": DEPLOYMENT_MAX_OUTPUT_TOKENS},
    }


def _resolve(
    section: str,
    key: str,
    account: dict | None,
    project: dict | None,
    attachment: dict | None,
) -> dict:
    dep = deployment_defaults()[section][key]
    value, source = dep, ("deployment" if dep is not None else None)
    acc = _value(account, section, key)
    if acc is not None:
        value = min(acc, value) if value is not None else acc
        source = "account"
    proj = _value(project, section, key)
    if proj is not None:
        value = min(proj, value) if value is not None else proj
        source = "project"
    att = _value(attachment, section, key)
    if att is not None:
        value = min(att, value) if value is not None else att
        source = "attachment"
    return {"value": value, "source": source}


def effective(
    account_settings: dict | None,
    project_settings: dict | None = None,
    attachment_settings: dict | None = None,
) -> dict:
    """The resolved policy with per-field provenance (memo dev/42: the third,
    attached-instance layer resolves exactly like the second — downward only)."""
    out: dict = {}
    for section, keys in _FIELDS.items():
        out[section] = {
            key: _resolve(section, key, account_settings, project_settings, attachment_settings)
            for key in keys
        }
    return out


_SCOPE_INDEX = {"account": 1, "project": 2, "attachment": 3}


def validate_patch(settings: object, scope: str, parent_effective: dict) -> dict:
    """Validate a scope's settings payload against its parent's effective policy.

    Returns the cleaned settings dict (known fields only). *parent_effective*
    is ``effective(...)`` of the scope above: the deployment view for the
    account scope, the account view for the project scope, the
    project-effective view for the attachment scope (memo dev/42).
    """
    if not isinstance(settings, dict):
        raise PolicyValidationError("settings must be an object")
    allowed_idx = _SCOPE_INDEX.get(scope, 2)
    cleaned: dict = {}
    for section, body in settings.items():
        keys = _FIELDS.get(section)
        if keys is None:
            raise PolicyValidationError(f"unknown settings section {section!r}")
        if not isinstance(body, dict):
            raise PolicyValidationError(f"settings.{section} must be an object")
        for key, value in body.items():
            spec = keys.get(key)
            if spec is None:
                raise PolicyValidationError(f"unknown setting {section}.{key}")
            kind = spec[0]
            if not spec[allowed_idx]:
                raise PolicyValidationError(f"{section}.{key} is not editable at the {scope} scope")
            if value is None:
                continue  # explicit null clears the override
            if isinstance(value, bool) or not isinstance(value, numbers.Real):
                raise PolicyValidationError(f"{section}.{key} must be a number")
            if kind == "int" and int(value) != value:
                raise PolicyValidationError(f"{section}.{key} must be an integer")
            if value <= 0:
                raise PolicyValidationError(f"{section}.{key} must be positive")
            ceiling = parent_effective.get(section, {}).get(key, {}).get("value")
            if ceiling is not None and value > ceiling:
                raise PolicyValidationError(
                    f"{section}.{key} may not exceed the inherited limit ({ceiling})"
                )
            cleaned.setdefault(section, {})[key] = int(value) if kind == "int" else float(value)
    return cleaned
