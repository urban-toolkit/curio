import sqlite3
from uuid import uuid4

conn = sqlite3.connect('project.db')

cursor = conn.cursor()

command = """
CREATE TABLE project (
    id TEXT PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    dependency TEXT,
    code TEXT,
    boxType VARCHAR(50) NOT NULL
);
"""

cursor.execute(command)
conn.commit()

conn.close()