"""The network guard fires, and lets the right things through.

A guard nobody has watched fail is indistinguishable from no guard, so these
assert the refusal itself rather than the absence of traffic.
"""

import socket

import pytest

from utk_curio.backend.tests import netguard


class TestItRefuses:
    def test_a_dns_lookup_for_a_public_name(self):
        with pytest.raises(netguard.NetworkAccessDenied) as exc:
            socket.getaddrinfo("example.org", 443)
        assert "example.org" in str(exc.value)

    def test_a_connection_to_a_public_address(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(netguard.NetworkAccessDenied):
                sock.connect(("93.184.216.34", 80))
        finally:
            sock.close()

    def test_create_connection(self):
        with pytest.raises(netguard.NetworkAccessDenied):
            socket.create_connection(("example.org", 80), timeout=1)

    def test_the_message_names_the_way_out(self):
        with pytest.raises(netguard.NetworkAccessDenied) as exc:
            socket.getaddrinfo("example.org", 443)
        message = str(exc.value)
        assert "contract" in message and "externalapi" in message

    def test_it_is_not_an_Exception(self):
        """The property the broad handlers in agents/ depend on not having.

        ``verify.verify_endpoint`` wraps its fetch in ``except Exception`` and
        would turn an ordinary exception into a tidy "unreachable" outcome, so
        the leak would pass as a normal test result.
        """
        assert issubclass(netguard.NetworkAccessDenied, BaseException)
        assert not issubclass(netguard.NetworkAccessDenied, Exception)

    def test_a_broad_except_does_not_swallow_it(self):
        with pytest.raises(netguard.NetworkAccessDenied):
            try:
                socket.getaddrinfo("example.org", 443)
            except Exception:  # noqa: BLE001 - the point of the test
                pytest.fail("an `except Exception` swallowed the guard")


class TestItAllows:
    @pytest.mark.parametrize(
        "host", ["127.0.0.1", "localhost", "::1", "0.0.0.0", "127.0.0.53"]
    )
    def test_loopback_resolves(self, host):
        """The suite's own stack: sandbox, health polls, the Playwright servers."""
        socket.getaddrinfo(host, 80, proto=socket.IPPROTO_TCP)

    def test_a_unix_socket_path_is_not_a_network_destination(self):
        assert netguard._host_of("/tmp/some.sock") is None
        assert netguard._is_local(None)

    def test_an_ipv4_mapped_loopback_is_loopback(self):
        assert netguard._is_local("::ffff:127.0.0.1")

    def test_an_ipv4_mapped_public_address_is_not(self):
        assert not netguard._is_local("::ffff:93.184.216.34")

    def test_the_env_escape_hatch(self, monkeypatch):
        assert not netguard._is_local("registry.internal")
        monkeypatch.setenv("CURIO_TEST_NET_ALLOW", "registry.internal, other.host")
        assert netguard._is_local("registry.internal")
        assert netguard._is_local("other.host")


@pytest.mark.contract
def test_the_contract_marker_lifts_the_guard():
    """Not a real contract test - it asserts the opt-out works at all.

    ``_is_local`` still says no; what changed is that the guard is not armed
    for this node. Nothing is actually sent.
    """
    assert not netguard._is_local("example.org")
    assert netguard._allowed is True


@pytest.mark.externalapi
def test_the_externalapi_marker_lifts_the_guard():
    """Deselected unless --longrun, so it is also proof the exclusion works."""
    assert netguard._allowed is True
