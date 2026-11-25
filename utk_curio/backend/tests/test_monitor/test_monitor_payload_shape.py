"""Every documented key is present, correctly typed, and correctly windowed.

The time-window tests are the substantive part. The DateTime columns are stored
naive while the code that writes them uses aware UTC datetimes, so a cutoff
built the obvious way compares naive to aware and silently matches nothing.
That failure mode reports "0 sessions active" on a busy instance and looks like
a product decision rather than a bug, so it gets rows seeded on both sides of
each boundary.
"""

from datetime import datetime, timedelta, timezone

import pytest


def naive_ago(**kwargs):
    """A stored-format timestamp N ago: UTC arithmetic, tzinfo stripped."""
    return (datetime.now(timezone.utc) - timedelta(**kwargs)).replace(tzinfo=None)


class TestTopLevelShape:
    def test_the_documented_keys_are_present_and_typed(self, client):
        body = client.get("/api/monitor").get_json()

        assert isinstance(body["generatedAt"], str)
        assert isinstance(body["uptimeSeconds"], int)
        for section in ("deployment", "execution", "accounts", "content"):
            assert isinstance(body[section], dict), section

        deployment = body["deployment"]
        for key in ("version", "isolation", "isolationActive", "env",
                    "platform", "pythonVersion", "bucketMounts", "memoryLimit"):
            assert isinstance(deployment[key], str), key
        assert deployment["bucketMountsProblem"] is None or isinstance(deployment["bucketMountsProblem"], str)
        assert deployment["memoryLimitReason"] is None or isinstance(deployment["memoryLimitReason"], str)
        for key in ("execUserConfigured", "authEnabled", "projectsEnabled",
                    "guestLoginAllowed",
                    "factoryPublishAllowed", "saveNodeOutputDefault",
                    "llmProviderConfigured", "searchToolConfigured"):
            assert isinstance(deployment[key], bool), key

    def test_no_chip_for_the_retired_shared_installs_flag(self, client):
        # #450: --allow-shared-installs is gone (users/capabilities.py), and
        # nothing sets CURIO_ALLOW_SHARED_INSTALLS, so the field could only say off.
        assert "sharedInstallsAllowed" not in client.get("/api/monitor").get_json()["deployment"]

    def test_no_chip_for_the_retired_collab_flag(self, client):
        # --collab is gone: every backend serves collaboration, so the field
        # could only say on.
        assert "collabEnabled" not in client.get("/api/monitor").get_json()["deployment"]

    def test_generated_at_parses_as_utc(self, client):
        stamp = client.get("/api/monitor").get_json()["generatedAt"]
        datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")

    def test_the_duration_histogram_is_a_fixed_shape(self, client):
        buckets = (
            client.get("/api/monitor").get_json()
            ["execution"]["backend"]["durations"]["buckets"]
        )
        assert len(buckets) == 6
        assert buckets[-1]["leMs"] is None, "the last bin must be the overflow"
        assert all(isinstance(b["count"], int) for b in buckets)


class TestTheDeploymentLlm:
    """``llmProviderConfigured`` says whether there is a Deployment default: an
    endpoint file with an endpoint, whose first model it is, read at call
    time."""

    def _flag(self, client, monkeypatch, *endpoints):
        from utk_curio.backend.tests._support import llm_deployment

        llm_deployment.offer(monkeypatch, *endpoints)
        return client.get("/api/monitor").get_json()["deployment"]["llmProviderConfigured"]

    def test_an_endpoint_with_a_model_is_configured(self, client, monkeypatch):
        from utk_curio.backend.tests._support import llm_deployment

        assert self._flag(client, monkeypatch, llm_deployment.endpoint(
            base_url="https://llm.example.com/v1", models=("m",))) is True

    def test_several_endpoints_are_configured(self, client, monkeypatch):
        from utk_curio.backend.tests._support import llm_deployment

        assert self._flag(client, monkeypatch, llm_deployment.endpoint("One", models=("m",)),
                          llm_deployment.endpoint("Two", models=("n",))) is True

    def test_nothing_set_is_not(self, client, monkeypatch):
        assert self._flag(client, monkeypatch) is False


