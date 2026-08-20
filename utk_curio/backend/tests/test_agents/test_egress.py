"""dev/67-4 (DEC-053) — the egress policy: default-deny SSRF shapes, capped
redirects and bodies, auditable. No test touches the network."""

from __future__ import annotations

import pytest

from utk_curio.backend.app.agents import egress


def _resolver(mapping):
    def _resolve(host):
        if host in mapping:
            return mapping[host]
        raise OSError(f"unknown host {host}")

    return _resolve


PUBLIC = _resolver({"api.example.org": ["93.184.216.34"]})


def _response(status=200, body=b'{"ok": true}', location=None, content_type="application/json"):
    headers = {"Content-Type": content_type}
    if location:
        headers["Location"] = location
    return status, headers, body, location


class TestCheckUrl:
    def test_schemes_are_allowlisted(self):
        for bad in ("ftp://x/", "file:///etc/passwd", "gopher://x/"):
            ok, reason = egress.check_url(bad, resolver=PUBLIC)
            assert not ok and "scheme" in reason

    def test_ssrf_shapes_are_refused_after_dns(self):
        cases = {
            "metadata.internal": ["169.254.169.254"],   # link-local (cloud metadata)
            "localhost": ["127.0.0.1"],                 # loopback
            "intranet.example": ["10.0.0.5"],           # private
            "rebind.example": ["93.184.216.34", "192.168.1.1"],  # DNS rebind: ANY bad addr refuses
        }
        for host, addrs in cases.items():
            ok, reason = egress.check_url(
                f"https://{host}/x", resolver=_resolver({host: addrs})
            )
            assert not ok, host
            assert "non-public address" in reason

    def test_public_hosts_pass(self):
        ok, reason = egress.check_url("https://api.example.org/data", resolver=PUBLIC)
        assert ok, reason


class TestFetch:
    def test_fetch_returns_bounded_result_with_audit(self):
        audit: list = []
        result = egress.fetch(
            "https://api.example.org/data.json",
            request_fn=lambda m, u: _response(),
            resolver=PUBLIC,
            audit=audit,
        )
        assert result.status == 200
        assert result.body == '{"ok": true}'
        assert audit == [{
            "url": "https://api.example.org/data.json",
            "finalUrl": "https://api.example.org/data.json",
            "status": 200, "bytes": 12,
        }]

    def test_redirect_to_a_private_address_is_refused_at_the_hop(self):
        resolver = _resolver({
            "api.example.org": ["93.184.216.34"],
            "internal.example": ["10.0.0.9"],
        })

        def _request(method, url):
            if "api.example.org" in url:
                return _response(status=302, location="https://internal.example/steal")
            return _response()

        with pytest.raises(egress.EgressRefused, match="non-public address"):
            egress.fetch("https://api.example.org/x", request_fn=_request, resolver=resolver)

    def test_redirect_cap(self):
        def _request(method, url):
            return _response(status=302, location=url + "/again")

        with pytest.raises(egress.EgressRefused, match="redirects"):
            egress.fetch("https://api.example.org/x", request_fn=_request, resolver=PUBLIC)

    def test_body_cap_truncates_with_a_marker(self):
        big = b"x" * (egress.MAX_BODY_BYTES + 100)
        result = egress.fetch(
            "https://api.example.org/big",
            request_fn=lambda m, u: _response(body=big, content_type="text/plain"),
            resolver=PUBLIC,
        )
        assert result.truncated is True
        assert "truncated" in result.body[-80:]
        assert len(result.body) <= egress.MAX_BODY_BYTES + 80


class TestTrustedHost:
    """dev/90 A2 — the operator-declared provider host is exempt from the
    address policy; everything else keeps the full default-deny gate."""

    # staticmethod: a bare function class attribute would bind ``self``.
    LOCAL = staticmethod(_resolver({"localhost": ["127.0.0.1"],
                                    "evil.internal": ["10.0.0.9"]}))

    def test_trusted_host_of_parses_operator_urls(self):
        assert egress.trusted_host_of(
            "http://localhost:8888/search?q={q}&format=json") == ("localhost", 8888)
        assert egress.trusted_host_of("https://searx.example/search?q={q}") == (
            "searx.example", None)
        assert egress.trusted_host_of("not a url") is None
        assert egress.trusted_host_of("") is None

    def test_loopback_refused_by_default_allowed_when_trusted(self):
        url = "http://localhost:8888/search?q=x&format=json"
        ok, reason = egress.check_url(url, resolver=self.LOCAL)
        assert not ok and "non-public address" in reason
        ok, reason = egress.check_url(
            url, resolver=self.LOCAL, trusted_host=("localhost", 8888))
        assert ok, reason
        # The exemption is EXACT (hostname AND port): another port stays refused.
        ok, _ = egress.check_url(
            url, resolver=self.LOCAL, trusted_host=("localhost", 9999))
        assert not ok

    def test_trusted_host_never_bypasses_the_scheme_allowlist(self):
        ok, reason = egress.check_url(
            "file:///etc/passwd", resolver=self.LOCAL,
            trusted_host=("localhost", None))
        assert not ok and "scheme" in reason

    def test_fetch_works_against_a_trusted_local_provider(self):
        result = egress.fetch(
            "http://localhost:8888/search?q=paris&format=json",
            request_fn=lambda m, u: _response(body=b'{"results": []}'),
            resolver=self.LOCAL,
            trusted_host=("localhost", 8888),
        )
        assert result.status == 200 and '"results"' in result.body

    def test_redirect_off_the_trusted_host_gets_the_full_policy(self):
        # A compromised/misbehaving provider cannot become an SSRF springboard:
        # the redirect hop is a DIFFERENT host and is refused as usual.
        def _request(method, url):
            if "localhost" in url:
                return _response(status=302, location="http://evil.internal/steal")
            return _response()

        with pytest.raises(egress.EgressRefused, match="non-public address"):
            egress.fetch(
                "http://localhost:8888/search?q=x",
                request_fn=_request,
                resolver=self.LOCAL,
                trusted_host=("localhost", 8888),
            )
