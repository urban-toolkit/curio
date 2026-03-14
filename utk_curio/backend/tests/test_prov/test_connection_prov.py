from .conftest import db_query


class TestNewConnectionProv:
    def test_sets_target_input_relation(self, client, two_boxes, prov_db):
        wf, src, tgt = two_boxes
        src_type, src_id = src.split("-")
        tgt_type, tgt_id = tgt.split("-")

        resp = client.post(
            "/newConnectionProv",
            json={
                "data": {
                    "workflow_name": wf,
                    "sourceNodeType": src_type,
                    "sourceNodeId": src_id,
                    "targetNodeType": tgt_type,
                    "targetNodeId": tgt_id,
                }
            },
        )
        assert resp.status_code == 200

        latest_wf = db_query(
            prov_db,
            "SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?",
            (wf,),
        )[0][0]

        target_act = db_query(
            prov_db,
            "SELECT input_relation_id FROM activity WHERE workflow_id = ? AND activity_name = ?",
            (latest_wf, tgt),
        )
        source_act = db_query(
            prov_db,
            "SELECT output_relation_id FROM activity WHERE workflow_id = ? AND activity_name = ?",
            (latest_wf, src),
        )
        assert target_act[0][0] == source_act[0][0]

    def test_missing_keys_returns_400(self, client, two_boxes, prov_db):
        resp = client.post(
            "/newConnectionProv",
            json={"data": {"workflow_name": "wf"}},
        )
        assert resp.status_code == 400

    def test_nonexistent_workflow_returns_error(self, client, prov_db):
        resp = client.post(
            "/newConnectionProv",
            json={
                "data": {
                    "workflow_name": "nonexistent",
                    "sourceNodeType": "A",
                    "sourceNodeId": "1",
                    "targetNodeType": "B",
                    "targetNodeId": "2",
                }
            },
        )
        assert resp.status_code in (400, 404, 500)

    def test_nonexistent_source_activity_returns_400(self, client, two_boxes, prov_db):
        wf, _, tgt = two_boxes
        tgt_type, tgt_id = tgt.split("-")
        resp = client.post(
            "/newConnectionProv",
            json={
                "data": {
                    "workflow_name": wf,
                    "sourceNodeType": "FAKE",
                    "sourceNodeId": "999",
                    "targetNodeType": tgt_type,
                    "targetNodeId": tgt_id,
                }
            },
        )
        assert resp.status_code == 400


class TestDeleteConnectionProv:
    def test_sets_target_input_to_null(self, client, two_boxes, prov_db):
        wf, src, tgt = two_boxes
        src_type, src_id = src.split("-")
        tgt_type, tgt_id = tgt.split("-")

        client.post(
            "/newConnectionProv",
            json={
                "data": {
                    "workflow_name": wf,
                    "sourceNodeType": src_type,
                    "sourceNodeId": src_id,
                    "targetNodeType": tgt_type,
                    "targetNodeId": tgt_id,
                }
            },
        )

        resp = client.post(
            "/deleteConnectionProv",
            json={
                "data": {
                    "workflow_name": wf,
                    "targetNodeType": tgt_type,
                    "targetNodeId": tgt_id,
                }
            },
        )
        assert resp.status_code == 200

        latest_wf = db_query(
            prov_db,
            "SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?",
            (wf,),
        )[0][0]
        target_act = db_query(
            prov_db,
            "SELECT input_relation_id FROM activity WHERE workflow_id = ? AND activity_name = ?",
            (latest_wf, tgt),
        )
        assert target_act[0][0] is None
