"""Child-side harness for the package backend sandbox (memo dev/91 §3).

This file is COPIED into the worker's read-only ``input/`` directory by
``backend_runtime`` and executed there as the worker's entry — it never runs
in the Curio host process, and the package's code never runs outside it.
It is deliberately self-contained: only the standard library plus the
``backend_contract`` module the runtime copies alongside it (one contract,
one spelling — the dev/90 A15 lesson).

What one worker run does, exactly once:

1. read the request envelope from ``input/payload.json``;
2. install the in-process network guard unless the package declared the
   ``server-network`` permission (ADVISORY by design — memo dev/91 §3: the
   hard guarantees are the process/rlimit/env boundary around this file);
3. load the package's ``backend/`` entry file in an isolated namespace
   (``runpy``-style — never a host import);
4. resolve the handler: a module-level ``HANDLERS`` dict (name → callable)
   when present, else the single ``handle`` callable serving every declared
   name;
5. a probe request (``{"__probe__": true}``) is answered ``ok`` right here —
   load + resolution IS the health check, the handler body never runs on a
   probe;
6. call the handler with the payload and write the reply envelope to
   ``output/reply.json``.

Handler failures become ``handler-error`` replies (exit 0 — the reply is the
diagnosis); only a harness-level catastrophe exits nonzero, which the runtime
reports as a contract error. Nothing here prints payloads or results to
stdout/stderr — those streams are capped diagnostics, not a data channel.
"""

from __future__ import annotations

import json
import os
import sys
import traceback


def _write_reply(output_dir: str, envelope: dict) -> None:
    path = os.path.join(output_dir, "reply.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(envelope, fh, ensure_ascii=False)


def _install_network_guard() -> None:
    import socket

    message = (
        "network access is disabled in the package backend sandbox — the "
        "package must declare the 'server-network' permission"
    )

    def _refused(*_args, **_kwargs):
        raise RuntimeError(message)

    socket.socket = _refused  # type: ignore[misc]
    socket.create_connection = _refused  # type: ignore[assignment]
    socket.socketpair = _refused  # type: ignore[assignment]


def main() -> int:
    input_dir = os.environ["CURIO_BUILD_INPUT_DIR"]
    output_dir = os.environ["CURIO_BUILD_OUTPUT_DIR"]
    sys.path.insert(0, input_dir)  # backend_contract.py rides input/
    import backend_contract as bc  # noqa: E402 — the copied contract module

    def fail(kind: str, error: str) -> int:
        _write_reply(output_dir, bc.error_reply(kind, error))
        return 0  # the reply is the diagnosis; nonzero = no reply written

    try:
        with open(os.path.join(input_dir, bc.REQUEST_FILENAME), "rb") as fh:
            envelope = json.load(fh)
    except (OSError, ValueError) as exc:
        return fail("contract-error", f"unreadable request envelope: {exc}")
    if (
        not isinstance(envelope, dict)
        or envelope.get("contract") != bc.PKGBACKEND_CONTRACT_VERSION
        or not isinstance(envelope.get("handler"), str)
        or "payload" not in envelope
    ):
        return fail("contract-error", "request envelope violates curio.pkgbackend.v1")
    handler_name = envelope["handler"]
    payload = envelope["payload"]

    if os.environ.get("CURIO_PKG_NET_ALLOWED") != "1":
        _install_network_guard()

    entry_rel = os.environ.get("CURIO_PKG_ENTRY", "")
    entry_path = os.path.normpath(os.path.join(input_dir, entry_rel))
    if not entry_rel or not entry_path.startswith(os.path.abspath(input_dir)) \
            or not os.path.isfile(entry_path):
        return fail("contract-error", f"backend entry {entry_rel!r} is not in the workspace")

    # The entry may import siblings shipped under the package's backend/ dir.
    sys.path.insert(0, os.path.dirname(entry_path))
    try:
        import runpy

        module_globals = runpy.run_path(entry_path, run_name="curio_pkg_backend")
    except BaseException as exc:  # noqa: BLE001 — loading generated code
        return fail("handler-error", f"backend entry failed to load: "
                                     f"{type(exc).__name__}: {exc}")

    fn = None
    handlers_map = module_globals.get("HANDLERS")
    if isinstance(handlers_map, dict):
        fn = handlers_map.get(handler_name)
    if fn is None:
        fn = module_globals.get("handle")
    if not callable(fn):
        return fail(
            "handler-error",
            f"the entry exposes no callable for {handler_name!r} — define "
            f"'def handle(payload)' or a HANDLERS dict naming it",
        )

    if bc.is_probe(payload):
        # Load + resolution succeeded: that IS the health check (dev/91 §3).
        _write_reply(output_dir, {
            "contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": True,
            "result": {"probe": "ok", "handler": handler_name},
        })
        return 0

    try:
        result = fn(payload)
    except BaseException as exc:  # noqa: BLE001 — generated handler code
        tail = traceback.format_exception_only(type(exc), exc)[-1].strip()
        return fail("handler-error", f"handler {handler_name!r} raised: {tail}")

    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        return fail("handler-error",
                    f"handler {handler_name!r} returned a non-JSON result: {exc}")
    _write_reply(output_dir, {
        "contract": bc.PKGBACKEND_CONTRACT_VERSION, "ok": True, "result": result,
    })
    return 0


if __name__ == "__main__":
    sys.exit(main())
