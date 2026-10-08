"""A node's code as the sandbox defines it: the ``userCode`` function.

Node code reads files by paths relative to the folder it runs in, and the
dataflows Curio ships read their example data at ``docs/examples/data/...``.
A clone, the Docker image and CI run node code in a folder that holds
``docs/``. A pip install keeps ``docs/`` inside ``utk_curio/``
(``utk_curio/shipped.py``) and runs node code in the folder Curio started
from, which is the user's and holds none.

So a string literal in the code that is a relative path in ``docs/``, which the
folder the code runs in does not hold and Curio ships, is read where Curio
ships it: the literal becomes that file's absolute path. Every other literal,
and code with no such literal, is left as it is. The in-process path
(``app/worker.py``) and the isolated child (``isolation/child.py``) both define
the function here; an isolated run's work directory links the ``docs/`` Curio
ships instead (``isolation/supervisor.py``), so there the folder holds it.
"""

import ast
import os
from pathlib import PurePosixPath

from utk_curio import shipped

#: The folder of Curio's that node code reads by a path relative to it.
DOCS = "docs"


def _shipped_path(literal, cwd):
    """The absolute path *literal* reads, when it is a relative path in
    ``docs/`` that *cwd* does not hold and Curio ships; else None."""
    if not literal.startswith(DOCS + "/"):
        return None
    try:
        if os.path.lexists(os.path.join(cwd, literal)):
            return None
        target = shipped.path(PurePosixPath(literal))
        if not target.exists():
            return None
    except (OSError, ValueError):
        return None
    return str(target) + ("/" if literal.endswith("/") else "")


class _ShippedDocs(ast.NodeTransformer):
    """Points each literal that reads a shipped file at that file."""

    def __init__(self, cwd):
        self.cwd = cwd
        self.changed = False

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            target = _shipped_path(node.value, self.cwd)
            if target is not None:
                self.changed = True
                return ast.copy_location(ast.Constant(value=target), node)
        return node


def compile_user_code(code, cwd):
    """What the sandbox executes to define ``userCode`` from *code*, a node's
    code indented for ``def userCode(arg):``, run in the folder *cwd*.

    That is the source itself, or, when a literal in it reads a file Curio
    ships (see the module docstring), the source compiled with that literal
    pointed at the file. The compiled code keeps the source's line numbers
    and its ``<string>`` file name, and code that does not compile is handed
    back as it is, so it fails as it always has."""
    source = f"def userCode(arg):\n{code}"
    if DOCS + "/" not in code:
        return source
    try:
        tree = ast.parse(source, filename="<string>")
        resolver = _ShippedDocs(cwd)
        tree = resolver.visit(tree)
        if not resolver.changed:
            return source
        return compile(tree, "<string>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return source
