"""Block outbound network access from the test process.

Nothing stopped a test from opening a real socket before this. Every
"CI never touches the network" claim in the suite rested on per-call-site
discipline, and the discipline had gaps that were one forgetful commit from
real traffic:

- ``agents/egress.py`` has **two** seams that default independently.
  ``fetch(request_fn=...)`` replaces the transport; ``check_url(resolver=...)``
  replaces DNS. Injecting one still leaves the other doing the real thing, and
  a resolver-only leak is invisible because nothing downstream fails.
- ``agents/tools.py::_execute_web_search`` falls back to
  ``https://api.duckduckgo.com/`` when ``CURIO_SEARCH_URL`` is unset, so any
  test that scripts a ``web.search`` tool request dials out.
- ``packages/build_deps.py::resolve_dependencies`` constructs a real
  ``HttpRegistryFetcher`` when ``CURIO_JS_REGISTRY_URL`` happens to be exported
  in the ambient environment.

A test that reaches the network is not merely impure: it is slow, it fails when
a third party is down, and it fails differently on a developer's machine than
in CI. That is the definition of a flaky test. This makes the failure
deterministic and immediate instead, and names the host it caught.

**Why NetworkAccessDenied derives from BaseException, not Exception.**
Deliberate, and the whole point of the module. The code most likely to leak is
also the code that catches broadly: ``verify.verify_endpoint`` wraps its fetch
in ``except Exception`` and converts anything it catches into an
``"unreachable"`` outcome, and ``egress.check_url`` catches ``OSError`` from
the resolver and converts it into a polite ``(False, "the host does not
resolve")``. A guard raising an ordinary ``Exception`` would be swallowed by
exactly those handlers, the test would pass, and the socket attempt would be
invisible - the one outcome this module exists to prevent. Deriving from
``BaseException`` puts it in the same class as ``KeyboardInterrupt``: ``finally``
blocks and context managers still run, pytest still reports it, but no
``except Exception`` absorbs it.

**Loopback stays allowed**, because the suite genuinely needs it: the sandbox,
the backend health polls, and the Playwright stack all talk to 127.0.0.1.

**What this does NOT cover**, stated plainly rather than implied:

- **The e2e backend subprocess.** ``test_frontend`` starts the backend with
  ``subprocess``, so this guard - which lives in the pytest process - has no
  reach into it. Covering that needs a seam inside the backend itself; the Data
  Lake Catalog uses ``CURIO_DATALAKE_FIXTURES`` for exactly this reason.
- **The browser.** Playwright's Chromium is its own process and still reaches
  whatever a page asks for.

Opting out, by marker:

- ``@pytest.mark.externalapi`` - may reach the network; **deselected by
  default**, needs ``--longrun``. The marker predates this module (it was wired
  into ``pytest_configure`` and applied to nothing); this gives it teeth.
- ``@pytest.mark.contract`` - reaches a real third party on purpose and **runs
  in CI**, because it is written so that unreachability is a skip and only a
  changed response shape is a failure.
"""

from __future__ import annotations

import ipaddress
import os
import socket

#: Names that mean "this machine". Not resolved - resolving them is the thing
#: being guarded - so they are matched textually before any lookup happens.
_LOCAL_NAMES = frozenset(
    {"", "localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

_MARKERS = ("externalapi", "contract")

# Flipped per test by the autouse fixture. Module-level rather than passed
# around because the patch sites are socket's own functions, which any thread
# in the process may call - the backend serves threaded under test.
_allowed = False
_installed = False
_originals: dict = {}


class NetworkAccessDenied(BaseException):
    """A test tried to reach the network. See this module's docstring."""


def _extra_allowed_hosts() -> frozenset[str]:
    """Hosts the operator declared local, beyond loopback.

    ``CURIO_E2E_HOST`` is read because the e2e harness parameterises the stack's
    hostname (``shards.py`` defaults it to ``localhost``, but a container run
    may set it to something else, and that target is still this machine).
    ``CURIO_TEST_NET_ALLOW`` is the escape hatch, so a deployment quirk never
    needs a code change here.
    """
    hosts = {h.strip().lower() for h in os.environ.get("CURIO_TEST_NET_ALLOW", "").split(",")}
    e2e_host = (os.environ.get("CURIO_E2E_HOST") or "").strip().lower()
    if e2e_host:
        hosts.add(e2e_host)
    hosts.discard("")
    return frozenset(hosts)


def _host_of(address) -> str | None:
    """The hostname/IP out of a connect() address, or None when there is none.

    AF_UNIX passes a path (str/bytes) and AF_INET/AF_INET6 pass a tuple whose
    first element is the host. Anything else is not an address this guard
    understands, and it says so by returning None rather than guessing.
    """
    if isinstance(address, (str, bytes)):
        return None  # AF_UNIX socket path - never a network destination
    if isinstance(address, (tuple, list)) and address:
        return address[0]
    return None


def _is_local(host) -> bool:
    if host is None:
        return True
    text = str(host).strip().strip("[]").lower()
    if text in _LOCAL_NAMES or text in _extra_allowed_hosts():
        return True
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        # A name we do not recognise. Resolving it to decide would BE the
        # network access in question, so an unknown name is refused.
        return False
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return ip.is_loopback or ip.is_unspecified


def _deny(host, what: str) -> "NetworkAccessDenied":
    return NetworkAccessDenied(
        f"{what} to {host!r} was blocked: tests must not reach the network. "
        f"Inject a fake transport (see utk_curio/backend/tests/netguard.py), or "
        f"mark the test @pytest.mark.contract (runs in CI, skips when "
        f"unreachable) or @pytest.mark.externalapi (needs --longrun)."
    )


def _check(host, what: str) -> None:
    if _allowed or _is_local(host):
        return
    raise _deny(host, what)


def install() -> None:
    """Patch socket once per process. Idempotent."""
    global _installed
    if _installed:
        return

    _originals["connect"] = socket.socket.connect
    _originals["connect_ex"] = socket.socket.connect_ex
    _originals["create_connection"] = socket.create_connection
    _originals["getaddrinfo"] = socket.getaddrinfo

    def connect(self, address, *args, **kwargs):
        _check(_host_of(address), "a socket connection")
        return _originals["connect"](self, address, *args, **kwargs)

    def connect_ex(self, address, *args, **kwargs):
        _check(_host_of(address), "a socket connection")
        return _originals["connect_ex"](self, address, *args, **kwargs)

    def create_connection(address, *args, **kwargs):
        _check(_host_of(address), "a socket connection")
        return _originals["create_connection"](address, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        # Guarded as well as connect(), because a DNS lookup is itself network
        # traffic and is the exact shape of the egress.check_url resolver leak
        # this module's docstring describes: it never reaches connect().
        _check(host, "a DNS lookup")
        return _originals["getaddrinfo"](host, *args, **kwargs)

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create_connection
    socket.getaddrinfo = getaddrinfo
    _installed = True


def set_allowed(value: bool) -> None:
    global _allowed
    _allowed = value


def allowed_by(node) -> bool:
    """True when *node* carries a marker that opts out of the guard."""
    return any(node.get_closest_marker(name) is not None for name in _MARKERS)
