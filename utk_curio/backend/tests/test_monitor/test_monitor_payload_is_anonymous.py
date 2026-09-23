"""Nothing on the aggregate routes may name a person.

`/api/monitor` is public. It reports on accounts, sessions, sign-in attempts
and storage, and every one of those has an identifier sitting next to the
number. This suite is what stands between "14 accounts" and "14 accounts, one
of them alice@lab.edu".

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

from utk_curio.backend.app.monitor import counters

IPV4 = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

# Every string an aggregate payload is allowed to contain, beyond a timestamp.
# Closed vocabularies only: if a value cannot be enumerated here, it does not
# belong on a public route.
ALLOWED_STRINGS = set()
ALLOWED_STRINGS |= {"fork", "off", "auto", "unavailable", "unknown", "pending"}
ALLOWED_STRINGS |= {"dev", "prod", "test"}
ALLOWED_STRINGS |= {"users", "data", "exec-overlays", "exec-scratch"}
ALLOWED_STRINGS |= {"timeout", "oom", "cpu", "signal", "refused", "exit", "unknown"}


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
    assert "@" not in raw, "an email-shaped string reached the payload"
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
