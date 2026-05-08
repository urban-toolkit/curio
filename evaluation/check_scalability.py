import argparse
import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path(".curio/provenance.db")


def get_latest_session_id(conn):
    columns = [row[1] for row in conn.execute("PRAGMA table_info(interaction_session)")]

    if "session_id" in columns:
        id_col = "session_id"
    elif "id" in columns:
        id_col = "id"
    else:
        raise RuntimeError("Could not find session id column in interaction_session table.")

    row = conn.execute(
        f"SELECT {id_col} FROM interaction_session ORDER BY {id_col} DESC LIMIT 1"
    ).fetchone()

    if not row:
        raise RuntimeError("No sessions found in interaction_session.")

    return row[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Path to provenance SQLite database"
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional specific session id to check"
    )

    args = parser.parse_args()
    db_path = Path(args.db)

    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    session_id = args.session_id or get_latest_session_id(conn)

    event_count = conn.execute(
        "SELECT COUNT(*) AS c FROM interaction_event WHERE session_id = ?",
        (session_id,)
    ).fetchone()["c"]

    event_type_rows = conn.execute(
        """
        SELECT event_type, COUNT(*) AS c
        FROM interaction_event
        WHERE session_id = ?
        GROUP BY event_type
        ORDER BY event_type
        """,
        (session_id,)
    ).fetchall()

    snapshot_count = conn.execute(
        "SELECT COUNT(*) AS c FROM graph_snapshot WHERE session_id = ?",
        (session_id,)
    ).fetchone()["c"]

    result_text = []
    result_text.append(f"Session ID: {session_id}")
    result_text.append(f"Total events stored: {event_count}")
    result_text.append(f"Total snapshots stored: {snapshot_count}")
    result_text.append("")
    result_text.append("Event distribution:")

    for row in event_type_rows:
        result_text.append(f"  {row['event_type']}: {row['c']}")

    result_text.append("")
    if event_count >= 800:
        result_text.append("PASS: System stored at least 800 events.")
    else:
        result_text.append("WARNING: Stored fewer than 800 events.")

    output = "\n".join(result_text)
    print(output)

    results_dir = Path(__file__).parent / "results"
    results_dir.mkdir(exist_ok=True)

    out_file = results_dir / "scalability_results.txt"
    out_file.write_text(output)

    print(f"\nSaved result to: {out_file}")

    conn.close()


if __name__ == "__main__":
    main()