class TestTheSearchProvider:
    """#450: ``searchToolConfigured`` says whether the operator named a search
    provider: ``--agent-search-url`` sets ``CURIO_SEARCH_URL``, the variable
    ``web.search`` reads. Unset, search falls back to its keyless default.

    ``searchProvider`` names the provider ``web.search`` asks: the host of its
    URL, with the port when the URL names one, and nothing else of the URL,
    where a provider's key can be; None when ``web.search`` can ask no URL."""

    def _flag(self, client):
        return client.get("/api/monitor").get_json()["deployment"]["searchToolConfigured"]

    def _provider(self, client):
        """``searchProvider``, and the whole payload's text."""
        response = client.get("/api/monitor")
        assert response.status_code == 200
        # Read with a default, so a payload without the field fails on its value.
        provider = response.get_json()["deployment"].get("searchProvider", "no searchProvider")
        return provider, response.get_data(as_text=True)

    def test_a_named_provider_is_configured(self, client, monkeypatch):
        monkeypatch.delenv("CURIO_AGENT_SEARCH_URL", raising=False)
        monkeypatch.setenv("CURIO_SEARCH_URL", "https://search.example.com/?q={q}")
        assert self._flag(client) is True

    def test_unset_is_not(self, client, monkeypatch):
        monkeypatch.delenv("CURIO_SEARCH_URL", raising=False)
        monkeypatch.setenv("CURIO_AGENT_SEARCH_URL", "https://search.example.com/?q={q}")
        assert self._flag(client) is False

    def test_a_searxng_url_names_the_host_and_port_web_search_asks(self, client, monkeypatch):
        """The hosted stacks' URL: the monitor names ``searxng:8080``, and a
        search goes to that host and port."""
        from urllib.parse import urlsplit

        from utk_curio.backend.app.agents.application import tools
        from utk_curio.backend.app.agents.infrastructure import egress
        from utk_curio.backend.app.agents.infrastructure.egress import EgressResult

        monkeypatch.setenv("CURIO_SEARCH_URL", "http://searxng:8080/search?q={q}&format=json")
        provider, _ = self._provider(client)
        assert provider == "searxng:8080"
        asked = []

        def _fake_fetch(url, **kwargs):
            asked.append(url)
            return EgressResult(url=url, final_url=url, status=200,
                                content_type="application/json", body='{"results": []}')

        monkeypatch.setattr(egress, "fetch", _fake_fetch)
        status, _ = tools.execute_read_tool(
            "web.search", user_key="42", project_id="none", target=None,
            params={"q": "cool roofs in Chicago"},
        )
        assert status == "ok"
        assert [urlsplit(url).netloc for url in asked] == [provider]

    def test_unset_names_duckduckgos_host(self, client, monkeypatch):
        monkeypatch.delenv("CURIO_SEARCH_URL", raising=False)
        monkeypatch.setenv("CURIO_AGENT_SEARCH_URL", "https://search.example.com/?q={q}")
        provider, _ = self._provider(client)
        assert provider == "api.duckduckgo.com"

    @pytest.mark.parametrize("url, host", [
        # A key in the query, as SerpAPI's and Google's URLs carry it.
        ("https://api.provider.test/v1/search?api_key=zqxkey7351&q={q}", "api.provider.test"),
        # A key in the user part and in the path, with a port.
        ("https://zqxuser:zqxkey7351@api.provider.test:8443/zqxkey7351/search?q={q}",
         "api.provider.test:8443"),
    ])
    def test_a_key_in_the_url_is_left_out(self, client, monkeypatch, url, host):
        monkeypatch.setenv("CURIO_SEARCH_URL", url)
        provider, raw = self._provider(client)
        assert provider == host
        assert "zqx" not in raw.lower(), "a part of the search URL but its host and port reached the payload"

    @pytest.mark.parametrize("url, host", [
        ("https://Search.Example.ORG/?q={q}", "search.example.org"),
        ("http://[::1]:8888/search?q={q}&format=json", "[::1]:8888"),
    ])
    def test_a_host_is_named_in_lower_case_and_an_ipv6_one_in_brackets(self, client, monkeypatch, url, host):
        monkeypatch.setenv("CURIO_SEARCH_URL", url)
        provider, _ = self._provider(client)
        assert provider == host

    @pytest.mark.parametrize("url", [
        # No {q}: web.search refuses to search.
        "https://api.provider.test/v1?key=K",
        # A port that is not a number.
        "http://searxng:80a/search?q={q}&format=json",
    ])
    def test_a_url_web_search_cannot_ask_names_no_provider(self, client, monkeypatch, url):
        monkeypatch.setenv("CURIO_SEARCH_URL", url)
        provider, _ = self._provider(client)
        assert provider is None


