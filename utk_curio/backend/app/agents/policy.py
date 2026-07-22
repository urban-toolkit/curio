"""Effective agent policy: resolution + downward-only validation (memo ``dev/24``).

One resolver serves both the settings screens (display) and run admission
(enforcement), so what a user sees is exactly what runs hit. Resolution per
field is ``project ?? account ?? deployment``, **clamped downward at read** —
a stored value looser than its parent scope's effective value can never leak
through, even if it was legal when written. ``validate_patch`` additionally
rejects loosening at write time with field-specific messages (memo ``dev/11``'s
tighten-only rule).

v1 fields (all optional per scope):
  quotas.runsPerDay              int > 0    account + project
  cost.dailyBudgetUsd            number > 0 account + project
  cost.estimatedCostPerRunUsd    number > 0 account only (pricing, not per-template)
  resources.maxOutputTokens      int > 0    account + project
"""

from __future__ import annotations

import numbers

from utk_curio.backend.app.agents import quotas

DEPLOYMENT_MAX_OUTPUT_TOKENS = 4096

# section -> {key: (numeric_kind, account_allowed, project_allowed)}
_FIELDS: dict[str, dict[str, tuple[str, bool, bool]]] = {
    "quotas": {"runsPerDay": ("int", True, True)},
    "cost": {
        "dailyBudgetUsd": ("number", True, True),
        "estimatedCostPerRunUsd": ("number", True, False),
    },
    "resources": {"maxOutputTokens": ("int", True, True)},
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
        "quotas": {"runsPerDay": quotas.runs_per_day_limit()},
        "cost": {"dailyBudgetUsd": None, "estimatedCostPerRunUsd": None},
        "resources": {"maxOutputTokens": DEPLOYMENT_MAX_OUTPUT_TOKENS},
    }


def _resolve(section: str, key: str, account: dict | None, project: dict | None) -> dict:
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
    return {"value": value, "source": source}


def effective(account_settings: dict | None, project_settings: dict | None = None) -> dict:
    """The resolved policy with per-field provenance."""
    out: dict = {}
    for section, keys in _FIELDS.items():
        out[section] = {key: _resolve(section, key, account_settings, project_settings) for key in keys}
    budget = out["cost"]["dailyBudgetUsd"]["value"]
    estimate = out["cost"]["estimatedCostPerRunUsd"]["value"]
    # The estimated-budget gate is active only when both halves are configured.
    out["cost"]["configured"] = budget is not None and estimate is not None
    return out


def validate_patch(settings: object, scope: str, parent_effective: dict) -> dict:
    """Validate a scope's settings payload against its parent's effective policy.

    Returns the cleaned settings dict (known fields only). *parent_effective*
    is ``effective(...)`` of the scope above: the deployment view for the
    account scope, the account view for the project scope.
    """
    if not isinstance(settings, dict):
        raise PolicyValidationError("settings must be an object")
    allowed_idx = 1 if scope == "account" else 2
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
