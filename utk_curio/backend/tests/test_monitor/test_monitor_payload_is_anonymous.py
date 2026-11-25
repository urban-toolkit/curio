"""Nothing on the aggregate routes may name a person.

`/api/monitor` is public, as are `/api/monitor/storage`, `/api/monitor/usage`,
`/api/monitor/llm` and `/api/monitor/open-files`. It reports on accounts,
sessions, sign-in attempts and storage, and every one of those has an
identifier sitting next to the number. This suite is what stands between "14
accounts" and "14 accounts, one of them alice@lab.edu".

DELIBERATELY NOT COVERED: `/api/monitor/errors`. That route returns raw
tracebacks by an explicit product decision, and will contain paths, code
fragments and whatever a traceback interpolated. See
`utk_curio/backend/app/monitor/errors.py` for what that exposes. Keeping the
raw text on its own route is precisely what lets the assertions below be total
instead of a list of exceptions.

The substring checks catch today's fields. The leaf-type walk is the one that
matters: it catches a field somebody adds next year.
"""

import json
import re

import pytest

from utk_curio.backend.app.discovery.infrastructure import bucket_mounts
from utk_curio.backend.app.monitor import counters, llm_performance

IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# An address, not any "@": the hardware section names the CPU, and an Intel
# model reads "Intel(R) Xeon(R) Platinum 8370C CPU @ 2.80GHz".
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# A host name with a top-level domain, as a model name never needs one.
HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,24}\b", re.I)
# A host, or an IPv6 address in brackets, and a port: all a search URL may give.
HOST_AND_PORT = re.compile(r"(?:[a-z0-9_-]+(?:\.[a-z0-9_-]+)*|\[[0-9a-f:.]+\])(?::\d{1,5})?")

# Every string an aggregate payload is allowed to contain, beyond a timestamp.
# Closed vocabularies only: if a value cannot be enumerated here, it does not
# belong on a public route.
ALLOWED_STRINGS = set()
ALLOWED_STRINGS |= {"fork", "off", "auto", "unavailable", "unknown", "pending"}
ALLOWED_STRINGS |= {"dev", "prod", "test"}
ALLOWED_STRINGS |= {"users", "data", "exec-overlays", "exec-scratch"}
ALLOWED_STRINGS |= {"timeout", "oom", "cpu", "signal", "refused", "exit", "unknown"}
# The bucket mount service's self-test: its states, and the words of why it
# is unavailable, a closed list (bucket_mounts.PROBLEMS).
ALLOWED_STRINGS |= {"none", "passed"} | set(bucket_mounts.PROBLEMS.values())


@pytest.fixture()
def seeded(app, db):
    """A user, project, dataset and failed sign-in, all with findable names."""
    from utk_curio.backend.app.datasets.models import DatasetIndexEntry
    from utk_curio.backend.app.projects.models import Project
    from utk_curio.backend.app.users.models import AuthAttempt, User, UserSession

    user = User(username="zqxprobe", name="Zqx Probe", email="zqxprobe@probe.invalid")
    db.session.add(user)
    db.session.flush()
    db.session.add(UserSession(user_id=user.id, token="zqxprobe-token"))
    db.session.add(Project(
        user_id=user.id, name="Zqx Secret Project", slug="zqx-secret",
        folder_path="/Users/zqxprobe/curio/zqx-secret",
    ))
    db.session.add(AuthAttempt(
        ip="203.0.113.77", identifier="zqxprobe@probe.invalid", success=False,
    ))
    db.session.add(DatasetIndexEntry(
        user_key=str(user.id), dataset_id="zqx.dataset", dir_name="zqx-dataset",
        origin="imported", title="Zqx Dataset", format="parquet",
        data_file="zqx.parquet", size_bytes=4096, publisher="Zqx Publisher",
    ))
    db.session.commit()
    # A node type id is user-authored too, so make sure one has been recorded.
    counters.record_execution(
        language="python", node_type="zqxprobe/secret-node", ok=False,
        duration_ms=12,
    )
    return user


def test_no_identifier_appears_in_the_payload(client, seeded):
    raw = client.get("/api/monitor").get_data(as_text=True)

    assert "zqx" not in raw.lower(), "a seeded name reached the payload"
    assert EMAIL.search(raw) is None, "an email-shaped string reached the payload"
    assert "probe.invalid" not in raw
    assert IPV4.search(raw) is None, "an IP-shaped string reached the payload"
    assert "/Users/" not in raw, "a filesystem path reached the payload"
    # The hardware section describes the machine, never who owns it.
    assert "hostname" not in raw.lower()