class TestTheBucketMounts:
    """``bucketMounts`` says how the bucket mount service's self-test went:
    ``none`` when no service is named (``--bucket-mounts-dir`` and
    ``--bucket-mount-socket``), then ``pending``, ``passed`` or
    ``unavailable``, with why in ``bucketMountsProblem``."""

    def _line(self, client):
        deployment = client.get("/api/monitor").get_json()["deployment"]
        return deployment["bucketMounts"], deployment["bucketMountsProblem"]

    def _named(self, monkeypatch):
        from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

        monkeypatch.setenv(bucket_mounts.DIR_VARIABLE, "/bucket-mounts")
        monkeypatch.setenv(bucket_mounts.SOCKET_VARIABLE, "/run/curio-bucket-mounts/rc.sock")

    def _record(self, *outcome):
        from utk_curio.backend.app.discovery.application import bucket_mount_check
        from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

        bucket_mount_check.record(bucket_mounts.SelfTest(*outcome))

    def setup_method(self):
        from utk_curio.backend.app.discovery.application import bucket_mount_check

        bucket_mount_check.reset()

    def teardown_method(self):
        from utk_curio.backend.app.discovery.application import bucket_mount_check

        bucket_mount_check.reset()

    def test_none_when_no_service_is_named(self, client, monkeypatch):
        from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

        monkeypatch.delenv(bucket_mounts.DIR_VARIABLE, raising=False)
        monkeypatch.delenv(bucket_mounts.SOCKET_VARIABLE, raising=False)
        assert self._line(client) == ("none", None)

    def test_pending_until_the_self_test_ends(self, client, monkeypatch):
        self._named(monkeypatch)
        assert self._line(client) == ("pending", None)

    def test_passed(self, client, monkeypatch):
        self._named(monkeypatch)
        self._record(True, None, "mounted /selftest at /mounts/.selftest, read it, unmounted it")
        assert self._line(client) == ("passed", None)

    def test_unavailable_says_why_in_words_alone(self, client, monkeypatch):
        from utk_curio.backend.app.discovery.infrastructure import bucket_mounts

        self._named(monkeypatch)
        self._record(False, "mount-refused", "mounting /selftest at /mounts/.selftest: Permission denied")
        assert self._line(client) == ("unavailable", bucket_mounts.PROBLEMS["mount-refused"])
        errors = client.get("/api/monitor/errors").get_json()["errors"]
        assert [entry["detail"] for entry in errors] == [
            "mounting /selftest at /mounts/.selftest: Permission denied",
        ]


class TestThePublishSwitch:
    """#450: ``factoryPublishAllowed`` reports the switch the catalog routes
    obey, which defaults on, not an environment variable read as off when unset."""

    def _flag(self, client, monkeypatch, allowed: bool):
        from utk_curio.backend.app.packages.routes import common as routes_common

        monkeypatch.delenv("CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", raising=False)
        monkeypatch.setattr(routes_common, "CURIO_ALLOW_FACTORY_CATALOG_PUBLISH", allowed)
        return client.get("/api/monitor").get_json()["deployment"]["factoryPublishAllowed"]

    def test_on(self, client, monkeypatch):
        assert self._flag(client, monkeypatch, True) is True

    def test_off(self, client, monkeypatch):
        assert self._flag(client, monkeypatch, False) is False


