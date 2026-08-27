"""The E2E harness must never orphan the stack it spawned.

An orphaned ``curio.py start`` tree keeps ports 5002/2000/8080 and the test
sqlite file, and the damage lands on the *next* run rather than this one: it
dies at conftest import with ``PermissionError: [WinError 32]`` before
collecting a single test, or it sails through ``wait_for_port`` because a stale
process is answering on the port being waited for and then fails somewhere far
away with ``ERR_CONNECTION_REFUSED``.

``curio_servers`` used to register its cleanup finalizer *after* the readiness
gates, which allow up to ~6.5 minutes between the spawn and the registration. A
gate that timed out therefore raised out of the fixture with nothing registered
to kill what had already started - and a slow cold start is exactly when a gate
trips, so the failure clustered on the machines least able to absorb it.

These are structural checks, deliberately. The behavioural version has to boot a
real stack, force a gate to fail, and then enumerate OS processes to look for
orphans - about 35 seconds and a platform-specific process query for an
invariant that is a two-line ordering property of the source. The bug was an
ordering mistake; this is the shape that catches an ordering mistake.

The ordering was verified behaviourally once, by hand, with a plugin that forced
``wait_for_http_ready`` to raise: the old order left
``curio.py start --backend-port 5002 ... --save-node-outputs`` plus its webpack
child alive with all three ports held; the new order left nothing.

No fixtures are requested here on purpose - this file must not boot the very
stack it is making claims about.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

FIXTURES_PATH = Path(__file__).with_name("fixtures.py")

#: Calls that can block for minutes and can raise. Anything spawned before one
#: of these must already have a finalizer registered.
_GATE_CALLS = {"wait_for_port", "wait_for_http_ready"}


def _fixture_body() -> ast.FunctionDef:
    tree = ast.parse(FIXTURES_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "curio_servers":
            return node
    pytest.fail("curio_servers is gone from fixtures.py; this file needs updating")


def _called_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _line_of_first(body: ast.FunctionDef, predicate) -> int | None:
    return next(
        (
            node.lineno
            for node in ast.walk(body)
            if isinstance(node, ast.Call) and predicate(_called_name(node))
        ),
        None,
    )


class TestNoOrphanedStack:
    def test_the_finalizer_is_registered_before_any_readiness_gate(self):
        """The invariant, stated once.

        Registration has to happen between the spawn and the first thing that
        can raise. Everything else in this file is a corollary.
        """
        body = _fixture_body()
        finalizer = _line_of_first(body, lambda n: n == "addfinalizer")
        gate = _line_of_first(body, lambda n: n in _GATE_CALLS)

        assert finalizer is not None, (
            "curio_servers no longer registers a cleanup finalizer at all"
        )
        assert gate is not None, (
            "no readiness gate found; if the gates moved out of curio_servers, "
            "check that the spawned stack is still cleaned up on their failure"
        )
        assert finalizer < gate, (
            f"request.addfinalizer is on line {finalizer} but a readiness gate "
            f"runs first on line {gate}. A gate that times out will raise out of "
            f"the fixture with nothing registered to kill the stack it already "
            f"spawned, and the orphans break the NEXT run at conftest import."
        )

    def test_the_finalizer_is_registered_immediately_after_the_spawn(self):
        """And after the spawn, or it would have nothing to clean up."""
        body = _fixture_body()
        spawn = _line_of_first(body, lambda n: n == "Popen")
        finalizer = _line_of_first(body, lambda n: n == "addfinalizer")
        assert spawn is not None, "curio_servers no longer spawns the stack"
        assert spawn < finalizer, (
            f"addfinalizer (line {finalizer}) runs before Popen (line {spawn}), "
            f"so it cannot be closing over the process it is meant to kill"
        )

    def test_terminate_walks_the_tree_even_when_the_root_has_exited(self):
        """A dead supervisor is the case that most needs sweeping.

        ``curio.py start`` only supervises; the backend, sandbox and webpack are
        separate processes. If the supervisor dies without running its own
        cleanup - killed, crashed, or terminated by an outer harness - those
        children are precisely what is left over. An early
        ``if process.poll() is not None: return`` would skip them, which reads
        like a safety check and is the opposite.
        """
        from .fixtures import _terminate_process_tree

        source = inspect.getsource(_terminate_process_tree)
        tree = ast.parse(source.lstrip())
        func = tree.body[0]
        assert isinstance(func, ast.FunctionDef)

        # Any bare `return` guarded by a poll() test, before the kill happens.
        for node in func.body:
            if not isinstance(node, ast.If):
                continue
            calls = {
                _called_name(c)
                for c in ast.walk(node.test)
                if isinstance(c, ast.Call)
            }
            returns_early = any(
                isinstance(inner, ast.Return) for inner in ast.walk(node)
            )
            assert not ("poll" in calls and returns_early), (
                "_terminate_process_tree returns early when the root process "
                "has already exited, which skips exactly the orphaned children "
                "it exists to remove. taskkill on a dead pid answers 128 and "
                "the POSIX branch already handles ProcessLookupError, so the "
                "guard buys nothing."
            )
