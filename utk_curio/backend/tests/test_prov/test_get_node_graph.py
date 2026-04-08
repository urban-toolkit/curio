class TestGetNodeGraph:
    def test_returns_graph_after_execution(self, client, executed_box, prov_db):
        wf, activity = executed_box
        resp = client.post(
            "/getNodeGraph",
            json={"data": {"workflow_name": wf, "activity_name": activity}},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert "graph" in data
        assert len(data["graph"]) == 1
        node = data["graph"][0]
        assert "id" in node
        assert "code" in node
        assert node["code"] == "print('hello')"
        assert "inputs" in node
        assert "outputs" in node

    def test_multiple_executions(self, client, executed_box, prov_db):
        wf, activity = executed_box
        client.post(
            "/nodeExecProv",
            json={
                "data": {
                    "workflow_name": wf,
                    "activity_name": activity,
                    "activityexec_start_time": "2026-01-01T01:00:00",
                    "activityexec_end_time": "2026-01-01T01:01:00",
                    "activity_source_code": "y = 2",
                    "types_input": {"DATAFRAME": 1},
                    "types_output": {"DATAFRAME": 1},
                    "interaction": False,
                }
            },
        )
        resp = client.post(
            "/getNodeGraph",
            json={"data": {"workflow_name": wf, "activity_name": activity}},
        )
        data = resp.get_json()
        assert len(data["graph"]) == 2

    def test_type_mappings_in_graph(self, client, executed_box, prov_db):
        wf, activity = executed_box
        resp = client.post(
            "/getNodeGraph",
            json={"data": {"workflow_name": wf, "activity_name": activity}},
        )
        node = resp.get_json()["graph"][0]
        assert "DATAFRAME" in node["inputs"]
        assert "DATAFRAME" in node["outputs"]
