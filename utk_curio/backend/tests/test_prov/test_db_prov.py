from .conftest import db_query


class TestCheckDB:
    def test_returns_ok(self, client, prov_db):
        resp = client.get("/checkDB")
        assert resp.status_code == 200
        assert b"OK" in resp.data


class TestTruncateDBProv:
    def test_clears_all_tables(self, client, prov_db):
        client.post("/saveWorkflowProv", json={"workflow": "to_delete"})
        wfs_before = db_query(prov_db, "SELECT * FROM workflow")
        assert len(wfs_before) >= 1

        resp = client.get("/truncateDBProv")
        assert resp.status_code == 200

        wfs_after = db_query(prov_db, "SELECT * FROM workflow")
        assert len(wfs_after) == 0

        versions_after = db_query(prov_db, "SELECT * FROM version")
        assert len(versions_after) == 0

    def test_reseeds_attribute_rows(self, client, prov_db):
        client.get("/truncateDBProv")

        attrs = db_query(
            prov_db, "SELECT attribute_id, attribute_name, attribute_type FROM attribute ORDER BY attribute_id"
        )
        assert len(attrs) == 5
        expected_names = ["DATAFRAME", "GEODATAFRAME", "VALUE", "LIST", "JSON"]
        assert [a[1] for a in attrs] == expected_names
        assert all(a[2] == "Data" for a in attrs)

    def test_truncate_is_idempotent(self, client, prov_db):
        client.get("/truncateDBProv")
        client.get("/truncateDBProv")

        attrs = db_query(prov_db, "SELECT * FROM attribute")
        assert len(attrs) == 5