def test_node_type_ids_are_reduced_to_a_count(client, seeded):
    body = client.get("/api/monitor").get_json()
    # A user can name a node package anything, so the ids are a text channel.
    # Only the cardinality may escape.
    assert body["execution"]["backend"]["distinctNodeTypes"] == 1
    assert "secret-node" not in json.dumps(body)


def test_the_seeded_rows_were_actually_counted(client, seeded):
    """Guards against the assertions above passing on an empty payload."""
    body = client.get("/api/monitor").get_json()
    assert body["accounts"]["total"] == 1
    assert body["accounts"]["signIn"]["failure"] == 1
    assert body["accounts"]["signIn"]["distinctSources"] == 1
    assert body["content"]["projects"]["total"] == 1
    assert body["content"]["datasets"]["total"] == 1


def test_every_string_leaf_is_a_timestamp_or_a_known_token(client, seeded):
    """The assertion that survives new fields.

    A substring check only knows about the names this test happened to seed.
    This one rejects any string that is not a timestamp or a member of a closed
    vocabulary, so a field added later fails here rather than shipping a name.
    """
    body = client.get("/api/monitor").get_json()

    # Process and machine facts, not user data, and free-form by nature.
    # Popped by name rather than pattern-matched, so adding another free-text
    # field means editing this list on purpose rather than it slipping through.
    deployment = body["deployment"]
    cpu = body["hardware"]["cpu"]
    # The search provider the agents ask, which the operator's configuration
    # or web.search's default names, never a person: popped by name, and held
    # to a host and port, nothing else of its URL (test_monitor_payload_shape.py
    # puts a key in the URL).
    search_provider = deployment.pop("searchProvider")
    assert search_provider is None or HOST_AND_PORT.fullmatch(search_provider), search_provider
    exempt = {
        deployment.pop("version"),
        deployment.pop("platform"),
        deployment.pop("pythonVersion"),
        cpu.pop("model"),
        cpu.pop("arch"),
    }

    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            if node in exempt or ISO_Z.match(node) or node in ALLOWED_STRINGS:
                return
            offenders.append((path, node))

    walk(body, "$")
    assert not offenders, (
        "free-text strings reached a public aggregate payload: "
        f"{offenders}. Either reduce the value to a count, or add it to "
        "ALLOWED_STRINGS if it is genuinely a closed vocabulary."
    )


def test_a_failed_bucket_mount_self_test_names_no_path_or_host(client, monkeypatch):
    """What went wrong names paths, hosts and rclone's answer, which only the
    errors route shows; the aggregate route says why in a closed list of words."""
    from utk_curio.backend.app.discovery.application import bucket_mount_check

    monkeypatch.setenv(bucket_mounts.DIR_VARIABLE, "/srv/zqxprobe/bucket-mounts")
    monkeypatch.setenv(bucket_mounts.SOCKET_VARIABLE, "/srv/zqxprobe/run/rc.sock")
    bucket_mount_check.reset()
    try:
        bucket_mount_check.record(bucket_mounts.SelfTest(
            False, "not-readable",
            "reading /srv/zqxprobe/bucket-mounts/.selftest/ok as curio-exec (uid 999) from "
            "data.zqxprobe.example at 203.0.113.77: Permission denied (errno 13)",
        ))
        response = client.get("/api/monitor")
    finally:
        bucket_mount_check.reset()

    raw = response.get_data(as_text=True)
    assert "zqx" not in raw.lower()
    assert IPV4.search(raw) is None
    assert "/srv/" not in raw
    deployment = response.get_json()["deployment"]
    # Not vacuous: the failure was read.
    assert (deployment["bucketMounts"], deployment["bucketMountsProblem"]) == (
        "unavailable", bucket_mounts.PROBLEMS["not-readable"],
    )
    for key in ("bucketMounts", "bucketMountsProblem"):
        assert deployment[key] in ALLOWED_STRINGS, key


