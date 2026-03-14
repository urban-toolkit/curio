import sqlite3
import pytest
from utk_curio.backend.create_provenance_db import initialize_db


SEED_ATTRIBUTES = [
    (1, "DATAFRAME", "Data"),
    (2, "GEODATAFRAME", "Data"),
    (3, "VALUE", "Data"),
    (4, "LIST", "Data"),
    (5, "JSON", "Data"),
]


@pytest.fixture
def prov_db(tmp_path, monkeypatch):
    """Fresh provenance DB for each test, with default ATTRIBUTE rows."""
    db_file = str(tmp_path / "provenance.db")
    initialize_db(db_file)

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    for attr_id, name, atype in SEED_ATTRIBUTES:
        cur.execute(
            "INSERT OR IGNORE INTO attribute (attribute_id, attribute_name, attribute_type) VALUES (?, ?, ?)",
            (attr_id, name, atype),
        )
    conn.commit()
    conn.close()

    monkeypatch.setattr(
        "utk_curio.backend.app.api.routes.get_db_path", lambda: db_file
    )
    return db_file


@pytest.fixture
def client(app):
    """Flask test client from the session-scoped app fixture."""
    return app.test_client()


@pytest.fixture
def seeded_workflow(client, prov_db):
    """Creates a workflow named 'test_wf' and returns the name."""
    resp = client.post("/saveWorkflowProv", json={"workflow": "test_wf"})
    assert resp.status_code == 200
    return "test_wf"


@pytest.fixture
def seeded_box(client, seeded_workflow):
    """Adds a COMPUTATION_ANALYSIS box to the seeded workflow. Returns (workflow_name, activity_name)."""
    activity = "COMPUTATION_ANALYSIS-box1"
    resp = client.post(
        "/newBoxProv",
        json={"data": {"workflow_name": seeded_workflow, "activity_name": activity}},
    )
    assert resp.status_code == 200
    return seeded_workflow, activity


@pytest.fixture
def two_boxes(client, seeded_workflow):
    """Adds two boxes and returns (workflow_name, source_activity, target_activity)."""
    src = "DATA_LOADING-src1"
    tgt = "COMPUTATION_ANALYSIS-tgt1"
    client.post(
        "/newBoxProv",
        json={"data": {"workflow_name": seeded_workflow, "activity_name": src}},
    )
    client.post(
        "/newBoxProv",
        json={"data": {"workflow_name": seeded_workflow, "activity_name": tgt}},
    )
    return seeded_workflow, src, tgt


@pytest.fixture
def executed_box(client, seeded_box):
    """Executes a box once and returns (workflow_name, activity_name)."""
    wf, activity = seeded_box
    resp = client.post(
        "/boxExecProv",
        json={
            "data": {
                "workflow_name": wf,
                "activity_name": activity,
                "activityexec_start_time": "2026-01-01T00:00:00",
                "activityexec_end_time": "2026-01-01T00:01:00",
                "activity_source_code": "print('hello')",
                "types_input": {"DATAFRAME": 1, "GEODATAFRAME": 0},
                "types_output": {"DATAFRAME": 1, "GEODATAFRAME": 0},
                "interaction": False,
            }
        },
    )
    assert resp.status_code == 200
    return wf, activity


def db_query(db_path, sql, params=()):
    """Convenience helper to run a read query and return all rows."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return rows
