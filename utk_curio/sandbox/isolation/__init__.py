"""Process isolation for node execution.

Curio executes user-authored node code. Today ``worker.py::execute_code`` runs
it with ``exec()`` inside the sandbox process, with unrestricted builtins and
no resource limits, which makes node-authoring rights equivalent to shell
access on the host.

This package moves that execution into a short-lived, unprivileged child
process. The pieces:

``mode``
    Resolves whether isolation is active for this launch, and what to do when
    it cannot be. POSIX only; Windows and macOS keep the in-process path.
``protocol``
    The JSON manifest crossing the boundary in both directions, and the
    validation the parent applies to anything a child sends back.

The parent keeps every privilege the child must not have: it owns the DuckDB
connection, resolves artifacts, and enforces session scoping. The child sees
only a scratch directory of staged files.
"""