class TestSandboxSection:
    def test_an_unreachable_sandbox_nulls_every_field(self, client):
        sandbox = client.get("/api/monitor").get_json()["execution"]["sandbox"]
        assert sandbox["reachable"] is False
        for key, value in sandbox.items():
            if key != "reachable":
                assert value is None, f"{key} should be None when unreachable"

    def test_a_reachable_sandbox_is_passed_through(self, client, monkeypatch):
        from utk_curio.backend.app.monitor import routes

        monkeypatch.setattr(routes, "_sandbox_monitor", lambda: {
            "isolation": "fork", "isolation_active": "fork",
            "zygote_running": True, "parallelism": 2, "slotsInUse": 1,
            "memory_limit_mb": 4096, "cpu_seconds_limit": 300,
            "wall_timeout_seconds": 300,
            "total": 7, "isolated": 7, "inProcess": 0,
            "childDeaths": {"oom": 2},
        })
        body = client.get("/api/monitor").get_json()
        sandbox = body["execution"]["sandbox"]
        assert sandbox["reachable"] is True
        assert sandbox["parallelism"] == 2
        assert sandbox["childDeaths"] == {"oom": 2}
        # The badge and the monitor read the same two fields, so the
        # deployment section must agree with the sandbox section.
        assert body["deployment"]["isolation"] == "fork"
        assert body["deployment"]["isolationActive"] == "fork"

    def test_an_unreachable_sandbox_reports_isolation_as_unknown(self, client):
        deployment = client.get("/api/monitor").get_json()["deployment"]
        # Not "off": a silent sandbox is not evidence that confinement failed.
        assert deployment["isolation"] == "unknown"
        assert deployment["isolationActive"] == "unknown"

    def test_the_deployment_names_the_memory_limit_nodes_run_under(self, client, monkeypatch):
        """A cgroup, or the address-space cap and why, as the sandbox says;
        unknown, with no reason, when the sandbox cannot be asked."""
        from utk_curio.backend.app.monitor import routes

        deployment = client.get("/api/monitor").get_json()["deployment"]
        assert (deployment["memoryLimit"], deployment["memoryLimitReason"]) == ("unknown", None)

        why = "the container's cgroups are read-only (Docker's writable-cgroups option)"
        for limit, reason in (("cgroup", None), ("address space", why), ("none", None)):
            monkeypatch.setattr(routes, "_sandbox_monitor", lambda limit=limit, reason=reason: {
                "isolation": "fork", "isolation_active": "pending",
                "memory_limit": limit, "memory_limit_reason": reason,
            })
            deployment = client.get("/api/monitor").get_json()["deployment"]
            assert (deployment["memoryLimit"], deployment["memoryLimitReason"]) == (limit, reason)


