from .conftest import db_query


class TestNewNodeProv:
    def test_creates_new_workflow_version(self, client, seeded_workflow, prov_db):
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "COMPUTATION_ANALYSIS-box1",
                }
            },
        )
        wfs = db_query(
            prov_db,
            "SELECT workflow_name FROM workflow WHERE workflow_name = ?",
            (seeded_workflow,),
        )
        assert len(wfs) == 2

    def test_activity_inserted(self, client, seeded_workflow, prov_db):
        activity = "DATA_LOADING-node1"
        client.post(
            "/newNodeProv",
            json={"data": {"workflow_name": seeded_workflow, "activity_name": activity}},
        )
        rows = db_query(
            prov_db,
            "SELECT activity_name FROM activity WHERE activity_name = ?",
            (activity,),
        )
        assert len(rows) == 1

    def test_output_relation_created(self, client, seeded_workflow, prov_db):
        activity = "DATA_LOADING-rel1"
        client.post(
            "/newNodeProv",
            json={"data": {"workflow_name": seeded_workflow, "activity_name": activity}},
        )
        rows = db_query(
            prov_db,
            "SELECT relation_name FROM relation WHERE relation_name = ?",
            (activity + "_out",),
        )
        assert len(rows) == 1

    def test_attribute_relations_created_for_output_types(self, client, seeded_workflow, prov_db):
        activity = "COMPUTATION_ANALYSIS-ar1"
        resp = client.post(
            "/newNodeProv",
            json={"data": {"workflow_name": seeded_workflow, "activity_name": activity}},
        )
        assert resp.status_code == 200
        ars = db_query(prov_db, "SELECT * FROM attributeRelation")
        assert len(ars) >= 1

    def test_old_activities_duplicated(self, client, seeded_workflow, prov_db):
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "DATA_LOADING-a1",
                }
            },
        )
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "COMPUTATION_ANALYSIS-a2",
                }
            },
        )
        latest_wf = db_query(
            prov_db,
            "SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?",
            (seeded_workflow,),
        )[0][0]
        activities = db_query(
            prov_db,
            "SELECT activity_name FROM activity WHERE workflow_id = ?",
            (latest_wf,),
        )
        names = {a[0] for a in activities}
        assert "DATA_LOADING-a1" in names
        assert "COMPUTATION_ANALYSIS-a2" in names


class TestDeleteNodeProv:
    def test_creates_new_version_and_excludes_deleted(self, client, seeded_workflow, prov_db):
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "DATA_LOADING-d1",
                }
            },
        )
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "COMPUTATION_ANALYSIS-d2",
                }
            },
        )
        resp = client.post(
            "/deleteNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "DATA_LOADING-d1",
                }
            },
        )
        assert resp.status_code == 200

        latest_wf = db_query(
            prov_db,
            "SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?",
            (seeded_workflow,),
        )[0][0]
        activities = db_query(
            prov_db,
            "SELECT activity_name FROM activity WHERE workflow_id = ?",
            (latest_wf,),
        )
        names = {a[0] for a in activities}
        assert "DATA_LOADING-d1" not in names
        assert "COMPUTATION_ANALYSIS-d2" in names

    def test_delete_only_activity_leaves_zero(self, client, seeded_workflow, prov_db):
        client.post(
            "/newNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "DATA_LOADING-solo",
                }
            },
        )
        client.post(
            "/deleteNodeProv",
            json={
                "data": {
                    "workflow_name": seeded_workflow,
                    "activity_name": "DATA_LOADING-solo",
                }
            },
        )
        latest_wf = db_query(
            prov_db,
            "SELECT MAX(workflow_id) FROM workflow WHERE workflow_name = ?",
            (seeded_workflow,),
        )[0][0]
        activities = db_query(
            prov_db,
            "SELECT * FROM activity WHERE workflow_id = ?",
            (latest_wf,),
        )
        assert len(activities) == 0