def test_the_storage_payload_is_anonymous_too(client, seeded, state_root):
    """The other aggregate route, held to the same rule.

    Store directories are named by user id, so the walk sees identifiers even
    though the payload must not.
    """
    for name in ("zqxprobe", "alice"):
        store = state_root / "users" / name
        store.mkdir(parents=True)
        (store / "blob.bin").write_bytes(b"x" * 1024)

    from utk_curio.backend.app.monitor import storage
    storage.reset()

    response = client.get("/api/monitor/storage")
    raw = response.get_data(as_text=True)
    assert "zqx" not in raw.lower()
    assert "alice" not in raw
    assert "@" not in raw
    assert IPV4.search(raw) is None

    body = response.get_json()
    # Not vacuous: the stores really were measured.
    assert body["userStores"]["count"] == 2

    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            if ISO_Z.match(node) or node in ALLOWED_STRINGS:
                return
            offenders.append((path, node))

    walk(body, "$")
    assert not offenders, f"free-text strings reached the storage payload: {offenders}"


def test_the_llm_payload_names_curios_own_models_and_nobody(client):
    """The third aggregate route, held to the same rule with one exemption.

    It names this Curio's own models that answered, so only the values of
    ``model`` are exempt from the closed vocabulary, and the scans still run
    on them: a model named as an address, a host or a sentence is recorded as
    ``other``. A request on a key a user set for their own, whose model is
    whatever the user typed, is recorded not at all, and nothing says where a
    model ran.
    """
    from utk_curio.backend.app.agents.infrastructure import providers, testing_provider

    llm_performance.record("gemma4", ms=1200, first_token_ms=300, output_tokens=30)
    named = (
        "zqxprobe@probe.invalid", "https://llm.zqx.example/v1", "llm.zqx.example",
        "llm.zqx.example:8443", "203.0.113.77", "203.0.113.77:11434", "zqx probe",
    )
    for model in named:
        llm_performance.record(model, ms=500, output_tokens=1)
    testing_provider.reset()
    try:
        for model in ("zqxtyped@probe.invalid", "https://zqx-own.example/v1", "198.51.100.23"):
            testing_provider.push_reply("A reply on the user's own key.")
            own = providers.ProviderConfig(api_key="", api_type="testing", base_url="", model=model)
            asked = [{"role": "user", "content": "Hello"}]
            assert providers.run_chat_turn(own, asked).text == "A reply on the user's own key."
    finally:
        testing_provider.reset()
    # Written, as the process's writer does each minute: the route reads the file.
    assert llm_performance.HISTORY.flush() is True

    response = client.get("/api/monitor/llm")
    raw = response.get_data(as_text=True)
    assert "zqx" not in raw.lower(), "a named or typed address reached the payload"
    assert EMAIL.search(raw) is None, "an email-shaped string reached the payload"
    assert "probe.invalid" not in raw
    assert IPV4.search(raw) is None, "an IP-shaped string reached the payload"
    assert "hostname" not in raw.lower()
    assert "curio" not in raw.lower(), "the payload says where a model ran"

    body = response.get_json()
    # Not vacuous: every named address was counted, as other, in every view,
    # and no request on a user's own key.
    for name, view in body["views"].items():
        assert {entry["model"]: entry["requests"] for entry in view["models"]} == {
            "gemma4": 1,
            "other": len(named),
        }, name

    offenders = []

    def walk(node, path, key=None):
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, f"{path}.{name}", name)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            if key == "model":
                if EMAIL.search(node) or IPV4.search(node) or HOST.search(node):
                    offenders.append((path, node))
                return
            if ISO_Z.match(node) or node in ALLOWED_STRINGS:
                return
            offenders.append((path, node))

    walk(body, "$")
    assert not offenders, f"free text or an address reached the LLM payload: {offenders}"