class TestTimeWindows:
    """The timezone trap. Rows on both sides of each boundary."""

    def test_accounts_created_in_the_last_24h(self, client, db):
        from utk_curio.backend.app.users.models import User

        db.session.add(User(username="recent", name="R", created_at=naive_ago(hours=2)))
        db.session.add(User(username="older", name="O", created_at=naive_ago(hours=25)))
        db.session.commit()

        accounts = client.get("/api/monitor").get_json()["accounts"]
        assert accounts["total"] == 2
        assert accounts["createdLast24h"] == 1

    def test_sessions_are_bucketed_by_last_seen(self, client, db):
        from utk_curio.backend.app.users.models import User, UserSession

        user = User(username="u", name="U")
        db.session.add(user)
        db.session.flush()
        db.session.add(UserSession(user_id=user.id, token="t-now",
                                   last_seen_at=naive_ago(minutes=2)))
        db.session.add(UserSession(user_id=user.id, token="t-30m",
                                   last_seen_at=naive_ago(minutes=30)))
        db.session.add(UserSession(user_id=user.id, token="t-90m",
                                   last_seen_at=naive_ago(minutes=90)))
        db.session.commit()

        sessions = client.get("/api/monitor").get_json()["accounts"]["sessions"]
        assert sessions["seenLast5m"] == 1
        assert sessions["seenLast1h"] == 2

    def test_an_expired_session_is_not_active(self, client, db):
        from utk_curio.backend.app.users.models import User, UserSession

        user = User(username="u", name="U")
        db.session.add(user)
        db.session.flush()
        db.session.add(UserSession(user_id=user.id, token="live",
                                   expires_at=naive_ago(days=-1)))
        db.session.add(UserSession(user_id=user.id, token="dead",
                                   expires_at=naive_ago(days=1)))
        db.session.add(UserSession(user_id=user.id, token="endless"))
        db.session.commit()

        sessions = client.get("/api/monitor").get_json()["accounts"]["sessions"]
        # The future-dated one and the null-expiry one; not the past-dated one.
        assert sessions["active"] == 2

    def test_sign_in_attempts_use_a_one_hour_window(self, client, db):
        from utk_curio.backend.app.users.models import AuthAttempt

        db.session.add(AuthAttempt(ip="10.0.0.1", identifier="a",
                                   success=False, created_at=naive_ago(minutes=30)))
        db.session.add(AuthAttempt(ip="10.0.0.2", identifier="b",
                                   success=True, created_at=naive_ago(minutes=30)))
        db.session.add(AuthAttempt(ip="10.0.0.3", identifier="c",
                                   success=False, created_at=naive_ago(minutes=90)))
        db.session.commit()

        sign_in = client.get("/api/monitor").get_json()["accounts"]["signIn"]
        assert sign_in["windowMinutes"] == 60
        assert sign_in["failure"] == 1
        assert sign_in["success"] == 1
        assert sign_in["distinctSources"] == 2

    def test_guest_and_registered_accounts_split(self, client, db):
        from utk_curio.backend.app.users.models import User

        db.session.add(User(username="real", name="R", is_guest=False))
        db.session.add(User(username="guest_shared", name="G", is_guest=True))
        db.session.commit()

        accounts = client.get("/api/monitor").get_json()["accounts"]
        assert (accounts["total"], accounts["registered"], accounts["guest"]) == (2, 1, 1)


class TestContentSection:
    def test_datasets_split_by_origin_with_sizes(self, client, db):
        from utk_curio.backend.app.datasets.models import DatasetIndexEntry

        for i, (origin, size) in enumerate(
            [("imported", 100), ("imported", 300), ("computed", 200)]
        ):
            db.session.add(DatasetIndexEntry(
                user_key="1", dataset_id=f"d{i}", dir_name=f"d{i}",
                origin=origin, title="", format="parquet",
                data_file=f"d{i}.parquet", size_bytes=size,
            ))
        db.session.commit()

        datasets = client.get("/api/monitor").get_json()["content"]["datasets"]
        assert datasets["total"] == 3
        assert datasets["imported"] == 2
        assert datasets["computed"] == 1
        assert datasets["totalBytes"] == 600
        assert datasets["largestBytes"] == 300
        assert datasets["medianBytes"] == 200
        assert datasets["stores"] == 1

    def test_an_empty_instance_reports_zeros_not_nulls(self, client):
        content = client.get("/api/monitor").get_json()["content"]
        assert content["projects"]["total"] == 0
        assert content["datasets"]["totalBytes"] == 0
        assert content["datasets"]["medianBytes"] == 0
        assert content["execCacheEntries"] == 0


