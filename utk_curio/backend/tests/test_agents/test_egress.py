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
