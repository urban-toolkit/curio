"""Every documented key is present, correctly typed, and correctly windowed.

The time-window tests are the substantive part. The DateTime columns are stored
naive while the code that writes them uses aware UTC datetimes, so a cutoff
built the obvious way compares naive to aware and silently matches nothing.
That failure mode reports "0 sessions active" on a busy instance and looks like
a product decision rather than a bug, so it gets rows seeded on both sides of
each boundary.
"""

from datetime import datetime, timedelta, timezone


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
                    "platform", "pythonVersion"):
            assert isinstance(deployment[key], str), key
        for key in ("execUserConfigured", "authEnabled", "projectsEnabled",
                    "guestLoginAllowed", "collabEnabled", "sharedInstallsAllowed",
                    "factoryPublishAllowed", "saveNodeOutputDefault",
                    "llmProviderConfigured", "searchToolConfigured"):
            assert isinstance(deployment[key], bool), key

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
