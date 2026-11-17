"""An account's own node libraries, which its nodes import in front of the image's, installed offline.

Under fork isolation an account's package libraries go to a tree of its own
(``backend_runtime.user_node_overlay_dir``), which node code imports in front
of this interpreter, the image's. The tests here install into such trees with
the real pip, from a wheelhouse of their own (``PIP_FIND_LINKS`` with
``PIP_NO_INDEX``), never an index:

- :data:`OTHER_TORCH`, a torch that is not the image's: version 2.99.0, above
  every torch the image has, a module of one string;
- :data:`NEEDS_TORCH`, a library the image lacks that requires ``torch>=2.6``,
  as the Discovery Catalog's Hugging Face models declare it.

The image's torch is this interpreter's own, which :func:`the_images_torch`
checks meets ``>=2.6`` and is below 2.99, so a test about it cannot pass for
a torch that is not there.
"""

from __future__ import annotations

from importlib.metadata import distributions, version
from pathlib import Path

from utk_curio.backend.tests._support.offline_wheels import WheelLibrary, write_wheelhouse

#: A torch that is not the image's.
OTHER_TORCH = WheelLibrary(
    dist="torch", version="2.99.0", module="curio_not_the_images_torch", message="not the image's torch",
)
#: A library the image lacks, which requires a torch the image's meets.
NEEDS_TORCH = WheelLibrary(
    dist="curio-needs-torch", version="1.0.0", module="curio_needs_torch", message="needs torch",
    requires=("torch>=2.6",),
)


def offline_pip(monkeypatch, folder) -> Path:
    """pip, for the rest of the test, installs from a wheelhouse in *folder*
    holding :data:`OTHER_TORCH` and :data:`NEEDS_TORCH`, never from an index,
    and as this process's account."""
    house = write_wheelhouse(folder, [OTHER_TORCH, NEEDS_TORCH])
    monkeypatch.setenv("PIP_NO_INDEX", "1")
    monkeypatch.setenv("PIP_FIND_LINKS", str(house))
    monkeypatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    monkeypatch.delenv("CURIO_EXEC_USER", raising=False)
    return house


def the_images_torch() -> str:
    """This interpreter's torch, the image's: its version, checked to meet
    ``>=2.6`` and to be below :data:`OTHER_TORCH`'s."""
    from packaging.specifiers import SpecifierSet

    torch = version("torch")
    assert torch in SpecifierSet(">=2.6") and torch not in SpecifierSet(f">={OTHER_TORCH.version}"), (
        f"this interpreter's torch is {torch}: the tests about the image's need one of 2.6 or later, "
        f"below {OTHER_TORCH.version}")
    return torch


def held(tree) -> dict[str, str]:
    """Each distribution the tree *tree* holds, by the name its metadata
    gives, with its version."""
    return {dist.metadata["Name"]: dist.version for dist in distributions(path=[str(tree)])}
