"""The packages package's layering, as a test (memo dev/143, B5) — the same rule
engine as the agents suite (``tests/_support/layering.py``), parameterized:

- ``domain ← schemas ← repositories ← infrastructure ← application ← routes``:
  ``domain/`` imports nothing from the other layers or from other features;
  ``schemas/`` imports only ``domain``; ``repositories/`` imports ``domain`` (and
  ``common``); ``infrastructure/`` imports ``domain`` and ``repositories`` (memo
  §3.2 rule 2: the store paths are downward of the processes); ``application/``
  imports everything beneath it plus ``builder/``, the Package Builder subsystem
  beside the layers, which may reach every layer and is reached only by
  ``application`` and ``routes``.
- No in-function import inside the package of the facade, ``application/`` or
  ``builder/`` — the cycle-hiding pattern the monolith lived on; only the two
  cross-feature imports (``users.services``, ``config``) stay lazy.
- ``service.py`` is a facade: it defines nothing, it re-exports.
- No function under ``application/`` or ``builder/`` exceeds 150 lines (B3).
- The B1 alias shims and the B2 compatibility modules are gone: the root is
  ``__init__.py`` + ``service.py``; ``routes.py`` and ``services.py`` do not exist.
"""

from __future__ import annotations

from pathlib import Path

import utk_curio.backend.app.packages as packages_pkg
from utk_curio.backend.tests._support import layering

BASE = "utk_curio.backend.app.packages"
PACKAGES = layering.LayeredPackage(
    root=Path(packages_pkg.__file__).resolve().parent,
    base=BASE,
    may_import={
        "domain": {"domain"},
        "schemas": {"domain", "schemas"},
        "repositories": {"domain", "repositories"},
        "infrastructure": {"domain", "repositories", "infrastructure"},
        "application": {"domain", "schemas", "repositories", "infrastructure", "application", "builder"},
    },
    beside={"builder"},
    bounded_dirs=("application", "builder"),
    lazy_allowed_inside={f"{BASE}.domain", f"{BASE}.repositories", f"{BASE}.infrastructure", f"{BASE}.schemas"},
)


def test_layers_only_import_downward():
    assert layering.downward_only_offenders(PACKAGES) == []


def test_domain_imports_no_other_layer_and_no_other_feature():
    assert layering.pure_layer_offenders(PACKAGES, "domain", (f"{BASE}.domain",)) == []


def test_schemas_import_only_domain():
    assert layering.pure_layer_offenders(PACKAGES, "schemas", (f"{BASE}.domain", f"{BASE}.schemas")) == []


def test_no_in_function_import_of_the_facade_application_or_builder_inside_the_package():
    assert layering.lazy_inside_offenders(PACKAGES) == []


def test_the_facade_defines_nothing():
    assert layering.facade_defines_nothing(PACKAGES)


def test_no_application_or_builder_function_exceeds_150_lines():
    assert layering.oversize_functions(PACKAGES) == []


def test_the_shims_and_the_compatibility_modules_are_gone():
    assert layering.root_modules(PACKAGES) == ["__init__.py", "service.py"]
    assert not (PACKAGES.root / "routes.py").exists()
    assert not (PACKAGES.root / "services.py").exists()
