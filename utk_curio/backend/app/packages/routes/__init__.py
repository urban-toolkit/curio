"""Flask blueprint mounted at ``/api/packages`` (memo dev/143, B4: one blueprint, registered
from the resource modules that import it — ``store``, ``catalog``, ``factory``, ``dependencies``,
``projects``, ``defaults``, ``libraries``, ``backend``; thin over ``application/``).

Endpoint matrix (every route is ``@require_auth``; user storage key
derives from ``app.projects.services._user_dir_key`` just like
``/api/projects``):

+-------------------------------------------+--------------------------------+
| Endpoint                                  | Plan todo                      |
+===========================================+================================+
| ``GET /api/packages``                        | spike (already shipped)        |
| ``POST /api/packages/upload``                | catalog-api-ui (this commit)   |
| ``DELETE /api/packages/<dir>``               | catalog-api-ui (this commit)   |
| ``GET /api/packages/<dir>/archive``          | catalog-api-ui (this commit)   |
| ``GET /api/packages/catalog``                | catalog-api-ui (this commit)   |
| ``POST /api/packages/factory/build``         | factory-impl (this commit)     |
| ``POST /api/packages/factory/install``       | factory-impl (this commit)     |
| ``GET /api/packages/factory/capabilities``  | wizard - publish gated flags   |
| ``POST /api/packages/factory/publish-catalog`` | dev catalog fixture write (on by default; env to disable) |
| ``DELETE /api/packages/catalog/<dir>``       | dev catalog fixture remove (same env gate as publish) |
| ``POST /api/packages/resolve``               | dep-resolver (this commit)     |
+-------------------------------------------+--------------------------------+

``GET /api/packages/catalog`` is **catalog-backed**: it scans committed packages
under ``<repo_root>/packages/`` and returns package rows plus a family index and
collision report. A **separate remote package-registry** service is still future work.
"""

from utk_curio.backend.app.packages.routes.common import (  # noqa: F401
    _error,
    _map_package_errors,
    _packages_error,
    packages_bp,
)
from utk_curio.backend.app.packages.routes import (  # noqa: E402,F401  (handlers register on import)
    backend,
    catalog,
    defaults,
    dependencies,
    factory,
    libraries,
    projects,
    store,
)

__all__ = ["packages_bp", "_error", "_map_package_errors", "_packages_error"]