def test_the_open_files_payload_is_timestamps_and_numbers(client, monkeypatch):
    """The fourth aggregate route: each server's open files and limit, every
    hour. The servers are its keys, so every string in it is a timestamp, and
    every other value a number or null, but for the version each deploy the
    chart marks started, popped by name."""
    # Imported here, so a tree without the sampler fails this test alone.
    from datetime import datetime, timedelta, timezone

    from utk_curio.backend.app.monitor import open_files, routes, usage

    open_files.reset()
    # An hour keeps one row, so the two samples are an hour apart.
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(open_files, "_now", lambda: now - timedelta(hours=1))
    monkeypatch.setattr(routes, "_sandbox_monitor", lambda: {"open_files": 96, "open_files_limit": 1024})
    open_files.sample()
    # A deploy between the two samples.
    monkeypatch.setattr(usage, "_now", lambda: now - timedelta(minutes=30))
    assert usage.record_start("0.17.400") is True
    monkeypatch.setattr(open_files, "_now", lambda: now)
    monkeypatch.setattr(routes, "_sandbox_monitor", lambda: None)
    open_files.sample()

    body = client.get("/api/monitor/open-files").get_json()
    # Not vacuous: both samples are there, the sandbox's counts in the first,
    # and the deploy.
    assert len(body["samples"]) == 2
    assert body["samples"][0]["sandbox"] == {"open": 96, "limit": 1024}
    assert body["samples"][1]["sandbox"] is None
    assert [deploy["version"] for deploy in body["deploys"]] == ["0.17.400"]
    # The version a deploy started, Curio's own: popped by name, as the other
    # payloads' free-text fields are.
    for deploy in body["deploys"]:
        deploy.pop("version")

    offenders = []

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")
        elif isinstance(node, str):
            if not ISO_Z.match(node):
                offenders.append((path, node))
        elif node is not None and (isinstance(node, bool) or not isinstance(node, (int, float))):
            offenders.append((path, node))

    walk(body, "$")
    open_files.reset()
    assert not offenders, f"something other than a timestamp or a number reached the open-files payload: {offenders}"


def test_the_usage_payload_is_counts_measures_timestamps_and_versions(client, seeded, db, monkeypatch):
    """The fifth aggregate route: what this Curio did by measure, the
    sessions seen and the deploys. Its strings are timestamps, the names of
    its measures (as the values of ``key`` and of ``measures`` alone) and the
    version each deploy started, popped by name; every other value is a
    number or null. The sessions are counts: nothing of who signed in."""
    from datetime import datetime, timedelta, timezone

    from utk_curio.backend.app.monitor import usage
    from utk_curio.backend.app.users.models import UserSession

    now = datetime.now(timezone.utc)
    clock = {"at": now - timedelta(hours=2)}
    monkeypatch.setattr(usage, "_now", lambda: clock["at"])
    assert usage.record_start("0.17.400") is True
    clock["at"] = now
    assert usage.record_start("0.17.401") is True
    for key in usage.MEASURES:
        usage.record(key, ms=1200, failed=key == "run")
    # The seeded account's sign-in, seen a minute ago, as a request stamps it,
    # and the sessions sample of its 5 minutes.
    signed_in = db.session.query(UserSession).filter_by(token="zqxprobe-token").one()
    signed_in.last_seen_at = now - timedelta(minutes=1)
    db.session.commit()
    assert usage.sample_sessions(now=now)["accounts5m"] == 1
    # Written, as the process's writer does each minute: the route reads the file.
    assert usage.HISTORY.flush() is True

    response = client.get("/api/monitor/usage")
    raw = response.get_data(as_text=True)
    assert "zqx" not in raw.lower(), "a seeded name reached the payload"
    assert EMAIL.search(raw) is None, "an email-shaped string reached the payload"
    assert "probe.invalid" not in raw
    assert IPV4.search(raw) is None, "an IP-shaped string reached the payload"

    body = response.get_json()
    # Not vacuous: every measure was counted in every view, the sign-in, and
    # both deploys.
    assert body["sessionsLast24h"] == {"accounts": 1, "guests": 0}
    for name, view in body["views"].items():
        assert [(each["key"], each["count"], each["failed"]) for each in view["measures"]] == [
            (key, 1, 1 if key == "run" else 0) for key in usage.MEASURES], name
        assert [deploy["version"] for deploy in view["deploys"]] == ["0.17.400", "0.17.401"], name
        assert [(each["accounts"], each["guests"]) for each in view["sessions"]] == [(1, 0)], name
        # The version a deploy started, Curio's own: popped by name, as the
        # other payloads' free-text fields are.
        for deploy in view["deploys"]:
            deploy.pop("version")

    offenders = []

    def walk(node, path, key=None):
        if isinstance(node, dict):
            for name, value in node.items():
                walk(value, f"{path}.{name}", name)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]", key)
        elif isinstance(node, str):
            if key in ("key", "measures") and node in usage.MEASURES:
                return
            if not ISO_Z.match(node):
                offenders.append((path, node))
        elif node is not None and (isinstance(node, bool) or not isinstance(node, (int, float))):
            offenders.append((path, node))

    walk(body, "$")
    assert not offenders, f"free text reached the usage payload: {offenders}"
