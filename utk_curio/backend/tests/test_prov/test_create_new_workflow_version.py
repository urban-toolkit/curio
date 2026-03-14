import sqlite3
import pytest
from utk_curio.backend.create_provenance_db import initialize_db
from utk_curio.backend.app.api.routes import create_new_workflow_version


@pytest.fixture
def conn(tmp_path):
    """In-memory-like DB with schema + a v1.0 workflow called 'wf'."""
    db_file = str(tmp_path / "test.db")
    initialize_db(db_file)
    c = sqlite3.connect(db_file)
    cur = c.cursor()
    cur.execute("INSERT INTO version (version_number) VALUES (?)", ("1.0",))
    c.commit()
    vid = cur.lastrowid
    cur.execute("INSERT INTO versionedElement (version_id) VALUES (?)", (vid,))
    c.commit()
    veid = cur.lastrowid
    cur.execute("INSERT INTO workflow (workflow_name, ve_id) VALUES (?, ?)", ("wf", veid))
    c.commit()
    yield c
    c.close()


class TestCreateNewWorkflowVersion:
    def test_returns_old_and_new_ids(self, conn):
        old_id, new_id = create_new_workflow_version(conn, "wf")
        assert isinstance(old_id, int)
        assert isinstance(new_id, int)
        assert old_id != new_id

    def test_version_increments(self, conn):
        create_new_workflow_version(conn, "wf")
        cur = conn.cursor()
        cur.execute("SELECT version_number FROM version ORDER BY version_id")
        versions = [row[0] for row in cur.fetchall()]
        assert versions == ["1.0", "2.0"]

    def test_multiple_increments(self, conn):
        create_new_workflow_version(conn, "wf")
        create_new_workflow_version(conn, "wf")
        cur = conn.cursor()
        cur.execute("SELECT version_number FROM version ORDER BY version_id")
        versions = [row[0] for row in cur.fetchall()]
        assert versions == ["1.0", "2.0", "3.0"]

    def test_new_workflow_row_created(self, conn):
        _, new_id = create_new_workflow_version(conn, "wf")
        cur = conn.cursor()
        cur.execute("SELECT workflow_name FROM workflow WHERE workflow_id = ?", (new_id,))
        assert cur.fetchone()[0] == "wf"

    def test_versioned_element_chain(self, conn):
        old_id, new_id = create_new_workflow_version(conn, "wf")
        cur = conn.cursor()
        cur.execute("SELECT ve_id FROM workflow WHERE workflow_id = ?", (old_id,))
        old_ve = cur.fetchone()[0]
        cur.execute("SELECT ve_id FROM workflow WHERE workflow_id = ?", (new_id,))
        new_ve = cur.fetchone()[0]
        cur.execute("SELECT previous_ve_id FROM versionedElement WHERE ve_id = ?", (new_ve,))
        assert cur.fetchone()[0] == old_ve

    def test_preserves_row_factory(self, conn):
        conn.row_factory = sqlite3.Row
        create_new_workflow_version(conn, "wf")
        assert conn.row_factory is sqlite3.Row
