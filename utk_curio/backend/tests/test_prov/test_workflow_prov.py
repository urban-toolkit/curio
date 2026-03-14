from .conftest import db_query


class TestSaveUserProv:
    def test_inserts_new_user(self, client, prov_db):
        resp = client.post(
            "/saveUserProv",
            json={
                "user": {
                    "user_name": "alice",
                    "user_type": "programmer",
                    "user_IP": "127.0.0.1",
                }
            },
        )
        assert resp.status_code == 200
        rows = db_query(prov_db, "SELECT user_name, user_type, user_IP FROM user")
        assert len(rows) == 1
        assert rows[0] == ("alice", "programmer", "127.0.0.1")

    def test_duplicate_user_not_inserted(self, client, prov_db):
        payload = {
            "user": {
                "user_name": "bob",
                "user_type": "analyst",
                "user_IP": "10.0.0.1",
            }
        }
        client.post("/saveUserProv", json=payload)
        client.post("/saveUserProv", json=payload)
        rows = db_query(prov_db, "SELECT * FROM user WHERE user_name = 'bob'")
        assert len(rows) == 1

    def test_different_users_both_inserted(self, client, prov_db):
        client.post(
            "/saveUserProv",
            json={"user": {"user_name": "u1", "user_type": "t", "user_IP": "1"}},
        )
        client.post(
            "/saveUserProv",
            json={"user": {"user_name": "u2", "user_type": "t", "user_IP": "2"}},
        )
        rows = db_query(prov_db, "SELECT * FROM user")
        assert len(rows) == 2


class TestSaveWorkflowProv:
    def test_creates_version_ve_workflow(self, client, prov_db):
        resp = client.post("/saveWorkflowProv", json={"workflow": "my_wf"})
        assert resp.status_code == 200

        versions = db_query(prov_db, "SELECT version_number FROM version")
        assert len(versions) == 1
        assert versions[0][0] == "1.0"

        ves = db_query(prov_db, "SELECT * FROM versionedElement")
        assert len(ves) == 1

        wfs = db_query(prov_db, "SELECT workflow_name FROM workflow")
        assert len(wfs) == 1
        assert wfs[0][0] == "my_wf"

    def test_two_workflows_independent(self, client, prov_db):
        client.post("/saveWorkflowProv", json={"workflow": "wf_a"})
        client.post("/saveWorkflowProv", json={"workflow": "wf_b"})

        wfs = db_query(prov_db, "SELECT workflow_name FROM workflow ORDER BY workflow_name")
        assert [w[0] for w in wfs] == ["wf_a", "wf_b"]

        versions = db_query(prov_db, "SELECT version_number FROM version")
        assert len(versions) == 2
        assert all(v[0] == "1.0" for v in versions)
