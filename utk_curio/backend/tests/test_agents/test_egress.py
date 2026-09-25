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


# ---------------------------------------------------------------------------
# The gaps the merge review found
# ---------------------------------------------------------------------------


class TestAddressPolicyIsAnAllowlist:
    """``is_global`` rather than a denylist of the ranges we remembered."""

    def test_carrier_grade_nat_space_is_refused(self):
        # RFC 6598 100.64.0.0/10 is not private, loopback, link-local,
        # reserved, multicast or unspecified, so the old six-predicate
        # denylist let it through. It is routable internal space on any
        # CGNAT or cloud-NAT deployment.
        ok, reason = egress.check_url(
            "https://cgnat.example", resolver=lambda h: ["100.64.1.1"]
        )
        assert not ok
        assert "non-public" in reason

    @pytest.mark.parametrize(
        "address",
        [
            "127.0.0.1",
            "10.0.0.1",
            "192.168.1.1",
            "169.254.169.254",   # cloud metadata
            "::1",
            "fc00::1",
            "::ffff:169.254.169.254",  # IPv4-mapped metadata address
            "::ffff:127.0.0.1",
        ],
    )
    def test_the_classic_internal_addresses_stay_refused(self, address):
        ok, _reason = egress.check_url(
            "https://host.example", resolver=lambda h: [address]
        )
        assert not ok

    def test_a_public_address_is_still_allowed(self):
        ok, reason = egress.check_url(
            "https://ok.example", resolver=lambda h: ["93.184.216.34"]
        )
        assert ok, reason


class TestCallBudgetCountsRequests:
    def test_redirect_hops_are_charged(self):
        """A redirect chain costs what it actually costs.

        The budget used to be counted one tick per candidate row, so a chain
        of hops was free and a row could issue many more requests than the
        documented bound.
        """
        budget = egress.CallBudget(limit=3)
        hops = {"n": 0}

        def _request(method, url, **kwargs):
            hops["n"] += 1
            return 302, {}, b"", "https://next.example/again"

        with pytest.raises(egress.EgressRefused, match="budget"):
            egress.fetch(
                "https://start.example",
                request_fn=_request,
                resolver=lambda h: ["93.184.216.34"],
                budget=budget,
            )
        assert budget.used == 3
        assert hops["n"] == 3

    def test_an_unbudgeted_fetch_is_unchanged(self):
        called = {"n": 0}

        def _request(method, url, **kwargs):
            called["n"] += 1
            return 200, {"Content-Type": "application/json"}, b"{}", None

        result = egress.fetch(
            "https://ok.example",
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
        )
        assert result.status == 200
        assert called["n"] == 1


class TestKeyedRequests:
    """dev/116: a probe may carry a connection key as a query parameter or a
    header — the parameters join the URL BEFORE the policy check, the header
    reaches only a request_fn that accepts one."""

    def test_params_join_the_url_before_the_policy_check(self):
        seen = []

        def _fn(method, url, trusted_host=None):
            seen.append(url)
            return _response()

        result = egress.fetch("https://api.example.org/data?get=NAME", request_fn=_fn, resolver=PUBLIC,
                              params={"key": "s3cr3t-value-0123"})
        assert seen == ["https://api.example.org/data?get=NAME&key=s3cr3t-value-0123"]
        assert result.url == seen[0] and result.final_url == seen[0]
        assert egress.with_params("https://x.org/a", {"k": "v w"}) == "https://x.org/a?k=v+w"
        assert egress.with_params("https://x.org/a", None) == "https://x.org/a"

    def test_headers_reach_a_request_fn_that_accepts_them(self):
        seen = {}

        def _with(method, url, headers=None):
            seen["headers"] = headers
            return _response()

        def _without(method, url):
            return _response()

        egress.fetch("https://api.example.org/x", request_fn=_with, resolver=PUBLIC,
                     headers={"X-Api-Key": "s3cr3t-value-0123"})
        assert seen["headers"] == {"X-Api-Key": "s3cr3t-value-0123"}
        # A request_fn without the keyword is still called (the header is dropped, not an error).
        egress.fetch("https://api.example.org/x", request_fn=_without, resolver=PUBLIC,
                     headers={"X-Api-Key": "s3cr3t-value-0123"})


# ── The policy moved to common/egress_policy.py; the transport stayed here ──


class TestTheSplitIsInvisibleToCallers:
    """``agents/egress`` re-exports the policy, so callers see the SAME objects.

    Identity, not equality: ``except egress.EgressRefused`` in tools.py and
    verify.py must catch what ``egress_policy`` raises. A second class with the
    same name would be caught by neither.
    """

    def test_the_names_are_the_same_objects(self):
        from utk_curio.backend.app.common import egress_policy

        for name in (
            "EgressRefused",
            "EgressTooLarge",
            "CallBudget",
            "check_url",
            "trusted_host_of",
            "ALLOWED_SCHEMES",
            "MAX_REDIRECTS",
            "MAX_CALLS_PER_RUN",
        ):
            assert getattr(egress, name) is getattr(egress_policy, name), name

    def test_too_large_is_a_refusal(self):
        """So every existing ``except EgressRefused`` still catches it."""
        assert issubclass(egress.EgressTooLarge, egress.EgressRefused)


