import duckdb, os
from pathlib import Path

def _db_path() -> Path:
    root = Path(os.environ.get("CURIO_LAUNCH_CWD", os.getcwd())) / ".curio" / "data"

    return root / "softartifacts.duckdb"

def _connect():
    con = duckdb.connect(str(_db_path()))
    con.execute("""
  CREATE TABLE IF NOT EXISTS chunks (
    artifact_id VARCHAR,
    chunk_id    VARCHAR,
    text        VARCHAR,
    kind        VARCHAR,
    page        INTEGER,
    char_start  INTEGER,
    char_end    INTEGER,
    PRIMARY KEY (artifact_id, chunk_id)
);
                """)
    
    con.execute("""
  CREATE TABLE IF NOT EXISTS softartifacts (
    artifact_id VARCHAR PRIMARY KEY,
    source_file VARCHAR,
    mimetype VARCHAR,
    kind VARCHAR,
    created_at TIMESTAMP
);
                """)
    return con
    
#update and insert the database based on the ingested artifact
def upsert_softartifact(meta: dict, chunks: list[dict]):
    #meta: artifact_id, source_file, mimetype, kind
    con = _connect()
    try:
        aid = meta["artifact_id"]
        con.execute("DELETE FROM chunks WHERE artifact_id = ?", [aid])
        con.execute(
            """
            INSERT OR REPLACE INTO softartifacts
              (artifact_id, source_file, mimetype, kind, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,
            [aid, meta["source_file"], meta["mimetype"], meta["kind"]],
        ) 

        rows = [
            (
                aid,
                c.get("chunk_id"),
                c.get("text"),
                c.get("kind"),
                c.get("page"),
                c.get("char_start"),
                c.get("char_end"),
            )
            for c in chunks
        ]

        con.executemany(
            """
            INSERT INTO chunks (
                artifact_id, chunk_id, text, kind, page, char_start, char_end
            ) VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            rows
        )
    finally:
        con.close()
    

#parameter: artifact_id
#return: all the chunks that is from parameter artifact_id
def list_chunks(artifact_id: str) -> list[dict]:
    con = _connect()
    try:
        cur = con.execute("SELECT * FROM chunks WHERE artifact_id = ?", [artifact_id])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()

# parameter: artifact_id
# return: dict of an artifact_id   
def get_artifact(artifact_id: str) -> dict | None:
    con = _connect()
    try:
        rows = con.execute(
            " SELECT * FROM softartifacts WHERE artifact_id = ?", [artifact_id]
        ).fetchone()
        # guard against no value found
        if rows is None:
            return None
        cols = [d[0] for d in con.description]
        return dict(zip(cols, rows))
    finally:
        con.close()

    