class TestTheLlmRoute:
    """``/api/monitor/llm``: the last 24 hours, 7 days and 90 days of this
    Curio's own models, each view's rows and each model's stats, every
    documented key present and typed."""

    STAMP = "%Y-%m-%dT%H:%M:%SZ"
    ROW = {"at", "model", "requests", "failed", "ms"}
    STATS = {"requests", "failed", "averageMs", "p95Ms", "firstTokenMs", "tokensPerSecond"}
    NOW = datetime(2026, 11, 6, 15, 20, 7, tzinfo=timezone.utc)

    def test_the_documented_keys_are_present_and_typed(self, client, monkeypatch):
        from utk_curio.backend.app.monitor import llm_performance

        monkeypatch.setattr(llm_performance, "_now", lambda: self.NOW)
        llm_performance.record("gemma4", ms=1200, first_token_ms=300, output_tokens=60)
        llm_performance.record("qwen3", ms=800, failed=True)
        # Written, as the process's writer does each minute: the route reads the file.
        assert llm_performance.HISTORY.flush() is True
        body = client.get("/api/monitor/llm").get_json()

        assert set(body) == {"computedAt", "maxDays", "ageSeconds", "ttlSeconds", "views"}
        assert body["computedAt"] == "2026-11-06T15:20:07Z"
        assert body["maxDays"] == 90
        assert isinstance(body["ageSeconds"], int) and body["ttlSeconds"] == 60
        assert list(body["views"]) == ["24h", "7d", "90d"]

        spans = {"24h": (timedelta(minutes=5), 288), "7d": (timedelta(hours=1), 168), "90d": (timedelta(days=1), 90)}
        for name, view in body["views"].items():
            assert set(view) == {"from", "to", "stepSeconds", "rows", "models", "all"}, name
            step, steps = spans[name]
            assert view["stepSeconds"] == step.total_seconds(), name
            # From the first row's start to the current one's, as many as the view spans.
            assert (datetime.strptime(view["to"], self.STAMP)
                    - datetime.strptime(view["from"], self.STAMP)) == step * (steps - 1), name
            assert datetime.strptime(view["to"], self.STAMP) <= self.NOW.replace(tzinfo=None), name

            assert [(row["model"], row["requests"], row["failed"], row["ms"]) for row in view["rows"]] == [
                ("gemma4", 1, 0, 1200), ("qwen3", 1, 1, 800)], name
            for row in view["rows"]:
                assert set(row) == self.ROW, row
                datetime.strptime(row["at"], self.STAMP)
                assert all(type(row[key]) is int for key in self.ROW - {"at", "model"}), row

            assert [entry["model"] for entry in view["models"]] == ["gemma4", "qwen3"], name
            for stats in (*view["models"], view["all"]):
                assert set(stats) - {"model"} == self.STATS, stats
            assert view["models"][0] == {"model": "gemma4", "requests": 1, "failed": 0, "averageMs": 1200,
                                         "p95Ms": 2425, "firstTokenMs": 300, "tokensPerSecond": 50.0}, name
            # What no request gave is null, never 0.
            assert view["models"][1] == {"model": "qwen3", "requests": 1, "failed": 1, "averageMs": 800,
                                         "p95Ms": 975, "firstTokenMs": None, "tokensPerSecond": None}, name
            assert view["all"] == {"requests": 2, "failed": 1, "averageMs": 1000, "p95Ms": 2350,
                                   "firstTokenMs": 300, "tokensPerSecond": 50.0}, name
        assert (body["views"]["24h"]["from"], body["views"]["24h"]["to"]) == (
            "2026-11-05T15:25:00Z", "2026-11-06T15:20:00Z")
        assert (body["views"]["7d"]["from"], body["views"]["7d"]["to"]) == (
            "2026-10-30T16:00:00Z", "2026-11-06T15:00:00Z")
        assert (body["views"]["90d"]["from"], body["views"]["90d"]["to"]) == (
            "2026-08-09T00:00:00Z", "2026-11-06T00:00:00Z")

    def test_an_instance_no_model_answered_lists_nothing(self, client):
        body = client.get("/api/monitor/llm").get_json()
        for name, view in body["views"].items():
            assert (view["rows"], view["models"]) == ([], []), name
            assert view["all"] == {"requests": 0, "failed": 0, "averageMs": None, "p95Ms": None,
                                   "firstTokenMs": None, "tokensPerSecond": None}, name
        assert body["maxDays"] == 90