class TestFetchBodyBound:
    def test_the_default_is_still_256_KiB(self):
        """Pinned. It bounds what becomes prompt text; raising it by accident
        is how a tool result blows the model's context."""
        assert egress.MAX_BODY_BYTES == 256 * 1024

    def test_the_default_truncates_at_that_bound(self):
        body = b"x" * (egress.MAX_BODY_BYTES + 100)
        result = egress.fetch(
            "https://big.example",
            request_fn=lambda m, u: (200, {"Content-Type": "text/plain"}, body, None),
            resolver=lambda h: ["93.184.216.34"],
        )
        assert result.truncated
        assert result.body.startswith("x" * 100)
        assert "truncated" in result.body

    def test_a_caller_may_raise_it(self):
        """A portal's package_search page routinely exceeds 256 KiB, and it is
        not going into a prompt."""
        body = b"y" * (egress.MAX_BODY_BYTES + 100)
        result = egress.fetch(
            "https://big.example",
            request_fn=lambda m, u: (200, {"Content-Type": "application/json"}, body, None),
            resolver=lambda h: ["93.184.216.34"],
            max_bytes=egress.MAX_BODY_BYTES * 4,
        )
        assert not result.truncated
        assert len(result.body) == len(body)

    def test_a_caller_may_lower_it(self):
        result = egress.fetch(
            "https://small.example",
            request_fn=lambda m, u: (200, {"Content-Type": "text/plain"}, b"abcdef", None),
            resolver=lambda h: ["93.184.216.34"],
            max_bytes=3,
        )
        assert result.truncated
        assert result.body.startswith("abc")


class _NoBody:
    """An empty, closeable chunk stream - for hops that only redirect."""

    def __iter__(self):
        return iter(())

    def close(self):
        pass


def _stream(chunks, *, status=200, headers=None, location=None):
    """A ``download`` transport double. Records whether it was closed."""
    state = {"closed": False}

    class _Chunks:
        def __iter__(self):
            return iter(chunks)

        def close(self):
            state["closed"] = True

    def _request(method, url, **kwargs):
        return status, dict(headers or {}), location, _Chunks()

    return _request, state


