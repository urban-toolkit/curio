"""Deciding whether node execution runs isolated, and what to do if it cannot.

Isolation needs primitives that only exist on POSIX: ``os.fork`` to get a warm
child cheaply, ``resource.setrlimit`` to cap it, and ``os.killpg`` to reap it.
Windows has none of them, and Curio is developed on Windows, so the in-process
path has to remain a first-class supported configuration rather than a broken
leftover.

The rule that matters is asymmetric, and deliberately so:

- On a **local single-user launch**, a missing capability degrades to the
  in-process path with one loud warning. Breaking a developer's laptop to
  enforce a boundary that only matters for shared instances would be the wrong
  trade.
- On a **hosted launch** (``--auth`` / ``--deploy``), the same missing
  capability is fatal. A production instance that silently ran unisolated
  would be the exact failure this work exists to prevent, and it would be
  invisible: everything would appear to work.

``resolve_mode`` is pure and takes its inputs as arguments, so the whole
decision table is testable on any platform, including the Windows fallback
that CI can never reach.
"""

import os
import sys

OFF = "off"
FORK = "fork"
AUTO = "auto"

VALID_MODES = (AUTO, FORK, OFF)

MODE_ENV = "CURIO_ISOLATION"

_warned = False


class IsolationUnavailable(RuntimeError):
    """Isolation was required but the platform cannot provide it.

    Raised at startup on a hosted instance. Never raised for a local launch,
    which falls back instead.
    """


def capabilities(platform=None, module_probe=None):
    """Report which isolation primitives this interpreter actually has.

    *platform* and *module_probe* are injectable so the full decision table can
    be exercised from any host. ``module_probe(name)`` should return True when
    the named module is importable.
    """
    platform = platform if platform is not None else sys.platform
    if module_probe is None:
        def module_probe(name):
            try:
                __import__(name)
                return True
            except Exception:
                return False

    has_fork = hasattr(os, "fork")
    has_rlimit = module_probe("resource")
    has_seccomp = module_probe("pyseccomp")

    return {
        "platform": platform,
        "fork": bool(has_fork),
        "rlimit": bool(has_rlimit),
        # Linux-only. Absent on macOS, which is why macOS cannot host even
        # though it is POSIX and has fork.
        "seccomp": bool(has_seccomp) and platform.startswith("linux"),
        "linux": platform.startswith("linux"),
    }


def missing_requirements(caps, *, hosted):
    """Return the capabilities needed but absent, most fundamental first.

    Hosting additionally requires Linux and seccomp, because without a syscall
    filter the child keeps unrestricted network access, and an isolated child
    that can still open sockets is not isolated in the sense a hosted instance
    needs.
    """
    missing = []
    if not caps["fork"]:
        missing.append("os.fork")
    if not caps["rlimit"]:
        missing.append("the resource module (setrlimit)")
    if hosted:
        if not caps["linux"]:
            missing.append("Linux (seccomp has no equivalent elsewhere)")
        elif not caps["seccomp"]:
            missing.append("pyseccomp (pip install pyseccomp)")
    return missing


def resolve_mode(requested=None, *, hosted=False, caps=None):
    """Decide the effective isolation mode.

    Returns ``(mode, reason)`` where *mode* is :data:`FORK` or :data:`OFF` and
    *reason* is a human-readable sentence for the log, or None when there is
    nothing worth saying.

    Raises :class:`IsolationUnavailable` when a hosted instance asked for
    isolation it cannot have, or when *requested* is not a valid mode.
    """
    requested = (requested or AUTO).strip().lower()
    if requested not in VALID_MODES:
        raise IsolationUnavailable(
            f"{MODE_ENV}={requested!r} is not valid; expected one of "
            f"{', '.join(VALID_MODES)}"
        )

    caps = caps if caps is not None else capabilities()

    if requested == OFF:
        if hosted:
            # Explicit, so honour it, but this is worth shouting about: the
            # operator has turned off the only thing standing between a node
            # author and the host.
            return OFF, (
                "Isolation is explicitly disabled on an instance with user auth "
                "enabled. Node code runs in-process with full privileges; treat "
                "node-authoring rights as shell access."
            )
        return OFF, None

    missing = missing_requirements(caps, hosted=hosted)

    if requested == FORK:
        if missing:
            if hosted:
                raise IsolationUnavailable(
                    "Isolation was requested (--isolation=fork) on an instance "
                    "with user auth enabled, but this platform is missing: "
                    + ", ".join(missing)
                    + ". Refusing to start unisolated. Run the Docker image, or "
                    "pass --isolation=off to accept the risk explicitly."
                )
            return OFF, (
                "Isolation was requested but is unavailable here ("
                + ", ".join(missing)
                + "). Falling back to in-process execution, which is the normal "
                "local-development path."
            )
        return FORK, None

    # AUTO resolves to OFF, deliberately, and will keep doing so until the
    # fork path has actually run somewhere.
    #
    # The tempting behaviour is "isolate wherever it is possible", which would
    # switch every hosted Linux instance over the moment this ships. That is
    # the wrong default for code whose confinement step (child.confine) has
    # never executed: a silent switch would move every hosted deployment onto
    # an untested execution path, and CI (Linux, --auth) would be the first
    # thing to discover it.
    #
    # Isolation is therefore opt-in via --isolation=fork. When the fork path is
    # verified, this branch becomes `return FORK` for hosted instances and the
    # decision table in test_isolation_fallback.py changes with it.
    if hosted and not missing:
        return OFF, (
            "Node execution is NOT isolated: it runs in-process with the "
            "sandbox's full privileges. This platform supports isolation, so "
            "consider --isolation=fork. Until then, treat node-authoring "
            "rights on this instance as equivalent to shell access."
        )
    return OFF, None


def mode_from_environment(env=None):
    """Read the requested mode and hosted flag out of the process environment."""
    env = env if env is not None else os.environ
    requested = env.get(MODE_ENV, AUTO)
    hosted = env.get("CURIO_NO_AUTH", "1").strip().lower() in ("0", "false", "no", "off")
    return requested, hosted


def resolve_from_environment(env=None, *, caps=None):
    """Convenience wrapper: resolve the mode using the process environment."""
    requested, hosted = mode_from_environment(env)
    return resolve_mode(requested, hosted=hosted, caps=caps)


def warn_once(reason):
    """Emit *reason* to stderr the first time only.

    Every node execution consults the mode, so an unconditional warning would
    bury the log. The operator needs to see this once.
    """
    global _warned
    if _warned or not reason:
        return
    _warned = True
    print(f"[sandbox isolation] {reason}", file=sys.stderr, flush=True)


def reset_warning_state():
    """Test hook: forget that the warning was already emitted."""
    global _warned
    _warned = False
