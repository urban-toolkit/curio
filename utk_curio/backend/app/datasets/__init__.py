"""Dataset catalog feature boundary."""

# Imported for its side effect: registering DatasetIndexEntry on the SQLAlchemy
# metadata, so ``db.create_all()`` (tests) and Alembic autogenerate see the
# table. The projects package gets this transitively through its repositories
# module; the dataset index is only touched through lazy imports, so it needs an
# explicit one here.
from utk_curio.backend.app.datasets import models as _models  # noqa: F401
from utk_curio.backend.app.datasets.routes import datasets_bp

__all__ = ["datasets_bp"]