class TestDownload:
    def test_it_streams_to_the_sink_and_hashes_what_it_wrote(self):
        import hashlib

        payload = [b"hello ", b"world"]
        request_fn, _ = _stream(payload, headers={"Content-Type": "text/csv"})
        written = []
        result = egress.download(
            "https://portal.example/data.csv",
            sink=written.append,
            max_bytes=1024,
            request_fn=request_fn,
            resolver=lambda h: ["93.184.216.34"],
        )
        assert b"".join(written) == b"hello world"
        assert result.bytes_written == 11
        assert result.sha256 == hashlib.sha256(b"hello world").hexdigest()
        assert result.content_type == "text/csv"

    def test_it_closes_the_stream(self):
        request_fn, state = _stream([b"x"])
        egress.download(
            "https://portal.example/d",
            sink=lambda c: None,
            max_bytes=1024,
            request_fn=request_fn,
            resolver=lambda h: ["93.184.216.34"],
        )
        assert state["closed"]

    def test_a_declared_length_over_the_bound_is_refused_before_any_body(self):
        request_fn, state = _stream(
            [b"z" * 100], headers={"Content-Length": "999999"}
        )
        written = []
        with pytest.raises(egress.EgressTooLarge, match="declares"):
            egress.download(
                "https://portal.example/huge",
                sink=written.append,
                max_bytes=1024,
                request_fn=request_fn,
                resolver=lambda h: ["93.184.216.34"],
            )
        assert written == []      # not one byte read
        assert state["closed"]

    def test_a_lying_content_length_is_still_caught_while_streaming(self):
        """The bound is enforced against bytes actually written, so an absent
        or dishonest Content-Length cannot get past it."""
        request_fn, _ = _stream([b"a" * 60, b"b" * 60], headers={"Content-Length": "10"})
        written = []
        with pytest.raises(egress.EgressTooLarge, match="while streaming"):
            egress.download(
                "https://portal.example/liar",
                sink=written.append,
                max_bytes=100,
                request_fn=request_fn,
                resolver=lambda h: ["93.184.216.34"],
            )
        # Checked before writing: the sink never saw the chunk that crossed it.
        assert b"".join(written) == b"a" * 60

    def test_it_shares_the_ssrf_policy(self):
        request_fn, _ = _stream([b"x"])
        with pytest.raises(egress.EgressRefused, match="non-public"):
            egress.download(
                "https://metadata.internal/latest",
                sink=lambda c: None,
                max_bytes=1024,
                request_fn=request_fn,
                resolver=_resolver({"metadata.internal": ["169.254.169.254"]}),
            )

    def test_it_shares_the_scheme_allowlist(self):
        with pytest.raises(egress.EgressRefused, match="scheme"):
            egress.download(
                "file:///etc/passwd",
                sink=lambda c: None,
                max_bytes=1024,
                request_fn=_stream([b"x"])[0],
                resolver=PUBLIC,
            )

    def test_every_redirect_hop_is_re_checked(self):
        """The hop off the public host lands on link-local and is refused."""
        seen = []

        def _request(method, url, **kwargs):
            seen.append(url)
            if "start" in url:
                return 302, {"Location": "https://metadata.internal/x"}, "https://metadata.internal/x", _NoBody()
            return 200, {}, None, _NoBody()

        with pytest.raises(egress.EgressRefused, match="non-public"):
            egress.download(
                "https://start.example/f",
                sink=lambda c: None,
                max_bytes=1024,
                request_fn=_request,
                resolver=_resolver(
                    {
                        "start.example": ["93.184.216.34"],
                        "metadata.internal": ["169.254.169.254"],
                    }
                ),
            )
        assert seen == ["https://start.example/f"]

    def test_the_redirect_cap_is_shared(self):
        def _request(method, url, **kwargs):
            return 302, {"Location": "https://a.example/next"}, "https://a.example/next", _NoBody()

        with pytest.raises(egress.EgressRefused, match="redirects"):
            egress.download(
                "https://a.example/start",
                sink=lambda c: None,
                max_bytes=1024,
                request_fn=_request,
                resolver=lambda h: ["93.184.216.34"],
            )

    def test_the_budget_is_charged_per_hop(self):
        def _request(method, url, **kwargs):
            if url.endswith("start"):
                return 302, {"Location": "https://a.example/end"}, "https://a.example/end", _NoBody()
            return 200, {}, None, _NoBody()

        budget = egress.CallBudget(limit=4)
        egress.download(
            "https://a.example/start",
            sink=lambda c: None,
            max_bytes=1024,
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
            budget=budget,
        )
        assert budget.used == 2      # the redirect cost what it cost

    def test_progress_reports_bytes_and_the_declared_total(self):
        request_fn, _ = _stream(
            [b"a" * 10, b"b" * 10], headers={"Content-Length": "20"}
        )
        seen = []
        egress.download(
            "https://portal.example/d",
            sink=lambda c: None,
            max_bytes=1024,
            request_fn=request_fn,
            resolver=lambda h: ["93.184.216.34"],
            progress=lambda written, total: seen.append((written, total)),
        )
        assert seen == [(10, 20), (20, 20)]

    def test_audit_records_what_was_written(self):
        request_fn, _ = _stream([b"x" * 7])
        audit = []
        egress.download(
            "https://portal.example/d",
            sink=lambda c: None,
            max_bytes=1024,
            request_fn=request_fn,
            resolver=lambda h: ["93.184.216.34"],
            audit=audit,
        )
        assert audit == [
            {
                "url": "https://portal.example/d",
                "finalUrl": "https://portal.example/d",
                "status": 200,
                "bytes": 7,
            }
        ]


class TestTheBodyBoundReachesTheTransport:
    """``max_bytes`` has to stop the READ, not just truncate what arrived.

    Reading a fixed 256 KiB while the caller asked for more made the parameter
    a lie: the body came back pre-cut, and ``truncated`` then compared that
    short body against the larger bound and reported False. A caller got a
    silently truncated document with no indication - which is how a 425 KB WFS
    capabilities response became an XML parse error a long way from here.
    """

    def test_the_default_request_fn_honours_the_callers_bound(self):
        seen = {}

        def _request(method, url, *, trusted_host=None, max_bytes=None):
            seen["max_bytes"] = max_bytes
            return 200, {"Content-Type": "text/plain"}, b"x" * 10, None

        egress.fetch(
            "https://big.example",
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
            max_bytes=2 * 1024 * 1024,
        )
        assert seen["max_bytes"] == 2 * 1024 * 1024

    def test_the_default_is_passed_when_the_caller_says_nothing(self):
        seen = {}

        def _request(method, url, *, trusted_host=None, max_bytes=None):
            seen["max_bytes"] = max_bytes
            return 200, {}, b"ok", None

        egress.fetch(
            "https://ok.example",
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
        )
        assert seen["max_bytes"] == egress.MAX_BODY_BYTES

    def test_a_two_argument_double_is_still_called_with_two_arguments(self):
        """Every existing test double takes ``(method, url)``. Widening the
        call unconditionally would break all of them."""
        calls = []

        def _request(method, url):
            calls.append((method, url))
            return 200, {}, b"ok", None

        egress.fetch(
            "https://ok.example",
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
            max_bytes=999,
        )
        assert calls == [("GET", "https://ok.example")]

    def test_a_kwargs_double_receives_both_extras(self):
        seen = {}

        def _request(method, url, **kwargs):
            seen.update(kwargs)
            return 200, {}, b"ok", None

        egress.fetch(
            "https://ok.example",
            request_fn=_request,
            resolver=lambda h: ["93.184.216.34"],
            max_bytes=4096,
        )
        assert seen == {"trusted_host": None, "max_bytes": 4096}
