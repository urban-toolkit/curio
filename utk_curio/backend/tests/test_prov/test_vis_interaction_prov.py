import sqlite3
from .conftest import db_query


class TestInsertVisualization:
    def test_creates_visualization_row(self, client, executed_box, prov_db):
        _, activity = executed_box
        resp = client.post(
            "/insert_visualization",
            json={"data": {"activity_name": activity}},
        )
        assert resp.status_code == 201

        rows = db_query(prov_db, "SELECT * FROM visualization")
        assert len(rows) >= 1

    def test_visualization_linked_to_execution(self, client, executed_box, prov_db):
        _, activity = executed_box
        client.post(
            "/insert_visualization",
            json={"data": {"activity_name": activity}},
        )

        ae = db_query(
            prov_db,
            "SELECT activityexec_id FROM activityExecution ORDER BY activityexec_id DESC LIMIT 1",
        )
        vis = db_query(
            prov_db,
            "SELECT activityexec_id FROM visualization ORDER BY vis_id DESC LIMIT 1",
        )
        assert vis[0][0] == ae[0][0]

    def test_no_execution_returns_error(self, client, seeded_box, prov_db):
        _, activity = seeded_box
        resp = client.post(
            "/insert_visualization",
            json={"data": {"activity_name": activity}},
        )
        assert resp.status_code in (400, 404, 500)


class TestInsertInteraction:
    def _setup_vis(self, client, executed_box, prov_db):
        """Helper: create a visualization for the executed node."""
        _, activity = executed_box
        client.post(
            "/insert_visualization",
            json={"data": {"activity_name": activity}},
        )
        return activity

    def test_creates_interaction_row(self, client, executed_box, prov_db):
        activity = self._setup_vis(client, executed_box, prov_db)
        resp = client.post(
            "/insert_interaction",
            json={"data": {"activity_name": activity, "int_time": "2026-01-01T12:00:00"}},
        )
        assert resp.status_code == 201

        rows = db_query(prov_db, "SELECT * FROM interaction")
        assert len(rows) >= 1

    def test_interaction_linked_to_visualization(self, client, executed_box, prov_db):
        activity = self._setup_vis(client, executed_box, prov_db)
        client.post(
            "/insert_interaction",
            json={"data": {"activity_name": activity, "int_time": "2026-01-01T12:00:00"}},
        )

        vis = db_query(prov_db, "SELECT vis_id FROM visualization ORDER BY vis_id DESC LIMIT 1")
        interaction = db_query(prov_db, "SELECT vis_id FROM interaction ORDER BY int_id DESC LIMIT 1")
        assert interaction[0][0] == vis[0][0]

    def test_no_visualization_returns_error(self, client, executed_box, prov_db):
        _, activity = executed_box
        resp = client.post(
            "/insert_interaction",
            json={"data": {"activity_name": activity, "int_time": "2026-01-01T12:00:00"}},
        )
        assert resp.status_code in (400, 500)


class TestInsertAttributeValueChange:
    def _full_setup(self, client, executed_box, prov_db):
        """Helper: executed node + visualization + interaction."""
        wf, activity = executed_box
        client.post(
            "/insert_visualization",
            json={"data": {"activity_name": activity}},
        )
        client.post(
            "/insert_interaction",
            json={"data": {"activity_name": activity, "int_time": "2026-01-01T12:00:00"}},
        )
        return activity

    def test_records_value_change(self, client, executed_box, prov_db):
        activity = self._full_setup(client, executed_box, prov_db)
        resp = client.post(
            "/insert_attribute_value_change",
            json={"data": {"activity_name": activity}},
        )
        assert resp.status_code == 201

        rows = db_query(prov_db, "SELECT * FROM attributeValueChange")
        assert len(rows) >= 1

    def test_value_change_has_old_value(self, client, executed_box, prov_db):
        activity = self._full_setup(client, executed_box, prov_db)
        client.post(
            "/insert_attribute_value_change",
            json={"data": {"activity_name": activity}},
        )
        rows = db_query(prov_db, "SELECT old_value FROM attributeValueChange")
        assert rows[0][0] is not None
        assert rows[0][0] != ""

    def test_no_interaction_returns_404(self, client, executed_box, prov_db):
        _, activity = executed_box
        resp = client.post(
            "/insert_attribute_value_change",
            json={"data": {"activity_name": activity}},
        )
        assert resp.status_code == 404
