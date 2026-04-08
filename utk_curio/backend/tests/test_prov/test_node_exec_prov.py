from .conftest import db_query


def _exec_payload(wf, activity, interaction=False, source_code="x = 1"):
    return {
        "data": {
            "workflow_name": wf,
            "activity_name": activity,
            "activityexec_start_time": "2026-01-01T10:00:00",
            "activityexec_end_time": "2026-01-01T10:01:00",
            "activity_source_code": source_code,
            "types_input": {"DATAFRAME": 1, "GEODATAFRAME": 0},
            "types_output": {"DATAFRAME": 1, "GEODATAFRAME": 0, "VALUE": 1},
            "interaction": interaction,
        }
    }


class TestNodeExecProv:
    def test_creates_workflow_execution(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        resp = client.post("/nodeExecProv", json=_exec_payload(wf, activity))
        assert resp.status_code == 200

        rows = db_query(prov_db, "SELECT * FROM workflowExecution")
        assert len(rows) >= 1

    def test_creates_activity_execution(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        client.post("/nodeExecProv", json=_exec_payload(wf, activity))

        rows = db_query(prov_db, "SELECT * FROM activityExecution")
        assert len(rows) >= 1

    def test_source_code_stored(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        code = "result = df.sum()"
        client.post("/nodeExecProv", json=_exec_payload(wf, activity, source_code=code))

        rows = db_query(
            prov_db,
            "SELECT activity_source_code FROM activityExecution ORDER BY activityexec_id DESC LIMIT 1",
        )
        assert rows[0][0] == code

    def test_relation_instances_created(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        client.post("/nodeExecProv", json=_exec_payload(wf, activity))

        rows = db_query(prov_db, "SELECT * FROM relationInstance")
        assert len(rows) >= 2  # input + output

    def test_attribute_values_recorded(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        client.post("/nodeExecProv", json=_exec_payload(wf, activity))

        rows = db_query(prov_db, "SELECT * FROM attributeValue")
        assert len(rows) >= 1

    def test_multiple_executions_increment(self, client, seeded_box, prov_db):
        wf, activity = seeded_box
        client.post("/nodeExecProv", json=_exec_payload(wf, activity))
        client.post("/nodeExecProv", json=_exec_payload(wf, activity, source_code="y = 2"))

        rows = db_query(prov_db, "SELECT * FROM activityExecution")
        assert len(rows) >= 2

    def test_interaction_true_links_interaction_id(self, client, executed_box, prov_db):
        """When interaction=True, the workflowExecution should have an int_id set,
        but only if an interaction row exists. We set one up manually first."""
        import sqlite3

        wf, activity = executed_box

        conn = sqlite3.connect(prov_db)
        cur = conn.cursor()
        ae = cur.execute(
            "SELECT activityexec_id FROM activityExecution ORDER BY activityexec_id DESC LIMIT 1"
        ).fetchone()
        cur.execute(
            "INSERT INTO visualization (vis_path, vis_content, activityexec_id) VALUES (?, ?, ?)",
            ("", "VIS_VEGA", ae[0]),
        )
        conn.commit()
        vis_id = cur.lastrowid
        cur.execute(
            "INSERT INTO interaction (int_time, user_id, vis_id) VALUES (?, ?, ?)",
            ("2026-01-01T10:02:00", "", vis_id),
        )
        conn.commit()
        conn.close()

        resp = client.post(
            "/nodeExecProv",
            json=_exec_payload(wf, activity, interaction=True),
        )
        assert resp.status_code == 200

        rows = db_query(
            prov_db,
            "SELECT int_id FROM workflowExecution ORDER BY workflowexec_id DESC LIMIT 1",
        )
        assert rows[0][0] is not None
